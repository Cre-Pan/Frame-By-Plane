#!/usr/bin/env python3
"""Conservative static audit for potentially orphaned Python symbols.

The report is deliberately a candidate list, not an automatic deletion list.
Blender add-ons use registration tuples, string operator identifiers and RNA
callbacks, so every candidate still needs a runtime and registration review.
"""

from __future__ import annotations

import argparse
import ast
import io
import json
import tokenize
from collections import Counter, defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = ROOT / "frame_by_plane"
EXCLUDED_REFERENCE_ROOTS = {".git", "dist", "work"}


def _python_files(source: Path) -> list[Path]:
    files = []
    for path in source.rglob("*.py"):
        if "__pycache__" in path.parts:
            continue
        try:
            relative = path.relative_to(ROOT)
        except ValueError:
            relative = path
        if relative.parts and relative.parts[0] in EXCLUDED_REFERENCE_ROOTS:
            continue
        files.append(path)
    return sorted(files)


def _name_counts(files: list[Path]) -> Counter[str]:
    counts: Counter[str] = Counter()
    for path in files:
        text = path.read_text(encoding="utf-8")
        for token in tokenize.generate_tokens(io.StringIO(text).readline):
            if token.type == tokenize.NAME:
                counts[token.string] += 1
    return counts


def _string_references(
    files: list[Path], trees: dict[Path, ast.Module]
) -> dict[str, list[str]]:
    references: dict[str, list[str]] = defaultdict(list)
    for path in files:
        tree = trees[path]
        relative = path.relative_to(ROOT).as_posix()
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                value = node.value.strip()
                if value.isidentifier():
                    references[value].append(f"{relative}:{node.lineno}")
    return references


def _unused_imports(files: list[Path], trees: dict[Path, ast.Module]) -> list[dict[str, object]]:
    candidates = []
    for path in files:
        tree = trees[path]
        loaded_names = {
            node.id for node in ast.walk(tree)
            if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load)
        }
        relative = path.relative_to(ROOT).as_posix()
        for node in tree.body:
            aliases = ()
            module = ""
            if isinstance(node, ast.Import):
                aliases = node.names
            elif isinstance(node, ast.ImportFrom):
                if node.module == "__future__":
                    continue
                aliases = node.names
                module = str(node.module or "")
            else:
                continue
            for alias in aliases:
                if alias.name == "*":
                    continue
                bound_name = alias.asname or (
                    alias.name.split(".")[0] if isinstance(node, ast.Import) else alias.name
                )
                if bound_name in loaded_names:
                    continue
                candidates.append({
                    "path": relative,
                    "line": node.lineno,
                    "module": module or alias.name,
                    "name": alias.name,
                    "bound_name": bound_name,
                })
    return candidates


def audit(source: Path) -> dict[str, object]:
    files = _python_files(source)
    reference_files = _python_files(ROOT)
    trees = {
        path: ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for path in reference_files
    }
    counts = _name_counts(reference_files)
    string_references = _string_references(reference_files, trees)
    symbols = []
    module_functions = 0
    module_classes = 0
    module_assignments = 0

    for path in files:
        tree = trees[path]
        relative = path.relative_to(ROOT).as_posix()
        for node in tree.body:
            assignment_name = ""
            if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
                assignment_name = node.targets[0].id
            elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                assignment_name = node.target.id
            if assignment_name:
                if assignment_name.startswith("__") or assignment_name in {"bl_info", "classes"}:
                    continue
                name = assignment_name
                kind = "constant" if name.isupper() else "variable"
                module_assignments += 1
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                name = node.name
                kind = "class" if isinstance(node, ast.ClassDef) else "function"
                if kind == "class":
                    module_classes += 1
                else:
                    module_functions += 1
            else:
                continue
            lexical_uses = max(0, counts[name] - 1)
            strings = string_references.get(name, [])
            symbols.append({
                "path": relative,
                "line": node.lineno,
                "end_line": int(getattr(node, "end_lineno", node.lineno) or node.lineno),
                "name": name,
                "kind": kind,
                "private": name.startswith("_"),
                "docstring": (
                    ast.get_docstring(node, clean=True)
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
                    else ""
                ) or "",
                "lexical_uses": lexical_uses,
                "string_references": strings,
                "candidate": lexical_uses == 0 and not strings,
            })

    candidates = [item for item in symbols if item["candidate"]]
    candidates.sort(key=lambda item: (item["path"], item["line"]))
    unused_imports = _unused_imports(files, trees)
    unused_imports.sort(key=lambda item: (item["path"], item["line"], item["bound_name"]))

    module_candidates = []
    known_stems = {path.stem for path in files}
    module_references: dict[str, list[tuple[Path, int]]] = defaultdict(list)
    for other, tree in trees.items():
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                stem = str(node.module or "").split(".")[-1]
                if stem in known_stems:
                    module_references[stem].append((other, node.lineno))
                for alias in node.names:
                    if alias.name in known_stems:
                        module_references[alias.name].append((other, node.lineno))
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    stem = str(alias.name).split(".")[-1]
                    if stem in known_stems:
                        module_references[stem].append((other, node.lineno))
            elif isinstance(node, ast.Constant) and isinstance(node.value, str):
                if node.value in known_stems:
                    module_references[node.value].append((other, node.lineno))
    for path in files:
        if path.name == "__init__.py" or "tests" in path.parts:
            continue
        stem = path.stem
        references = [item for item in module_references.get(stem, ()) if item[0] != path]
        if not references:
            module_candidates.append(path.relative_to(ROOT).as_posix())

    return {
        "source": str(source),
        "python_files": len(files),
        "module_functions": module_functions,
        "module_classes": module_classes,
        "module_assignments": module_assignments,
        "candidate_count": len(candidates),
        "candidates": candidates,
        "unused_import_count": len(unused_imports),
        "unused_imports": unused_imports,
        "module_candidate_count": len(module_candidates),
        "module_candidates": module_candidates,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON")
    args = parser.parse_args()
    report = audit(args.source.resolve())
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(
            f"{report['python_files']} files; {report['module_functions']} functions; "
            f"{report['module_classes']} classes; {report['module_assignments']} assignments; "
            f"{report['candidate_count']} symbol candidates; "
            f"{report['unused_import_count']} unused import candidates; "
            f"{report['module_candidate_count']} module candidates"
        )
        for path in report["module_candidates"]:
            print(f"{path}: module has no import or dynamic-list reference")
        for item in report["candidates"]:
            print(
                f"{item['path']}:{item['line']}: {item['kind']} {item['name']} "
                f"(lexical uses={item['lexical_uses']})"
            )
        for item in report["unused_imports"]:
            print(
                f"{item['path']}:{item['line']}: unused import candidate "
                f"{item['bound_name']} from {item['module']}"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
