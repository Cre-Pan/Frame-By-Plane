"""Small context helpers shared by interactive Frame By Plane operators.

The helpers in this module deliberately avoid importing feature modules.  They
can therefore be reused by Shader and Geometry Nodes workflows without creating
circular imports or duplicating editor-selection behavior.
"""

from __future__ import annotations

from .runtime import FBP_DATA_ERRORS


def _area_size(area):
    """Return a stable visual-size score for one Blender area."""
    try:
        return max(0, int(getattr(area, "width", 0) or 0)) * max(
            0, int(getattr(area, "height", 0) or 0)
        )
    except FBP_DATA_ERRORS:
        return 0


def restore_modal_cursor(context) -> bool:
    """Restore Blender's modal cursor without leaking stale-window errors."""
    try:
        context.window.cursor_modal_restore()
        return True
    except FBP_DATA_ERRORS:
        return False


def resolve_node_editor_area(context):
    """Return a Node Editor, converting a 3D View only when necessary.

    Operators are commonly invoked from Properties.  Older duplicated helpers
    converted that Properties area immediately, even when a large 3D View was
    available in the same workspace.  Prefer an existing Node Editor, then the
    current 3D View, then the largest 3D View.  Properties is never replaced as
    a hidden side effect; callers can report that the workspace has no suitable
    editor instead.
    """
    if context is None:
        return None
    try:
        current = getattr(context, "area", None)
        if current is not None and getattr(current, "type", "") == "NODE_EDITOR":
            return current

        screen = getattr(context, "screen", None)
        areas = tuple(getattr(screen, "areas", ()) or ())
        for area in areas:
            if getattr(area, "type", "") == "NODE_EDITOR":
                return area

        candidates = [
            area for area in areas
            if getattr(area, "type", "") == "VIEW_3D"
        ]
        if current is not None and getattr(current, "type", "") == "VIEW_3D":
            target = current
        elif candidates:
            target = max(candidates, key=_area_size)
        else:
            return None
        target.type = "NODE_EDITOR"
        return target
    except FBP_DATA_ERRORS:
        return None


__all__ = ("resolve_node_editor_area", "restore_modal_cursor")
