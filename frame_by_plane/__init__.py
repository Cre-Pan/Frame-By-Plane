import importlib

from .constants import FBP_VERSION


bl_info = {
    "name": "Frame By Plane",
    "author": "Alessandro Pannoli",
    "version": FBP_VERSION,
    "blender": (5, 1, 2),
    "location": "View3D > Sidebar > Frame by Plane",
    "description": "Animation workflow for images, sequences, videos, PSD/PSB/Procreate layers, Toon Boom exports, cutouts and multiplane setups.",
    "category": "Animation",
}


_MODULE_NAMES = (
    "constants", "matrix_presets", "path_utils", "alpha_crop", "runtime", "storage_keys", "safe_tasks", "lifecycle", "effect_schema", "object_masks",
    # Register Object properties before the Effects UI/handler. On unregister
    # the reverse order removes the frame handler before deleting its RNA props.
    "properties", "compositor", "feedback", "custom_effects", "effects_registry", "geometry_nodes", "effect_controls", "materials", "layers", "scene_sync", "persistence", "endurance", "render_parity",
    "native_backend", "builder", "procreate_import", "layered_import", "importer", "core", "drawing_plane", "handlers",
    "operator_common", "operator_layers", "operator_import",
    "operator_sequence", "operator_render", "operator_procedural",
    "operator_project", "developer_tools", "operators", "ui_icons", "ui_layout", "ui", "viewport_pie", "tooltips",
)

_loaded_modules = []
for _name in _MODULE_NAMES:
    # Check before importing. import_module() automatically exposes the
    # submodule on this package, so checking globals afterwards caused every
    # module to be imported and immediately reloaded even on the first enable.
    _existing_module = globals().get(_name)
    if _existing_module is None:
        _module = importlib.import_module(f".{_name}", __package__)
    else:
        _module = importlib.reload(_existing_module)
    globals()[_name] = _module
    _loaded_modules.append(_module)

# Keep the heavy procedural builders lazy on a normal enable. During an
# in-place development reload, refresh them only when they were already loaded
# by an effect request in the current Blender session.
_existing_builtin_effects = globals().get("builtin_effects")
if _existing_builtin_effects is not None:
    globals()["builtin_effects"] = importlib.reload(_existing_builtin_effects)

modules = tuple(_loaded_modules)
_runtime_module = globals()["runtime"]

# Apply centralized hover help after all UI/operator classes have been imported
# and before any class is registered with Blender.
globals()["tooltips"].apply_tooltips(modules)


def register():
    registered = []
    for mod in modules:
        register_fn = getattr(mod, "register", None)
        if not callable(register_fn):
            continue
        try:
            register_fn()
            registered.append(mod)
        except Exception as exc:
            _runtime_module.fbp_warn(f"Registration failed in {mod.__name__}", exc)
            unregister_fn = getattr(mod, "unregister", None)
            if callable(unregister_fn):
                try:
                    unregister_fn()
                except Exception as cleanup_exc:
                    _runtime_module.fbp_warn(f"Could not clean partial registration for {mod.__name__}", cleanup_exc)
            for previous in reversed(registered):
                rollback_fn = getattr(previous, "unregister", None)
                if not callable(rollback_fn):
                    continue
                try:
                    rollback_fn()
                except Exception as rollback_exc:
                    _runtime_module.fbp_warn(f"Could not roll back {previous.__name__}", rollback_exc)
            raise


def unregister():
    for mod in reversed(modules):
        unregister_fn = getattr(mod, "unregister", None)
        if not callable(unregister_fn):
            continue
        try:
            unregister_fn()
        except Exception as exc:
            _runtime_module.fbp_warn(f"Could not unregister {mod.__name__}", exc)
