import importlib
import os
import time




_IS_BACKGROUND = bool(getattr(__import__("bpy").app, "background", False))
_IS_FBP_RENDER_CHILD = bool(_IS_BACKGROUND and os.environ.get("FBP_BACKGROUND_RENDER_CHILD") == "1")
_PROFILE_ENV_ENABLED = str(os.environ.get("FBP_PROFILE", "") or "").strip().lower() in {
    "1", "true", "yes", "on",
}
_FBP_STARTUP_PROFILE = {
    "enabled_at_import": bool(_PROFILE_ENV_ENABLED),
    "import_total_ms": 0.0,
    "module_imports": [],
    "register_total_ms": 0.0,
    "module_registers": [],
    "registered_classes": 0,
}

_MODULE_NAMES = (
    "support_policy", "constants", "math_utils", "color_names", "feature_scope", "compatibility_52", "matrix_presets", "path_utils", "alpha_crop", "runtime", "service_registry", "runtime_scheduler", "managed_timers", "interface_preferences", "preference_application", "registration", "ui_list_state", "node_sockets", "ui_context", "compositor_contracts", "render_output", "fbp_index", "storage_keys",
    "identifiers", "ownership",
    "safe_tasks", "transactions", "generation_transaction", "project_schema", "fbp_dirty", "lifecycle", "effect_schema", "effect_instances", "object_masks",
    # Register Object properties before the Effects UI/handler. On unregister
    # the reverse order removes the frame handler before deleting its RNA props.
    "properties", "layer_tree_snapshot", "shortcut_runtime", "motion_runtime", "grease_pencil_scrub", "grease_pencil_bridge", "layer_sets", "grease_pencil_workflow", "grease_pencil_limited_loop", "feedback", "custom_effects", "effects_registry", "geometry_nodes", "mask_stack", "effect_stack_presets", "effect_controls", "materials", "layers", "layer_filters", "visibility_snapshots", "compositor", "compositor_sets", "projector", "live_tutorial", "scene_sync", "persistence",
    "native_backend", "builder", "procreate_import", "layered_import", "importer", "core", "drawing_plane", "handlers",
    "operator_common", "operator_layers", "operator_import",
    "operator_sequence", "operator_render", "operator_procedural",
    "performance_dashboard", "project_health", "actionable_issues", "operator_project", "operators", "ui_icons", "ui_layout", "ui", "compositor_layer_node", "viewport_pie", "tooltips",
)
if _IS_BACKGROUND:
    # Purely interactive modules are neither imported nor registered in a
    # background process. The dedicated FBP render child goes further and omits
    # authoring and import modules; operator_render registers only
    # its lightweight render-state validator in that process.
    _BACKGROUND_SKIP_MODULES = {"feedback", "live_tutorial", "grease_pencil_scrub", "ui", "viewport_pie", "tooltips"}
    if _IS_FBP_RENDER_CHILD:
        _BACKGROUND_SKIP_MODULES.update({
            "procreate_import", "layered_import", "importer",
            "operator_layers", "operator_import", "operator_sequence",
            "operator_procedural", "performance_dashboard", "project_health", "actionable_issues", "operator_project", "compositor_layer_node",
            "operators",
        })
    _MODULE_NAMES = tuple(name for name in _MODULE_NAMES if name not in _BACKGROUND_SKIP_MODULES)

_loaded_modules = []
_imports_started = time.perf_counter() if _PROFILE_ENV_ENABLED else 0.0
for _name in _MODULE_NAMES:
    # Check before importing. import_module() automatically exposes the
    # submodule on this package, so checking globals afterwards caused every
    # module to be imported and immediately reloaded even on the first enable.
    _existing_module = globals().get(_name)
    _module_started = time.perf_counter() if _PROFILE_ENV_ENABLED else 0.0
    if _existing_module is None:
        _module = importlib.import_module(f".{_name}", __package__)
        _import_mode = "import"
    else:
        _module = importlib.reload(_existing_module)
        _import_mode = "reload"
    globals()[_name] = _module
    _loaded_modules.append(_module)
    if _PROFILE_ENV_ENABLED:
        _FBP_STARTUP_PROFILE["module_imports"].append({
            "module": _name,
            "mode": _import_mode,
            "milliseconds": round((time.perf_counter() - _module_started) * 1000.0, 6),
        })

