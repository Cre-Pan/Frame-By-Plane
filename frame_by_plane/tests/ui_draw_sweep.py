"""Draw every Frame By Plane panel and the preferences through the UILayout stub.

A keyword or enum value Blender rejects only shows up as an empty or broken
panel in the real UI; the stub raises on it instead.
"""

import importlib
import inspect
import os
import sys
import traceback
import types
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


class _OperatorProxy:
    """Stand-in ``self`` for an operator dialog: properties read as their defaults."""

    def __init__(self, cls):
        object.__setattr__(self, "_cls", cls)
        object.__setattr__(self, "layout", StubLayout())
        values = {}
        for name, deferred in _operator_annotations(cls).items():
            keywords = dict(getattr(deferred, "keywords", {}) or {})
            if "default" in keywords:
                values[name] = keywords["default"]
            elif getattr(deferred, "function", None) is bpy.props.CollectionProperty:
                values[name] = []
            elif getattr(deferred, "function", None) is bpy.props.StringProperty:
                values[name] = ""
            elif getattr(deferred, "function", None) in (bpy.props.IntProperty, bpy.props.FloatProperty):
                values[name] = 0
            elif getattr(deferred, "function", None) is bpy.props.BoolProperty:
                values[name] = False
        module, _dot, operator = str(getattr(cls, "bl_idname", "")).partition(".")
        try:
            values["bl_rna"] = getattr(getattr(bpy.ops, module), operator).get_rna_type()
        except (AttributeError, KeyError):
            pass
        object.__setattr__(self, "_values", values)

    def __getattr__(self, name):
        values = object.__getattribute__(self, "_values")
        if name in values:
            return values[name]
        attr = getattr(object.__getattribute__(self, "_cls"), name)
        if isinstance(attr, types.FunctionType):
            return types.MethodType(attr, self)
        return attr

    def __setattr__(self, name, value):
        object.__getattribute__(self, "_values")[name] = value


def _operator_annotations(cls):
    annotations = {}
    for base in reversed(cls.__mro__):
        annotations.update(vars(base).get("__annotations__", {}) or {})
    return annotations


def _addon_operator_dialogs():
    seen = set()
    for name, module in list(sys.modules.items()):
        if not name.startswith(addon.__name__):
            continue
        for _attr, cls in inspect.getmembers(module, inspect.isclass):
            if cls in seen or cls.__module__ != module.__name__:
                continue
            if issubclass(cls, bpy.types.Operator) and "draw" in vars(cls):
                seen.add(cls)
                yield cls


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

    # Background Blender skips the Viewport-only modules; import them so their
    # panels are drawn too.
    importlib.import_module(addon.__name__ + ".grease_pencil_scrub")
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
            except NameError as exc:
                failures.append(f"{mode} {cls.__name__}: {exc}")
            except (TypeError, AttributeError) as exc:
                if "UILayout" in str(exc) or " has no property " in str(exc):
                    failures.append(f"{mode} {cls.__name__}: {exc}")
            except Exception:
                pass
    bpy.ops.object.mode_set(mode="OBJECT")

    # Operator dialogs (invoke_props_dialog) draw only in a live window. A
    # name lost in a merge raises NameError there and leaves an empty popup.
    dialogs = sorted(_addon_operator_dialogs(), key=lambda cls: cls.__name__)
    dialogs_drawn = 0
    for cls in dialogs:
        # Background Blender skips some Viewport-only operators; register them
        # for the draw so their properties resolve.
        registered_here = False
        if not hasattr(bpy.types, cls.__name__):
            try:
                bpy.utils.register_class(cls)
                registered_here = True
            except (RuntimeError, ValueError):
                pass
        try:
            cls.draw(_OperatorProxy(cls), bpy.context)
            dialogs_drawn += 1
        except NameError as exc:
            failures.append(f"Operator {cls.__name__}: {exc}\n{traceback.format_exc()}")
        except (TypeError, AttributeError) as exc:
            if "UILayout" in str(exc) or " has no property " in str(exc):
                failures.append(f"Operator {cls.__name__}: {exc}")
        except Exception:
            pass
        finally:
            if registered_here:
                bpy.utils.unregister_class(cls)
    drawn += dialogs_drawn
    assert any(cls.__name__ == "FBP_OT_DropMedia" for cls in dialogs), "drop dialog not swept"

    if addon.__name__ not in bpy.context.preferences.addons:
        bpy.context.preferences.addons.new().module = addon.__name__
    prefs = bpy.context.preferences.addons[addon.__name__].preferences
    prefs_cls = type(prefs)
    try:
        prefs_cls.draw(_PanelProxy(prefs_cls, prefs), bpy.context)
        drawn += 1
    except (TypeError, AttributeError) as exc:
        failures.append(f"Preferences: {exc}\n{traceback.format_exc()}")

    # The Viewport header strip: pin, Return to Start, menu.
    scrub = importlib.import_module(addon.__name__ + ".grease_pencil_scrub")
    available = scrub._scrub_header_available
    scrub._scrub_header_available = lambda _context: True
    try:
        header = StubLayout()
        scrub._draw_scrub_header_control(header, bpy.context)
        drawn += 1
        assert any(call[0] == "prop" and call[1][1] == "gp_scrub_return_to_start" for call in header.calls)
        popover_cls = scrub.FBP_PT_GreasePencilScrubSliderPopover
        popover_cls.draw(_PanelProxy(popover_cls), bpy.context)
        drawn += 1
    except (TypeError, AttributeError) as exc:
        failures.append(f"Scrub header: {exc}")
    finally:
        scrub._scrub_header_available = available

    assert drawn > 5, drawn
    assert not failures, "\n".join(failures)
    print(f"FBPTEST ui_draw_sweep: PASS ({drawn} draws)")
except Exception:
    traceback.print_exc()
    print("FBPTEST ui_draw_sweep: FAIL")
    sys.exit(1)
