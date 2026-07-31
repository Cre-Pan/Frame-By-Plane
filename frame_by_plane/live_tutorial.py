# SPDX-License-Identifier: GPL-3.0-or-later
"""Frame By Plane — Live Tutorial

Blender 5.2 interactive tutorial overlay.

The module uses a compact top-center HUD that inherits Blender's active theme.
Flat contextual controls launch the required tools, and unhandled input passes
through so the user can keep working normally.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Iterable
import math
import time

import bpy
import blf
import gpu
from gpu_extras.batch import batch_for_shader

from .effects_registry import fbp_effect_definition
from .geometry_nodes import fbp_effect_ids_for_rig
from .grease_pencil_bridge import gp_mask_canvas_for_rig
from .layers import (
    fbp_layer_backend_type,
    fbp_resolve_rig_from_any_object,
    is_fbp_layer_object,
    iter_scene_fbp_rigs,
)
from .materials import rig_holdout_is_active
from .interface_preferences import fbp_get_addon_preferences
from .ui_style import configure_layout, section_header
from .registration import register_interactive_classes, unregister_classes
from .runtime import FBP_DATA_ERRORS


_PREVIOUS_TUTORIAL_OPERATOR = globals().get("_ACTIVE_OPERATOR")


def _retire_previous_tutorial_operator_early():
    operator = _PREVIOUS_TUTORIAL_OPERATOR
    if operator is None:
        return False
    try:
        operator._close(bpy.context)
        return True
    except FBP_DATA_ERRORS:
        return False


_PREVIOUS_TUTORIAL_RETIRED = _retire_previous_tutorial_operator_early()


# -----------------------------------------------------------------------------
# Configuration

DETECTION_INTERVAL = 0.45

@dataclass(frozen=True, slots=True)
class TaskSpec:
    key: str
    label: str
    icon: str
    detector: str
    optional: bool = False


@dataclass(frozen=True, slots=True)
class PageSpec:
    title: str
    subtitle: str
    icon: str
    description: tuple[str, ...]
    shortcut: tuple[tuple[str, str], ...] = ()
    tasks: tuple[TaskSpec, ...] = ()
    pro_tip: str = ""
    help_title: str = ""
    help_steps: tuple[str, ...] = ()
    help_notes: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class RouteSpec:
    key: str
    title: str
    subtitle: str
    icon: str
    pages: tuple[PageSpec, ...]


ROUTES: dict[str, RouteSpec] = {
    "IMAGE": RouteSpec(
        key="IMAGE",
        title="Create your first Frame By Plane",
        subtitle="Import, frame, mask and style a single image.",
        icon="IMAGE",
        pages=(
            PageSpec(
                title="Import and frame your image",
                subtitle="Create a Single Plane, then frame it with the Z-menu handles.",
                icon="IMAGE",
                description=(
                    "Start with any supported image. Move, rotate and scale the resulting plane",
                    "as a normal Blender object, then adjust its visible canvas.",
                ),
                shortcut=(("KEY", "Shift + A"), ("TEXT", "Frame By Plane"), ("IMAGE", "Single Plane")),
                tasks=(
                    TaskSpec("image_open_importer", "Open Single Plane", "IMAGE", ""),
                    TaskSpec("image_import", "Choose an image", "IMAGE", "image_import"),
                    TaskSpec("image_open_crop", "Open Crop / Expand", "CROP", "crop_open"),
                    TaskSpec("image_crop", "Adjust the visible canvas", "CROP", "image_crop"),
                ),
                pro_tip="Press Z, choose Crop or Expand, then drag the existing edge controllers directly in the viewport.",
                help_title="Import & Framing",
                help_steps=(
                    "Move the pointer over the 3D Viewport.",
                    "Press Shift + A, open Frame By Plane, then choose Single Plane.",
                    "Select an image and confirm the import.",
                    "Press Z and choose Crop or Expand. No popup is needed: use the visible edge handles.",
                ),
                help_notes=(
                    "Crop hides pixels without changing the original file.",
                    "Expand adds transparent canvas around the source image.",
                ),
            ),
            PageSpec(
                title="Mask and style the plane",
                subtitle="Draw a Grease Pencil mask, then add Pixelate from Modifiers.",
                icon="MASK",
                description=(
                    "Masks and image effects remain non-destructive. You can reorder, disable",
                    "or edit them later from the Frame By Plane effect stack.",
                ),
                shortcut=(("KEY", "Z"), ("MASK", "Grease Pencil Mask"), ("TEXT", "then"), ("EFFECT", "Modifiers > Pixelate")),
                tasks=(
                    TaskSpec("image_mask", "Add a Grease Pencil Mask", "MASK", "image_mask"),
                    TaskSpec("image_open_effects", "Open the Modifiers tab", "EFFECT", "effects_2d_open"),
                    TaskSpec("image_effect", "Add the Pixelate effect", "EFFECT", "image_effect"),
                ),
                pro_tip="The wrench icon in Properties opens the real non-destructive Frame By Plane effect stack.",
                help_title="Grease Pencil Mask & Pixelate",
                help_steps=(
                    "Select the imported plane.",
                    "Press Z and choose Grease Pencil Mask, then draw the matte in native Draw Mode.",
                    "When the mask is ready, open Properties and click the wrench (Modifiers).",
                    "In the unified Frame By Plane Effect Stack, add Pixelate and adjust its controls.",
                ),
                help_notes=(
                    "The mask and effect stack can be reordered at any time.",
                    "Pixelate remains editable and can be restricted by the Grease Pencil mask.",
                ),
            ),
            PageSpec(
                title="Single Plane explored",
                subtitle="Keep experimenting or return to the tutorial library.",
                icon="CHECK",
                description=(
                    "You now have the essential single-image workflow: import, framing,",
                    "masking and non-destructive image effects.",
                ),
                tasks=(
                    TaskSpec("image_import", "Single Plane", "IMAGE", "image_import"),
                    TaskSpec("image_crop", "Crop / Expand", "CROP", "image_crop"),
                    TaskSpec("image_mask", "Mask", "MASK", "image_mask"),
                    TaskSpec("image_effect", "2D Effect", "EFFECT", "image_effect"),
                ),
                help_title="Single Plane Recap",
                help_steps=(
                    "Import through Shift + A > Frame By Plane > Single Plane.",
                    "Frame the image with Crop / Expand.",
                    "Use a mask for local control.",
                    "Add and reorder 2D effects.",
                ),
            ),
        ),
    ),
    "COLOR": RouteSpec(
        key="COLOR",
        title="Create an animated Color Plane",
        subtitle="Build colors, gradients, animation and geometry effects.",
        icon="COLOR",
        pages=(
            PageSpec(
                title="Build a procedural Color Plane",
                subtitle="Generate the plane, add colors and create a gradient.",
                icon="COLOR",
                description=(
                    "A Color Plane needs no external image. It is useful for backgrounds,",
                    "graphic shapes, cards, matte elements and motion design.",
                ),
                shortcut=(("KEY", "Shift + A"), ("TEXT", "Frame By Plane"), ("COLOR", "Color Plane")),
                tasks=(
                    TaskSpec("color_open_creator", "Open Color Plane", "COLOR", ""),
                    TaskSpec("color_generate", "Generate a Color Plane", "COLOR", "color_generate"),
                    TaskSpec("color_open_settings", "Open Layer Settings", "PALETTE", "layer_settings_open"),
                    TaskSpec("color_edit", "Edit its colors", "PALETTE", "color_edit"),
                    TaskSpec("color_add_gradient", "Add a Gradient frame", "GRADIENT", "color_gradient"),
                    TaskSpec("color_gradient_edit", "Edit the Gradient", "GRADIENT", "color_gradient_edit"),
                    TaskSpec("color_preview", "View it in Material Preview", "MATERIAL", "color_preview"),
                ),
                pro_tip="Press Z and switch to Material Preview to see the procedural gradient correctly in the Viewport.",
                help_title="Color Plane",
                help_steps=(
                    "Press Shift + A, open Frame By Plane, then choose Color Plane.",
                    "Open Layer Settings: the Frames UI List already contains the first Color row.",
                    "Select that row and edit its color in Frame Appearance.",
                    "Use the custom Gradient Plane + icon beside Frames to add a Gradient row.",
                    "Select the Gradient row and edit color stops, position, rotation and scale.",
                    "Press Z and choose Material Preview to see the material result.",
                ),
                help_notes=(
                    "Solid shading does not display the full material result.",
                    "Each Frames UI List row stores an independent Color or Gradient appearance.",
                ),
            ),
            PageSpec(
                title="Animate with procedural frames",
                subtitle="Add Color or Gradient rows, then add a mesh-based effect.",
                icon="ANIMATE",
                description=(
                    "Color Planes animate through the Frames UI List. Each row keeps its own",
                    "appearance and duration; no I-keyframes are required for this workflow.",
                ),
                shortcut=(("ANIMATE", "Frames"), ("COLOR", "Add Color / Gradient Frame"), ("MESH", "Mesh Effect")),
                tasks=(
                    TaskSpec("color_add_frame", "Add another Color or Gradient frame", "ANIMATE", "color_animate"),
                    TaskSpec("color_open_mesh_effects", "Open Mesh Effects", "MESH", "effects_3d_open"),
                    TaskSpec("color_mesh", "Add one mesh effect", "MESH", "color_mesh"),
                ),
                pro_tip="Set a different duration per row, reorder or duplicate frames, and mix Color, Gradient and Transparent rows in one procedural animation.",
                help_title="Frames & Mesh Effects",
                help_steps=(
                    "Select the Color Plane and open Layer Settings > Frames.",
                    "Use the custom Color Plane or Gradient Plane + icon beside the Frames UI List.",
                    "The new row is inserted after the active row, or after the last checked row.",
                    "Select the new row and edit its colors or gradient in Frame Appearance.",
                    "Adjust each row duration, reorder or duplicate rows, then preview from the timeline.",
                    "Press Z and choose a favourite 3D effect, or open Effects & Masks > Mesh.",
                    "Add Extrude, Bend, Lattice, Surface Conform, Sphere Screen or another mesh effect.",
                ),
                help_notes=(
                    "Pressing I is not required: Color Plane animation is driven by the ordered Frames UI List.",
                    "Gradient rows are useful for light sweeps; Transparent rows create visible pauses or cuts.",
                    "Mesh effects preserve the procedural material.",
                ),
            ),
            PageSpec(
                title="Animated Color Plane explored",
                subtitle="The procedural workflow is ready for further design.",
                icon="CHECK",
                description=(
                    "You created a material-driven plane that can be animated and modified",
                    "geometrically without relying on an imported texture.",
                ),
                tasks=(
                    TaskSpec("color_generate", "Color Plane", "COLOR", "color_generate"),
                    TaskSpec("color_add_gradient", "Gradient", "GRADIENT", "color_gradient"),
                    TaskSpec("color_add_frame", "Animation", "ANIMATE", "color_animate"),
                    TaskSpec("color_mesh", "Mesh Effect", "MESH", "color_mesh"),
                ),
                help_title="Color Plane Recap",
                help_steps=(
                    "Generate the Color Plane.",
                    "Build the color or gradient in Material Preview.",
                    "Add and arrange Color or Gradient rows in the Frames UI List.",
                    "Add a geometry effect.",
                ),
            ),
        ),
    ),
    "MULTIPLANE": RouteSpec(
        key="MULTIPLANE",
        title="Create a Multiplane Setup",
        subtitle="Import organized layers, set depth and build masks.",
        icon="MULTIPLANE",
        pages=(
            PageSpec(
                title="Prepare and import the artwork",
                subtitle="Use clear names; unsupported and temporary files are skipped.",
                icon="FOLDER",
                description=(
                    "Recommended example: 01_BG.png, 02_Mountains.png, 03_Character/0001.png,",
                    "04_Foreground.png. Numeric prefixes make the intended order explicit.",
                ),
                shortcut=(("KEY", "Shift + A"), ("TEXT", "Frame By Plane"), ("FOLDER", "Multiplane Project")),
                tasks=(
                    TaskSpec("multi_open_importer", "Open Multiplane Project", "MULTIPLANE", ""),
                    TaskSpec("multi_generate", "Generate a multiplane setup", "MULTIPLANE", "multi_generate"),
                ),
                help_title="Multiplane Import",
                help_steps=(
                    "Place one visual layer in each file or numbered sequence folder.",
                    "Use prefixes such as 01_BG, 02_Midground, 03_Character and 04_FG.",
                    "Press Shift + A > Frame By Plane > Multiplane Project.",
                    "Review the import report for imported and skipped files.",
                ),
                help_notes=(
                    "Accepted: PNG, JPG, TIFF, EXR, numbered sequences and supported video formats.",
                    "Skipped: hidden files, thumbnails, temporary files, empty folders and unsupported formats.",
                ),
            ),
            PageSpec(
                title="Set the camera and create depth",
                subtitle="Distribute the layers in space and preserve their framing.",
                icon="CAMERA",
                description=(
                    "Place background, midground and foreground at different distances.",
                    "Scale layers as needed, then move the camera to preview parallax.",
                ),
                shortcut=(("CAMERA", "Frame By Plane Camera"), ("KEY", "G / S"), ("KEY", "Z > Cursor to Selected")),
                tasks=(
                    TaskSpec("multi_open_camera", "Open Camera Setup", "CAMERA", ""),
                    TaskSpec("multi_camera", "Set an active camera", "CAMERA", "multi_camera"),
                    TaskSpec("multi_start_depth", "Start moving a layer", "DEPTH", ""),
                    TaskSpec("multi_depth", "Separate layers in depth", "DEPTH", "multi_depth"),
                ),
                pro_tip="Cursor to Selected from the Z Pie Menu makes local scaling and rotation around the chosen layer faster.",
                help_title="Camera & Depth",
                help_steps=(
                    "Create a Frame By Plane Camera or select the existing scene camera.",
                    "Select a layer and move it away from the camera.",
                    "Scale it to preserve the desired framing.",
                    "Repeat for foreground and background layers.",
                    "Move the camera slightly to preview parallax.",
                ),
                help_notes=(
                    "Close layers move faster; distant layers move more slowly.",
                    "Check the camera clipping range if a layer disappears.",
                ),
            ),
            PageSpec(
                title="Timing, effects and layer relationships",
                subtitle="Configure animated media, then test clipping and holdout.",
                icon="LAYERS",
                description=(
                    "Animated layers can use independent timing and loop modes. Effects,",
                    "clipping masks and holdouts add depth and local compositing control.",
                ),
                shortcut=(("KEY", "Z"), ("MASK", "Masks / Favourite Effects"), ("TEXT", "or"), ("EFFECT", "Effects & Masks")),
                tasks=(
                    TaskSpec("multi_open_settings", "Open Layer Settings", "LOOP", "layer_settings_open"),
                    TaskSpec("multi_loop", "Set a loop mode on animated media", "LOOP", "multi_loop", optional=True),
                    TaskSpec("multi_open_effects", "Open Effects", "EFFECT", "effects_2d_open"),
                    TaskSpec("multi_effect", "Add an effect to one layer", "EFFECT", "multi_effect"),
                    TaskSpec("multi_open_masks", "Open Masks", "MASK", "masks_open"),
                    TaskSpec("multi_clipping", "Create a clipping relationship", "CLIP", "multi_clipping", optional=True),
                    TaskSpec("multi_holdout", "Create a holdout", "HOLDOUT", "multi_holdout", optional=True),
                ),
                pro_tip="Blur distant backgrounds, add atmospheric color, and use Grease Pencil holdouts for editable animated cut-outs.",
                help_title="Timing & Compositing",
                help_steps=(
                    "Select a video or image-sequence layer and choose One Shot, Loop or Ping-Pong.",
                    "Press Z and add a favourite effect, or open Effects & Masks and use Image or Mesh.",
                    "Place a layer above another, then use Z > Clipping Mask or Effects & Masks > Masks.",
                    "Create a holdout to cut transparent space through selected layers.",
                ),
                help_notes=(
                    "Different animated layers can use independent offsets, speeds and ranges.",
                    "Clipping and holdout relationships remain editable after creation.",
                ),
            ),
            PageSpec(
                title="Multiplane Setup explored",
                subtitle="The layered scene is ready for camera animation.",
                icon="CHECK",
                description=(
                    "You prepared layered artwork, generated the setup, created depth and",
                    "explored timing, effects and compositing relationships.",
                ),
                tasks=(
                    TaskSpec("multi_generate", "Multiplane", "MULTIPLANE", "multi_generate"),
                    TaskSpec("multi_camera", "Camera", "CAMERA", "multi_camera"),
                    TaskSpec("multi_depth", "Depth", "DEPTH", "multi_depth"),
                    TaskSpec("multi_effect", "Effects", "EFFECT", "multi_effect"),
                ),
                pro_tip="Animate a camera controller rather than every layer when you want a clean multiplane move.",
                help_title="Multiplane Recap",
                help_steps=(
                    "Prepare clearly named layers and sequences.",
                    "Import the folder and review skipped files.",
                    "Set the camera and arrange the layers in depth.",
                    "Configure animation, effects, clipping and holdout.",
                ),
            ),
        ),
    ),
}


# -----------------------------------------------------------------------------
# Lightweight scene inspection

_IMAGE_BACKENDS = frozenset({"NATIVE_IMAGE", "NATIVE_SEQUENCE", "NATIVE_MOVIE"})
_CROP_PROPS = (
    "fbp_crop_left", "fbp_crop_right", "fbp_crop_top", "fbp_crop_bottom",
    "fbp_extend_left", "fbp_extend_right", "fbp_extend_top", "fbp_extend_bottom",
    "fbp_extend_mode",
)
_COLOR_PROPS = (
    "fbp_color_plane_mode", "fbp_color_plane_color",
    "fbp_gradient_mode", "fbp_gradient_kind", "fbp_gradient_color_a",
    "fbp_gradient_color_b", "fbp_gradient_reverse", "fbp_gradient_offset_x",
    "fbp_gradient_offset_y", "fbp_gradient_scale_x", "fbp_gradient_scale_y",
    "fbp_gradient_rotation",
)


def _safe_keys(data: Any) -> tuple[str, ...]:
    try:
        return tuple(str(key) for key in data.keys())
    except FBP_DATA_ERRORS:
        return ()


def _marker_score(data: Any) -> int:
    score = 0
    name = str(getattr(data, "name", "")).lower()
    if name.startswith("fbp") or "frame by plane" in name or "frame_by_plane" in name:
        score += 2
    for key in _safe_keys(data):
        low = key.lower()
        if low.startswith("fbp") or "frame_by_plane" in low or "frame by plane" in low:
            score += 3
    return score


def _is_fbp_object(obj: bpy.types.Object) -> bool:
    try:
        if is_fbp_layer_object(obj):
            return True
        resolved = fbp_resolve_rig_from_any_object(obj, context=bpy.context)
        if resolved is not None and is_fbp_layer_object(resolved):
            return True
    except FBP_DATA_ERRORS:
        pass
    if _marker_score(obj) > 0 or _marker_score(getattr(obj, "data", None)) > 0:
        return True
    try:
        return any(bool(getattr(col, "is_fbp_collection", False)) or _marker_score(col) > 0 for col in obj.users_collection)
    except FBP_DATA_ERRORS:
        return False


def _rig_target(obj: bpy.types.Object | None) -> bpy.types.Object | None:
    if obj is None:
        return None
    try:
        resolved = fbp_resolve_rig_from_any_object(obj, context=bpy.context)
    except FBP_DATA_ERRORS:
        resolved = None
    rig = resolved or obj
    try:
        return getattr(rig, "fbp_plane_target", None) or rig
    except FBP_DATA_ERRORS:
        return rig


def _material_objects(obj: bpy.types.Object) -> tuple[bpy.types.Object, ...]:
    target = _rig_target(obj)
    if target is obj or target is None:
        return (obj,)
    return (obj, target)


def _material_has_image(obj: bpy.types.Object) -> bool:
    for material_obj in _material_objects(obj):
        for slot in getattr(material_obj, "material_slots", ()):
            mat = getattr(slot, "material", None)
            if not mat or not mat.use_nodes or not mat.node_tree:
                continue
            for node in mat.node_tree.nodes:
                if node.type == "TEX_IMAGE" and getattr(node, "image", None) is not None:
                    return True
    return False


def _material_has_gradient(obj: bpy.types.Object) -> bool:
    try:
        if bool(getattr(obj, "fbp_is_color_plane", False)) and str(getattr(obj, "fbp_color_plane_mode", "SOLID")) == "GRADIENT":
            return True
    except FBP_DATA_ERRORS:
        pass
    for material_obj in _material_objects(obj):
        for slot in getattr(material_obj, "material_slots", ()):
            mat = getattr(slot, "material", None)
            if not mat or not mat.use_nodes or not mat.node_tree:
                continue
            for node in mat.node_tree.nodes:
                label = f"{node.name} {node.label}".lower()
                if node.type in {"TEX_GRADIENT", "VALTORGB"} or "gradient" in label:
                    return True
    return False


def _value_signature(value: Any) -> str:
    try:
        if isinstance(value, (bool, int, float, str)):
            return repr(value)
        if hasattr(value, "__len__") and not isinstance(value, (bytes, bytearray)):
            vals = tuple(round(float(v), 5) for v in value)
            return repr(vals)
    except FBP_DATA_ERRORS:
        pass
    try:
        return repr(value)
    except FBP_DATA_ERRORS:
        return "<?>"


def _custom_signature(data: Any, contains: tuple[str, ...] = ()) -> tuple[tuple[str, str], ...]:
    result: list[tuple[str, str]] = []
    for key in _safe_keys(data):
        low = key.lower()
        if contains and not any(token in low for token in contains):
            continue
        try:
            result.append((key, _value_signature(data.get(key))))
        except FBP_DATA_ERRORS:
            continue
    return tuple(sorted(result))


def _rna_signature(data: Any, names: tuple[str, ...]) -> tuple[tuple[str, str], ...]:
    result: list[tuple[str, str]] = []
    if data is None:
        return ()
    for name in names:
        if not hasattr(data, name):
            continue
        try:
            result.append((name, _value_signature(getattr(data, name))))
        except FBP_DATA_ERRORS:
            continue
    return tuple(result)


def _material_signature(obj: bpy.types.Object) -> tuple[Any, ...]:
    output: list[Any] = []
    for material_obj in _material_objects(obj):
        for slot in getattr(material_obj, "material_slots", ()):
            mat = getattr(slot, "material", None)
            if not mat:
                continue
            output.append(("diffuse", tuple(round(float(v), 5) for v in mat.diffuse_color)))
            if not mat.use_nodes or not mat.node_tree:
                continue
            for node in mat.node_tree.nodes:
                node_sig: list[Any] = [node.type, node.name]
                node_sig.extend(
                    (socket.name, _value_signature(socket.default_value))
                    for socket in list(node.inputs)[:8]
                    if hasattr(socket, "default_value")
                )
                output.append(tuple(node_sig))
    return tuple(output)


def _transform_signature(obj: bpy.types.Object) -> tuple[float, ...]:
    return tuple(round(float(v), 5) for v in (*obj.location, *obj.rotation_euler, *obj.scale))


def _scene_fbp_objects(context: bpy.types.Context) -> tuple[bpy.types.Object, ...]:
    try:
        return tuple(iter_scene_fbp_rigs(context.scene, fallback=True))
    except FBP_DATA_ERRORS:
        return tuple(obj for obj in context.scene.objects if _is_fbp_object(obj))


def _possible_image_planes(context: bpy.types.Context, state: "TutorialState") -> tuple[bpy.types.Object, ...]:
    del state
    result = []
    for rig in _scene_fbp_objects(context):
        try:
            backend = str(fbp_layer_backend_type(rig) or "")
        except FBP_DATA_ERRORS:
            backend = ""
        if backend in _IMAGE_BACKENDS or _material_has_image(rig):
            result.append(rig)
    return tuple(result)


def _possible_color_planes(context: bpy.types.Context, state: "TutorialState") -> tuple[bpy.types.Object, ...]:
    del state
    return tuple(rig for rig in _scene_fbp_objects(context) if bool(getattr(rig, "fbp_is_color_plane", False)))


def _new_tutorial_rigs(objects: Iterable[bpy.types.Object], state: "TutorialState") -> tuple[bpy.types.Object, ...]:
    return tuple(obj for obj in objects if obj.as_pointer() not in state.baseline_objects)


def _active_or_last(objects: Iterable[bpy.types.Object], context: bpy.types.Context) -> bpy.types.Object | None:
    items = tuple(objects)
    active = context.view_layer.objects.active
    try:
        active = fbp_resolve_rig_from_any_object(active, context=context) or active
    except FBP_DATA_ERRORS:
        pass
    if active in items:
        return active
    return items[-1] if items else None


def _activate_tutorial_color_rig(
    context: bpy.types.Context,
    state: "TutorialState",
) -> bpy.types.Object | None:
    """Activate the Color Plane created during this tutorial session."""
    rig = _active_or_last(_new_tutorial_rigs(_possible_color_planes(context, state), state), context)
    if rig is None:
        return None
    context.view_layer.objects.active = rig
    rig.select_set(True)
    return rig


def _effect_ids(rig: bpy.types.Object, category: str | None = None) -> tuple[str, ...]:
    result: list[str] = []
    try:
        active_ids = tuple(fbp_effect_ids_for_rig(rig))
    except FBP_DATA_ERRORS:
        active_ids = tuple(
            str(getattr(item, "effect_id", "") or "")
            for item in tuple(getattr(rig, "fbp_effects", ()) or ())
            if str(getattr(item, "row_type", "EFFECT")) == "EFFECT"
        )
    for effect_id in active_ids:
        if not effect_id:
            continue
        if category is not None:
            definition = fbp_effect_definition(effect_id) or {}
            if str(definition.get("category", "2D") or "2D").upper() != category.upper():
                continue
            if category.upper() == "2D" and effect_id in {"CROP", "EXTEND"}:
                continue
        result.append(effect_id)
    return tuple(result)


# -----------------------------------------------------------------------------
# Tutorial state and detectors


@dataclass(slots=True)
class TutorialState:
    route_key: str | None = None
    page_index: int = 0
    completed: set[str] = field(default_factory=set)
    manual_completed: set[str] = field(default_factory=set)
    hitboxes: dict[str, tuple[float, float, float, float]] = field(default_factory=dict)
    hover: str = ""
    baseline_objects: set[int] = field(default_factory=set)
    baseline_collections: set[int] = field(default_factory=set)
    baseline_modifiers: dict[int, int] = field(default_factory=dict)
    baseline_props: dict[int, tuple[tuple[str, str], ...]] = field(default_factory=dict)
    baseline_materials: dict[int, tuple[Any, ...]] = field(default_factory=dict)
    baseline_transforms: dict[int, tuple[float, ...]] = field(default_factory=dict)
    anchors: dict[str, Any] = field(default_factory=dict)
    last_detection: float = 0.0

    def reset_baseline(self, context: bpy.types.Context) -> None:
        objects = tuple(context.scene.objects)
        self.baseline_objects = {obj.as_pointer() for obj in objects}
        self.baseline_collections = {col.as_pointer() for col in bpy.data.collections}
        self.baseline_modifiers = {obj.as_pointer(): len(obj.modifiers) for obj in objects}
        self.baseline_props = {obj.as_pointer(): _custom_signature(obj) for obj in objects}
        self.baseline_materials = {obj.as_pointer(): _material_signature(obj) for obj in objects}
        self.baseline_transforms = {obj.as_pointer(): _transform_signature(obj) for obj in objects}
        self.anchors.clear()

    @property
    def route(self) -> RouteSpec | None:
        return ROUTES.get(self.route_key or "")

    @property
    def page(self) -> PageSpec | None:
        route = self.route
        if not route:
            return None
        return route.pages[max(0, min(self.page_index, len(route.pages) - 1))]

    def task_is_done(self, task: TaskSpec) -> bool:
        return task.key in self.completed or task.key in self.manual_completed

    @property
    def active_task(self) -> TaskSpec | None:
        page = self.page
        if page is None:
            return None
        # Preserve the authored micro-step order. Optional actions remain in
        # sequence and expose an explicit Skip button instead of disappearing.
        for task in page.tasks:
            if not self.task_is_done(task):
                return task
        return None

    def enter_route(self, context: bpy.types.Context, route_key: str = "IMAGE") -> None:
        self.route_key = route_key if route_key in ROUTES else "IMAGE"
        self.page_index = 0
        self.completed.clear()
        self.manual_completed.clear()
        self.reset_baseline(context)


Detector = Callable[[bpy.types.Context, TutorialState], bool]


def _detect_image_import(context: bpy.types.Context, state: TutorialState) -> bool:
    return bool(_new_tutorial_rigs(_possible_image_planes(context, state), state))


def _detect_crop_open(context: bpy.types.Context, state: TutorialState) -> bool:
    for rig in _new_tutorial_rigs(_possible_image_planes(context, state), state):
        if any(effect_id in {"CROP", "EXTEND"} for effect_id in _effect_ids(rig)):
            return True
    return False


def _detect_layer_settings_open(context: bpy.types.Context, state: TutorialState) -> bool:
    del state
    categories = set(_layer_settings_categories(context))
    if not categories:
        return False
    screen = getattr(context, "screen", None)
    for area in tuple(getattr(screen, "areas", ()) or ()):
        if area.type != "VIEW_3D":
            continue
        try:
            if not bool(area.spaces.active.show_region_ui):
                continue
            region = next((item for item in area.regions if item.type == "UI"), None)
            if region is not None and str(region.active_panel_category) in categories:
                return True
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            continue
    return False


def _detect_effects_panel_open(context: bpy.types.Context, view: str) -> bool:
    if str(getattr(context.scene, "fbp_effects_view", "") or "") != view:
        return False
    screen = getattr(context, "screen", None)
    for area in tuple(getattr(screen, "areas", ()) or ()):
        if area.type != "PROPERTIES":
            continue
        try:
            if str(area.spaces.active.context or "") == "MODIFIER":
                return True
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            continue
    return False


def _detect_masks_open(context: bpy.types.Context, state: TutorialState) -> bool:
    del state
    return _detect_effects_panel_open(context, "MASK")


def _detect_effects_2d_open(context: bpy.types.Context, state: TutorialState) -> bool:
    del state
    return _detect_effects_panel_open(context, "2D")


def _detect_effects_3d_open(context: bpy.types.Context, state: TutorialState) -> bool:
    del state
    return _detect_effects_panel_open(context, "3D")


def _detect_image_crop(context: bpy.types.Context, state: TutorialState) -> bool:
    anchor = state.anchors.get("image_crop")
    plane = _active_or_last(_new_tutorial_rigs(_possible_image_planes(context, state), state), context)
    if plane is None:
        return False
    current = _rna_signature(plane, _CROP_PROPS)
    return bool(anchor is not None and current != anchor)


def _detect_image_mask(context: bpy.types.Context, state: TutorialState) -> bool:
    for rig in _new_tutorial_rigs(_possible_image_planes(context, state), state):
        try:
            if gp_mask_canvas_for_rig(rig) is not None:
                return True
        except FBP_DATA_ERRORS:
            pass
    return False


def _detect_image_effect(context: bpy.types.Context, state: TutorialState) -> bool:
    for rig in _new_tutorial_rigs(_possible_image_planes(context, state), state):
        if "PIXELATE" in _effect_ids(rig, "2D"):
            return True
    return False


def _detect_color_generate(context: bpy.types.Context, state: TutorialState) -> bool:
    return bool(_new_tutorial_rigs(_possible_color_planes(context, state), state))


def _detect_color_edit(context: bpy.types.Context, state: TutorialState) -> bool:
    plane = _active_or_last(_new_tutorial_rigs(_possible_color_planes(context, state), state), context)
    anchor = state.anchors.get("color_values")
    return bool(plane is not None and anchor is not None and _rna_signature(plane, _COLOR_PROPS) != anchor)


def _detect_color_gradient(context: bpy.types.Context, state: TutorialState) -> bool:
    return any(_material_has_gradient(obj) for obj in _new_tutorial_rigs(_possible_color_planes(context, state), state))


def _detect_color_gradient_edit(context: bpy.types.Context, state: TutorialState) -> bool:
    plane = _active_or_last(_new_tutorial_rigs(_possible_color_planes(context, state), state), context)
    anchor = state.anchors.get("color_gradient_values")
    if plane is None or anchor is None:
        return False
    current = (_rna_signature(plane, _COLOR_PROPS), _material_signature(plane))
    return current != anchor


def _detect_color_preview(context: bpy.types.Context, state: TutorialState) -> bool:
    if not _new_tutorial_rigs(_possible_color_planes(context, state), state):
        return False
    screen = getattr(context, "screen", None)
    for area in tuple(getattr(screen, "areas", ()) or ()):
        if area.type != "VIEW_3D":
            continue
        try:
            if area.spaces.active.shading.type in {"MATERIAL", "RENDERED"}:
                return True
        except FBP_DATA_ERRORS:
            pass
    return False


def _detect_color_animate(context: bpy.types.Context, state: TutorialState) -> bool:
    anchors = state.anchors.get("color_frame_counts", {})
    for rig in _new_tutorial_rigs(_possible_color_planes(context, state), state):
        count = len(getattr(rig, "fbp_images", ()) or ())
        baseline = int(anchors.get(rig.as_pointer(), 1 if count else 0))
        if count >= 2 and count > baseline:
            return True
    return False


def _detect_color_mesh(context: bpy.types.Context, state: TutorialState) -> bool:
    anchors = state.anchors.get("color_3d_effects", {})
    for rig in _new_tutorial_rigs(_possible_color_planes(context, state), state):
        current = _effect_ids(rig, "3D")
        if len(current) > int(anchors.get(rig.as_pointer(), 0)):
            return True
    return False


def _detect_multi_generate(context: bpy.types.Context, state: TutorialState) -> bool:
    new_fbp = [obj for obj in _scene_fbp_objects(context) if obj.as_pointer() not in state.baseline_objects]
    if len(new_fbp) >= 2:
        return True
    try:
        if any(col.as_pointer() not in state.baseline_collections and bool(getattr(col, "is_fbp_collection", False)) for col in bpy.data.collections):
            return True
    except FBP_DATA_ERRORS:
        pass
    return False


def _detect_multi_camera(context: bpy.types.Context, state: TutorialState) -> bool:
    return bool(_new_tutorial_rigs(_scene_fbp_objects(context), state)) and context.scene.camera is not None


def _detect_multi_depth(context: bpy.types.Context, state: TutorialState) -> bool:
    objects = _new_tutorial_rigs(_scene_fbp_objects(context), state)
    anchors = state.anchors.get("multi_transforms", {})
    if len(objects) < 2 or not anchors:
        return False
    return any(_transform_signature(obj) != anchors.get(obj.as_pointer()) for obj in objects)


def _detect_multi_loop(context: bpy.types.Context, state: TutorialState) -> bool:
    for obj in _new_tutorial_rigs(_scene_fbp_objects(context), state):
        try:
            if str(getattr(obj, "fbp_loop_mode", "NONE") or "NONE").upper() not in {"", "NONE"}:
                return True
        except FBP_DATA_ERRORS:
            continue
    return False


def _detect_multi_effect(context: bpy.types.Context, state: TutorialState) -> bool:
    anchors = state.anchors.get("multi_effects", {})
    for obj in _new_tutorial_rigs(_scene_fbp_objects(context), state):
        if len(_effect_ids(obj)) > int(anchors.get(obj.as_pointer(), 0)):
            return True
    return False


def _detect_multi_clipping(context: bpy.types.Context, state: TutorialState) -> bool:
    for obj in _new_tutorial_rigs(_scene_fbp_objects(context), state):
        try:
            if getattr(obj, "fbp_clipping_mask_source", None) is not None and "CLIPPING_MASK" in _effect_ids(obj):
                return True
        except FBP_DATA_ERRORS:
            continue
    return False


def _detect_multi_holdout(context: bpy.types.Context, state: TutorialState) -> bool:
    for obj in _new_tutorial_rigs(_scene_fbp_objects(context), state):
        try:
            if rig_holdout_is_active(obj):
                return True
            if bool(getattr(obj, "fbp_is_color_plane", False)) and str(getattr(obj, "fbp_color_plane_mode", "")) == "HOLDOUT":
                return True
        except FBP_DATA_ERRORS:
            continue
    return False


DETECTORS: dict[str, Detector] = {
    "crop_open": _detect_crop_open,
    "layer_settings_open": _detect_layer_settings_open,
    "masks_open": _detect_masks_open,
    "effects_2d_open": _detect_effects_2d_open,
    "effects_3d_open": _detect_effects_3d_open,
    "image_import": _detect_image_import,
    "image_crop": _detect_image_crop,
    "image_mask": _detect_image_mask,
    "image_effect": _detect_image_effect,
    "color_generate": _detect_color_generate,
    "color_edit": _detect_color_edit,
    "color_gradient": _detect_color_gradient,
    "color_gradient_edit": _detect_color_gradient_edit,
    "color_preview": _detect_color_preview,
    "color_animate": _detect_color_animate,
    "color_mesh": _detect_color_mesh,
    "multi_generate": _detect_multi_generate,
    "multi_camera": _detect_multi_camera,
    "multi_depth": _detect_multi_depth,
    "multi_loop": _detect_multi_loop,
    "multi_effect": _detect_multi_effect,
    "multi_clipping": _detect_multi_clipping,
    "multi_holdout": _detect_multi_holdout,
}


def _all_route_tasks(route: RouteSpec) -> tuple[TaskSpec, ...]:
    unique: dict[str, TaskSpec] = {}
    for page in route.pages:
        for task in page.tasks:
            unique.setdefault(task.key, task)
    return tuple(unique.values())


def _capture_completion_anchors(context: bpy.types.Context, state: TutorialState, task_key: str) -> None:
    if task_key == "image_import":
        plane = _active_or_last(_new_tutorial_rigs(_possible_image_planes(context, state), state), context)
        if plane:
            state.anchors["image_crop"] = _rna_signature(plane, _CROP_PROPS)
            state.anchors["image_2d_effects"] = {plane.as_pointer(): len(_effect_ids(plane, "2D"))}
    elif task_key == "color_generate":
        plane = _active_or_last(_new_tutorial_rigs(_possible_color_planes(context, state), state), context)
        if plane:
            state.anchors["color_values"] = _rna_signature(plane, _COLOR_PROPS)
            state.anchors["color_3d_effects"] = {plane.as_pointer(): len(_effect_ids(plane, "3D"))}
            frame_count = len(getattr(plane, "fbp_images", ()) or ())
            state.anchors["color_frame_counts"] = {plane.as_pointer(): 1 if frame_count else 0}
    elif task_key == "color_add_gradient":
        plane = _active_or_last(_new_tutorial_rigs(_possible_color_planes(context, state), state), context)
        if plane:
            state.anchors["color_gradient_values"] = (
                _rna_signature(plane, _COLOR_PROPS),
                _material_signature(plane),
            )
    elif task_key == "multi_generate":
        objects = _new_tutorial_rigs(_scene_fbp_objects(context), state)
        state.anchors["multi_transforms"] = {obj.as_pointer(): _transform_signature(obj) for obj in objects}
        state.anchors["multi_effects"] = {obj.as_pointer(): len(_effect_ids(obj)) for obj in objects}


def _update_progress(context: bpy.types.Context, state: TutorialState) -> None:
    route = state.route
    if route is None:
        return

    task = state.active_task
    if task is not None:
        detector = DETECTORS.get(task.detector)
        try:
            if detector is not None and detector(context, state):
                state.completed.add(task.key)
                _capture_completion_anchors(context, state, task.key)
        except (ReferenceError, RuntimeError, AttributeError, TypeError, ValueError):
            # Scene data may be edited while the timer is reading it. Retry on the
            # next detection tick instead of interrupting the user.
            pass
    _advance_completed_page(state)


def _advance_completed_page(state: TutorialState) -> bool:
    """Advance after every micro-step on the current page is done or skipped."""
    route = state.route
    page = state.page
    if route is None or page is None or state.page_index >= len(route.pages) - 1:
        return False
    if page.tasks and not all(state.task_is_done(task) for task in page.tasks):
        return False
    state.page_index += 1
    return True


from .ui_icons import custom_icon_path_for_ui_key, ui_label_icon_kwargs

# -----------------------------------------------------------------------------
# Adaptive HUD drawing

_COLOR_SHADER = None
_IMAGE_SHADER = None
_TUTORIAL_ICON_IMAGES: dict[str, str] = {}
_TUTORIAL_ICON_TEXTURES: dict[str, tuple[int, Any]] = {}
_TUTORIAL_ICON_COLORSPACES = ("Non-Color", "Raw")
_IMAGE_SHADER_SUPPORTS_TINT = False

_CUSTOM_UI_KEYS = {
    "IMAGE": "menu.image_plane",
    "COLOR": "menu.color_plane",
    "MULTIPLANE": "menu.multiplane",
    "MASK": "layer.clipping_on",
    "CLIPPING": "layer.clipping_on",
    "HOLDOUT": "menu.holdout_plane",
    "MATERIAL": "menu.gradient_plane",
    "GRADIENT": "menu.gradient_plane",
    "ANIMATE": "menu.color_plane",
    "LOOP": "menu.video_plane",
    "MESH": "menu.cutout_plane",
    "EFFECT": "menu.gradient_plane",
    "CROP": "menu.image_plane",
    "CAMERA": "menu.multiplane",
    "FOLDER": "menu.multiplane",
    "DEPTH": "menu.multiplane",
}

_NATIVE_HELP_ICONS = {
    "KEY": "EVENT_SHIFT",
    "TEXT": "RENDERLAYERS",
    "CHECK": "CHECKMARK",
    "CROP": "IMAGE_BACKGROUND",
    "MASK": "MOD_MASK",
    "EFFECT": "SHADERFX",
    "PALETTE": "COLOR",
    "GRADIENT": "COLOR",
    "MATERIAL": "SHADING_RENDERED",
    "ANIMATE": "RENDER_RESULT",
    "MESH": "MESH_DATA",
    "FOLDER": "FILE_FOLDER",
    "CAMERA": "CAMERA_DATA",
    "DEPTH": "FULLSCREEN_ENTER",
    "LOOP": "FILE_REFRESH",
    "CLIPPING": "CLIPUV_HLT",
    "HOLDOUT": "GHOST_DISABLED",
    "INFO": "INFO",
}

_FALLBACK_COLORS = {
    "panel": (0.135, 0.135, 0.135, 0.98),
    "header": (0.105, 0.105, 0.105, 0.99),
    "card": (0.18, 0.18, 0.18, 0.99),
    "card_hover": (0.24, 0.24, 0.24, 1.0),
    "accent": (0.19, 0.48, 0.80, 1.0),
    "text": (0.90, 0.90, 0.90, 1.0),
    "muted": (0.74, 0.74, 0.74, 1.0),
    "line": (0.04, 0.04, 0.04, 0.90),
    "success": (0.31, 0.68, 0.34, 1.0),
}


def _color_shader():
    global _COLOR_SHADER
    if _COLOR_SHADER is None:
        _COLOR_SHADER = gpu.shader.from_builtin("UNIFORM_COLOR")
    return _COLOR_SHADER


def _image_shader():
    global _IMAGE_SHADER, _IMAGE_SHADER_SUPPORTS_TINT
    if _IMAGE_SHADER is None:
        try:
            # Blender's IMAGE_COLOR built-in performs the texture-by-color
            # multiplication in its supported GPU backend. Unlike the removed
            # direct GPUShader constructor, this works on Blender 5.2 and keeps
            # monochrome PNG artwork theme-colored instead of raw white/black.
            _IMAGE_SHADER = gpu.shader.from_builtin("IMAGE_COLOR")
            _IMAGE_SHADER_SUPPORTS_TINT = True
        except (AttributeError, RuntimeError, SystemError, TypeError, ValueError):
            try:
                _IMAGE_SHADER = gpu.shader.from_builtin("IMAGE")
            except ValueError:
                _IMAGE_SHADER = gpu.shader.from_builtin("2D_IMAGE")
            _IMAGE_SHADER_SUPPORTS_TINT = False
    return _IMAGE_SHADER


def _theme_rgba(value: Any, fallback: tuple[float, float, float, float], *, alpha: float | None = None):
    try:
        result = tuple(float(component) for component in value)
        if len(result) == 3:
            result = (*result, fallback[3])
        if len(result) != 4:
            return fallback
        if alpha is not None:
            result = (*result[:3], alpha)
        return result
    except (TypeError, ValueError, ReferenceError):
        return fallback


def _mix_color(a, b, factor: float, *, alpha: float | None = None):
    t = max(0.0, min(1.0, float(factor)))
    result = tuple(float(a[index]) * (1.0 - t) + float(b[index]) * t for index in range(3))
    return (*result, float(alpha if alpha is not None else a[3]))


def _relative_luminance(color) -> float:
    def linear(component: float) -> float:
        value = max(0.0, min(1.0, float(component)))
        return value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4

    red, green, blue = (linear(component) for component in color[:3])
    return red * 0.2126 + green * 0.7152 + blue * 0.0722


def _contrast_ratio(foreground, background) -> float:
    lighter = max(_relative_luminance(foreground), _relative_luminance(background))
    darker = min(_relative_luminance(foreground), _relative_luminance(background))
    return (lighter + 0.05) / (darker + 0.05)


def _ensure_contrast(foreground, background, minimum: float = 4.5):
    candidate = tuple(float(value) for value in foreground)
    if _contrast_ratio(candidate, background) >= minimum:
        return candidate
    light = (0.96, 0.96, 0.96, candidate[3])
    dark = (0.035, 0.035, 0.035, candidate[3])
    return light if _contrast_ratio(light, background) >= _contrast_ratio(dark, background) else dark


def _theme_palette(context: bpy.types.Context) -> dict[str, tuple[float, float, float, float]]:
    """Read Blender's current widget theme so the HUD belongs to the host UI."""
    palette = dict(_FALLBACK_COLORS)
    try:
        widgets = context.preferences.themes[0].user_interface
        regular = widgets.wcol_regular
        tool = widgets.wcol_tool
        menu = widgets.wcol_menu
        palette.update({
            "panel": _theme_rgba(menu.inner, palette["panel"], alpha=0.98),
            "header": _theme_rgba(tool.inner, palette["header"], alpha=0.99),
            "card": _theme_rgba(regular.inner, palette["card"], alpha=0.99),
            "card_hover": _theme_rgba(regular.inner_sel, palette["card_hover"], alpha=1.0),
            "accent": _theme_rgba(tool.inner_sel, palette["accent"], alpha=1.0),
            "text": _theme_rgba(regular.text, palette["text"], alpha=1.0),
            "muted": _theme_rgba(menu.text, palette["muted"], alpha=0.88),
            "line": _theme_rgba(regular.outline, palette["line"], alpha=0.95),
        })
    except (AttributeError, IndexError, ReferenceError, RuntimeError, TypeError, ValueError):
        pass
    palette["text"] = _ensure_contrast(palette["text"], palette["panel"], 4.5)
    palette["header_text"] = _ensure_contrast(palette["text"], palette["header"], 4.5)
    palette["card_text"] = _ensure_contrast(palette["text"], palette["card"], 4.5)
    muted = _mix_color(palette["card_text"], palette["card"], 0.24, alpha=0.92)
    palette["muted"] = _ensure_contrast(muted, palette["card"], 3.2)
    accent_label = _mix_color(palette["accent"], palette["card_text"], 0.40, alpha=1.0)
    palette["accent_label"] = _ensure_contrast(accent_label, palette["card"], 3.2)
    palette["accent_text"] = _ensure_contrast(palette["text"], palette["accent"], 4.5)
    palette["progress_active"] = (*palette["accent"][:3], 0.38)
    return palette


