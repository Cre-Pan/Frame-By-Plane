"""Collect the interface strings Frame By Plane shows, for translation.

Blender translates interface text at draw time by looking the exact English
string up in the registered dictionaries, so the catalog only needs the
literal strings that reach the UI: class labels and descriptions, property
names, descriptions and enum items, and literal text passed to layout and
UI-helper calls. Report and log messages are not translated by Blender and are
skipped.

Usage: python tools/extract_translations.py  (writes frame_by_plane/translations/messages.json)
"""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "frame_by_plane"
OUTPUT = PACKAGE / "translations" / "messages.json"

CLASS_ATTRIBUTES = {"bl_label", "bl_description", "bl_category"}
TEXT_KEYWORDS = {"text", "name", "description", "title", "message", "confirm_text", "heading", "label"}
SKIP_CALLS = {
    "report", "print", "get", "getattr", "hasattr", "setattr", "startswith", "endswith",
    "join", "format", "split", "replace", "strip", "warn", "_fbp_warn", "debug", "info",
    "warning", "error", "exception", "log", "open", "Path", "compile", "match", "search",
    "sub", "fullmatch", "encode", "decode", "lower", "upper", "find", "index", "count",
    "write", "append", "add", "pop", "remove", "discard", "update", "setdefault",
    "isinstance", "RuntimeError", "ValueError", "TypeError", "OSError", "KeyError",
    "Exception", "AttributeError", "run", "Popen", "fbp_runtime_get", "fbp_runtime_set",
    "new", "operator", "prop", "prop_enum", "menu", "popover", "keymap_items", "cancel_task",
    "schedule_task", "_set_socket", "_socket", "_fbp_bg_update_scene_status",
}
# Calls that name data (sockets, nodes, IDs) rather than interface text.
DATA_CALLS = {"new_socket", "new", "new_from_object", "copy", "_ensure_group_interface_socket", "_unique_socket_name"}
SKIP_FILES = {"tooltips.py"}  # handled through the property descriptions it feeds
HUMAN_TEXT = re.compile(r"[A-Za-z]")
IDENTIFIER_LIKE = re.compile(r"^[A-Za-z0-9_.\-/\\:]+$")


def is_ui_text(value):
    if not isinstance(value, str):
        return False
    text = value.strip()
    if not text or len(text) > 400 or not HUMAN_TEXT.search(text):
        return False
    if "\n" in text and len(text) < 3:
        return False
    if any(token in text for token in ("{", "%s", "%d", "\\", "://", ".py", ".blend", "bpy.")):
        return False
    if IDENTIFIER_LIKE.match(text):
        # Single words count only when they read like a label ("Opacity"),
        # not like identifiers ("OPACITY", "fbp_layer", "node.group").
        return bool(re.match(r"^[A-Z][a-z]+[0-9]*$|^[A-Z][a-z]+(?:[A-Z][a-z]+)?$|^[0-9]+[A-Za-z]+$", text)) and "_" not in text
    return True


def call_name(node):
    func = node.func
    if isinstance(func, ast.Attribute):
        return func.attr
    if isinstance(func, ast.Name):
        return func.id
    return ""


def enum_item_strings(node):
    if not isinstance(node, (ast.List, ast.Tuple)):
        return
    for item in node.elts:
        if isinstance(item, ast.Tuple) and len(item.elts) >= 3:
            for element in item.elts[1:3]:
                if isinstance(element, ast.Constant) and isinstance(element.value, str):
                    yield element.value


def collect(path):
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            for statement in node.body:
                if (
                    isinstance(statement, ast.Assign)
                    and any(isinstance(t, ast.Name) and t.id in CLASS_ATTRIBUTES for t in statement.targets)
                    and isinstance(statement.value, ast.Constant)
                ):
                    found.add(statement.value.value)
        elif isinstance(node, ast.Assign):
            names = [t.id for t in node.targets if isinstance(t, ast.Name)]
            if any("ITEMS" in name.upper() for name in names):
                found.update(enum_item_strings(node.value))
        elif isinstance(node, ast.Call):
            name = call_name(node)
            for keyword in node.keywords:
                if name in DATA_CALLS:
                    break
                if keyword.arg == "items":
                    found.update(enum_item_strings(keyword.value))
                elif keyword.arg in TEXT_KEYWORDS and isinstance(keyword.value, ast.Constant):
                    found.add(keyword.value.value)
            if name not in SKIP_CALLS and name not in DATA_CALLS and not name.startswith(("_fbp_bg", "fbp_runtime")):
                for argument in node.args:
                    if isinstance(argument, ast.Constant):
                        found.add(argument.value)
    return {text for text in found if is_ui_text(text)}


def main():
    messages = set()
    for path in sorted(PACKAGE.glob("*.py")):
        if path.name in SKIP_FILES:
            continue
        messages |= collect(path)
    tooltips = PACKAGE / "tooltips.py"
    if tooltips.exists():
        tree = ast.parse(tooltips.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and is_ui_text(node.value) and " " in node.value:
                messages.add(node.value)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(sorted(messages), ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"{len(messages)} messages -> {OUTPUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