if _PROFILE_ENV_ENABLED:
    _FBP_STARTUP_PROFILE["import_total_ms"] = round(
        (time.perf_counter() - _imports_started) * 1000.0,
        6,
    )

# Keep the heavy procedural builders lazy on a normal enable. During an
# in-place development reload, refresh them only when they were already loaded
# by an effect request in the current Blender session.
_existing_builtin_effects = globals().get("builtin_effects")
if _existing_builtin_effects is not None:
    globals()["builtin_effects"] = importlib.reload(_existing_builtin_effects)

modules = tuple(_loaded_modules)
_runtime_module = globals()["runtime"]


def _profile_enabled():
    """Return the process-local profiler state without reading project data."""
    if _PROFILE_ENV_ENABLED:
        return True
    try:
        return bool(_runtime_module.fbp_runtime_get("fbp_profile_enabled", False))
    except (AttributeError, TypeError, ValueError):
        return False


def fbp_startup_profile_snapshot():
    """Return primitive-only import/register timings for local diagnostics."""
    return {
        "enabled": bool(_profile_enabled()),
        "enabled_at_import": bool(_FBP_STARTUP_PROFILE["enabled_at_import"]),
        "import_total_ms": float(_FBP_STARTUP_PROFILE["import_total_ms"]),
        "register_total_ms": float(_FBP_STARTUP_PROFILE["register_total_ms"]),
        "registered_classes": int(_FBP_STARTUP_PROFILE["registered_classes"]),
        "module_imports": tuple(dict(item) for item in _FBP_STARTUP_PROFILE["module_imports"]),
        "module_registers": tuple(dict(item) for item in _FBP_STARTUP_PROFILE["module_registers"]),
    }


def _registered_addon_class_count():
    classes = set()
    for module in modules:
        for value in vars(module).values():
            if not isinstance(value, type):
                continue
            if not str(getattr(value, "__module__", "")).startswith(f"{__package__}."):
                continue
            if "bl_rna" in vars(value):
                classes.add(value)
    return len(classes)

# Apply centralized hover help only for interactive Blender. Background render
# children have no UI and avoid traversing every operator/panel class at startup.
if not _IS_BACKGROUND:
    globals()["tooltips"].apply_tooltips(modules)


def _quiesce_deferred_runtime():
    """Close every deferred-work gate before Blender RNA teardown begins."""
    failures = []
    operations = (
        ("runtime callbacks", globals().get("runtime"), "fbp_quiesce_runtime_callbacks"),
        ("runtime scheduler", globals().get("runtime_scheduler"), "quiesce_scheduler"),
        ("safe tasks", globals().get("safe_tasks"), "bump_task_epoch"),
        ("managed timers", globals().get("managed_timers"), "fbp_bump_timer_epoch"),
        ("Scrub Bar modal", globals().get("grease_pencil_scrub"), "quiesce_scrub_runtime"),
        ("Live Tutorial modal", globals().get("live_tutorial"), "quiesce_live_tutorial"),
        ("feedback popup", globals().get("feedback"), "quiesce_feedback_runtime"),
        ("generation modal", globals().get("operator_common"), "quiesce_generation_runtime"),
        ("background render monitor", globals().get("operator_render"), "quiesce_background_render_runtime"),
        ("active transactions", globals().get("transactions"), "abort_active_transactions"),
        ("incremental generation", globals().get("generation_transaction"), "retire_active_generation"),
    )
    for label, module, function_name in operations:
        if module is None:
            continue
        callback = getattr(module, function_name, None)
        if not callable(callback):
            continue
        try:
            callback()
        except Exception as exc:
            failures.append((label, exc))
    for label, exc in failures:
        try:
            _runtime_module.fbp_error(
                f"Could not quiesce {label}",
                exc,
                event="addon.quiesce_runtime",
                context={"service": label},
            )
        except Exception:
            pass
    return not failures


def _set_registration_runtime_state(state, *, busy):
    """Update primitive lifecycle markers without retaining Blender RNA."""
    state_callback = getattr(_runtime_module, "fbp_set_registration_state", None)
    if callable(state_callback):
        state_callback(state)
    _runtime_module.fbp_set_registration_busy(bool(busy))