def _draw_rect(x: float, y: float, w: float, h: float, color: tuple[float, float, float, float]) -> None:
    if w <= 0.0 or h <= 0.0:
        return
    shader = _color_shader()
    batch = batch_for_shader(
        shader,
        "TRIS",
        {"pos": ((x, y), (x + w, y), (x + w, y + h), (x, y + h))},
        indices=((0, 1, 2), (0, 2, 3)),
    )
    shader.bind()
    shader.uniform_float("color", color)
    batch.draw(shader)


def _round_rect_points(x: float, y: float, w: float, h: float, radius: float, segments: int = 10):
    radius = max(0.0, min(float(radius), float(w) * 0.5, float(h) * 0.5))
    if radius <= 0.0:
        return ((x, y), (x + w, y), (x + w, y + h), (x, y + h))
    points: list[tuple[float, float]] = []
    corners = (
        (x + radius, y + radius, math.pi, math.pi * 1.5),
        (x + w - radius, y + radius, math.pi * 1.5, math.tau),
        (x + w - radius, y + h - radius, 0.0, math.pi * 0.5),
        (x + radius, y + h - radius, math.pi * 0.5, math.pi),
    )
    for cx, cy, start, end in corners:
        for index in range(segments + 1):
            angle = start + (end - start) * (index / segments)
            points.append((cx + math.cos(angle) * radius, cy + math.sin(angle) * radius))
    return tuple(points)


