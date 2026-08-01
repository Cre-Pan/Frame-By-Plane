#!/usr/bin/env python3
"""Reject undefined Python globals and unresolved Blender RNA callback symbols."""

from __future__ import annotations

import ast
import builtins
import symtable
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ADDON = ROOT / "frame_by_plane"
PROPERTY_CALLBACK_KEYWORDS = {"update", "get", "set", "items", "poll", "search"}
GLOBAL_WHITELIST = {"__file__"}


def module_definitions(tree: ast.Module) -> set[str]:
    definitions = set(dir(builtins))
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            definitions.add(node.name)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                definitions.add(alias.asname or alias.name.split(".", 1)[0])
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                for child in ast.walk(target):
                    if isinstance(child, ast.Name):
                        definitions.add(child.id)
    return definitions


def property_callback_errors(path: Path, tree: ast.Module) -> tuple[list[str], int]:
    definitions = module_definitions(tree)
    errors: list[str] = []
    references = 0
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        function = node.func
        name = (
            function.id
            if isinstance(function, ast.Name)
            else function.attr
            if isinstance(function, ast.Attribute)
            else ""
        )
        if not (name.endswith("Property") or name == "property"):
            continue
        for keyword in node.keywords:
            if keyword.arg not in PROPERTY_CALLBACK_KEYWORDS:
                continue
            if not isinstance(keyword.value, ast.Name):
                continue
            references += 1
            symbol = keyword.value.id
            if symbol not in definitions:
                errors.append(
                    f"{path.relative_to(ROOT)}:{node.lineno}: "
                    f"{name} {keyword.arg}= references undefined symbol {symbol!r}"
                )
    return errors, references


def unresolved_global_errors(path: Path, source: str) -> list[str]:
    table = symtable.symtable(source, str(path), "exec")
    module_symbols = set(table.get_identifiers())
    builtin_symbols = set(dir(builtins))
    errors: list[str] = []

    def visit(scope: symtable.SymbolTable) -> None:
        for name in scope.get_identifiers():
            symbol = scope.lookup(name)
            if (
                symbol.is_referenced()
                and symbol.is_global()
                and name not in module_symbols
                and name not in builtin_symbols
                and name not in GLOBAL_WHITELIST
            ):
                errors.append(
                    f"{path.relative_to(ROOT)}: scope {scope.get_name()!r} "
                    f"references undefined global {name!r}"
                )
        for child in scope.get_children():
            visit(child)

    visit(table)
    return errors


def main() -> None:
    errors: list[str] = []
    python_files = 0
    callback_references = 0

    for path in sorted(ADDON.rglob("*.py")):
        python_files += 1
        source = path.read_text(encoding="utf-8")
        try:
            tree = ast.parse(source, filename=str(path))
        except SyntaxError as exc:
            errors.append(f"{path.relative_to(ROOT)}: {exc}")
            continue
        callback_errors, count = property_callback_errors(path, tree)
        callback_references += count
        errors.extend(callback_errors)
        errors.extend(unresolved_global_errors(path, source))

    if errors:
        print("Python symbol validation failed:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        raise SystemExit(1)

    print(f"Python symbol validation passed for {python_files} modules")
    print(f"RNA callback references checked: {callback_references}")


if __name__ == "__main__":
    main()
