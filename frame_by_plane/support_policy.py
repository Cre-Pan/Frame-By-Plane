"""Runtime support and feature policy for Frame By Plane 7.1 LTS."""

from __future__ import annotations



FBP_LTS_TARGET_VERSION = "7.1.10"
FBP_LTS_BLENDER_SERIES = "5.2"
FBP_LTS_PLATFORM_IDS = (
    "windows-x64",
    "windows-arm64",
    "macos-x64",
    "macos-arm64",
    "linux-x64",
)
FBP_LTS_PLATFORM_LABEL = (
    "Windows x64/ARM64, macOS Intel/Apple Silicon and Linux x64"
)
FBP_LTS_SUPPORT_STATEMENT = (
    "Frame By Plane 7.1 LTS is supported on Blender 5.2.x for Windows "
    "x64/ARM64, macOS Intel/Apple Silicon and Linux x64."
)

FBP_FEATURE_SCOPE_SCHEMA = 2
FBP_FEATURE_LTS = "LTS"
FBP_FEATURE_PREVIEW = "PREVIEW"
FBP_FEATURE_DEFINITIONS = (
    {
        "id": "layer_workflow",
        "label": "Layer and Collection Workflow",
        "maturity": FBP_FEATURE_LTS,
        "description": "Layer ordering, grouping, visibility, color tags and native Frame By Plane object ownership.",
        "scene_property": "",
        "preference_property": "",
    },
    {
        "id": "media_import",
        "label": "Image, Sequence and Video Import",
        "maturity": FBP_FEATURE_LTS,
        "description": "Image, numbered-sequence and movie import through the native Frame By Plane layer workflow.",
        "scene_property": "",
        "preference_property": "",
    },
    {
        "id": "psd_import",
        "label": "PSD / PSB Import",
        "maturity": FBP_FEATURE_LTS,
        "description": "Layered Photoshop import with safe raster fallbacks and import reporting.",
        "scene_property": "",
        "preference_property": "",
    },
    {
        "id": "source_refresh",
        "label": "Source Refresh and Relink",
        "maturity": FBP_FEATURE_LTS,
        "description": "Refresh images, sequences and movies while preserving layer state.",
        "scene_property": "",
        "preference_property": "",
    },
    {
        "id": "grease_pencil_workflow",
        "label": "Grease Pencil and Scrub Bar",
        "maturity": FBP_FEATURE_LTS,
        "description": "Draw, Edit, Sculpt and Object workflows, key editing, persistent Scrub Bar and Undo isolation.",
        "scene_property": "",
        "preference_property": "",
    },
    {
        "id": "mask_stack",
        "label": "Mask Stack",
        "maturity": FBP_FEATURE_LTS,
        "description": "Shape, imported and Grease Pencil masks with contract auditing.",
        "scene_property": "",
        "preference_property": "",
    },
    {
        "id": "effect_stack",
        "label": "Plane and Grease Pencil Effects",
        "maturity": FBP_FEATURE_LTS,
        "description": "Frozen built-in effect identifiers, effect stacks, presets and supported plane/Grease Pencil targets.",
        "scene_property": "",
        "preference_property": "",
    },
    {
        "id": "project_render",
        "label": "Project Doctor, Persistence and Render",
        "maturity": FBP_FEATURE_LTS,
        "description": "Project diagnostics, persistence checks, save/reopen, Eevee/Cycles contracts and render workflow.",
        "scene_property": "",
        "preference_property": "",
    },
    {
        "id": "compositor_layers",
        "label": "Compositor Layers",
        "maturity": FBP_FEATURE_PREVIEW,
        "description": "Generated View Layers, compositor layer packages and output nodes.",
        "scene_property": "fbp_experimental_compositor",
        "preference_property": "default_preview_compositor",
        "disable_hint": "Disable Compositor Preview for an LTS-only project.",
    },
    {
        "id": "procreate_import",
        "label": "Procreate Import",
        "maturity": FBP_FEATURE_PREVIEW,
        "description": "Local Procreate archive/tile decoding with a flattened preview fallback.",
        "scene_property": "fbp_preview_procreate_import",
        "preference_property": "default_preview_procreate_import",
        "disable_hint": "Disable Procreate Preview for an LTS-only project.",
    },
    {
        "id": "generic_mesh_effects",
        "label": "Generic Mesh Effects",
        "maturity": FBP_FEATURE_PREVIEW,
        "description": "Apply selected Frame By Plane Geometry Nodes effects to ordinary meshes.",
        "scene_property": "fbp_preview_generic_mesh_effects",
        "preference_property": "default_preview_generic_mesh_effects",
        "disable_hint": "Disable Generic Mesh Preview for an LTS-only project.",
    },
)

FBP_LTS_CORE_SCOPE = tuple(
    item["label"] for item in FBP_FEATURE_DEFINITIONS
    if item["maturity"] == FBP_FEATURE_LTS
)
FBP_LTS_PREVIEW_SCOPE = tuple(
    item["label"] for item in FBP_FEATURE_DEFINITIONS
    if item["maturity"] == FBP_FEATURE_PREVIEW
)

FBP_LTS_SOURCE_FORMATS = {
    "images": (
        ".avif", ".bmp", ".dds", ".exr", ".gif", ".hdr", ".j2k", ".jp2",
        ".jpeg", ".jpg", ".pic", ".png", ".rgb", ".rgba", ".sgi", ".tif",
        ".tiff", ".webp",
    ),
    "videos": (".avi", ".m4v", ".mkv", ".mov", ".mp4", ".mpeg", ".mpg", ".mxf", ".ogv", ".webm"),
    "layered_lts": (".psb", ".psd"),
    "layered_preview": (".procreate",),
}

FBP_LTS_COMPATIBILITY_POLICY = {
    "public_bl_idname": "Frozen for the complete 7.1.x line. Renames require a compatibility alias.",
    "persistent_rna": "Saved RNA names and Frame By Plane IDProperty keys are frozen for the complete 7.1.x line.",
    "effect_ids": "Built-in effect and mask IDs are frozen. Display labels may change without changing IDs.",
    "schemas": "Frame By Plane 7.1 is the supported persistent-data baseline. Newer schemas must be rejected safely rather than guessed or converted implicitly.",
    "python_api": "Internal Python functions may move. Documented public helpers require a forwarding alias through 7.1.x.",
    "preview": "Preview APIs and data remain readable but are excluded from the LTS stability promise.",
}

FBP_API_CLASSIFICATIONS = ("PUBLIC", "INTERNAL", "PREVIEW")


__all__ = (
    "FBP_API_CLASSIFICATIONS",
    "FBP_FEATURE_DEFINITIONS",
    "FBP_FEATURE_LTS",
    "FBP_FEATURE_PREVIEW",
    "FBP_FEATURE_SCOPE_SCHEMA",
    "FBP_LTS_BLENDER_SERIES",
    "FBP_LTS_COMPATIBILITY_POLICY",
    "FBP_LTS_CORE_SCOPE",
    "FBP_LTS_PLATFORM_IDS",
    "FBP_LTS_PLATFORM_LABEL",
    "FBP_LTS_PREVIEW_SCOPE",
    "FBP_LTS_SOURCE_FORMATS",
    "FBP_LTS_SUPPORT_STATEMENT",
    "FBP_LTS_TARGET_VERSION",
)