def _draw_round_rect(x: float, y: float, w: float, h: float, radius: float, color) -> None:
    if w <= 0.0 or h <= 0.0:
        return
    perimeter = _round_rect_points(x, y, w, h, radius)
    vertices = ((x + w * 0.5, y + h * 0.5), *perimeter, perimeter[0])
    shader = _color_shader()
    batch = batch_for_shader(shader, "TRI_FAN", {"pos": vertices})
    shader.bind()
    shader.uniform_float("color", color)
    batch.draw(shader)


def _draw_round_outline(x: float, y: float, w: float, h: float, radius: float, color, width: float = 1.0) -> None:
    perimeter = _round_rect_points(x, y, w, h, radius)
    shader = _color_shader()
    batch = batch_for_shader(shader, "LINE_STRIP", {"pos": (*perimeter, perimeter[0])})
    gpu.state.line_width_set(max(1.0, float(width)))
    shader.bind()
    shader.uniform_float("color", color)
    batch.draw(shader)
    gpu.state.line_width_set(1.0)


def _prepare_tutorial_icon_image(image: bpy.types.Image | None) -> bpy.types.Image | None:
    """Load PNG UI artwork as straight-alpha, color-management-neutral data."""
    if image is None:
        return None
    try:
        image.alpha_mode = "STRAIGHT"
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        pass
    try:
        image.use_view_as_render = False
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        pass
    for colorspace_name in _TUTORIAL_ICON_COLORSPACES:
        try:
            image.colorspace_settings.name = colorspace_name
            break
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            continue
    return image


