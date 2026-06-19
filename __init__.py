import importlib


bl_info = {
    "name": "Frame By Plane",
    "author": "Alessandro Pannoli",
    "version": (5, 2, 1),
    "blender": (5, 1, 0),
    "location": "View3D > Sidebar > Frame by Plane",
    "description": "Import images, PNG sequences, videos and layered folders as animated image planes.",
    "category": "Animation",
}


_MODULE_NAMES = (
    "constants", "matrix_presets", "path_utils", "safe_tasks", "runtime", "effect_schema",
    # Register Object properties before the Effects UI/handler. On unregister
    # the reverse order removes the frame handler before deleting its RNA props.
    "properties", "custom_effects", "effects_registry", "builtin_effects", "geometry_nodes", "materials", "layers", "scene_sync",
    "native_backend", "builder", "importer", "core", "drawing_plane", "handlers",
    "operator_common", "operator_layers", "operator_import",
    "operator_sequence", "operator_render", "operator_procedural",
    "operator_project", "operators", "ui_icons", "ui_layout", "ui",
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

modules = tuple(_loaded_modules)
_runtime_module = globals()["runtime"]


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
