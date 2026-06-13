bl_info = {
    "name": "Frame by Plane",
    "author": "Alessandro Pannoli",
    "version": (4, 1, 7),
    "blender": (5, 1, 0),
    "location": "View3D > Sidebar > Frame by Plane",
    "description": "Version 4.1.7: flatten single-sequence and single-static-image folders.",
    "category": "Animation",
}


import importlib

_MODULE_NAMES = (
    "constants", "path_utils", "profiling", "safe_tasks", "runtime",
    "properties", "materials", "migrations", "layers", "scene_sync",
    "native_backend", "builder", "importer", "core", "handlers",
    "operator_common", "operator_layers", "operator_import",
    "operator_sequence", "operator_render", "operator_procedural",
    "operator_project", "operators", "ui_icons", "ui_layout", "ui",
)

_loaded_modules = []
for _name in _MODULE_NAMES:
    _module = importlib.import_module(f".{_name}", __package__)
    if _name in globals():
        _module = importlib.reload(_module)
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
                except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError) as cleanup_exc:
                    _runtime_module.fbp_warn(f"Could not clean partial registration for {mod.__name__}", cleanup_exc)
            for previous in reversed(registered):
                rollback_fn = getattr(previous, "unregister", None)
                if not callable(rollback_fn):
                    continue
                try:
                    rollback_fn()
                except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError) as rollback_exc:
                    _runtime_module.fbp_warn(f"Could not roll back {previous.__name__}", rollback_exc)
            raise


def unregister():
    for mod in reversed(modules):
        unregister_fn = getattr(mod, "unregister", None)
        if not callable(unregister_fn):
            continue
        try:
            unregister_fn()
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError) as exc:
            _runtime_module.fbp_warn(f"Could not unregister {mod.__name__}", exc)