def _tutorial_image_identity(image) -> int:
    if image is None:
        return 0
    try:
        session_uid = int(getattr(image, "session_uid", 0) or 0)
        if session_uid > 0:
            return -session_uid
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        pass
    try:
        return int(image.as_pointer())
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        return 0


def _load_tutorial_icon(ui_key: str) -> tuple[bpy.types.Image | None, Any | None]:
    path = custom_icon_path_for_ui_key(ui_key)
    if not path:
        return None, None

    # Keep only the datablock name between redraws. A live Image wrapper can be
    # invalidated by File > Open, Factory Settings or Undo/Main replacement.
    image_name = str(_TUTORIAL_ICON_IMAGES.get(path, "") or "")
    try:
        image = bpy.data.images.get(image_name) if image_name else None
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        image = None
    if image is None:
        try:
            image = bpy.data.images.load(path, check_existing=True)
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, OSError):
            _TUTORIAL_ICON_IMAGES.pop(path, None)
            _TUTORIAL_ICON_TEXTURES.pop(path, None)
            return None, None
        # Custom UI artwork is data, not scene color. It is drawn with straight
        # alpha so translucent anti-aliased edges do not turn into dark halos.
        image = _prepare_tutorial_icon_image(image)
        try:
            _TUTORIAL_ICON_IMAGES[path] = str(getattr(image, "name", "") or "")
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            _TUTORIAL_ICON_IMAGES.pop(path, None)

    image_identity = _tutorial_image_identity(image)
    texture_entry = _TUTORIAL_ICON_TEXTURES.get(path)
    texture = (
        texture_entry[1]
        if isinstance(texture_entry, tuple)
        and len(texture_entry) == 2
        and int(texture_entry[0] or 0) == image_identity
        else None
    )
    if texture is None:
        try:
            texture = gpu.texture.from_image(image)
        except (AttributeError, ReferenceError, RuntimeError, ValueError, TypeError):
            _TUTORIAL_ICON_TEXTURES.pop(path, None)
            return image, None
        _TUTORIAL_ICON_TEXTURES[path] = (image_identity, texture)
    return image, texture


