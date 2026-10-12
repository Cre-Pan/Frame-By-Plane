"""Draw every Frame By Plane panel and the preferences through the UILayout stub.

A keyword or enum value Blender rejects only shows up as an empty or broken
panel in the real UI; the stub raises on it instead.
"""

import importlib
import inspect
import os
import sys
import traceback
from pathlib import Path

import bpy

INSTALLED_PACKAGE = os.environ.get("FBP_TEST_INSTALLED") == "1"
PACKAGE_NAME = os.environ.get(
    "FBP_TEST_PACKAGE",
    "bl_ext.fbp_audit.frame_by_plane" if INSTALLED_PACKAGE else "frame_by_plane",
)
if not INSTALLED_PACKAGE:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from ui_layout_stub import StubLayout  # noqa: E402

addon = importlib.import_module(PACKAGE_NAME)


class _PanelProxy:
    def __init__(self, cls, owner=None):
        object.__setattr__(self, "_cls", cls)
        object.__setattr__(self, "_owner", owner)
        object.__setattr__(self, "layout", StubLayout())

    def __getattr__(self, name):
        owner = object.__getattribute__(self, "_owner")
        if owner is not None and hasattr(owner, name):
            return getattr(owner, name)
        return getattr(object.__getattribute__(self, "_cls"), name)


def _addon_panels():
    seen = set()
    for name, module in list(sys.modules.items()):
        if not name.startswith(addon.__name__):
            continue
        for _attr, cls in inspect.getmembers(module, inspect.isclass):
            if cls in seen or cls.__module__ != module.__name__:
                continue
            if issubclass(cls, (bpy.types.Panel, bpy.types.Menu)) and "draw" in vars(cls):
                seen.add(cls)
                yield cls


failures = []
try:
    if not INSTALLED_PACKAGE:
        addon.register()
    data = bpy.data.grease_pencils.new("FBP UI Sweep")
    obj = bpy.data.objects.new("FBP UI Sweep", data)
    bpy.context.scene.collection.objects.link(obj)
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    layer = data.layers.new("Layer", set_active=True)
    layer.frames.new(1).drawing.add_strokes([3])
    material = bpy.data.materials.new("FBP UI Sweep")
    bpy.data.materials.create_gpencil_data(material)
    data.materials.append(material)

    panels = sorted(_addon_panels(), key=lambda cls: cls.__name__)
    drawn = 0
    for mode in ("OBJECT", "EDIT", "PAINT_GREASE_PENCIL"):
        bpy.ops.object.mode_set(mode=mode)
        for cls in panels:
            try:
                if hasattr(cls, "poll") and not cls.poll(bpy.context):
                    continue
            except Exception:
                continue
            try:
                cls.draw(_PanelProxy(cls), bpy.context)
                drawn += 1
            except (TypeError, AttributeError) as exc:
                if "UILayout" in str(exc) or " has no property " in str(exc):
                    failures.append(f"{mode} {cls.__name__}: {exc}")
            except Exception:
                pass
    bpy.ops.object.mode_set(mode="OBJECT")

    if addon.__name__ not in bpy.context.preferences.addons:
        bpy.context.preferences.addons.new().module = addon.__name__
    prefs = bpy.context.preferences.addons[addon.__name__].preferences
    prefs_cls = type(prefs)
    try:
        prefs_cls.draw(_PanelProxy(prefs_cls, prefs), bpy.context)
        drawn += 1
    except (TypeError, AttributeError) as exc:
        failures.append(f"Preferences: {exc}\n{traceback.format_exc()}")

    assert drawn > 5, drawn
    assert not failures, "\n".join(failures)
    print(f"FBPTEST ui_draw_sweep: PASS ({drawn} draws)")
except Exception:
    traceback.print_exc()
    print("FBPTEST ui_draw_sweep: FAIL")
    sys.exit(1)
