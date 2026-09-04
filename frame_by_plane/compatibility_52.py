"""Cached Blender 5.2 LTS runtime contract for Frame By Plane.

The probes in this module are context-free and non-destructive. They validate
both API capabilities and the explicit pre-LTS release scope before any mutable
Frame By Plane subsystem is registered.
"""

from __future__ import annotations

import platform
import sys

import bpy

from .constants import (
    FBP_BLENDER_VERSION_MAX_EXCLUSIVE,
    FBP_BLENDER_VERSION_MIN,
    FBP_BLENDER_VERSION_MIN_STRING,
    FBP_BLENDER_VERSION_SERIES_STRING,
    FBP_LTS_TARGET_VERSION,
    FBP_RELEASE_CHANNEL,
    FBP_RELEASE_CHANNEL_LABEL,
    FBP_STRICT_RUNTIME_SCOPE,
    FBP_SUPPORTED_PLATFORM_IDS,
    FBP_SUPPORTED_PLATFORM_LABEL,
)


_REQUIRED_HANDLERS = (
    "depsgraph_update_pre",
    "depsgraph_update_post",
    "frame_change_pre",
    "frame_change_post",
    "render_init",
    "render_pre",
    "render_cancel",
    "render_complete",
    "undo_pre",
    "undo_post",
    "redo_pre",
    "redo_post",
    "load_pre",
    "load_post",
)
_CONTRACT_CACHE = None
_CONTRACT_CACHE_VERSION = None


def _rna_property(owner, name):
    try:
        rna = getattr(owner, "bl_rna", None)
        properties = getattr(rna, "properties", None)
        return properties.get(name) if properties is not None else None
    except (AttributeError, ReferenceError, RuntimeError, TypeError):
        return None


def _rna_function(owner, name):
    try:
        rna = getattr(owner, "bl_rna", None)
        functions = getattr(rna, "functions", None)
        return functions.get(name) if functions is not None else None
    except (AttributeError, ReferenceError, RuntimeError, TypeError):
        return None


def _first_type(*names):
    types = getattr(bpy, "types", None)
    if types is None:
        return None
    for name in names:
        value = getattr(types, name, None)
        if value is not None:
            return value
    return None


def _app_text(value):
    try:
        if isinstance(value, bytes):
            return value.decode("utf-8", "replace")
        return str(value or "")
    except (AttributeError, TypeError, UnicodeError, ValueError):
        return ""



def _machine_family():
    value = str(platform.machine() or "").strip().lower().replace("_", "-")
    if value in {"amd64", "x86-64", "x64"}:
        return "x64"
    if value in {"arm64", "aarch64"}:
        return "arm64"
    return value or "unknown"


def _runtime_platform_id():
    machine = _machine_family()
    if sys.platform.startswith("win"):
        return f"windows-{machine}"
    if sys.platform == "darwin":
        return f"macos-{machine}"
    if sys.platform.startswith("linux"):
        return f"linux-{machine}"
    return f"{sys.platform or 'unknown'}-{machine}"


def _runtime_policy(version, build):
    platform_id = _runtime_platform_id()
    return {
        "release_channel": FBP_RELEASE_CHANNEL,
        "release_channel_label": FBP_RELEASE_CHANNEL_LABEL,
        "lts_target_version": FBP_LTS_TARGET_VERSION,
        "blender_series": FBP_BLENDER_VERSION_SERIES_STRING,
        "blender_min": FBP_BLENDER_VERSION_MIN_STRING,
        "blender_max_exclusive": ".".join(str(part) for part in FBP_BLENDER_VERSION_MAX_EXCLUSIVE),
        "runtime_version": ".".join(str(part) for part in version),
        "runtime_platform": platform_id,
        "supported_platforms": tuple(FBP_SUPPORTED_PLATFORM_IDS),
        "supported_platform_label": FBP_SUPPORTED_PLATFORM_LABEL,
        "strict": bool(FBP_STRICT_RUNTIME_SCOPE),
        "version_cycle": str(build.get("version_cycle", "") or ""),
    }

def _build_date_number(value):
    text = "".join(ch for ch in _app_text(value) if ch.isdigit())
    try:
        return int(text[:8]) if len(text) >= 8 else 0
    except (TypeError, ValueError):
        return 0


def _blender_build_info():
    app = getattr(bpy, "app", None)
    return {
        "version_cycle": _app_text(getattr(app, "version_cycle", "")),
        "build_hash": _app_text(getattr(app, "build_hash", "")),
        "build_branch": _app_text(getattr(app, "build_branch", "")),
        "build_commit_date": _app_text(getattr(app, "build_commit_date", "")),
        "build_commit_time": _app_text(getattr(app, "build_commit_time", "")),
        "build_commit_timestamp": int(getattr(app, "build_commit_timestamp", 0) or 0),
        "background": bool(getattr(app, "background", False)),
    }