def _draw_custom_icon(
    ui_key: str,
    x: float,
    y: float,
    box_w: float,
    box_h: float,
    tint=(1.0, 1.0, 1.0, 1.0),
) -> bool:
    image, texture = _load_tutorial_icon(ui_key)
    if image is None or texture is None or box_w <= 0.0 or box_h <= 0.0:
        return False
    try:
        image_w, image_h = int(image.size[0]), int(image.size[1])
    except (ReferenceError, TypeError, ValueError):
        return False
    if image_w <= 0 or image_h <= 0:
        return False
    ratio = image_w / image_h
    target_ratio = box_w / box_h
    if ratio >= target_ratio:
        draw_w = box_w
        draw_h = box_w / ratio
    else:
        draw_h = box_h
        draw_w = box_h * ratio
    draw_x = x + (box_w - draw_w) * 0.5
    draw_y = y + (box_h - draw_h) * 0.5
    shader = _image_shader()
    batch = batch_for_shader(
        shader,
        "TRI_FAN",
        {
            "pos": (
                (draw_x, draw_y),
                (draw_x + draw_w, draw_y),
                (draw_x + draw_w, draw_y + draw_h),
                (draw_x, draw_y + draw_h),
            ),
            "texCoord": ((0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)),
        },
    )
    shader.bind()
    if _IMAGE_SHADER_SUPPORTS_TINT:
        try:
            shader.uniform_float("color", tuple(float(value) for value in tint))
        except (AttributeError, RuntimeError, TypeError, ValueError):
            pass
    try:
        shader.uniform_sampler("image", texture)
    except (ValueError, TypeError):
        return False
    gpu.state.blend_set("ALPHA")
    try:
        batch.draw(shader)
    finally:
        gpu.state.blend_set("ALPHA")
    return True


def _set_font_size(size: int) -> None:
    try:
        blf.size(0, max(8, int(size)))
    except TypeError:
        blf.size(0, max(8, int(size)), 72)


def _text_dimensions(text: str, size: int) -> tuple[float, float]:
    _set_font_size(size)
    return blf.dimensions(0, str(text or ""))


def _draw_text(
    text: str,
    x: float,
    y: float,
    size: int,
    color: tuple[float, float, float, float],
    *,
    align: str = "LEFT",
) -> float:
    value = str(text or "")
    _set_font_size(size)
    width, _height = blf.dimensions(0, value)
    tx = x
    if align == "CENTER":
        tx -= width * 0.5
    elif align == "RIGHT":
        tx -= width
    blf.color(0, *color)
    blf.position(0, tx, y, 0)
    blf.draw(0, value)
    return width


def _ellipsize(text: str, max_width: float, size: int) -> str:
    value = " ".join(str(text or "").split())
    if not value or _text_dimensions(value, size)[0] <= max_width:
        return value
    suffix = "…"
    lo, hi = 0, len(value)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        candidate = value[:mid].rstrip() + suffix
        if _text_dimensions(candidate, size)[0] <= max_width:
            lo = mid
        else:
            hi = mid - 1
    return value[:lo].rstrip() + suffix


def _wrap_measured(text: str, max_width: float, size: int, max_lines: int | None = None) -> list[str]:
    words = " ".join(str(text or "").split()).split()
    if not words:
        return []
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = word if not current else f"{current} {word}"
        if not current or _text_dimensions(candidate, size)[0] <= max_width:
            current = candidate
            continue
        lines.append(current)
        current = word
        if max_lines is not None and len(lines) >= max_lines:
            break
    if current and (max_lines is None or len(lines) < max_lines):
        lines.append(current)
    if max_lines is not None and len(lines) >= max_lines:
        consumed = " ".join(lines)
        original = " ".join(words)
        if len(consumed) < len(original):
            lines[-1] = _ellipsize(lines[-1] + " " + " ".join(words[len(consumed.split()):]), max_width, size)
    return lines


def _draw_text_lines(lines: Iterable[str], x: float, y: float, size: int, color: tuple[float, float, float, float], line_height: float) -> float:
    cursor = y
    for line in lines:
        _draw_text(line, x, cursor, size, color)
        cursor -= line_height
    return cursor


def _draw_flat_button(
    state: TutorialState,
    hud: dict[str, Any],
    key: str,
    rect: tuple[float, float, float, float],
    label: str,
    *,
    primary: bool = False,
) -> None:
    palette = hud["palette"]
    scale = hud["scale"]
    hovered = state.hover == key
    if primary:
        fill = _mix_color(palette["accent"], palette["card_text"], 0.16) if hovered else palette["accent"]
        text_color = palette["accent_text"]
    else:
        fill = palette["card_hover"] if hovered else palette["card"]
        text_color = palette["card_text"]
    state.hitboxes[key] = rect
    radius = min(3.0 * scale, rect[3] * 0.22)
    _draw_round_rect(*rect, radius, fill)
    _draw_round_outline(*rect, radius, palette["accent"] if hovered and not primary else palette["line"])
    _draw_text(
        _ellipsize(label, rect[2] - 12.0 * scale, hud["small_size"]),
        rect[0] + rect[2] * 0.5,
        rect[1] + rect[3] * 0.5 - 4.0 * scale,
        hud["small_size"],
        text_color,
        align="CENTER",
    )


def _inside(rect: tuple[float, float, float, float], x: float, y: float) -> bool:
    rx, ry, rw, rh = rect
    return rx <= x <= rx + rw and ry <= y <= ry + rh


def _ui_scale(context: bpy.types.Context) -> float:
    system = context.preferences.system
    base = float(getattr(system, "ui_scale", 1.0) or 1.0)
    dpi = float(getattr(system, "dpi", 72.0) or 72.0)
    pixel = float(getattr(system, "pixel_size", 1.0) or 1.0)
    dpi_factor = max(0.9, min(1.35, dpi / 72.0))
    pixel_factor = max(1.0, min(1.25, pixel))
    return max(0.82, min(1.65, base * dpi_factor * pixel_factor))


_ROUTE_SHORT_LABELS = {
    "IMAGE": "Image Plane",
    "COLOR": "Color Plane",
    "MULTIPLANE": "Multiplane",
}

_ROUTE_ICON_UI_KEYS = {
    "IMAGE": "menu.image_plane",
    "COLOR": "menu.color_plane",
    "MULTIPLANE": "menu.multiplane",
}

_ROUTE_CARD_DETAILS = {
    "IMAGE": "Import · crop · mask · 2D FX",
    "COLOR": "Color · gradient · animation · mesh",
    "MULTIPLANE": "Camera · depth · loop · masks",
}

_TASK_GUIDANCE = {
    "image_open_importer": "Open the Single Plane importer. The next card will wait for the file you choose.",
    "image_import": "Add a Single Plane and choose an image. The new layer is detected automatically.",
    "image_open_crop": "Press Z and choose Crop or Expand to reveal the existing viewport edge controllers.",
    "image_crop": "Drag a Crop or Expand edge controller to frame the selected plane.",
    "image_open_masks": "Press Z to reach Grease Pencil Mask.",
    "image_mask": "Press Z, choose Grease Pencil Mask, then draw directly in native Draw Mode.",
    "image_open_effects": "Open Properties > Modifiers using the wrench icon.",
    "image_effect": "Add Pixelate from the Image effects list in the Modifiers tab.",
    "color_open_creator": "Open the Color Plane creator. The next card will wait for the generated plane.",
    "color_generate": "Create a Color Plane directly from this guide.",
    "color_open_settings": "Reveal Layer Settings in the panel location enabled in Preferences.",
    "color_edit": "Change the selected Color Plane color in Layer Settings.",
    "color_add_gradient": "Add a Gradient row from the Frames UI List.",
    "color_gradient_edit": "Change the ramp or Position controls of the new Gradient frame.",
    "color_preview": "Switch the 3D Viewport to Material Preview.",
    "color_add_frame": "Add a Color or Gradient row from the Frames UI List, then edit its appearance and duration.",
    "color_open_mesh_effects": "Open the Mesh section for the selected Color Plane.",
    "color_mesh": "Use Z for a favourite 3D effect, or add one from Effects & Masks > Mesh.",
    "multi_open_importer": "Open Multiplane Project. The next card will wait for the imported layer setup.",
    "multi_generate": "Open Multiplane Project and import a folder containing at least two layers.",
    "multi_open_camera": "Open the Frame By Plane camera setup.",
    "multi_camera": "Create or choose the active scene camera.",
    "multi_start_depth": "Select one imported layer and start a constrained move.",
    "multi_depth": "Move at least one layer in depth to create parallax.",
    "multi_open_settings": "Reveal Layer Settings for the selected animated layer.",
    "multi_loop": "Choose a loop mode for an animated image or video layer.",
    "multi_open_effects": "Open Image Effects for one imported layer.",
    "multi_effect": "Use Z for a favourite effect, or add one from Effects & Masks.",
    "multi_open_masks": "Open Masks for the selected multiplane layer.",
    "multi_clipping": "Use Z > Clipping Mask, or create the relationship in Effects & Masks > Masks.",
    "multi_holdout": "Create or enable a holdout layer.",
}