def _rollback_failed_registration(current_module, registered, original_error):
    """Roll back one failed registration transaction in strict reverse order."""
    rollback_safe = bool(_quiesce_deferred_runtime())
    failed_module_name = str(
        getattr(current_module, "__name__", "preflight") or "preflight"
    )
    try:
        _runtime_module.fbp_error(
            f"Registration failed in {failed_module_name}",
            original_error,
            event="addon.register_module",
            context={"module": failed_module_name},
        )
    except Exception:
        rollback_safe = False

    rollback_modules = []
    if current_module is not None:
        rollback_modules.append((current_module, "addon.rollback_partial_module"))
    rollback_modules.extend(
        (previous, "addon.rollback_module") for previous in reversed(registered)
    )
    for rollback_module, event_name in rollback_modules:
        rollback_fn = getattr(rollback_module, "unregister", None)
        if not callable(rollback_fn):
            continue
        try:
            rollback_fn()
        except Exception as rollback_exc:
            rollback_safe = False
            try:
                _runtime_module.fbp_error(
                    f"Could not roll back {rollback_module.__name__}",
                    rollback_exc,
                    event=event_name,
                    context={"module": rollback_module.__name__},
                )
            except Exception:
                pass
    # A failed module can schedule work immediately before raising. Quiesce a
    # second time after all unregister callbacks have completed.
    rollback_safe = bool(_quiesce_deferred_runtime()) and rollback_safe
    return rollback_safe


def register():
    registered = []
    current_module = None
    completed = False
    rollback_safe = True
    profile_enabled = _profile_enabled()
    register_started = time.perf_counter() if profile_enabled else 0.0
    if profile_enabled:
        _FBP_STARTUP_PROFILE["module_registers"] = []
    _set_registration_runtime_state("REGISTERING", busy=True)
    try:
        globals()["compatibility_52"].assert_supported_runtime()
        for mod in modules:
            register_fn = getattr(mod, "register", None)
            if not callable(register_fn):
                continue
            current_module = mod
            module_started = time.perf_counter() if profile_enabled else 0.0
            register_fn()
            if profile_enabled:
                _FBP_STARTUP_PROFILE["module_registers"].append({
                    "module": str(getattr(mod, "__name__", "")).rsplit(".", 1)[-1],
                    "milliseconds": round(
                        (time.perf_counter() - module_started) * 1000.0,
                        6,
                    ),
                })
            registered.append(mod)
            current_module = None
        completed = True
    except Exception as exc:
        rollback_safe = _rollback_failed_registration(
            current_module,
            registered,
            exc,
        )
        raise
    finally:
        if completed:
            if profile_enabled:
                _FBP_STARTUP_PROFILE["register_total_ms"] = round(
                    (time.perf_counter() - register_started) * 1000.0,
                    6,
                )
                _FBP_STARTUP_PROFILE["registered_classes"] = (
                    _registered_addon_class_count()
                )
            _set_registration_runtime_state("ACTIVE", busy=False)
        else:
            _set_registration_runtime_state(
                "FAILED" if rollback_safe else "FAILED_UNSAFE",
                busy=not rollback_safe,
            )


def unregister():
    teardown_safe = True
    _set_registration_runtime_state("TEARDOWN", busy=True)
    try:
        # Stop every timer/task before any module starts unregistering classes
        # or deleting properties.
        teardown_safe = bool(_quiesce_deferred_runtime()) and teardown_safe

        # Leave Grease Pencil/Paint modes before Blender starts freeing Brush
        # data. This remains best-effort but is reflected in lifecycle state.
        try:
            gp_bridge = globals().get("grease_pencil_bridge")
            prepare_shutdown = getattr(gp_bridge, "prepare_shutdown", None)
            if callable(prepare_shutdown):
                prepare_shutdown()
        except Exception as exc:
            teardown_safe = False
            _runtime_module.fbp_error(
                "Could not prepare Grease Pencil shutdown",
                exc,
                event="addon.prepare_shutdown",
            )
        for mod in reversed(modules):
            unregister_fn = getattr(mod, "unregister", None)
            if not callable(unregister_fn):
                continue
            try:
                unregister_fn()
            except Exception as exc:
                teardown_safe = False
                _runtime_module.fbp_error(
                    f"Could not unregister {mod.__name__}",
                    exc,
                    event="addon.unregister_module",
                    context={"module": mod.__name__},
                )
    finally:
        teardown_safe = bool(_quiesce_deferred_runtime()) and teardown_safe
        _set_registration_runtime_state(
            "INACTIVE" if teardown_safe else "FAILED_UNSAFE",
            busy=not teardown_safe,
        )