def _clone_report(report):
    return {
        "version": tuple(report.get("version", (0, 0, 0))),
        "build": dict(report.get("build", {})),
        "issues": tuple(report.get("issues", ())),
        "warnings": tuple(report.get("warnings", ())),
        "capabilities": dict(report.get("capabilities", {})),
        "policy": dict(report.get("policy", {})),
        "compatible": bool(report.get("compatible", False)),
    }


def invalidate_blender_52_runtime_contract():
    """Forget cached RNA capability descriptors after reload or Main replacement."""
    global _CONTRACT_CACHE, _CONTRACT_CACHE_VERSION
    _CONTRACT_CACHE = None
    _CONTRACT_CACHE_VERSION = None


def _action_channelbag_available():
    try:
        from bpy_extras.anim_utils import action_get_channelbag_for_slot
        return callable(action_get_channelbag_for_slot)
    except (ImportError, AttributeError, RuntimeError, TypeError):
        return False


def blender_52_runtime_contract(*, refresh=False):
    """Return a cached, non-destructive report for Blender 5.2 APIs used by FBP."""
    global _CONTRACT_CACHE, _CONTRACT_CACHE_VERSION
    version = tuple(getattr(bpy.app, "version", (0, 0, 0)))[:3]
    if (
        not refresh
        and _CONTRACT_CACHE is not None
        and _CONTRACT_CACHE_VERSION == version
    ):
        return _clone_report(_CONTRACT_CACHE)

    issues = []
    warnings = []
    build = _blender_build_info()
    policy = _runtime_policy(version, build)
    capabilities = {"version": version}

    if version < FBP_BLENDER_VERSION_MIN:
        issues.append(
            f"Blender {FBP_BLENDER_VERSION_MIN_STRING} or newer is required; "
            f"running {'.'.join(str(part) for part in version)}"
        )
    elif version >= FBP_BLENDER_VERSION_MAX_EXCLUSIVE:
        message = (
            f"This {FBP_RELEASE_CHANNEL_LABEL} build is validated only for Blender "
            f"{FBP_BLENDER_VERSION_SERIES_STRING}; running "
            f"{'.'.join(str(part) for part in version)}"
        )
        (issues if FBP_STRICT_RUNTIME_SCOPE else warnings).append(message)

    runtime_platform = str(policy.get("runtime_platform", "") or "")
    if runtime_platform not in FBP_SUPPORTED_PLATFORM_IDS:
        message = (
            f"This archive supports {FBP_SUPPORTED_PLATFORM_LABEL}; runtime platform is "
            f"{runtime_platform or 'unknown'}. Install the matching platform build."
        )
        (issues if FBP_STRICT_RUNTIME_SCOPE else warnings).append(message)

    version_cycle = str(build.get("version_cycle", "") or "").strip().lower()
    if version_cycle and version_cycle not in {"release", "lts"}:
        warnings.append(
            f"Blender build cycle is {version_cycle}; production validation targets an official 5.2 LTS release"
        )

    capabilities["supported_blender_series"] = (
        version >= FBP_BLENDER_VERSION_MIN and version < FBP_BLENDER_VERSION_MAX_EXCLUSIVE
    )
    capabilities["supported_platform"] = runtime_platform in FBP_SUPPORTED_PLATFORM_IDS

    handlers = getattr(bpy.app, "handlers", None)
    missing_handlers = tuple(name for name in _REQUIRED_HANDLERS if not hasattr(handlers, name))
    capabilities["handlers"] = not bool(missing_handlers)
    if missing_handlers:
        issues.append("Missing Blender handlers: " + ", ".join(missing_handlers))

    id_type = _first_type("ID")
    modifier_type = _first_type("Modifier")
    material_type = _first_type("Material")
    capabilities["id_session_uid"] = bool(
        id_type is not None and _rna_property(id_type, "session_uid") is not None
    )
    capabilities["modifier_persistent_uid"] = bool(
        modifier_type is not None and _rna_property(modifier_type, "persistent_uid") is not None
    )
    capabilities["modifier_execution_time"] = bool(
        modifier_type is not None and _rna_property(modifier_type, "execution_time") is not None
    )
    capabilities["material_surface_render_method"] = bool(
        material_type is not None and _rna_property(material_type, "surface_render_method") is not None
    )
    capabilities["render_job_query"] = callable(getattr(getattr(bpy, "app", None), "is_job_running", None))
    capabilities["background_mode"] = hasattr(getattr(bpy, "app", None), "background")

    data = getattr(bpy, "data", None)
    grease_pencils = getattr(data, "grease_pencils", None)
    grease_pencil_type = _first_type("GreasePencil")
    grease_pencil_layer_type = _first_type("GreasePencilLayer")
    grease_pencil_drawing_type = _first_type("GreasePencilDrawing")
    capabilities["grease_pencil"] = bool(grease_pencils is not None and grease_pencil_type is not None)
    capabilities["grease_pencil_layers"] = bool(grease_pencil_layer_type is not None)
    capabilities["grease_pencil_drawing"] = bool(grease_pencil_drawing_type is not None)
    capabilities["grease_pencil_operators"] = bool(
        getattr(getattr(bpy, "ops", None), "grease_pencil", None) is not None
    )

    nodes_modifier = _first_type("NodesModifier")
    node_tree = _first_type("NodeTree")
    geometry_node_tree = _first_type("GeometryNodeTree")
    capabilities["geometry_nodes"] = bool(
        nodes_modifier is not None
        and _rna_property(nodes_modifier, "node_group") is not None
        and node_tree is not None
        and geometry_node_tree is not None
    )
    # Blender 5.2 generates modifier.properties.inputs from the assigned group.
    # Its absence on the static NodesModifier class is expected.
    capabilities["geometry_nodes_dynamic_inputs"] = capabilities["geometry_nodes"]
    capabilities["geometry_nodes_panels"] = bool(
        nodes_modifier is not None and _rna_property(nodes_modifier, "panels") is not None
    )
    capabilities["geometry_nodes_warnings"] = bool(
        nodes_modifier is not None
        and _rna_property(nodes_modifier, "node_warnings") is not None
        and _first_type("NodesModifierWarning") is not None
    )

    node_tree_interface = _first_type("NodeTreeInterface")
    capabilities["node_interface"] = bool(
        node_tree is not None
        and _rna_property(node_tree, "interface") is not None
        and node_tree_interface is not None
        and _rna_function(node_tree_interface, "new_socket") is not None
    )
    capabilities["node_interface_panels"] = bool(
        capabilities["node_interface"]
        and _rna_function(node_tree_interface, "new_panel") is not None
        and _rna_function(node_tree_interface, "remove") is not None
    )

    render_settings = _first_type("RenderSettings")
    capabilities["texture_cache"] = bool(
        render_settings is not None and _rna_property(render_settings, "use_texture_cache") is not None
    )
    capabilities["anisotropic_filter"] = bool(
        render_settings is not None and _rna_property(render_settings, "anisotropic_filter") is not None
    )

    gp_brush_settings = _first_type("BrushGpencilSettings")
    capabilities["gp_curve_conversion"] = bool(
        gp_brush_settings is not None
        and _rna_property(gp_brush_settings, "curve_type") is not None
        and _rna_property(gp_brush_settings, "conversion_threshold") is not None
    )
    capabilities["gp_fill_gap"] = bool(
        gp_brush_settings is not None and _rna_property(gp_brush_settings, "fill_gap_factor") is not None
    )

    gp_style = _first_type("MaterialGPencilStyle")
    capabilities["gp_material_placement"] = bool(
        gp_style is not None and _rna_property(gp_style, "placement_mode") is not None
    )
    capabilities["gp_material_randomization"] = bool(
        gp_style is not None
        and _rna_property(gp_style, "random_size_factor") is not None
        and _rna_property(gp_style, "random_noise_scale") is not None
    )

    capabilities["action_channelbags"] = _action_channelbag_available()
    capabilities["principled_thin_wall"] = bool(
        version >= (5, 2, 0) and _first_type("ShaderNodeBsdfPrincipled") is not None
    )

    for label, key in (
        ("ID session identities", "id_session_uid"),
        ("Modifier persistent identities", "modifier_persistent_uid"),
        ("Modifier execution timing", "modifier_execution_time"),
        ("Material surface render method", "material_surface_render_method"),
        ("Render job query", "render_job_query"),
        ("Grease Pencil drawing RNA", "grease_pencil_drawing"),
        ("Geometry Nodes modifier panels", "geometry_nodes_panels"),
        ("Geometry Nodes evaluation warnings", "geometry_nodes_warnings"),
        ("Geometry Nodes interface panels", "node_interface_panels"),
        ("Render texture cache", "texture_cache"),
        ("Render anisotropic filtering", "anisotropic_filter"),
        ("Action channelbags", "action_channelbags"),
    ):
        if not capabilities.get(key, False):
            warnings.append(f"Optional Blender 5.2 capability unavailable: {label}")

    build_date = _build_date_number(build.get("build_commit_date", ""))
    if version[:2] == (5, 2) and build_date:
        if build_date < 20260703:
            warnings.append(
                "This Blender 5.2 build predates the Geometry Nodes Grease Pencil Cycles/background-render fix"
            )
        if build_date < 20260713:
            warnings.append(
                "This Blender 5.2 build predates the Grease Pencil hidden-material visibility fix"
            )

    report = {
        "version": version,
        "build": build,
        "issues": tuple(issues),
        "warnings": tuple(warnings),
        "capabilities": capabilities,
        "policy": policy,
        "compatible": not bool(issues),
    }
    _CONTRACT_CACHE = _clone_report(report)
    _CONTRACT_CACHE_VERSION = version
    return _clone_report(report)


def blender_52_capability(name, default=False):
    return bool(blender_52_runtime_contract().get("capabilities", {}).get(str(name), default))


def assert_supported_runtime():
    """Fail before registration when the active build is outside LTS scope."""
    report = blender_52_runtime_contract(refresh=True)
    if report["issues"]:
        raise RuntimeError("; ".join(report["issues"]))
    return report


def register():
    invalidate_blender_52_runtime_contract()


def unregister():
    invalidate_blender_52_runtime_contract()