_TASK_ACTION_LABELS = {
    "image_open_importer": "Open Single Plane",
    "image_import": "Add Single Plane",
    "image_open_crop": "Open Z Pie",
    "image_crop": "Show Crop / Expand Handles",
    "image_open_masks": "Open Z Pie",
    "image_mask": "Z: Grease Pencil Mask",
    "image_open_effects": "Open Modifiers",
    "image_effect": "Add Pixelate",
    "color_open_creator": "Open Color Plane",
    "color_generate": "Add Color Plane",
    "color_open_settings": "Open Layer Settings",
    "color_edit": "Open Layer Settings",
    "color_add_gradient": "Add Gradient Frame",
    "color_gradient_edit": "Open Layer Settings",
    "color_preview": "Material Preview",
    "color_add_frame": "Add Color Frame",
    "color_open_mesh_effects": "Open Mesh Effects",
    "color_mesh": "Open Mesh Effects",
    "multi_open_importer": "Open Multiplane Project",
    "multi_generate": "Open Multiplane Project",
    "multi_open_camera": "Open Camera Setup",
    "multi_camera": "Create Camera",
    "multi_start_depth": "Move Selected Layer",
    "multi_depth": "Move Selected Layer",
    "multi_open_settings": "Open Layer Settings",
    "multi_loop": "Open Layer Settings",
    "multi_open_effects": "Open Effects",
    "multi_effect": "Open Effects",
    "multi_open_masks": "Open Masks",
    "multi_clipping": "Open Masks",
    "multi_holdout": "Open Masks",
}

_TASK_SHORTCUTS = {
    "image_open_importer": "Shift + A  >  Frame By Plane  >  Single Plane",
    "image_import": "Choose Image  >  Open Image",
    "image_open_crop": "Z  >  Crop or Expand",
    "image_crop": "Drag an edge controller  >  Confirm",
    "image_open_masks": "Z  >  Grease Pencil Mask",
    "image_mask": "Z  >  Grease Pencil Mask  >  Draw",
    "image_open_effects": "Properties  >  Modifiers (wrench)",
    "image_effect": "Image Effects  >  Add Effect  >  Pixelate",
    "color_open_creator": "Shift + A  >  Frame By Plane  >  Color Plane",
    "color_generate": "Choose Color settings  >  Create",
    "color_open_settings": "Layer Settings",
    "color_edit": "Frame Appearance  >  Color",
    "color_add_gradient": "Frames  >  + Gradient",
    "color_gradient_edit": "Frame Appearance  >  Gradient / Position",
    "color_preview": "Z  >  Material Preview",
    "color_add_frame": "Frames  >  + Color / Gradient",
    "color_open_mesh_effects": "Z  >  Favourite 3D Effects",
    "color_mesh": "Choose a Mesh Effect  >  Adjust it",
    "multi_open_importer": "Shift + A  >  Frame By Plane  >  Multiplane Project",
    "multi_generate": "Choose Folder  >  Review Layers  >  Generate",
    "multi_open_camera": "Frame By Plane  >  Camera",
    "multi_camera": "Choose Camera settings  >  Create",
    "multi_start_depth": "Select Layer  >  G",
    "multi_depth": "Move on depth axis  >  Confirm",
    "multi_open_settings": "Layer Settings",
    "multi_loop": "Media Timing  >  Loop Mode",
    "multi_open_effects": "Z  >  Favourite Effects",
    "multi_effect": "Choose Effect  >  Adjust it",
    "multi_open_masks": "Z  >  Masks",
    "multi_clipping": "Masks  >  Clipping Mask",
    "multi_holdout": "Masks  >  Holdout",
}


def _shortcut_text(page: PageSpec) -> str:
    return "  >  ".join(label for _kind, label in page.shortcut)


def _task_shortcut_text(context: bpy.types.Context, task: TaskSpec, page: PageSpec) -> str:
    if task.key in {"color_open_settings", "color_edit", "color_gradient_edit", "multi_open_settings", "multi_loop"}:
        categories = _layer_settings_categories(context)
        if categories and categories[0] == "Frame By Plane":
            return "N  >  Frame By Plane  >  Layer Settings"
        if "Tool" in categories:
            return "N  >  Tool  >  Layer Settings"
        return "Preferences  >  Interface  >  Enable Layer Settings"
    return _TASK_SHORTCUTS.get(task.key, _shortcut_text(page))


def _route_is_finished(state: TutorialState) -> bool:
    route = state.route
    return bool(route and state.page_index == len(route.pages) - 1 and state.active_task is None)


def _route_progress(state: TutorialState) -> tuple[int, int, float]:
    route = state.route
    if route is None:
        return 0, 0, 0.0
    tasks = _all_route_tasks(route)
    total = len(tasks)
    completed = sum(1 for task in tasks if state.task_is_done(task))
    current = min(total, completed + (1 if state.active_task is not None else 0))
    return current, total, (completed / total if total else 1.0)


# Compact top-center tutorial HUD.  The guide deliberately exposes only the
# current action so it can stay open while the viewport remains fully usable.
def _compute_hud(context: bpy.types.Context, region: bpy.types.Region, state: TutorialState) -> dict[str, Any]:
    scale = _ui_scale(context)
    region_w = max(1.0, float(region.width))
    region_h = max(1.0, float(region.height))
    desired_margin = max(10.0, 16.0 * scale)
    # Split/quad layouts can leave a very small 3D region. Never let the HUD
    # extend outside it; older minimum clamps could produce negative x values
    # and an unreachable Close button.
    margin = min(
        desired_margin,
        max(2.0, min(region_w, region_h) * 0.08),
    )
    available_w = max(1.0, region_w - margin * 2.0)
    width = min(available_w, max(360.0, 520.0 * scale))
    preferred_h = (174.0 if state.route is None else 220.0) * scale
    x = (region_w - width) * 0.5
    # Leave the translucent Viewport tool/header strip unobstructed. The HUD is
    # still top-centred, but starts just below Blender's overlay controls.
    desired_clearance = max(36.0, 46.0 * scale)
    available_h = max(1.0, region_h - margin * 2.0)
    top_clearance = min(
        desired_clearance,
        max(0.0, available_h - max(48.0, 96.0 * scale)),
    )
    height = min(preferred_h, max(1.0, available_h - top_clearance))
    y = max(margin, region_h - height - margin - top_clearance)
    header_h = min(38.0 * scale, height * 0.28)
    content_pad = 12.0 * scale
    action_h = min(28.0 * scale, height * 0.18)
    footer_y = y + 10.0 * scale
    control_h = action_h
    control_gap = 6.0 * scale
    back_w = 58.0 * scale
    next_w = 54.0 * scale
    close_size = min(20.0 * scale, header_h - 10.0 * scale)
    help_w = 50.0 * scale
    header_control_y = y + height - header_h + (header_h - close_size) * 0.5
    controls = {
        "close": (x + width - 8.0 * scale - close_size, header_control_y, close_size, close_size),
        "help": (
            x + width - 8.0 * scale - close_size - control_gap - help_w,
            header_control_y,
            help_w,
            close_size,
        ),
        "back": (x + 10.0 * scale, footer_y, back_w, control_h),
        "next": (x + width - 10.0 * scale - next_w, footer_y, next_w, control_h),
    }
    action_rect = None
    if state.route is not None and state.active_task is not None:
        action_left = controls["back"][0] + controls["back"][2] + control_gap
        action_right = controls["next"][0] - control_gap
        action_rect = (
            action_left,
            footer_y,
            max(1.0, action_right - action_left),
            action_h,
        )
    palette = _theme_palette(context)
    data = {
        "mode": "CHOOSER" if state.route is None else "STEP",
        "scale": scale,
        "x": x,
        "y": y,
        "width": width,
        "height": height,
        "margin": margin,
        "header_h": header_h,
        "content_x": x + content_pad,
        "content_w": width - content_pad * 2.0,
        "palette": palette,
        "title_size": max(13, round(14 * scale)),
        "body_size": max(10, round(11 * scale)),
        "small_size": max(9, round(10 * scale)),
        "line_h": max(14.0, 15.0 * scale),
        "action_rect": action_rect,
        "controls": controls,
    }
    return data


def _draw_route_chooser(state: TutorialState, hud: dict[str, Any]) -> None:
    palette = hud["palette"]
    scale = hud["scale"]
    x, y, w, h = hud["x"], hud["y"], hud["width"], hud["height"]
    content_x, content_w = hud["content_x"], hud["content_w"]
    top = y + h - hud["header_h"] - 15.0 * scale
    _draw_text("Choose what you want to explore", content_x, top, hud["body_size"], palette["card_text"])
    if w >= 460.0 * scale:
        _draw_text(
            "Each real action advances the guide",
            x + w - 12.0 * scale,
            top,
            hud["small_size"],
            palette["muted"],
            align="RIGHT",
        )
    gap = 6.0 * scale
    button_y = y + 12.0 * scale
    button_h = max(48.0 * scale, top - button_y - 23.0 * scale)
    button_w = (content_w - gap * 2.0) / 3.0
    for index, route_key in enumerate(("IMAGE", "COLOR", "MULTIPLANE")):
        key = f"route_{route_key}"
        rect = (content_x + index * (button_w + gap), button_y, button_w, button_h)
        state.hitboxes[key] = rect
        hovered = state.hover == key
        fill = palette["card_hover"] if hovered else palette["card"]
        _draw_round_rect(*rect, 4.0 * scale, fill)
        _draw_round_outline(*rect, 4.0 * scale, palette["accent"] if hovered else palette["line"])
        icon_size = min(30.0 * scale, rect[3] * 0.38)
        _draw_custom_icon(
            _ROUTE_ICON_UI_KEYS[route_key],
            rect[0] + rect[2] * 0.5 - icon_size * 0.5,
            rect[1] + rect[3] - icon_size - 8.0 * scale,
            icon_size,
            icon_size,
            tint=palette["accent_label"],
        )
        label = _ellipsize(_ROUTE_SHORT_LABELS[route_key], button_w - 16.0 * scale, hud["body_size"])
        _draw_text(
            label,
            rect[0] + rect[2] * 0.5,
            rect[1] + 25.0 * scale,
            hud["body_size"],
            palette["card_text"],
            align="CENTER",
        )
        detail = _ellipsize(_ROUTE_CARD_DETAILS[route_key], button_w - 14.0 * scale, hud["small_size"])
        _draw_text(
            detail,
            rect[0] + rect[2] * 0.5,
            rect[1] + 9.0 * scale,
            hud["small_size"],
            palette["muted"],
            align="CENTER",
        )


def _draw_step(state: TutorialState, hud: dict[str, Any]) -> None:
    palette = hud["palette"]
    scale = hud["scale"]
    _x, y, w, h = hud["x"], hud["y"], hud["width"], hud["height"]
    content_x, content_w = hud["content_x"], hud["content_w"]
    route = state.route
    page = state.page
    if route is None or page is None:
        return

    current, total, progress = _route_progress(state)
    header_bottom = y + h - hud["header_h"]
    progress_h = max(4.0, 5.0 * scale)
    progress_y = header_bottom - 11.0 * scale
    progress_rect = (content_x, progress_y, content_w, progress_h)
    _draw_round_rect(*progress_rect, progress_h * 0.5, palette["line"])
    position = current / total if total else 1.0
    if position > 0.0:
        _draw_round_rect(
            progress_rect[0],
            progress_rect[1],
            progress_rect[2] * position,
            progress_rect[3],
            progress_h * 0.5,
            palette["progress_active"],
        )
    if progress > 0.0:
        _draw_round_rect(
            progress_rect[0],
            progress_rect[1],
            progress_rect[2] * progress,
            progress_rect[3],
            progress_h * 0.5,
            palette["accent"],
        )

    card_bottom = y + 49.0 * scale
    card_top = progress_y - 8.0 * scale
    card_h = max(54.0 * scale, card_top - card_bottom)
    card = (content_x, card_bottom, content_w, card_h)
    card_radius = 4.0 * scale
    _draw_round_rect(*card, card_radius, palette["card"])
    _draw_round_outline(*card, card_radius, palette["line"])

    task = state.active_task
    if task is None:
        finished = _route_is_finished(state)
        title = "Tutorial complete" if finished else "Page complete"
        guidance = (
            "All tutorial actions were detected. Return to the library or review earlier pages."
            if finished else
            "This page is complete. Use Back to review it or Next to continue."
        )
        accent = palette["success"]
        shortcut = ""
    else:
        title = task.label + ("  ·  Optional" if task.optional else "")
        guidance = _TASK_GUIDANCE.get(task.key, "Complete this action in Blender to continue.")
        accent = palette["accent"]
        shortcut = _task_shortcut_text(bpy.context, task, page)

    title_y = card[1] + card[3] - 27.0 * scale
    accent_bar = (card[0] + 4.0 * scale, card[1] + 5.0 * scale, 3.0 * scale, max(1.0, card[3] - 10.0 * scale))
    _draw_round_rect(*accent_bar, accent_bar[2] * 0.5, accent)
    _draw_text(_ellipsize(title, content_w - 25.0 * scale, hud["title_size"]), card[0] + 14.0 * scale, title_y, hud["title_size"], palette["card_text"])
    guidance_lines = _wrap_measured(guidance, content_w - 26.0 * scale, hud["small_size"], max_lines=2)
    _draw_text_lines(guidance_lines, card[0] + 14.0 * scale, title_y - 22.0 * scale, hud["small_size"], palette["muted"], hud["line_h"])
    if shortcut and card_h >= 92.0 * scale:
        _draw_text(
            _ellipsize(shortcut, content_w - 26.0 * scale, hud["small_size"]),
            card[0] + 14.0 * scale,
            card[1] + 11.0 * scale,
            hud["small_size"],
            palette["accent_label"],
        )

    action_rect = hud.get("action_rect")
    if task is not None and action_rect is not None:
        label = _TASK_ACTION_LABELS.get(task.key, "Do This Step")
        _draw_flat_button(state, hud, "do_action", action_rect, label, primary=True)

    if not total:
        step_label = "Complete"
    elif w < 430.0 * scale:
        step_label = f"{current}/{total}"
    else:
        step_label = f"{current} / {total}  ·  {round(progress * 100):d}% complete"
    _draw_text(
        step_label,
        hud["controls"]["help"][0] - 8.0 * scale,
        y + h - hud["header_h"] * 0.5 - 4.0 * scale,
        hud["small_size"],
        palette["muted"],
        align="RIGHT",
    )


def _draw_overlay(operator: "FBP_OT_live_tutorial_modal") -> None:
    context = bpy.context
    area = context.area
    region = context.region
    if area is None or region is None or area.as_pointer() != operator._target_area_ptr or region.type != "WINDOW":
        return
    state = operator._state
    hud = _compute_hud(context, region, state)
    operator._hud_layout = hud
    x, y, w, h, scale = hud["x"], hud["y"], hud["width"], hud["height"], hud["scale"]
    palette = hud["palette"]

    gpu.state.blend_set("ALPHA")
    try:
        outer_radius = 6.0 * scale
        _draw_round_rect(x, y, w, h, outer_radius, palette["panel"])
        header_y = y + h - hud["header_h"]
        _draw_round_rect(x, header_y, w, hud["header_h"], outer_radius, palette["header"])
        _draw_rect(x, header_y, w, outer_radius, palette["header"])
        _draw_rect(x, header_y, w, max(1.0, scale), palette["line"])
        header_label = "Frame By Plane  Tutorial"
        if state.route is not None:
            header_label = f"{_ROUTE_SHORT_LABELS.get(state.route.key, state.route.title)}  Tutorial"
        if w < 430.0 * scale:
            header_label = "FBP  Tutorial"
        _draw_text(
            header_label,
            x + 12.0 * scale,
            header_y + hud["header_h"] * 0.5 - 5.0 * scale,
            hud["body_size"],
            palette["header_text"],
        )
        state.hitboxes.clear()
        if state.route is None:
            _draw_route_chooser(state, hud)
        else:
            _draw_step(state, hud)
        controls = hud["controls"]
        _draw_flat_button(state, hud, "control_close", controls["close"], "×")
        if state.route is not None:
            _draw_flat_button(state, hud, "control_help", controls["help"], "?  Help")
            task = state.active_task
            _draw_flat_button(state, hud, "control_back", controls["back"], "‹  Back")
            if task is not None:
                _draw_flat_button(state, hud, "control_skip", controls["next"], "Skip")
            else:
                next_label = "Tutorials" if _route_is_finished(state) else "Next"
                _draw_flat_button(state, hud, "control_next", controls["next"], next_label)
        _draw_round_outline(x, y, w, h, outer_radius, palette["line"], max(1.0, scale))
    finally:
        gpu.state.blend_set("NONE")


# -----------------------------------------------------------------------------
# Native Help popup and contextual tutorial actions


def _tutorial_preferences(context: bpy.types.Context):
    try:
        return fbp_get_addon_preferences(context)
    except (AttributeError, KeyError, ReferenceError, RuntimeError, TypeError, ValueError):
        return None


def _layer_settings_categories(context: bpy.types.Context) -> tuple[str, ...]:
    """Return enabled Layer Settings tabs in the user's preference order."""
    prefs = _tutorial_preferences(context)
    if prefs is None:
        return ("Tool",)
    if not bool(getattr(prefs, "show_panel_layer_settings", True)):
        return ()
    result = []
    if bool(getattr(prefs, "show_control_panel_n_panel", False)):
        result.append("Frame By Plane")
    if bool(getattr(prefs, "show_control_panel_properties", True)):
        result.append("Tool")
    return tuple(result)


def _show_layer_settings(context: bpy.types.Context) -> bool:
    area = _find_view3d_area(context)
    active = getattr(getattr(area, "spaces", None), "active", None)
    if area is None or active is None:
        return False
    categories = _layer_settings_categories(context)
    if not categories:
        return False
    category = categories[0]
    try:
        active.show_region_ui = True
        region = next((item for item in area.regions if item.type == "UI"), None)
        if region is not None:
            region.active_panel_category = category
        area.tag_redraw()
        return True
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        return False


def _open_effects_view(context: bpy.types.Context, view: str) -> bool:
    try:
        result = bpy.ops.fbp.open_effects_masks(view=str(view or "2D"))
        return "FINISHED" in result
    except (AttributeError, RuntimeError, TypeError):
        return False


def _operator_started(result: set[str]) -> bool:
    return bool({"FINISHED", "RUNNING_MODAL"}.intersection(result))


def _open_viewport_radial(context: bpy.types.Context) -> bool:
    area = _find_view3d_area(context)
    region = next(
        (
            item
            for item in tuple(getattr(area, "regions", ()) or ())
            if str(getattr(item, "type", "") or "") == "WINDOW"
        ),
        None,
    )
    window = getattr(context, "window", None)
    if area is None or region is None or window is None:
        return False
    try:
        with context.temp_override(
            window=window,
            area=area,
            region=region,
            space_data=area.spaces.active,
        ):
            return _operator_started(
                bpy.ops.fbp.call_viewport_pie("INVOKE_DEFAULT")
            )
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        return False


def _run_tutorial_task_action(context: bpy.types.Context, state: TutorialState) -> bool:
    task = state.active_task
    if task is None:
        return False
    key = task.key
    try:
        if key in {"image_open_importer", "image_import"}:
            return _operator_started(bpy.ops.fbp.popup_single_plane("INVOKE_DEFAULT"))
        if key in {"image_open_crop", "image_crop"}:
            return _open_viewport_radial(context)
        if key in {"image_open_masks", "image_mask"}:
            return _open_viewport_radial(context)
        if key in {"multi_open_masks", "multi_clipping", "multi_holdout"}:
            return _open_effects_view(context, "MASK")
        if key == "image_open_effects":
            return _open_effects_view(context, "2D")
        if key == "image_effect":
            if not _open_effects_view(context, "2D"):
                return False
            result = bpy.ops.fbp.add_effect(effect_id="PIXELATE")
            return _operator_started(result)
        if key in {"multi_open_effects", "multi_effect"}:
            return _open_effects_view(context, "2D")
        if key in {"color_open_creator", "color_generate"}:
            return _operator_started(bpy.ops.fbp.popup_color_plane("INVOKE_DEFAULT", preset_type="CUSTOM"))
        if key in {"color_open_settings", "color_edit", "color_gradient_edit", "multi_open_settings", "multi_loop"}:
            return _show_layer_settings(context)
        if key == "color_add_gradient":
            if _activate_tutorial_color_rig(context, state) is None:
                return False
            return _operator_started(bpy.ops.fbp.insert_images_after_selected(frame_mode="GRADIENT"))
        if key == "color_preview":
            space = getattr(getattr(context, "area", None), "spaces", None)
            active = getattr(space, "active", None)
            shading = getattr(active, "shading", None)
            if shading is None:
                return False
            shading.type = "MATERIAL"
            return True
        if key == "color_add_frame":
            if _activate_tutorial_color_rig(context, state) is None:
                return False
            return _operator_started(bpy.ops.fbp.insert_images_after_selected(frame_mode="COLOR"))
        if key in {"color_open_mesh_effects", "color_mesh"}:
            return _open_effects_view(context, "3D")
        if key in {"multi_open_importer", "multi_generate"}:
            return _operator_started(bpy.ops.fbp.popup_multiplane("INVOKE_DEFAULT", animation=True))
        if key in {"multi_open_camera", "multi_camera"}:
            return _operator_started(bpy.ops.fbp.popup_generate_camera("INVOKE_DEFAULT"))
        if key in {"multi_start_depth", "multi_depth"}:
            return _operator_started(bpy.ops.transform.translate("INVOKE_DEFAULT"))
    except (AttributeError, RuntimeError, TypeError, ValueError):
        return False
    return False


_MANUAL_ACTION_TASKS = frozenset({
    "image_open_importer", "image_open_crop", "image_open_masks", "image_open_effects",
    "color_open_creator", "color_open_settings", "color_open_mesh_effects",
    "multi_open_importer", "multi_open_camera", "multi_start_depth",
    "multi_open_settings", "multi_open_effects", "multi_open_masks",
})


def fbp_notify_tutorial_action(context: bpy.types.Context, *task_keys: str) -> bool:
    """Advance a matching manual micro-step invoked from normal add-on UI."""
    operator = _ACTIVE_OPERATOR
    if operator is None or not task_keys:
        return False
    state = operator._state
    task = state.active_task
    if task is None or task.key not in {str(key) for key in task_keys}:
        return False
    state.manual_completed.add(task.key)
    _capture_completion_anchors(context, state, task.key)
    _advance_completed_page(state)
    _tag_area(operator._target_area_ptr)
    return True

_ACTIVE_OPERATOR: "FBP_OT_live_tutorial_modal | None" = None
_RESUME_STATE: TutorialState | None = None
_RESUME_SCENE_PTR = 0


def _resume_state_for_context(context: bpy.types.Context) -> TutorialState:
    scene_ptr = context.scene.as_pointer()
    if _RESUME_STATE is not None and _RESUME_SCENE_PTR == scene_ptr:
        return _RESUME_STATE
    state = TutorialState()
    state.reset_baseline(context)
    return state


def _find_view3d_area(context: bpy.types.Context) -> bpy.types.Area | None:
    if context.area and context.area.type == "VIEW_3D":
        return context.area
    screen = context.window.screen if context.window else context.screen
    if screen:
        return next((area for area in screen.areas if area.type == "VIEW_3D"), None)
    return None


def _tag_area(area_ptr: int) -> None:
    for window in bpy.context.window_manager.windows:
        screen = window.screen
        if not screen:
            continue
        for area in screen.areas:
            if area.as_pointer() == area_ptr:
                area.tag_redraw()
                return


def _help_icon_kwargs(kind: str) -> dict[str, Any]:
    key = str(kind or "INFO").upper()
    custom = _CUSTOM_UI_KEYS.get(key)
    if custom:
        return ui_label_icon_kwargs(custom, fallback="generic.info")
    return {"icon": _NATIVE_HELP_ICONS.get(key, "DOT")}


def _help_wrap(text: str, width: int = 82) -> tuple[str, ...]:
    words = " ".join(str(text or "").split()).split()
    if not words:
        return ()
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = word if not current else f"{current} {word}"
        if len(candidate) <= width:
            current = candidate
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return tuple(lines)


def _help_labels(layout: bpy.types.UILayout, text: str, *, icon: str | None = None, width: int = 82) -> None:
    for index, line in enumerate(_help_wrap(text, width)):
        if index == 0 and icon:
            layout.label(text=line, icon=icon)
        else:
            layout.label(text=line)


class FBP_OT_tutorial_help(bpy.types.Operator):
    """Show the detailed native Blender guide for the current tutorial page."""

    bl_idname = "fbp.tutorial_help"
    bl_label = "Tutorial Help"
    bl_description = 'Open detailed native Blender help for the current live tutorial objective'
    bl_options = {"INTERNAL"}

    def invoke(self, context: bpy.types.Context, event: bpy.types.Event):
        del event
        if _ACTIVE_OPERATOR is None or _ACTIVE_OPERATOR._state.page is None:
            return {"CANCELLED"}
        return context.window_manager.invoke_popup(self, width=620)

    def execute(self, context: bpy.types.Context):
        del context
        return {"FINISHED"}

    def draw(self, context: bpy.types.Context) -> None:
        del context
        operator = _ACTIVE_OPERATOR
        if operator is None:
            self.layout.label(text="The live tutorial is no longer active.", icon="INFO")
            return
        state = operator._state
        route = state.route
        page = state.page
        if route is None or page is None:
            self.layout.label(text="Choose a tutorial route first.", icon="BOOKMARKS")
            return

        layout = configure_layout(self.layout)
        header = section_header(
            layout,
            page.help_title or page.title,
            icon_value=int(_help_icon_kwargs(page.icon).get("icon_value", 0) or 0),
            icon=str(_help_icon_kwargs(page.icon).get("icon", "INFO")),
            suffix=f"· {state.page_index + 1} / {len(route.pages)}",
        )
        header.alignment = 'LEFT'

        if page.shortcut:
            box = layout.box()
            configure_layout(box)
            section_header(box, "Shortcut", icon="EVENT_SHIFT")
            kind = page.shortcut[0][0]
            shortcut = " > ".join(label for _kind, label in page.shortcut)
            box.label(text=shortcut, **_help_icon_kwargs(kind))

        guide = layout.box()
        configure_layout(guide)
        section_header(guide, "Step by Step", icon="QUESTION")
        for index, step in enumerate(page.help_steps, start=1):
            for line_index, line in enumerate(_help_wrap(step, 88)):
                prefix = f"{index}. " if line_index == 0 else "   "
                guide.label(text=f"{prefix}{line}")

        if page.help_notes:
            notes = layout.box()
            configure_layout(notes)
            section_header(notes, "Notes", icon="INFO")
            for note in page.help_notes:
                col = notes.column(align=True)
                _help_labels(col, note, icon="DOT", width=78)

        if page.pro_tip:
            pro = layout.box()
            configure_layout(pro)
            section_header(pro, "PRO Tip", icon="SOLO_ON")
            _help_labels(pro, page.pro_tip, width=80)


class FBP_OT_live_tutorial_modal(bpy.types.Operator):
    """Internal persistent adaptive tutorial HUD."""

    bl_idname = "fbp.live_tutorial_modal"
    bl_label = "Frame By Plane Live Tutorial"
    bl_description = 'Run the persistent interactive tutorial while allowing normal Blender input'
    bl_options = {"INTERNAL"}

    _draw_handle = None
    _timer = None
    _target_area_ptr: int = 0
    _scene_ptr: int = 0
    _state: TutorialState
    _hud_layout: dict[str, Any]

    def invoke(self, context: bpy.types.Context, event: bpy.types.Event):
        del event
        global _ACTIVE_OPERATOR, _RESUME_STATE, _RESUME_SCENE_PTR
        if _ACTIVE_OPERATOR is not None:
            _ACTIVE_OPERATOR._close(context)

        area = _find_view3d_area(context)
        if area is None:
            self.report({"WARNING"}, "Open a 3D Viewport to start the Frame By Plane tutorial")
            return {"CANCELLED"}
        region = next((item for item in area.regions if item.type == "WINDOW"), None)
        if region is None:
            return {"CANCELLED"}

        scene_ptr = context.scene.as_pointer()
        self._scene_ptr = scene_ptr
        self._state = _resume_state_for_context(context)
        self._target_area_ptr = area.as_pointer()
        self._hud_layout = {}
        self._draw_handle = bpy.types.SpaceView3D.draw_handler_add(_draw_overlay, (self,), "WINDOW", "POST_PIXEL")
        self._timer = context.window_manager.event_timer_add(DETECTION_INTERVAL, window=context.window)
        context.window_manager.modal_handler_add(self)
        _ACTIVE_OPERATOR = self
        _tag_area(self._target_area_ptr)
        return {"RUNNING_MODAL"}

    def _close(self, context: bpy.types.Context) -> None:
        global _ACTIVE_OPERATOR, _RESUME_STATE, _RESUME_SCENE_PTR
        if self._draw_handle is not None:
            try:
                bpy.types.SpaceView3D.draw_handler_remove(self._draw_handle, "WINDOW")
            except (ReferenceError, RuntimeError):
                pass
            self._draw_handle = None
        if self._timer is not None:
            try:
                context.window_manager.event_timer_remove(self._timer)
            except (ReferenceError, RuntimeError):
                pass
            self._timer = None
        _tag_area(self._target_area_ptr)
        _RESUME_STATE = self._state
        _RESUME_SCENE_PTR = self._scene_ptr or context.scene.as_pointer()
        if _ACTIVE_OPERATOR is self:
            _ACTIVE_OPERATOR = None

    def cancel(self, context: bpy.types.Context) -> None:
        self._close(context)

    def perform_action(self, context: bpy.types.Context, action: str):
        state = self._state
        if action == "CLOSE":
            self._close(context)
            return {"FINISHED"}
        if action == "ACTION":
            task = state.active_task
            started = _run_tutorial_task_action(context, state)
            if started and task is not None and task.key in _MANUAL_ACTION_TASKS:
                state.manual_completed.add(task.key)
                _capture_completion_anchors(context, state, task.key)
                _advance_completed_page(state)
            if not started:
                task = state.active_task
                label = task.label if task is not None else "this step"
                self.report({"INFO"}, f"Select a compatible layer, then complete: {label}")
            _tag_area(self._target_area_ptr)
            return {"FINISHED"}
        if action == "RESTART":
            route = state.route
            if route is not None:
                state.enter_route(context, route.key)
            _tag_area(self._target_area_ptr)
            return {"FINISHED"}
        if action == "HELP":
            if state.route is None:
                state.enter_route(context)
            try:
                bpy.ops.fbp.tutorial_help("INVOKE_DEFAULT")
            except RuntimeError:
                pass
            _tag_area(self._target_area_ptr)
            return {"FINISHED"}
        if action == "BACK":
            if state.route is not None and state.page_index > 0:
                state.page_index -= 1
            elif state.route is not None:
                state.route_key = None
                state.page_index = 0
            _tag_area(self._target_area_ptr)
            return {"FINISHED"}
        if action == "SKIP":
            task = state.active_task
            if task is None:
                return {"CANCELLED"}
            state.manual_completed.add(task.key)
            _capture_completion_anchors(context, state, task.key)
            _advance_completed_page(state)
            self.report({"INFO"}, f"Skipped tutorial step: {task.label}")
            _tag_area(self._target_area_ptr)
            return {"FINISHED"}
        if action == "NEXT":
            if state.route is None:
                state.enter_route(context)
            else:
                task = state.active_task
                if task is not None and not task.optional:
                    self.report({'INFO'}, f"Complete this step first: {task.label}")
                    _tag_area(self._target_area_ptr)
                    return {"FINISHED"}
                if task is not None and task.optional:
                    state.manual_completed.add(task.key)
                    _advance_completed_page(state)
                    _tag_area(self._target_area_ptr)
                    return {"FINISHED"}
                if state.page_index < len(state.route.pages) - 1:
                    state.page_index += 1
                else:
                    state.route_key = None
                    state.page_index = 0
            _tag_area(self._target_area_ptr)
            return {"FINISHED"}
        return {"CANCELLED"}

    def modal(self, context: bpy.types.Context, event: bpy.types.Event):
        if self._draw_handle is None:
            return {"CANCELLED"}

        if event.type == "TIMER" and getattr(event, "timer", self._timer) == self._timer:
            now = time.monotonic()
            if now - self._state.last_detection >= DETECTION_INTERVAL:
                self._state.last_detection = now
                _update_progress(context, self._state)
                _tag_area(self._target_area_ptr)
            return {"PASS_THROUGH"}

        in_target = context.area is not None and context.area.as_pointer() == self._target_area_ptr
        if in_target and event.type == "MOUSEMOVE":
            hover = ""
            for key, rect in self._state.hitboxes.items():
                if _inside(rect, event.mouse_region_x, event.mouse_region_y):
                    hover = key
                    break
            if hover != self._state.hover:
                self._state.hover = hover
                _tag_area(self._target_area_ptr)
            return {"PASS_THROUGH"}

        if in_target and event.type == "LEFTMOUSE" and event.value == "PRESS":
            for key, rect in tuple(self._state.hitboxes.items()):
                if not _inside(rect, event.mouse_region_x, event.mouse_region_y):
                    continue
                control_actions = {
                    "control_close": "CLOSE",
                    "control_help": "HELP",
                    "control_back": "BACK",
                    "control_restart": "RESTART",
                    "control_next": "NEXT",
                    "control_skip": "SKIP",
                }
                if key in control_actions:
                    self.perform_action(context, control_actions[key])
                    return {"FINISHED"} if key == "control_close" else {"RUNNING_MODAL"}
                if key.startswith("route_"):
                    route_key = key.removeprefix("route_")
                    if route_key in ROUTES:
                        self._state.enter_route(context, route_key)
                        _tag_area(self._target_area_ptr)
                        return {"RUNNING_MODAL"}
                if key == "do_action":
                    self.perform_action(context, "ACTION")
                    return {"RUNNING_MODAL"}

        return {"PASS_THROUGH"}


class FBP_OT_live_tutorial(bpy.types.Operator):
    """Open the adaptive interactive Frame By Plane tutorial."""

    bl_idname = "fbp.live_tutorial"
    bl_label = "Tutorial"
    bl_description = "Open the interactive Frame By Plane tutorial"
    bl_options = {"REGISTER"}

    def execute(self, context: bpy.types.Context):
        area = _find_view3d_area(context)
        if area is None:
            self.report({"WARNING"}, "Open a 3D Viewport to start the Frame By Plane tutorial")
            return {"CANCELLED"}
        region = next((item for item in area.regions if item.type == "WINDOW"), None)
        if region is None:
            return {"CANCELLED"}
        window = getattr(context, "window", None)
        screen = getattr(context, "screen", None) or (getattr(window, "screen", None) if window else None)
        if window is None or screen is None:
            return {"CANCELLED"}
        with context.temp_override(window=window, screen=screen, area=area, region=region):
            return bpy.ops.fbp.live_tutorial_modal("INVOKE_DEFAULT")


CLASSES = [
    FBP_OT_tutorial_help,
    FBP_OT_live_tutorial_modal,
    FBP_OT_live_tutorial,
]


def quiesce_live_tutorial():
    """Close the modal overlay before class/property teardown begins."""
    global _ACTIVE_OPERATOR
    active = _ACTIVE_OPERATOR
    _ACTIVE_OPERATOR = None
    if active is None:
        return False
    try:
        active._close(bpy.context)
        return True
    except FBP_DATA_ERRORS:
        return False


def register() -> None:
    quiesce_live_tutorial()
    register_interactive_classes(CLASSES)


def unregister() -> None:
    global _COLOR_SHADER, _IMAGE_SHADER, _IMAGE_SHADER_SUPPORTS_TINT, _RESUME_STATE, _RESUME_SCENE_PTR
    quiesce_live_tutorial()
    unregister_classes(CLASSES)
    _RESUME_STATE = None
    _RESUME_SCENE_PTR = 0
    _TUTORIAL_ICON_TEXTURES.clear()
    _TUTORIAL_ICON_IMAGES.clear()
    _COLOR_SHADER = None
    _IMAGE_SHADER = None
    _IMAGE_SHADER_SUPPORTS_TINT = False
