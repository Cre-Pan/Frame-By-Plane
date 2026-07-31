"""Persistent Layer Set and FBP Output nodes for Blender 5.2.

Visible nodes are native compositor groups so evaluation remains entirely in
Blender. Instance state is serialized on the Scene and keyed by UUID; every
node instance owns a distinct group tree. This also gives Shift+D copies an
independent state after the next differential sync.
"""

import json
import math
import os
import re
import uuid

import bpy
from bpy.app.handlers import persistent
from bpy.props import BoolProperty, CollectionProperty, EnumProperty, FloatProperty, IntProperty, StringProperty
from bpy.types import Menu, Operator, Panel, PropertyGroup, UIList

from .compositor_contracts import (
    depth_split_thresholds,
    directed_cycles,
    nearest_existing_parent,
    normalized_destination,
    output_format_issues,
    path_component_issues,
    resolve_uuid_set_memberships,
    safe_path_component,
    split_path_components,
)
from .ui_list_state import invoke_with_selection_modifiers
from .shortcut_runtime import primary_shortcut_label
from .runtime import FBP_DATA_ERRORS, FBP_DATA_IO_ERRORS, fbp_warn
from .feature_scope import fbp_feature_enabled
from .layers import fbp_set_ui_units_x
from .registration import (
    append_handler_once,
    register_classes,
    remove_handlers_by_name,
    unregister_classes,
    unregister_type_properties,
)
from .safe_tasks import cancel_scheduled_prefixes, schedule_once
from .service_registry import call_service
from .ui_list_state import (
    clear_anchor,
    identity_at,
    resolve_anchor_index,
    restore_active_index,
    store_anchor,
    transient_get,
)
from .ui_list_state import mark_ui_list_draw, ui_list_mutation_delay
from .interface_preferences import (
    fbp_draw_uilist_spacer,
    fbp_draw_uilist_header,
    fbp_uilist_icon_order,
    fbp_uilist_is_spacer,
    fbp_uilist_visible_columns,
)
from .ui_style import (
    configure_layout,
    empty_state,
    hint_row,
    list_rows,
    section_gap,
    section_header,
)


STRUCTURE_VERSION = 4

_PREVIOUS_DRAW_ADD_MENU_CALLBACK = globals().get("_FBP_DRAW_ADD_MENU_CALLBACK")
ROLE_SET = "layer_set"
ROLE_OUTPUT = "output"
ROLE_STACK = "over_stack"

MASK_ITEMS = (
    ('COMBINED', "Combined Alpha", "Preserve partial alpha"),
    ('BINARY', "Binary", "Threshold alpha at 0.5"),
    ('INVERTED', "Inverted", "Invert combined alpha"),
    ('SOFT', "Soft", "Soft native alpha mask"),
    ('EDGE', "Edge", "Edge derived from alpha"),
)
SET_MODE_ITEMS = (
    ('MANUAL', "Manual", "Use eye states"),
    ('RULE', "Rule Based", "Evaluate the configured rule"),
    ('MIXED', "Mixed", "Rules with per-row overrides"),
)
OVERRIDE_ITEMS = (
    ('AUTO', "Auto", "Use the rule result"),
    ('INCLUDE', "Force Include", "Always include this source"),
    ('EXCLUDE', "Force Exclude", "Always exclude this source"),
)
MEMBERSHIP_ITEMS = (
    ('MULTIPLE', "Multiple Sets", "A source can be active in multiple Layer Sets"),
    ('EXCLUSIVE', "One Set Only", "Within the same exclusive group, enabling a source disables it in the other sets"),
)
SET_OPERATION_ITEMS = (
    ('UNION', "Union", "Include UUIDs active in either source Layer Set"),
    ('DIFFERENCE', "Difference", "Include UUIDs active in A but not B"),
    ('INTERSECTION', "Intersection", "Include UUIDs active in both source Layer Sets"),
    ('XOR', "XOR", "Include UUIDs active in exactly one source Layer Set"),
)
OUTPUT_MODE_ITEMS = (
    ('SEPARATE', "Separate Files", "One native File Output per pass"),
    ('MULTILAYER', "Multilayer EXR", "One multilayer EXR file"),
)

# One raw catalog feeds the normalized registry below. No second effect/menu
# list exists elsewhere in the add-on.
_FBP_NODE_ITEMS = (
    {"id": "layer_set", "label": "Layer Set", "category": "LAYERS", "icon": "RENDERLAYERS", "kind": "SET"},
    {"id": "empty_layer_set", "label": "Empty Layer Set", "category": "LAYERS", "icon": "RENDERLAYERS", "kind": "SET"},
    {"id": "selected_layer_set", "label": "Layer Set from Selected Layers", "category": "LAYERS", "icon": "RESTRICT_SELECT_OFF", "kind": "SET_SELECTED"},
    {"id": "folder_layer_set", "label": "Layer Set from Active Folder", "category": "LAYERS", "icon": "FILE_FOLDER", "kind": "SET_FOLDER"},
    {"id": "tag_layer_set", "label": "Layer Set from Color Tag", "category": "LAYERS", "icon": "COLOR", "kind": "SET_TAG"},
    {"id": "type_layer_set", "label": "Layer Set from Type", "category": "LAYERS", "icon": "IMAGE_DATA", "kind": "SET_TYPE"},
    {"id": "unassigned", "label": "Unassigned Layer Set", "category": "LAYERS", "icon": "QUESTION", "kind": "UNASSIGNED"},
    {"id": "foreground_set", "label": "Foreground Layer Set", "category": "LAYERS", "icon": "TRIA_UP", "kind": "SET_FG"},
    {"id": "midground_set", "label": "Midground Layer Set", "category": "LAYERS", "icon": "REMOVE", "kind": "SET_MID"},
    {"id": "background_set", "label": "Background Layer Set", "category": "LAYERS", "icon": "TRIA_DOWN", "kind": "SET_BG"},
    {"id": "fbp_output", "label": "FBP Output", "category": "OUTPUT", "icon": "OUTPUT", "kind": "OUTPUT"},
    {"id": "separate_output", "label": "Separate Files Output", "category": "OUTPUT", "icon": "FILE_IMAGE", "kind": "OUTPUT_SEPARATE"},
    {"id": "multilayer_output", "label": "Multilayer EXR Output", "category": "OUTPUT", "icon": "IMAGE_DATA", "kind": "OUTPUT_EXR"},
    {"id": "beauty_passes_output", "label": "Beauty + Passes Output", "category": "OUTPUT", "icon": "RENDER_RESULT", "kind": "OUTPUT_BEAUTY"},
    {"id": "glow", "label": "Glow", "category": "EFFECTS", "icon": "LIGHT_SUN", "kind": "CompositorNodeGlare"},
    {"id": "blur", "label": "Blur", "category": "EFFECTS", "icon": "NODE_COMPOSITING", "kind": "CompositorNodeBlur"},
    {"id": "defocus", "label": "Defocus", "category": "EFFECTS", "icon": "CAMERA_DATA", "kind": "CompositorNodeDefocus"},
    {"id": "color_grade", "label": "Color Grade", "category": "EFFECTS", "icon": "COLOR", "kind": "CompositorNodeColorBalance"},
    {"id": "pixelate", "label": "Pixelate", "category": "EFFECTS", "icon": "ALIASED", "kind": "CompositorNodePixelate"},
    {"id": "vignette", "label": "Vignette", "category": "EFFECTS", "icon": "IMAGE_ALPHA", "kind": "ASSET_VIGNETTE"},
    {"id": "unsharp", "label": "Unsharp Mask", "category": "EFFECTS", "icon": "SHARPCURVE", "kind": "ASSET_UNSHARP_MASK"},
    {"id": "tune", "label": "Tune Image", "category": "EFFECTS", "icon": "IMAGE_RGB_ALPHA", "kind": "ASSET_TUNE_IMAGE"},
    {"id": "grain", "label": "Film Grain", "category": "EFFECTS", "icon": "RNDCURVE", "kind": "ASSET_FILM_GRAIN"},
    {"id": "chromatic", "label": "Chromatic Aberration", "category": "EFFECTS", "icon": "COLOR", "kind": "ASSET_CHROMATIC_ABERRATION"},
    {"id": "sepia", "label": "Sepia", "category": "EFFECTS", "icon": "COLOR", "kind": "ASSET_SEPIA"},
    {"id": "alpha_mask", "label": "Alpha Mask", "category": "MASKS", "icon": "IMAGE_ALPHA", "kind": "CompositorNodeSetAlpha"},
    {"id": "combined_mask", "label": "Combined Mask", "category": "MASKS", "icon": "SELECT_EXTEND", "kind": "ShaderNodeMath"},
    {"id": "holdout", "label": "Holdout", "category": "MASKS", "icon": "CLIPUV_HLT", "kind": "CompositorNodeSetAlpha"},
    {"id": "inverted_mask", "label": "Inverted Mask", "category": "MASKS", "icon": "IMAGE_ALPHA", "kind": "ShaderNodeMath"},
    {"id": "edge_mask", "label": "Edge Mask", "category": "MASKS", "icon": "MOD_EDGESPLIT", "kind": "CompositorNodeFilter"},
    {"id": "soft_mask", "label": "Soft Mask", "category": "MASKS", "icon": "NODE_COMPOSITING", "kind": "CompositorNodeBlur"},
    {"id": "matte", "label": "Matte", "category": "MASKS", "icon": "IMAGE_ALPHA", "kind": "CompositorNodeSetAlpha"},
    {"id": "alpha_over", "label": "Alpha Over", "category": "UTILITIES", "icon": "NODE_COMPOSITING", "kind": "CompositorNodeAlphaOver"},
    {"id": "composite_stack", "label": "Composite Stack", "description": "Compact custom Alpha Over stack with dynamic inputs and a combined mask", "category": "UTILITIES", "icon": "NODETREE", "kind": "STACK"},
    {"id": "clean_pipeline", "label": "Clean FBP Pipeline", "description": "Rebuild the visible compositor as Layers, Effects / Masks and Export while preserving artist nodes", "category": "UTILITIES", "icon": "BRUSH_DATA", "kind": "CLEAN_PIPELINE"},
    {"id": "viewer", "label": "Viewer", "category": "UTILITIES", "icon": "HIDE_OFF", "kind": "CompositorNodeViewer"},
    {"id": "separate_rgba", "label": "Separate RGBA", "category": "UTILITIES", "icon": "NODE_COMPOSITING", "kind": "CompositorNodeSeparateColor"},
    {"id": "compare", "label": "Compare", "category": "UTILITIES", "icon": "ARROW_LEFTRIGHT", "kind": "CompositorNodeSplit"},
    {"id": "set_difference", "label": "Image Set Difference", "description": "Subtract one image or mask from another", "category": "UTILITIES", "icon": "SELECT_DIFFERENCE", "kind": "ShaderNodeMath"},
    {"id": "set_intersection", "label": "Image Set Intersection", "description": "Multiply two images or masks", "category": "UTILITIES", "icon": "SELECT_INTERSECT", "kind": "ShaderNodeMath"},
    {"id": "set_union", "label": "Image Set Union", "description": "Combine two images or masks using Maximum", "category": "UTILITIES", "icon": "SELECT_EXTEND", "kind": "ShaderNodeMath"},
    {"id": "set_combine", "label": "Image Set Combine", "description": "Combine two images or masks using Maximum", "category": "UTILITIES", "icon": "SELECT_EXTEND", "kind": "ShaderNodeMath"},
    {"id": "set_xor", "label": "Image Set XOR", "description": "Compare two images or masks", "category": "UTILITIES", "icon": "SELECT_DIFFERENCE", "kind": "ShaderNodeMath"},
    {"id": "uuid_set_union", "label": "UUID Set Union", "description": "Create a live Layer Set from the union of two Layer Sets", "category": "UTILITIES", "icon": "SELECT_EXTEND", "kind": "SET_UUID_UNION"},
    {"id": "uuid_set_difference", "label": "UUID Set Difference", "description": "Create a live Layer Set containing A minus B", "category": "UTILITIES", "icon": "SELECT_DIFFERENCE", "kind": "SET_UUID_DIFFERENCE"},
    {"id": "uuid_set_intersection", "label": "UUID Set Intersection", "description": "Create a live Layer Set from the intersection of two Layer Sets", "category": "UTILITIES", "icon": "SELECT_INTERSECT", "kind": "SET_UUID_INTERSECTION"},
    {"id": "uuid_set_xor", "label": "UUID Set XOR", "description": "Create a live Layer Set containing UUIDs active in exactly one source set", "category": "UTILITIES", "icon": "SELECT_DIFFERENCE", "kind": "SET_UUID_XOR"},
    {"id": "premultiply", "label": "Premultiply", "category": "UTILITIES", "icon": "IMAGE_ALPHA", "kind": "CompositorNodePremulKey"},
    {"id": "unpremultiply", "label": "Unpremultiply", "category": "UTILITIES", "icon": "IMAGE_ALPHA", "kind": "CompositorNodePremulKey"},
    {"id": "review", "label": "Animation Review", "category": "PRESETS", "icon": "PLAY", "kind": "PRESET_REVIEW"},
    {"id": "delivery", "label": "Compositing Delivery", "category": "PRESETS", "icon": "EXPORT", "kind": "PRESET_DELIVERY"},
    {"id": "final", "label": "Final Render", "category": "PRESETS", "icon": "RENDER_STILL", "kind": "PRESET_FINAL"},
    {"id": "debug", "label": "Debug", "category": "PRESETS", "icon": "CONSOLE", "kind": "PRESET_DEBUG"},
    {"id": "beauty_masks", "label": "Beauty + Masks", "category": "PRESETS", "icon": "IMAGE_ALPHA", "kind": "PRESET_BEAUTY_MASKS"},
    {"id": "character_composite", "label": "Character Composite", "category": "PRESETS", "icon": "OUTLINER_OB_ARMATURE", "kind": "PRESET_CHARACTER"},
    {"id": "background_defocus", "label": "Background Defocus", "category": "PRESETS", "icon": "CAMERA_DATA", "kind": "PRESET_BG_DEFOCUS"},
    {"id": "foreground_grade", "label": "Foreground Grade", "category": "PRESETS", "icon": "COLOR", "kind": "PRESET_FG_GRADE"},
    {"id": "beauty_separate", "label": "Beauty + Separate Passes", "category": "PRESETS", "icon": "FILE_IMAGE", "kind": "PRESET_BEAUTY_SEPARATE"},
    {"id": "beauty_multilayer", "label": "Beauty + Multilayer EXR", "category": "PRESETS", "icon": "IMAGE_DATA", "kind": "PRESET_BEAUTY_EXR"},
    {"id": "multilayer_delivery", "label": "Multilayer EXR Delivery", "category": "PRESETS", "icon": "EXPORT", "kind": "PRESET_EXR_DELIVERY"},
    {"id": "fg_mid_bg", "label": "Foreground / Midground / Background", "category": "PRESETS", "icon": "SEQ_STRIP_DUPLICATE", "kind": "PRESET_FMB"},
    {
        "id": "auto_depth_split",
        "label": "Auto Depth Split",
        "description": "Create Foreground, Midground and Background from deterministic camera-space source depths",
        "category": "PRESETS",
        "icon": "CAMERA_DATA",
        "kind": "PRESET_AUTO_DEPTH",
    },
    {"id": "full_setup", "label": "Full FBP Composite Setup", "category": "PRESETS", "icon": "NODETREE", "kind": "PRESET_FULL"},
)

FBP_NODE_REGISTRY = tuple(
    {
        **item,
        "identifier": item["id"],
        "description": item.get("description", f"Add {item['label']} to the compositor"),
        "builder": item["kind"],
        "version": STRUCTURE_VERSION,
        "search_keywords": tuple(
            dict.fromkeys(
                word.casefold()
                for word in re.split(
                    r"[^\w]+",
                    f"{item['label']} {item.get('description', '')} {item['category']} Frame by Plane",
                )
                if word
            )
        ),
        "compatibility": {"blender_min": (5, 2, 0), "tree": "CompositorNodeTree"},
        "preset_data": item.get("preset_data", {}),
    }
    for item in _FBP_NODE_ITEMS
)


def _id():
    return uuid.uuid4().hex


def _clean(value, fallback="Layer"):
    value = re.sub(r"[^\w .-]+", "_", str(value or "").strip(), flags=re.UNICODE)
    return value[:63] or fallback


def _tag(node, role, persistent_id):
    node["fbp_owned"] = True
    node["fbp_role"] = role
    node["fbp_uuid"] = persistent_id
    node["fbp_version"] = STRUCTURE_VERSION
    return node


_FBP_PENDING_NODE_SCENES = set()
_FBP_PENDING_STACK_SCENES = set()
_FBP_PENDING_OUTPUT_SCENES = set()
_FBP_ACTIVE_NODE_SCENES = set()
_FBP_ACTIVE_STACK_SCENES = set()
_FBP_ACTIVE_OUTPUT_SCENES = set()
_FBP_NODE_UPDATE_RETRIES = {}
_FBP_NODE_UPDATE_MAX_RETRIES = 3
_STACK_NODE_LINK_SIGNATURES = {}
_OUTPUT_NODE_LINK_SIGNATURES = {}
_LAYER_SET_OPERAND_ITEMS = ()


def fbp_reset_compositor_sets_runtime_state():
    """Retire process-only compositor state after Undo/Redo/Main replacement.

    Safe-task epochs invalidate callbacks but deliberately do not mutate module
    globals from Blender history handlers.  Clear those globals later from the
    idle history finalizer so stale scene pointers/signatures cannot suppress a
    fresh sync or be resolved against a replacement Main database.
    """
    global _SCENE_COPY_INDEX_COUNT, _LAYER_SET_OPERAND_ITEMS
    _FBP_PENDING_NODE_SCENES.clear()
    _FBP_PENDING_STACK_SCENES.clear()
    _FBP_PENDING_OUTPUT_SCENES.clear()
    _FBP_ACTIVE_NODE_SCENES.clear()
    _FBP_ACTIVE_STACK_SCENES.clear()
    _FBP_ACTIVE_OUTPUT_SCENES.clear()
    _FBP_NODE_UPDATE_RETRIES.clear()
    _STACK_NODE_LINK_SIGNATURES.clear()
    _OUTPUT_NODE_LINK_SIGNATURES.clear()
    globals().get("_NODE_SIGNATURES", {}).clear()
    globals().get("_SCENE_COPY_INDEX", {}).clear()
    _SCENE_COPY_INDEX_COUNT = -1
    _LAYER_SET_OPERAND_ITEMS = ()


def _set_compositor_runtime_status(scene, message):
    if scene is None or not hasattr(scene, "fbp_compositor_status"):
        return
    try:
        scene.fbp_compositor_status = str(message or "")
    except FBP_DATA_ERRORS:
        pass


def _queue_scene_property_sync(scene, *, first_interval=0.05):
    if scene is None or not hasattr(scene, "fbp_layer_sets"):
        return False
    key = _scene_runtime_key(scene)
    _FBP_PENDING_NODE_SCENES.add(key)
    accepted = schedule_once(
        "compositor_sets.node_properties",
        _flush_node_property_updates,
        first_interval=max(0.01, float(first_interval)),
    )
    if not accepted:
        _FBP_PENDING_NODE_SCENES.discard(key)
        _set_compositor_runtime_status(scene, "Compositor change pending · press Sync")
    return bool(accepted)


def _iter_compositor_nodes(tree, visited=None):
    """Iterate visible compositor nodes without entering FBP controller internals.

    Output and Stack rebuilds clear their owned child node trees.  Eagerly
    materializing those internal nodes and then rebuilding the controller leaves
    Python wrappers pointing at freed C nodes; Blender 5.2 can hard-crash before
    Python gets a chance to raise ``ReferenceError``.  Controller instances are
    yielded, but their implementation trees are deliberately treated as opaque.
    """
    if tree is None:
        return
    visited = visited if visited is not None else set()
    try:
        tree_key = int(tree.as_pointer())
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        tree_key = id(tree)
    if tree_key in visited:
        return
    visited.add(tree_key)
    for node in tuple(getattr(tree, 'nodes', ())):
        try:
            role = _node_role_without_idprops(node)
            yield node
            if role in {ROLE_SET, ROLE_OUTPUT, ROLE_STACK}:
                continue
            child = getattr(node, 'node_tree', None)
            if child is not None and getattr(child, 'bl_idname', '') == 'CompositorNodeTree':
                yield from _iter_compositor_nodes(child, visited)
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            continue


_FBP_NODE_ROLE_BY_IDNAME = {
    "FBPCompositorLayerSetNode": ROLE_SET,
    "FBPCompositorOutputNode": ROLE_OUTPUT,
    "FBPCompositorStackNode": ROLE_STACK,
}


def _node_role_without_idprops(node):
    """Identify FBP controller nodes without touching arbitrary IDProperty groups.

    Blender 5.2 can hard-crash in IDP_GetPropertyFromGroup when a timer calls
    ``node.get`` on a node whose custom-property metadata was invalidated by a
    concurrent tree/UI mutation. Native ``bl_idname`` and datablock names are
    safe enough to filter first, so deferred callbacks only inspect IDProperties
    on the three registered FBP controller node classes.
    """
    try:
        role = _FBP_NODE_ROLE_BY_IDNAME.get(str(getattr(node, "bl_idname", "") or ""))
        if role:
            return role
        child = getattr(node, "node_tree", None)
        name = str(getattr(child, "name", "") or "") if child is not None else ""
        node_name = str(getattr(node, "name", "") or "")
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        return ""
    if name.startswith("FBP Layers") or node_name in {"FBP Layers", "FBP Layers & Groups"}:
        return "layers_package"
    if name.startswith("FBP Output -"):
        return ROLE_OUTPUT
    if name.startswith("FBP Over Stack -"):
        return ROLE_STACK
    if name.startswith("FBP Layer Set -"):
        return ROLE_SET
    if name.startswith("FBP Effects & Masks"):
        return "effects_stage"
    return ""


def _controller_uuid(node):
    """Read a controller UUID only after the node class has been identified."""
    if _node_role_without_idprops(node) not in {ROLE_SET, ROLE_OUTPUT, ROLE_STACK}:
        return ""
    try:
        return str(node.get("fbp_uuid", "") or "")
    except FBP_DATA_ERRORS:
        return ""


def _tree_contains_compositor_tree(root, target, visited=None):
    if root is None or target is None:
        return False
    try:
        if root == target:
            return True
        root_key = int(root.as_pointer())
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        root_key = id(root)
    visited = visited if visited is not None else set()
    if root_key in visited:
        return False
    visited.add(root_key)
    for node in tuple(getattr(root, 'nodes', ())):
        try:
            child = getattr(node, 'node_tree', None)
            if child is not None and getattr(child, 'bl_idname', '') == 'CompositorNodeTree':
                if _tree_contains_compositor_tree(child, target, visited):
                    return True
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            continue
    return False


def _scene_for_compositor_node(node):
    tree = getattr(node, 'id_data', None)
    if tree is None:
        return None
    active = getattr(bpy.context, 'scene', None)
    candidates = ([active] if active is not None else []) + [
        scene for scene in bpy.data.scenes if scene != active
    ]
    for scene in candidates:
        try:
            if _tree_contains_compositor_tree(getattr(scene, 'compositing_node_group', None), tree):
                return scene
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            continue
    return None


def _node_link_signature_key(node):
    scene = _scene_for_compositor_node(node)
    try:
        pointer = int(node.as_pointer())
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        pointer = id(node)
    return (_scene_runtime_key(scene) if scene is not None else None, pointer)


def _linked_socket_title(socket, fallback="Input"):
    """Return a stable human title for a newly connected dynamic socket."""
    try:
        link = socket.links[0] if socket is not None and socket.is_linked else None
        source_node = link.from_node if link is not None else None
        source_socket = link.from_socket if link is not None else None
    except (AttributeError, IndexError, ReferenceError, RuntimeError, TypeError):
        return str(fallback or "Input")
    node_title = str(
        getattr(source_node, 'label', '')
        or getattr(source_node, 'name', '')
        or ''
    ).strip()
    socket_title = str(getattr(source_socket, 'name', '') or '').strip()
    if node_title and socket_title and socket_title.casefold() not in {'image', 'color', 'value', 'result'}:
        return _clean(f"{node_title} {socket_title}", fallback)
    return _clean(node_title or socket_title or fallback, fallback)


def _unique_dynamic_title(value, existing, fallback="Input"):
    base = _clean(value, fallback)
    used = {str(item or '').strip().casefold() for item in existing}
    candidate = base
    suffix = 2
    while candidate.casefold() in used:
        tail = f" {suffix}"
        candidate = f"{base[:max(1, 63 - len(tail))]}{tail}"
        suffix += 1
    return candidate


def _scene_runtime_key(scene):
    try:
        return int(scene.as_pointer())
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        return str(getattr(scene, "name_full", "") or getattr(scene, "name", "") or "")


def _scene_from_runtime_key(key):
    if isinstance(key, int):
        for scene in bpy.data.scenes:
            try:
                if int(scene.as_pointer()) == key:
                    return scene
            except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
                continue
        return None
    return bpy.data.scenes.get(str(key or ''))


def _controller_update_locator(scene, node, role):
    """Capture only primitive identity for a deferred controller update.

    Never place a Node RNA wrapper in a timer payload.  The node may be rebuilt,
    removed or have its internal tree cleared before the timer executes.
    """
    try:
        tree = getattr(node, 'id_data', None)
        if scene is None or tree is None:
            return None
        return (
            _scene_runtime_key(scene),
            str(getattr(tree, 'name_full', '') or getattr(tree, 'name', '') or ''),
            int(tree.as_pointer()),
            str(getattr(node, 'name', '') or ''),
            int(node.as_pointer()),
            str(role or ''),
            str(node.get('fbp_uuid', '') or ''),
        )
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        return None


def _node_tree_from_locator(scene, tree_name, tree_pointer):
    candidates = []
    root = getattr(scene, 'compositing_node_group', None) if scene is not None else None
    if root is not None:
        candidates.append(root)
    try:
        named = bpy.data.node_groups.get(str(tree_name or ''))
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        named = None
    if named is not None and named not in candidates:
        candidates.append(named)
    for tree in candidates:
        try:
            if int(tree.as_pointer()) == int(tree_pointer or 0):
                return tree
            if str(getattr(tree, 'name_full', '') or getattr(tree, 'name', '') or '') == str(tree_name or ''):
                return tree
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            continue
    try:
        for tree in bpy.data.node_groups:
            try:
                if int(tree.as_pointer()) == int(tree_pointer or 0):
                    return tree
            except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
                continue
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        pass
    return None


def _resolve_controller_update_locator(locator):
    """Resolve one fresh Node wrapper immediately before a deferred rebuild."""
    try:
        scene_key, tree_name, tree_pointer, node_name, node_pointer, role, persistent_id = locator
    except (TypeError, ValueError):
        return None, None, '', ''
    scene = _scene_from_runtime_key(scene_key)
    if scene is None:
        return None, None, str(role or ''), str(persistent_id or '')
    tree = _node_tree_from_locator(scene, tree_name, tree_pointer)
    if tree is None:
        return scene, None, str(role or ''), str(persistent_id or '')
    try:
        node = tree.nodes.get(str(node_name or ''))
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        node = None
    if node is not None:
        try:
            if int(node.as_pointer()) == int(node_pointer or 0):
                return scene, node, str(role or ''), str(persistent_id or '')
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            node = None
    # A user may rename the controller between update() and the timer.  Resolve
    # by pointer from a fresh collection traversal, without retaining wrappers.
    try:
        for candidate in tree.nodes:
            try:
                if int(candidate.as_pointer()) == int(node_pointer or 0):
                    return scene, candidate, str(role or ''), str(persistent_id or '')
            except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
                continue
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        pass
    return scene, None, str(role or ''), str(persistent_id or '')


def _locator_signature_key(locator):
    try:
        return locator[0], int(locator[4])
    except (IndexError, TypeError, ValueError):
        return None


def _purge_link_signature_cache(scene, role, cache):
    """Bound signature caches without traversing mutable compositor nodes.

    The previous live-node scan was itself unsafe inside a timer: rebuilding one
    controller can invalidate wrappers captured for another recursive node.  A
    bounded cache is sufficient because signatures are only an update debounce.
    """
    del role
    scene_key = _scene_runtime_key(scene)
    for key in tuple(cache):
        if not isinstance(key, tuple) or len(key) != 2:
            cache.pop(key, None)
    limit = 512
    if len(cache) <= limit:
        return
    removable = [key for key in tuple(cache) if key[0] == scene_key]
    for key in removable[:max(0, len(cache) - limit)]:
        cache.pop(key, None)
    while len(cache) > limit:
        cache.pop(next(iter(cache)), None)


def _flush_stack_link_updates():
    retry_delay = ui_list_mutation_delay()
    if retry_delay > 0.0:
        return retry_delay
    if bpy.app.is_job_running('RENDER'):
        return 0.1
    locators = tuple(_FBP_PENDING_STACK_SCENES)
    _FBP_PENDING_STACK_SCENES.clear()
    for locator in locators:
        scene, node, role, stack_uuid = _resolve_controller_update_locator(locator)
        if scene is None or node is None or role != ROLE_STACK or not hasattr(scene, 'fbp_over_stacks'):
            signature_key = _locator_signature_key(locator)
            if signature_key is not None:
                _STACK_NODE_LINK_SIGNATURES.pop(signature_key, None)
            continue
        _purge_link_signature_cache(scene, ROLE_STACK, _STACK_NODE_LINK_SIGNATURES)
        config = _find(scene.fbp_over_stacks, 'stack_uuid', stack_uuid)
        if config is None:
            continue
        renamed = False
        scene_key = _scene_runtime_key(scene)
        was_property_sync_active = scene_key in _FBP_ACTIVE_NODE_SCENES
        _FBP_ACTIVE_NODE_SCENES.add(scene_key)
        try:
            for index, row in enumerate(config.rows, start=1):
                if bool(getattr(row, 'is_placeholder', False)):
                    continue
                socket = _stack_input_socket(node, row)
                if socket is None or not socket.is_linked or str(row.source_key or ''):
                    continue
                current = str(row.name or '')
                automatic = not current or current.startswith('Layer ')
                if automatic:
                    existing = [
                        candidate.name for candidate in config.rows
                        if candidate != row and not bool(getattr(candidate, 'is_placeholder', False))
                    ]
                    row.name = _unique_dynamic_title(
                        _linked_socket_title(socket, _stack_row_name(index)),
                        existing,
                        _stack_row_name(index),
                    )
                    renamed = True
            changed = _ensure_stack_rows(config, node=node)
        finally:
            if not was_property_sync_active:
                _FBP_ACTIVE_NODE_SCENES.discard(scene_key)
        if changed or renamed:
            try:
                _build_stack_tree(scene, config, node)
            except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError) as exc:
                _set_compositor_runtime_status(scene, "Composite Stack changed · safe sync queued")
                _queue_scene_property_sync(scene, first_interval=0.12)
                fbp_warn("Composite Stack link sync failed", exc)
    return 0.05 if _FBP_PENDING_STACK_SCENES else None


def _queue_stack_link_update(node):
    scene = _scene_for_compositor_node(node)
    if scene is None:
        return
    key = _scene_runtime_key(scene)
    if key in _FBP_ACTIVE_STACK_SCENES:
        return
    locator = _controller_update_locator(scene, node, ROLE_STACK)
    if locator is None:
        return
    _FBP_PENDING_STACK_SCENES.add(locator)
    accepted = schedule_once(
        "compositor_sets.stack_links",
        _flush_stack_link_updates,
        first_interval=0.05,
    )
    if not accepted:
        _FBP_PENDING_STACK_SCENES.discard(locator)
        _set_compositor_runtime_status(scene, "Composite Stack change pending · press Sync")


def _flush_output_link_updates():
    retry_delay = ui_list_mutation_delay()
    if retry_delay > 0.0:
        return retry_delay
    if bpy.app.is_job_running('RENDER'):
        return 0.1
    locators = tuple(_FBP_PENDING_OUTPUT_SCENES)
    _FBP_PENDING_OUTPUT_SCENES.clear()
    for locator in locators:
        scene, node, role, output_uuid = _resolve_controller_update_locator(locator)
        if scene is None or node is None or role != ROLE_OUTPUT or not hasattr(scene, 'fbp_output_configs'):
            signature_key = _locator_signature_key(locator)
            if signature_key is not None:
                _OUTPUT_NODE_LINK_SIGNATURES.pop(signature_key, None)
            continue
        _purge_link_signature_cache(scene, ROLE_OUTPUT, _OUTPUT_NODE_LINK_SIGNATURES)
        config = _find(scene.fbp_output_configs, 'output_uuid', output_uuid)
        if config is None:
            continue
        try:
            _build_output_tree(scene, config, node, sync_files=True)
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError) as exc:
            _set_compositor_runtime_status(scene, "Export links changed · safe sync queued")
            _queue_scene_property_sync(scene, first_interval=0.12)
            fbp_warn("Export Add link sync failed", exc)
    return 0.05 if _FBP_PENDING_OUTPUT_SCENES else None


def _queue_output_link_update(node):
    scene = _scene_for_compositor_node(node)
    if scene is None:
        return
    key = _scene_runtime_key(scene)
    if key in _FBP_ACTIVE_OUTPUT_SCENES:
        return
    locator = _controller_update_locator(scene, node, ROLE_OUTPUT)
    if locator is None:
        return
    _FBP_PENDING_OUTPUT_SCENES.add(locator)
    accepted = schedule_once(
        "compositor_sets.output_links",
        _flush_output_link_updates,
        first_interval=0.05,
    )
    if not accepted:
        _FBP_PENDING_OUTPUT_SCENES.discard(locator)
        _set_compositor_runtime_status(scene, "Export link change pending · press Sync")


def _flush_node_property_updates():
    retry_delay = ui_list_mutation_delay()
    if retry_delay > 0.0:
        return retry_delay
    if bpy.app.is_job_running('RENDER'):
        return 0.15
    keys = tuple(_FBP_PENDING_NODE_SCENES)
    _FBP_PENDING_NODE_SCENES.clear()
    for key in keys:
        scene = _scene_from_runtime_key(key)
        if scene is None or not hasattr(scene, "fbp_layer_sets"):
            _FBP_NODE_UPDATE_RETRIES.pop(key, None)
            continue
        scene_key = _scene_runtime_key(scene)
        if scene_key in _FBP_ACTIVE_NODE_SCENES:
            _FBP_PENDING_NODE_SCENES.add(scene_key)
            continue
        _FBP_ACTIVE_NODE_SCENES.add(scene_key)
        try:
            fbp_sync_layer_set_nodes(scene, sync_file_outputs=True)
            _FBP_NODE_UPDATE_RETRIES.pop(scene_key, None)
            _set_compositor_runtime_status(scene, "Compositor controllers synchronized")
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError) as exc:
            attempts = int(_FBP_NODE_UPDATE_RETRIES.get(scene_key, 0) or 0) + 1
            if attempts < _FBP_NODE_UPDATE_MAX_RETRIES:
                _FBP_NODE_UPDATE_RETRIES[scene_key] = attempts
                _FBP_PENDING_NODE_SCENES.add(scene_key)
                _set_compositor_runtime_status(
                    scene,
                    f"Compositor safe retry {attempts}/{_FBP_NODE_UPDATE_MAX_RETRIES - 1}",
                )
            else:
                _FBP_NODE_UPDATE_RETRIES.pop(scene_key, None)
                _set_compositor_runtime_status(
                    scene,
                    "Compositor sync failed safely · use Validate or Safe Repair",
                )
            fbp_warn("Layer Set property sync failed", exc)
        finally:
            _FBP_ACTIVE_NODE_SCENES.discard(scene_key)
    return 0.08 if _FBP_PENDING_NODE_SCENES else None

def _schedule_node_property_update(owner, context):
    scene = getattr(context, "scene", None) if context is not None else getattr(owner, "id_data", None)
    if scene is None or not hasattr(scene, "fbp_layer_sets"):
        return
    key = _scene_runtime_key(scene)
    if key in _FBP_ACTIVE_NODE_SCENES or key in _FBP_ACTIVE_STACK_SCENES or key in _FBP_ACTIVE_OUTPUT_SCENES:
        return
    _queue_scene_property_sync(scene)


class FBP_SourceRecord(PropertyGroup):
    source_uuid: StringProperty(options={'HIDDEN'})
    name: StringProperty()
    icon: StringProperty(default="RENDERLAYERS")
    layer_type: StringProperty()
    parent_uuid: StringProperty()
    parent_name: StringProperty()
    color_tag: StringProperty()
    visible: BoolProperty(default=True)
    has_effect: BoolProperty(default=False)
    depth: FloatProperty(default=0.0)
    depth_valid: BoolProperty(default=False)
    order: IntProperty()
    view_layer_name: StringProperty()
    output_socket_name: StringProperty()
    valid: BoolProperty(default=True)


class FBP_LayerSetRow(PropertyGroup):
    source_uuid: StringProperty(options={'HIDDEN'})
    name: StringProperty()
    eye: BoolProperty(name="Included", default=False, update=_schedule_node_property_update)
    selected: BoolProperty(name="Selected", default=False)
    pinned: BoolProperty(name="Pin Socket", default=False, update=_schedule_node_property_update)
    missing: BoolProperty(default=False, options={'HIDDEN'})
    resolved_eye: BoolProperty(default=False, options={'HIDDEN'})
    exclusive_excluded: BoolProperty(default=False, options={'HIDDEN'})
    override: EnumProperty(items=OVERRIDE_ITEMS, default='AUTO', update=_schedule_node_property_update)
    input_identifier: StringProperty(options={'HIDDEN'})
    socket_identifier: StringProperty(options={'HIDDEN'})


class FBP_LayerSet(PropertyGroup):
    set_uuid: StringProperty(options={'HIDDEN'})
    name: StringProperty(default="Layer Set", update=_schedule_node_property_update)
    node_name: StringProperty(options={'HIDDEN'})
    tot_identifier: StringProperty(options={'HIDDEN'})
    mask_identifier: StringProperty(options={'HIDDEN'})
    mode: EnumProperty(items=SET_MODE_ITEMS, default='MANUAL', update=_schedule_node_property_update)
    mask_mode: EnumProperty(name="Mask Mode", items=MASK_ITEMS, default='COMBINED', update=_schedule_node_property_update)
    follow_layer_list: BoolProperty(name="Follow Layer List", default=True, update=_schedule_node_property_update)
    special: EnumProperty(items=(('NONE', "Normal", ""), ('UNASSIGNED', "Unassigned", ""), ('DERIVED', "Derived UUID Set", "Resolve membership from two other Layer Sets")), default='NONE', update=_schedule_node_property_update)
    set_operation: EnumProperty(name="UUID Operation", items=SET_OPERATION_ITEMS, default='UNION', update=_schedule_node_property_update)
    operand_a_uuid: StringProperty(options={'HIDDEN'}, update=_schedule_node_property_update)
    operand_b_uuid: StringProperty(options={'HIDDEN'}, update=_schedule_node_property_update)
    membership_mode: EnumProperty(name="Layer Membership", items=MEMBERSHIP_ITEMS, default='MULTIPLE', update=_schedule_node_property_update)
    exclusive_group: StringProperty(name="Exclusive Group", update=_schedule_node_property_update)
    rule_folder: StringProperty(name="Folder Contains", update=_schedule_node_property_update)
    rule_color_tag: StringProperty(name="Color Tag", update=_schedule_node_property_update)
    rule_type: StringProperty(name="Layer Type", update=_schedule_node_property_update)
    rule_name: StringProperty(name="Name Contains", update=_schedule_node_property_update)
    rule_name_mode: EnumProperty(name="Name Rule", items=(('CONTAINS',"Contains",""),('STARTS',"Starts With",""),('ENDS',"Ends With","")), default='CONTAINS', update=_schedule_node_property_update)
    rule_visibility: EnumProperty(name="Visibility", items=(('ANY',"Any",""),('VISIBLE',"Visible",""),('HIDDEN',"Hidden","")), default='ANY', update=_schedule_node_property_update)
    rule_effect: StringProperty(name="Effect Contains", update=_schedule_node_property_update)
    rule_depth_enabled: BoolProperty(name="Depth Range", default=False, update=_schedule_node_property_update)
    rule_depth_min: FloatProperty(name="Near", default=-1.0e20, update=_schedule_node_property_update)
    rule_depth_max: FloatProperty(name="Far", default=1.0e20, update=_schedule_node_property_update)
    rows: CollectionProperty(type=FBP_LayerSetRow)
    active_index: IntProperty(default=0)
    snapshot_a: StringProperty(options={'HIDDEN'})
    snapshot_b: StringProperty(options={'HIDDEN'})
    snapshot_c: StringProperty(options={'HIDDEN'})


class FBP_StackRow(PropertyGroup):
    row_uuid: StringProperty(options={'HIDDEN'})
    source_key: StringProperty(options={'HIDDEN'})
    name: StringProperty(default="Layer", update=_schedule_node_property_update)
    enabled: BoolProperty(name="Enabled", default=True, update=_schedule_node_property_update)
    selected: BoolProperty(name="Selected", default=False)
    missing: BoolProperty(default=False, options={'HIDDEN'})
    is_placeholder: BoolProperty(default=False, options={'HIDDEN'})
    input_identifier: StringProperty(options={'HIDDEN'})


class FBP_OverStack(PropertyGroup):
    stack_uuid: StringProperty(options={'HIDDEN'})
    name: StringProperty(default="Composite Stack", update=_schedule_node_property_update)
    node_name: StringProperty(options={'HIDDEN'})
    image_identifier: StringProperty(options={'HIDDEN'})
    mask_identifier: StringProperty(options={'HIDDEN'})
    follow_layer_list: BoolProperty(name="Follow Layer List", default=False, update=_schedule_node_property_update)
    auto_expand: BoolProperty(name="Auto Add Input", default=True, update=_schedule_node_property_update)
    is_default_pipeline: BoolProperty(default=False, options={'HIDDEN'})
    rows: CollectionProperty(type=FBP_StackRow)
    active_index: IntProperty(default=0)


def _stack_row_name(index):
    return f"Layer {index}"


def _add_stack_row(config, name=None, *, placeholder=False):
    row = config.rows.add()
    row.row_uuid = _id()
    row.is_placeholder = bool(placeholder)
    row.enabled = not placeholder
    row.name = "Add" if placeholder else (name or _stack_row_name(len(config.rows)))
    return row


def _add_stack_input_row(config, name=None):
    """Add a real input immediately before the permanent Add socket."""
    row = _add_stack_row(config, name=name, placeholder=False)
    placeholder_index = next(
        (index for index, item in enumerate(config.rows) if bool(getattr(item, 'is_placeholder', False))),
        -1,
    )
    if 0 <= placeholder_index < len(config.rows) - 1:
        config.rows.move(len(config.rows) - 1, placeholder_index)
        row = config.rows[placeholder_index]
    return row


def _stack_input_socket(node, row):
    identifier = str(getattr(row, 'input_identifier', '') or '')
    return next((sock for sock in getattr(node, 'inputs', ()) if sock.identifier == identifier), None) if identifier else None


def _ensure_stack_rows(config, node=None):
    rows = getattr(config, 'rows', None)
    if rows is None:
        return False
    changed = False
    placeholders = [index for index, row in enumerate(config.rows) if bool(getattr(row, 'is_placeholder', False))]
    if len(placeholders) > 1:
        for index in reversed(placeholders[1:]):
            socket = _stack_input_socket(node, config.rows[index]) if node is not None else None
            if socket is not None and socket.is_linked:
                config.rows[index].is_placeholder = False
                config.rows[index].enabled = True
                existing = [candidate.name for candidate in config.rows if candidate != config.rows[index] and not bool(getattr(candidate, 'is_placeholder', False))]
                config.rows[index].name = _unique_dynamic_title(_linked_socket_title(socket, _stack_row_name(index + 1)), existing, _stack_row_name(index + 1))
            else:
                config.rows.remove(index)
            changed = True
    placeholder_index = next((index for index, row in enumerate(config.rows) if bool(getattr(row, 'is_placeholder', False))), -1)
    if placeholder_index < 0:
        _add_stack_row(config, placeholder=True)
        placeholder_index = len(config.rows) - 1
        changed = True
    placeholder = config.rows[placeholder_index]
    socket = _stack_input_socket(node, placeholder) if node is not None else None
    if socket is not None and socket.is_linked and bool(getattr(config, 'auto_expand', True)):
        existing = [row.name for row in config.rows if str(row.row_uuid or '') != str(placeholder.row_uuid or '') and not bool(getattr(row, 'is_placeholder', False))]
        placeholder.is_placeholder = False
        placeholder.enabled = True
        placeholder.name = _unique_dynamic_title(_linked_socket_title(socket, "Layer"), existing, "Layer")
        _add_stack_row(config, placeholder=True)
        placeholder_index = len(config.rows) - 1
        changed = True
    else:
        placeholder.name = "Add"
        placeholder.enabled = False
        placeholder.selected = False
        placeholder.missing = False
        placeholder.source_key = ""
    if placeholder_index != len(config.rows) - 1:
        config.rows.move(placeholder_index, len(config.rows) - 1)
        changed = True
    config.active_index = max(0, min(int(getattr(config, 'active_index', 0) or 0), len(config.rows) - 1)) if config.rows else 0
    return changed


def _recover_linked_stack_inputs(config, node, tree):
    known = {str(getattr(row, 'input_identifier', '') or '') for row in config.rows}
    recovered = 0
    for item in tuple(_iface_sockets(tree, 'INPUT')):
        identifier = str(getattr(item, 'identifier', '') or '')
        if not identifier or identifier in known:
            continue
        socket = next((sock for sock in getattr(node, 'inputs', ()) if sock.identifier == identifier), None)
        if socket is None or not socket.is_linked:
            continue
        existing = [row.name for row in config.rows if not bool(getattr(row, 'is_placeholder', False))]
        row = _add_stack_input_row(
            config,
            _unique_dynamic_title(_linked_socket_title(socket, item.name or "Layer"), existing, "Layer"),
        )
        row.input_identifier = identifier
        recovered += 1
    return recovered


def _remove_unused_stack_inputs(config, node, tree):
    keep = {str(getattr(row, 'input_identifier', '') or '') for row in config.rows}
    removed = 0
    for item in tuple(_iface_sockets(tree, 'INPUT')):
        identifier = str(getattr(item, 'identifier', '') or '')
        if identifier in keep:
            continue
        socket = next((sock for sock in getattr(node, 'inputs', ()) if sock.identifier == identifier), None)
        if socket is not None and socket.is_linked:
            continue
        tree.interface.remove(item)
        removed += 1
    return removed


def _build_stack_tree_impl(scene, config, node):
    _repair_stack_row_ids(config)
    _ensure_stack_rows(config, node=node)
    tree = node.node_tree
    if tree is None or tree.get("fbp_stack_uuid", "") != config.stack_uuid:
        tree = next(
            (
                candidate for candidate in bpy.data.node_groups
                if getattr(candidate, 'bl_idname', '') == 'CompositorNodeTree'
                and str(getattr(candidate, 'name', '') or '').startswith('FBP Composite Stack')
                and str(candidate.get('fbp_stack_uuid', '') or '') == str(config.stack_uuid or '')
                and int(getattr(candidate, 'users', 0) or 0) == 0
            ),
            None,
        )
        if tree is None:
            tree = bpy.data.node_groups.new(f"FBP Composite Stack - {_clean(config.name, 'Stack')}", "CompositorNodeTree")
        tree["fbp_owned"] = True
        tree["fbp_role"] = ROLE_STACK
        tree["fbp_stack_uuid"] = config.stack_uuid
        tree["fbp_version"] = STRUCTURE_VERSION
        node.node_tree = tree
    tree["fbp_owned"] = True
    tree["fbp_role"] = ROLE_STACK
    tree["fbp_stack_uuid"] = config.stack_uuid
    tree["fbp_uuid"] = config.stack_uuid
    tree["fbp_version"] = STRUCTURE_VERSION
    _recover_linked_stack_inputs(config, node, tree)
    for index, row in enumerate(config.rows, start=1):
        if not str(getattr(row, 'row_uuid', '') or ''):
            row.row_uuid = _id()
        if not str(getattr(row, 'name', '') or '').strip():
            row.name = _stack_row_name(index)
        sock = _ensure_iface(tree, row.name, 'INPUT', 'NodeSocketColor', row.input_identifier)
        row.input_identifier = sock.identifier
    _remove_unused_stack_inputs(config, node, tree)
    image = _ensure_iface(tree, 'Image', 'OUTPUT', 'NodeSocketColor', config.image_identifier)
    mask = _ensure_iface(tree, 'Mask', 'OUTPUT', 'NodeSocketFloat', config.mask_identifier)
    config.image_identifier = image.identifier
    config.mask_identifier = mask.identifier
    ordered = _iface_sockets(tree, 'INPUT') + _iface_sockets(tree, 'OUTPUT')
    for target_index, socket in enumerate(ordered):
        current_index = list(tree.interface.items_tree).index(socket)
        if current_index != target_index:
            tree.interface.move(socket, target_index)
    _clear_internal_nodes(tree)
    group_in = _tag(tree.nodes.new('NodeGroupInput'), 'stack_inputs', config.stack_uuid)
    group_out = _tag(tree.nodes.new('NodeGroupOutput'), 'stack_outputs', config.stack_uuid)
    group_out.is_active_output = True
    group_in.location = (-640, 0)
    group_out.location = (520, 0)
    active_rows = []
    for row in config.rows:
        target = next((sock for sock in getattr(node, 'inputs', ()) if sock.identifier == row.input_identifier), None)
        if target is not None and target.is_linked and bool(getattr(row, 'enabled', True)):
            active_rows.append(row)
    combined = None
    for index, row in enumerate(reversed(active_rows)):
        socket = next((sock for sock in group_in.outputs if sock.identifier == row.input_identifier), None)
        if socket is None:
            continue
        if combined is None:
            combined = socket
        else:
            over = _tag(tree.nodes.new('CompositorNodeAlphaOver'), 'stack_alpha_over', row.row_uuid)
            over.location = (-160 + index * 160, -index * 88)
            factor = over.inputs.get('Factor')
            if factor is not None:
                factor.default_value = 1.0
            tree.links.new(combined, over.inputs['Background'])
            tree.links.new(socket, over.inputs['Foreground'])
            combined = over.outputs['Image']
    if combined is None:
        transparent = _tag(tree.nodes.new('CompositorNodeRGB'), 'stack_empty', config.stack_uuid)
        transparent.outputs[0].default_value = (0.0, 0.0, 0.0, 0.0)
        combined = transparent.outputs[0]
    tree.links.new(combined, next(sock for sock in group_out.inputs if sock.identifier == image.identifier))
    mask_socket = _build_mask(tree, combined, 'COMBINED', 180, -180)
    tree.links.new(mask_socket, next(sock for sock in group_out.inputs if sock.identifier == mask.identifier))
    node.label = config.name
    node.name = config.node_name or config.name
    config.node_name = node.name
    node.width = max(190, node.width)
    tree.update_tag()
    try:
        tree.interface_update(bpy.context)
        tree.update()
    except (AttributeError, RuntimeError, TypeError):
        pass
    _touch_group_links(node)
    if getattr(node, 'id_data', None) is not None:
        node.id_data.update_tag()
    scene.update_tag()
    return tree



def _build_stack_tree(scene, config, node):
    key = _scene_runtime_key(scene)
    if key in _FBP_ACTIVE_STACK_SCENES:
        return getattr(node, 'node_tree', None)
    _FBP_ACTIVE_STACK_SCENES.add(key)
    try:
        return _build_stack_tree_impl(scene, config, node)
    finally:
        _FBP_ACTIVE_STACK_SCENES.discard(key)

def _copy_stack(scene, source, new_uuid):
    clone = scene.fbp_over_stacks.add()
    clone.stack_uuid = new_uuid
    clone.name = f"{source.name} Copy"
    clone.image_identifier = ''
    clone.mask_identifier = ''
    clone.follow_layer_list = bool(source.follow_layer_list)
    clone.auto_expand = bool(source.auto_expand)
    clone.is_default_pipeline = False
    for source_row in source.rows:
        row = clone.rows.add()
        row.row_uuid = _id()
        row.source_key = source_row.source_key
        row.name = source_row.name
        row.enabled = source_row.enabled
        row.selected = source_row.selected
        row.missing = source_row.missing
        row.is_placeholder = bool(getattr(source_row, 'is_placeholder', False))
    if not clone.rows:
        _add_stack_row(clone, placeholder=True)
    return clone


def _add_stack(scene, tree, name='Composite Stack'):
    node = tree.nodes.new('FBPCompositorStackNode')
    config = _find(scene.fbp_over_stacks, 'stack_uuid', str(node.get('fbp_uuid', '') or ''))
    if config is None:
        config = scene.fbp_over_stacks.add()
        config.stack_uuid = str(node.get('fbp_uuid', '') or _id())
    if not str(config.stack_uuid or ''):
        config.stack_uuid = str(node.get('fbp_uuid', '') or _id())
    config.name = name
    if not config.rows:
        _add_stack_row(config, placeholder=True)
    _build_stack_tree(scene, config, node)
    node.location = (180, -220 * max(0, len(scene.fbp_over_stacks) - 1))
    return config, node




class FBP_OutputPass(PropertyGroup):
    pass_uuid: StringProperty(options={'HIDDEN'})
    enabled: BoolProperty(default=True, update=_schedule_node_property_update)
    name: StringProperty(default="Pass", update=_schedule_node_property_update)
    alias: StringProperty(update=_schedule_node_property_update)
    subfolder: StringProperty(default="Layers", update=_schedule_node_property_update)
    prefix: StringProperty(update=_schedule_node_property_update)
    format_override: BoolProperty(default=False, update=_schedule_node_property_update)
    file_format: EnumProperty(items=(('PNG', "PNG", ""), ('OPEN_EXR', "OpenEXR", ""), ('TIFF', "TIFF", "")), default='PNG', update=_schedule_node_property_update)
    color_mode: EnumProperty(items=(('RGB', "RGB", ""), ('RGBA', "RGBA", "")), default='RGBA', update=_schedule_node_property_update)
    color_depth: EnumProperty(items=(('8', "8 bit", ""), ('16', "16 bit", ""), ('32', "32 bit", "")), default='8', update=_schedule_node_property_update)
    compression: IntProperty(name="Compression", min=0, max=100, default=15, subtype='PERCENTAGE', update=_schedule_node_property_update)
    exr_pass_name: StringProperty(name="EXR Pass Name", update=_schedule_node_property_update)
    input_identifier: StringProperty(options={'HIDDEN'})


class FBP_OutputConfig(PropertyGroup):
    output_uuid: StringProperty(options={'HIDDEN'})
    name: StringProperty(default="FBP Output", update=_schedule_node_property_update)
    node_name: StringProperty(options={'HIDDEN'})
    beauty_identifier: StringProperty(options={'HIDDEN'})
    add_identifier: StringProperty(options={'HIDDEN'})
    image_identifier: StringProperty(options={'HIDDEN'})
    mode: EnumProperty(items=OUTPUT_MODE_ITEMS, default='SEPARATE', update=_schedule_node_property_update)
    save_beauty: BoolProperty(name="Save Beauty Through FBP Output", default=False, update=_schedule_node_property_update)
    auto_expand: BoolProperty(name="Auto Add Input", default=True, update=_schedule_node_property_update)
    passes: CollectionProperty(type=FBP_OutputPass)
    active_index: IntProperty(default=0)


def _find(collection, attr, value):
    return next((item for item in collection if str(getattr(item, attr, "") or "") == value), None)


def _root_tree(scene):
    tree = scene.compositing_node_group
    if tree is None:
        tree = bpy.data.node_groups.new(f"FBP Composite - {_clean(scene.name)}", "CompositorNodeTree")
        tree.interface.new_socket(name="Image", in_out='OUTPUT', socket_type='NodeSocketColor')
        render = getattr(scene, "render", None)
        use_compositing_before = bool(getattr(render, "use_compositing", False)) if render is not None else False
        scene.compositing_node_group = tree
        if render is not None:
            render.use_compositing = use_compositing_before
    scene_uuid = str(getattr(scene, "fbp_compositor_scene_id", "") or "")
    if not scene_uuid:
        scene_uuid = _id()
        try:
            scene.fbp_compositor_scene_id = scene_uuid
        except (AttributeError, TypeError):
            pass
    tree["fbp_owned"] = True
    tree["fbp_role"] = "compositor_root"
    tree["fbp_uuid"] = scene_uuid
    tree["fbp_version"] = STRUCTURE_VERSION
    # Building or repairing Frame By Plane node data never changes Blender's
    # Use Compositor switch. Native F12 and compositor rendering remain explicit.
    return tree


def fbp_refresh_source_registry(scene):
    """Differential UUID registry; removed records remain as invalid sources."""
    valid_ids = set()
    folders = {item.layer_id: item for item in scene.fbp_compositor_layers if item.row_type == 'FOLDER'}
    for order, layer in enumerate(scene.fbp_compositor_layers):
        if layer.row_type == 'FOLDER':
            continue
        source_uuid = str(layer.source_key or layer.layer_id)
        valid_ids.add(source_uuid)
        record = _find(scene.fbp_compositor_sources, "source_uuid", source_uuid)
        if record is None:
            record = scene.fbp_compositor_sources.add()
            record.source_uuid = source_uuid
        parent = folders.get(str(layer.parent_folder_id or ""))
        rig = next((obj for obj in scene.objects if str(getattr(obj, "fbp_compositor_source_id", "") or "") == source_uuid), None)
        record.name = layer.name
        record.icon = "RENDERLAYERS"
        record.layer_type = str(layer.source_kind or 'LAYER')
        record.parent_uuid = str(parent.source_key or parent.layer_id) if parent else ""
        record.parent_name = parent.name if parent else ""
        record.color_tag = str(getattr(rig, "fbp_color_tag", "") or "") if rig else ""
        record.visible = bool(layer.enabled)
        record.has_effect = any(effect.enabled and effect.effect_type != 'NONE' for effect in layer.effects)
        record.depth = 0.0
        record.depth_valid = False
        camera = getattr(scene, "camera", None)
        if rig is not None and camera is not None:
            try:
                camera_space = camera.matrix_world.inverted_safe() @ rig.matrix_world.translation
                depth = -float(camera_space.z)
                if math.isfinite(depth):
                    record.depth = depth
                    record.depth_valid = True
            except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
                pass
        if rig is not None:
            try:
                from .layers import fbp_layer_backend_type
                record.layer_type = str(fbp_layer_backend_type(rig) or record.layer_type)
            except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
                pass
        record.order = order
        record.view_layer_name = layer.view_layer_name
        record.output_socket_name = layer.output_socket_name
        record.valid = True
    for record in scene.fbp_compositor_sources:
        if record.source_uuid not in valid_ids:
            record.valid = False
    return len(valid_ids)


def _normalize_layer_set_contract(layer_set):
    """Normalize current Layer Set invariants without converting old schemas."""
    if layer_set.special == 'DERIVED':
        layer_set.mode = 'MANUAL'
        layer_set.membership_mode = 'MULTIPLE'
        layer_set.exclusive_group = ""
    if layer_set.membership_mode == 'MULTIPLE':
        for row in layer_set.rows:
            row.exclusive_excluded = False
    if layer_set.rule_depth_min > layer_set.rule_depth_max:
        layer_set.rule_depth_min, layer_set.rule_depth_max = (
            layer_set.rule_depth_max,
            layer_set.rule_depth_min,
        )


def _exclusive_membership_enabled(layer_set):
    return (
        layer_set.special != 'DERIVED'
        and layer_set.membership_mode == 'EXCLUSIVE'
        and bool(str(layer_set.exclusive_group or "").strip())
    )


def _apply_exclusive_membership(scene, layer_set, source_uuids):
    """Move sources atomically inside one explicit exclusive-set group."""
    if not _exclusive_membership_enabled(layer_set):
        return
    source_uuids = {str(value or "") for value in source_uuids if value}
    if not source_uuids:
        return
    for row in layer_set.rows:
        if row.source_uuid in source_uuids:
            row.exclusive_excluded = False
    group = str(layer_set.exclusive_group or "").strip()
    for other in scene.fbp_layer_sets:
        if other.set_uuid == layer_set.set_uuid:
            continue
        if not _exclusive_membership_enabled(other):
            continue
        if str(other.exclusive_group or "").strip() != group:
            continue
        for row in other.rows:
            if row.source_uuid in source_uuids:
                row.eye = False
                row.exclusive_excluded = True


def _row_rule_value(layer_set, row, record):
    match = True
    if layer_set.rule_folder:
        match &= layer_set.rule_folder.casefold() in record.parent_name.casefold()
    if layer_set.rule_color_tag:
        match &= layer_set.rule_color_tag.casefold() == record.color_tag.casefold()
    if layer_set.rule_type:
        match &= layer_set.rule_type.casefold() in record.layer_type.casefold()
    if layer_set.rule_name:
        needle = layer_set.rule_name.casefold()
        name = record.name.casefold()
        if layer_set.rule_name_mode == 'STARTS':
            match &= name.startswith(needle)
        elif layer_set.rule_name_mode == 'ENDS':
            match &= name.endswith(needle)
        else:
            match &= needle in name
    if layer_set.rule_visibility == 'VISIBLE':
        match &= record.visible
    elif layer_set.rule_visibility == 'HIDDEN':
        match &= not record.visible
    if layer_set.rule_effect:
        match &= record.has_effect
    if layer_set.rule_depth_enabled:
        match &= bool(record.depth_valid)
        if record.depth_valid:
            match &= layer_set.rule_depth_min <= record.depth <= layer_set.rule_depth_max
    if layer_set.mode == 'MIXED':
        if row.override == 'INCLUDE':
            return True
        if row.override == 'EXCLUDE':
            return False
    return bool(match)


def _base_effective_eye(scene, layer_set, row):
    if row.missing:
        return False
    if layer_set.special == 'UNASSIGNED':
        return not any(
            other.set_uuid != layer_set.set_uuid
            and any(candidate.source_uuid == row.source_uuid and candidate.resolved_eye for candidate in other.rows)
            for other in scene.fbp_layer_sets
            if other.special != 'UNASSIGNED'
        )
    if layer_set.mode == 'MANUAL':
        return bool(row.eye)
    record = _find(scene.fbp_compositor_sources, "source_uuid", row.source_uuid)
    return _row_rule_value(layer_set, row, record) if record is not None else False


def _effective_eye(scene, layer_set, row):
    if _exclusive_membership_enabled(layer_set) and row.exclusive_excluded:
        return False
    return _base_effective_eye(scene, layer_set, row)


def _derived_set_graph(scene):
    """Return persistent UUID dependencies for derived Layer Sets only."""
    known = {str(item.set_uuid or "") for item in scene.fbp_layer_sets if str(item.set_uuid or "")}
    graph = {}
    for layer_set in scene.fbp_layer_sets:
        set_uuid = str(layer_set.set_uuid or "")
        if not set_uuid or layer_set.special != 'DERIVED':
            continue
        graph[set_uuid] = tuple(
            value
            for value in (
                str(layer_set.operand_a_uuid or ""),
                str(layer_set.operand_b_uuid or ""),
            )
            if value and value in known
        )
    return graph


def _would_create_derived_cycle(scene, target_uuid, side, candidate_uuid):
    target_uuid = str(target_uuid or "")
    candidate_uuid = str(candidate_uuid or "")
    if not target_uuid or not candidate_uuid:
        return False
    graph = dict(_derived_set_graph(scene))
    layer_set = _find(scene.fbp_layer_sets, "set_uuid", target_uuid)
    if layer_set is None:
        return True
    left = candidate_uuid if side == 'A' else str(layer_set.operand_a_uuid or "")
    right = candidate_uuid if side == 'B' else str(layer_set.operand_b_uuid or "")
    graph[target_uuid] = tuple(value for value in (left, right) if value)
    return any(target_uuid in cycle for cycle in directed_cycles(graph))


def _layer_set_display_name(scene, set_uuid, fallback="Not Set"):
    layer_set = _find(scene.fbp_layer_sets, "set_uuid", str(set_uuid or ""))
    if layer_set is None:
        return fallback
    return str(layer_set.name or "Layer Set")


def _resolved_membership_sets(scene):
    """Resolve live UUID membership without rebuilding compositor nodes."""
    valid_source_ids = {
        str(record.source_uuid or "")
        for record in scene.fbp_compositor_sources
        if record.valid and str(record.source_uuid or "")
    }
    base_memberships = {}
    derived_specs = {}
    unassigned_ids = set()
    for layer_set in scene.fbp_layer_sets:
        set_uuid = str(layer_set.set_uuid or "")
        if not set_uuid:
            continue
        if layer_set.special == 'DERIVED':
            derived_specs[set_uuid] = (
                layer_set.set_operation,
                str(layer_set.operand_a_uuid or ""),
                str(layer_set.operand_b_uuid or ""),
            )
        elif layer_set.special == 'UNASSIGNED':
            unassigned_ids.add(set_uuid)
        else:
            base_memberships[set_uuid] = {
                row.source_uuid
                for row in layer_set.rows
                if row.source_uuid in valid_source_ids and _effective_eye(scene, layer_set, row)
            }
    return resolve_uuid_set_memberships(
        base_memberships,
        derived_specs,
        valid_source_ids,
        unassigned_ids,
    )


def _resolve_all_set_rows(scene):
    memberships = _resolved_membership_sets(scene)
    for layer_set in scene.fbp_layer_sets:
        active_ids = memberships.get(str(layer_set.set_uuid or ""), frozenset())
        for row in layer_set.rows:
            row.resolved_eye = bool(not row.missing and row.source_uuid in active_ids)
    return memberships


def _resolve_exclusive_conflicts(scene):
    """Resolve rule/manual conflicts deterministically while preserving the last explicit owner."""
    changed = False
    groups = {}
    for layer_set in scene.fbp_layer_sets:
        if not _exclusive_membership_enabled(layer_set):
            continue
        groups.setdefault(str(layer_set.exclusive_group or "").strip(), []).append(layer_set)
    for layer_sets in groups.values():
        source_rows = {}
        for layer_set in layer_sets:
            for row in layer_set.rows:
                source_rows.setdefault(row.source_uuid, []).append((layer_set, row))
        for pairs in source_rows.values():
            base_active = [pair for pair in pairs if _base_effective_eye(scene, pair[0], pair[1])]
            allowed = [pair for pair in base_active if not pair[1].exclusive_excluded]
            winner = allowed[0] if allowed else (base_active[0] if base_active else None)
            active_pointers = {int(pair[1].as_pointer()) for pair in base_active}
            winner_pointer = int(winner[1].as_pointer()) if winner is not None else -1
            for pair in pairs:
                row_pointer = int(pair[1].as_pointer())
                desired = bool(row_pointer in active_pointers and row_pointer != winner_pointer)
                if pair[1].exclusive_excluded != desired:
                    pair[1].exclusive_excluded = desired
                    changed = True
    return changed


def _row_socket_linked(scene, layer_set, row):
    tree = scene.compositing_node_group
    if tree is None or not row.socket_identifier:
        return False
    node = next((item for item in tree.nodes if item.get("fbp_uuid", "") == layer_set.set_uuid), None)
    socket = next((item for item in node.outputs if item.identifier == row.socket_identifier), None) if node else None
    return bool(socket and socket.is_linked)


def _output_input_label(scene, node, socket):
    config = _find(scene.fbp_output_configs, "output_uuid", str(node.get("fbp_uuid", "") or ""))
    if config is None:
        return node.label or node.name
    if socket.identifier == config.beauty_identifier:
        return f"{config.name} · Beauty"
    item = next(
        (candidate for candidate in config.passes if candidate.input_identifier == socket.identifier),
        None,
    )
    return f"{config.name} · {(item.alias or item.name) if item else socket.name}"


def _reachable_dependency_labels(scene, start_sockets):
    """Trace downstream links without treating visible names as identities."""
    outputs, artist_nodes = set(), set()
    pending = list(start_sockets)
    visited_sockets = set()
    visited_nodes = set()
    while pending and len(visited_nodes) < 256:
        socket = pending.pop()
        socket_key = int(socket.as_pointer())
        if socket_key in visited_sockets:
            continue
        visited_sockets.add(socket_key)
        for link in tuple(socket.links):
            target = link.to_node
            node_key = int(target.as_pointer())
            role = _node_role_without_idprops(target)
            if role == ROLE_OUTPUT:
                outputs.add(_output_input_label(scene, target, link.to_socket))
                continue
            try:
                target_name = str(getattr(target, "name", "") or "")
                target_label = str(getattr(target, "label", "") or "")
                target_bl_label = str(getattr(target, "bl_label", "") or "")
            except FBP_DATA_ERRORS:
                target_name = target_label = target_bl_label = ""
            if not role and not target_name.startswith("FBP "):
                artist_nodes.add(target_label or target_name or target_bl_label)
            if node_key in visited_nodes:
                continue
            visited_nodes.add(node_key)
            pending.extend(target.outputs)
    return outputs, artist_nodes


def fbp_source_dependency_usage(scene, source_uuid):
    """Describe every persisted or linked use of one source UUID."""
    source_uuid = str(source_uuid or "")
    usage = {"layer_sets": set(), "outputs": set(), "artist_nodes": set(), "source": set()}
    record = _find(scene.fbp_compositor_sources, "source_uuid", source_uuid)
    if record is not None:
        usage["source"].add(
            f"Source Registry · {record.name}{' (Missing)' if not record.valid else ''}"
        )
    tree = scene.compositing_node_group
    if tree is None:
        return {key: tuple(sorted(value)) for key, value in usage.items()}
    for layer_set in scene.fbp_layer_sets:
        row = _find(layer_set.rows, "source_uuid", source_uuid)
        if row is None:
            continue
        flags = []
        if row.resolved_eye:
            flags.append("Active")
        if row.pinned:
            flags.append("Pinned")
        if row.missing:
            flags.append("Missing")
        node = next(
            (candidate for candidate in tree.nodes if candidate.get("fbp_uuid", "") == layer_set.set_uuid),
            None,
        )
        sockets = []
        if node is not None:
            individual = next(
                (candidate for candidate in node.outputs if candidate.identifier == row.socket_identifier),
                None,
            )
            if individual is not None:
                sockets.append(individual)
            if row.resolved_eye:
                sockets.extend(
                    candidate for candidate in (node.outputs.get("TOT"), node.outputs.get("MASK"))
                    if candidate is not None
                )
        linked = any(socket.is_linked for socket in sockets)
        if linked:
            flags.append("Linked")
        if layer_set.special == 'DERIVED' and row.resolved_eye:
            flags.append(f"UUID {layer_set.set_operation.title()}")
        if flags or linked:
            suffix = f" [{', '.join(dict.fromkeys(flags))}]" if flags else ""
            usage["layer_sets"].add(f"{layer_set.name}{suffix}")
            outputs, artist_nodes = _reachable_dependency_labels(scene, sockets)
            usage["outputs"].update(outputs)
            usage["artist_nodes"].update(artist_nodes)
    return {key: tuple(sorted(value)) for key, value in usage.items()}


def _sync_rows(scene, layer_set):
    _normalize_layer_set_contract(layer_set)
    active_uuid = identity_at(layer_set.rows, "source_uuid", layer_set.active_index)
    # Repair historic/remap duplicates by UUID before applying the registry
    # diff. Prefer the row whose exposed socket is pinned or externally linked.
    primary_by_uuid = {}
    remove_pointers = set()
    for candidate in layer_set.rows:
        primary = primary_by_uuid.get(candidate.source_uuid)
        if primary is None:
            primary_by_uuid[candidate.source_uuid] = candidate
            continue
        primary_protected = primary.pinned or _row_socket_linked(scene, layer_set, primary)
        candidate_protected = candidate.pinned or _row_socket_linked(scene, layer_set, candidate)
        keeper, removed = (candidate, primary) if candidate_protected and not primary_protected else (primary, candidate)
        keeper.eye = keeper.eye or removed.eye
        keeper.selected = keeper.selected or removed.selected
        keeper.pinned = keeper.pinned or removed.pinned
        keeper.exclusive_excluded = keeper.exclusive_excluded and removed.exclusive_excluded
        if keeper.override == 'AUTO' and removed.override != 'AUTO':
            keeper.override = removed.override
        primary_by_uuid[candidate.source_uuid] = keeper
        remove_pointers.add(int(removed.as_pointer()))
    for index in reversed(range(len(layer_set.rows))):
        if int(layer_set.rows[index].as_pointer()) in remove_pointers:
            layer_set.rows.remove(index)
    existing = {row.source_uuid: row for row in layer_set.rows}
    for record in scene.fbp_compositor_sources:
        row = existing.get(record.source_uuid)
        if row is None:
            row = layer_set.rows.add()
            row.source_uuid = record.source_uuid
            row.eye = False
            row.selected = False
            row.pinned = False
            row.exclusive_excluded = False
        row.name = record.name if record.valid else "Missing Layer"
        row.missing = not record.valid
    if layer_set.follow_layer_list:
        wanted = [record.source_uuid for record in sorted(scene.fbp_compositor_sources, key=lambda value: value.order)]
        for target, source_uuid in enumerate(wanted):
            current = next((i for i, row in enumerate(layer_set.rows) if row.source_uuid == source_uuid), -1)
            if current >= 0 and current != target:
                layer_set.rows.move(current, target)
    layer_set.active_index = restore_active_index(
        layer_set.rows, "source_uuid", active_uuid,
        fallback=layer_set.active_index,
    )


def _iface_sockets(tree, in_out):
    return [item for item in tree.interface.items_tree if getattr(item, "item_type", "") == 'SOCKET' and item.in_out == in_out]


def _iface_by_identifier(tree, identifier):
    return next((item for item in tree.interface.items_tree if getattr(item, "identifier", "") == identifier), None)


def _ensure_iface(tree, name, in_out, socket_type, identifier=""):
    item = _iface_by_identifier(tree, identifier) if identifier else None
    if item is not None and (
        getattr(item, "item_type", "") != 'SOCKET'
        or getattr(item, "in_out", "") != in_out
    ):
        item = None
    if item is None and not identifier:
        item = next(
            (
                candidate for candidate in tree.interface.items_tree
                if getattr(candidate, "item_type", "") == 'SOCKET'
                and candidate.in_out == in_out and candidate.name == name
            ),
            None,
        )
    if item is None:
        item = tree.interface.new_socket(name=name, in_out=in_out, socket_type=socket_type)
    else:
        item.name = name
    return item


def _clear_internal_nodes(tree):
    tree.nodes.clear()


def _socket_runtime_id(socket):
    try:
        return (
            str(getattr(socket, "identifier", "") or ""),
            str(getattr(socket, "name", "") or ""),
        )
    except FBP_DATA_ERRORS:
        return ("", "")


def _resolve_socket(sockets, socket_id):
    identifier, name = socket_id
    try:
        if identifier:
            match = next(
                (socket for socket in sockets if str(getattr(socket, "identifier", "") or "") == identifier),
                None,
            )
            if match is not None:
                return match
        if name:
            return next(
                (socket for socket in sockets if str(getattr(socket, "name", "") or "") == name),
                None,
            )
    except FBP_DATA_ERRORS:
        return None
    return None


def _node_from_pointer(tree, pointer):
    if tree is None or not pointer:
        return None
    for candidate in tuple(getattr(tree, "nodes", ()) or ()):
        try:
            if int(candidate.as_pointer()) == int(pointer):
                return candidate
        except FBP_DATA_ERRORS:
            continue
    return None


def _touch_group_links(node):
    """Invalidate compositor cache without retaining socket RNA across unlink."""
    try:
        root = getattr(node, "id_data", None)
        node_pointer = int(node.as_pointer())
    except FBP_DATA_ERRORS:
        return
    if root is None or not node_pointer:
        return

    reconnect = []
    for target_socket in tuple(getattr(node, "inputs", ()) or ()):
        target_id = _socket_runtime_id(target_socket)
        for link in tuple(getattr(target_socket, "links", ()) or ()):
            try:
                reconnect.append(
                    (
                        int(link.from_node.as_pointer()),
                        _socket_runtime_id(link.from_socket),
                        target_id,
                    )
                )
                root.links.remove(link)
            except FBP_DATA_ERRORS:
                continue

    target_node = _node_from_pointer(root, node_pointer)
    if target_node is None:
        return
    for source_pointer, source_id, target_id in reconnect:
        source_node = _node_from_pointer(root, source_pointer)
        if source_node is None:
            continue
        source_socket = _resolve_socket(getattr(source_node, "outputs", ()), source_id)
        target_socket = _resolve_socket(getattr(target_node, "inputs", ()), target_id)
        if source_socket is None or target_socket is None:
            continue
        try:
            root.links.new(source_socket, target_socket)
        except FBP_DATA_ERRORS:
            continue


def _build_mask(tree, image, mode, x, y):
    separate = _tag(tree.nodes.new("CompositorNodeSeparateColor"), "set_mask_alpha", _id())
    separate.mode = 'RGB'
    separate.location = (x, y)
    tree.links.new(image, separate.inputs[0])
    alpha = separate.outputs.get("Alpha") or separate.outputs[-1]
    if mode == 'COMBINED':
        return alpha
    math = _tag(tree.nodes.new("ShaderNodeMath"), "set_mask_mode", _id())
    math.location = (x + 180, y)
    if mode == 'INVERTED':
        math.operation = 'SUBTRACT'
        math.inputs[0].default_value = 1.0
        tree.links.new(alpha, math.inputs[1])
    elif mode == 'BINARY':
        math.operation = 'GREATER_THAN'
        math.inputs[1].default_value = 0.5
        tree.links.new(alpha, math.inputs[0])
    elif mode == 'SOFT':
        tree.nodes.remove(math)
        blur = _tag(tree.nodes.new("CompositorNodeBlur"), "set_mask_soft", _id())
        if blur.inputs.get("Type") is not None:
            blur.inputs["Type"].default_value = 'Gaussian'
        if blur.inputs.get("Size") is not None:
            blur.inputs["Size"].default_value = (8.0, 8.0)
        blur.location = (x + 180, y)
        tree.links.new(alpha, blur.inputs["Image"])
        return blur.outputs["Image"]
    else:
        tree.nodes.remove(math)
        edge = _tag(tree.nodes.new("CompositorNodeFilter"), "set_mask_edge", _id())
        if edge.inputs.get("Type") is not None:
            edge.inputs["Type"].default_value = 'Sobel'
        edge.location = (x + 180, y)
        tree.links.new(alpha, edge.inputs["Image"])
        return edge.outputs["Image"]
    return math.outputs[0]


def _build_set_tree(scene, layer_set, node, resolve_memberships=True):
    if resolve_memberships:
        _resolve_all_set_rows(scene)
    tree = node.node_tree
    if tree is None or tree.get("fbp_set_uuid", "") != layer_set.set_uuid:
        tree = bpy.data.node_groups.new(f"FBP Layer Set - {_clean(layer_set.name)}", "CompositorNodeTree")
        tree["fbp_owned"] = True
        tree["fbp_role"] = ROLE_SET
        tree["fbp_set_uuid"] = layer_set.set_uuid
        tree["fbp_version"] = STRUCTURE_VERSION
        node.node_tree = tree
    tree["fbp_owned"] = True
    tree["fbp_role"] = ROLE_SET
    tree["fbp_set_uuid"] = layer_set.set_uuid
    tree["fbp_uuid"] = layer_set.set_uuid
    tree["fbp_version"] = STRUCTURE_VERSION
    for row in layer_set.rows:
        inp = _ensure_iface(tree, f"Source {row.source_uuid[:8]}", 'INPUT', 'NodeSocketColor', row.input_identifier)
        row.input_identifier = inp.identifier
    if not layer_set.tot_identifier:
        layer_set.tot_identifier = next((sock.identifier for sock in node.outputs if sock.name == 'TOT' and sock.is_linked), "")
    if not layer_set.mask_identifier:
        layer_set.mask_identifier = next((sock.identifier for sock in node.outputs if sock.name == 'MASK' and sock.is_linked), "")
    tot = _ensure_iface(tree, "TOT", 'OUTPUT', 'NodeSocketColor', layer_set.tot_identifier)
    mask = _ensure_iface(tree, "MASK", 'OUTPUT', 'NodeSocketFloat', layer_set.mask_identifier)
    layer_set.tot_identifier = tot.identifier
    layer_set.mask_identifier = mask.identifier
    keep_outputs = {tot.identifier, mask.identifier}
    for row in layer_set.rows:
        linked = False
        if row.socket_identifier:
            external = next((sock for sock in node.outputs if sock.identifier == row.socket_identifier), None)
            linked = bool(external and external.is_linked)
        if row.resolved_eye or row.pinned or linked:
            out = _ensure_iface(tree, row.name, 'OUTPUT', 'NodeSocketColor', row.socket_identifier)
            row.socket_identifier = out.identifier
            keep_outputs.add(out.identifier)
    # Blender's full-frame compositor expects group inputs before outputs in
    # the interface tree. Moving interface items retains socket identifiers and
    # therefore all external links.
    ordered = _iface_sockets(tree, 'INPUT') + _iface_sockets(tree, 'OUTPUT')
    for target_index, socket in enumerate(ordered):
        current_index = list(tree.interface.items_tree).index(socket)
        if current_index != target_index:
            tree.interface.move(socket, target_index)
    for item in tuple(_iface_sockets(tree, 'OUTPUT')):
        if item.identifier not in keep_outputs:
            tree.interface.remove(item)
    _clear_internal_nodes(tree)
    group_in = _tag(tree.nodes.new("NodeGroupInput"), "set_inputs", layer_set.set_uuid)
    group_out = _tag(tree.nodes.new("NodeGroupOutput"), "set_outputs", layer_set.set_uuid)
    group_out.is_active_output = True
    group_in.location = (-650, 0)
    group_out.location = (520, 0)
    active = [row for row in layer_set.rows if row.resolved_eye]
    combined = None
    for index, row in enumerate(reversed(active)):
        socket = next((sock for sock in group_in.outputs if sock.identifier == row.input_identifier), None)
        if socket is None:
            continue
        if combined is None:
            combined = socket
        else:
            over = _tag(tree.nodes.new("CompositorNodeAlphaOver"), "set_alpha_over", row.source_uuid)
            over.location = (-180 + index * 150, -index * 90)
            factor = over.inputs.get("Factor")
            if factor is not None:
                factor.default_value = 1.0
            tree.links.new(combined, over.inputs["Background"])
            tree.links.new(socket, over.inputs["Foreground"])
            combined = over.outputs["Image"]
    if combined is None:
        transparent = _tag(tree.nodes.new("CompositorNodeRGB"), "set_empty", layer_set.set_uuid)
        transparent.outputs[0].default_value = (0.0, 0.0, 0.0, 0.0)
        combined = transparent.outputs[0]
        empty_image = combined
    else:
        transparent = _tag(tree.nodes.new("CompositorNodeRGB"), "set_transparent_socket", layer_set.set_uuid)
        transparent.outputs[0].default_value = (0.0, 0.0, 0.0, 0.0)
        empty_image = transparent.outputs[0]
    tree.links.new(combined, next(sock for sock in group_out.inputs if sock.identifier == tot.identifier))
    mask_socket = _build_mask(tree, combined, layer_set.mask_mode, 160, -180)
    tree.links.new(mask_socket, next(sock for sock in group_out.inputs if sock.identifier == mask.identifier))
    for row in layer_set.rows:
        if not row.socket_identifier:
            continue
        target = next((sock for sock in group_out.inputs if sock.identifier == row.socket_identifier), None)
        source = next((sock for sock in group_in.outputs if sock.identifier == row.input_identifier), None)
        if target is not None and source is not None:
            tree.links.new(source if row.resolved_eye else empty_image, target)
    node.label = layer_set.name
    node.name = layer_set.node_name or layer_set.name
    layer_set.node_name = node.name
    node.width = max(190, node.width)
    tree.update_tag()
    try:
        tree.interface_update(bpy.context)
        tree.update()
    except (AttributeError, RuntimeError, TypeError):
        pass
    _touch_group_links(node)
    if getattr(node, "id_data", None) is not None:
        node.id_data.update_tag()
    scene.update_tag()
    return tree


def _copy_set(scene, source, new_uuid):
    clone = scene.fbp_layer_sets.add()
    clone.set_uuid = new_uuid
    for attr in (
        "name", "mode", "mask_mode", "follow_layer_list", "special",
        "set_operation", "operand_a_uuid", "operand_b_uuid",
        "membership_mode", "exclusive_group", "rule_folder", "rule_color_tag",
        "rule_type", "rule_name", "rule_name_mode", "rule_visibility",
        "rule_effect", "rule_depth_enabled", "rule_depth_min", "rule_depth_max",
        "snapshot_a", "snapshot_b", "snapshot_c",
    ):
        setattr(clone, attr, getattr(source, attr))
    clone.name = f"{source.name} Copy"
    clone.tot_identifier = ""
    clone.mask_identifier = ""
    for source_row in source.rows:
        row = clone.rows.add()
        for attr in (
            "source_uuid", "name", "eye", "selected", "pinned", "missing",
            "override", "exclusive_excluded",
        ):
            setattr(row, attr, getattr(source_row, attr))
    return clone


def _copy_output(scene, source, new_uuid):
    clone = scene.fbp_output_configs.add()
    clone.output_uuid = new_uuid
    clone.name = f"{source.name} Copy"
    clone.mode = source.mode
    clone.save_beauty = source.save_beauty
    clone.beauty_identifier = ""
    clone.add_identifier = ""
    clone.image_identifier = ""
    clone.auto_expand = bool(getattr(source, 'auto_expand', True))
    for old in source.passes:
        item = clone.passes.add()
        for attr in ("pass_uuid", "enabled", "name", "alias", "subfolder", "prefix", "format_override", "file_format", "color_mode", "color_depth", "compression", "exr_pass_name"):
            setattr(item, attr, getattr(old, attr))
        item.pass_uuid = _id()
    return clone


def _repair_output_pass_ids(config, used_ids=None):
    used = used_ids if used_ids is not None else set()
    changed = 0
    for item in config.passes:
        value = str(getattr(item, "pass_uuid", "") or "")
        if not value or value in used:
            value = _id()
            item.pass_uuid = value
            changed += 1
        used.add(value)
    config.active_index = (
        max(0, min(int(config.active_index), len(config.passes) - 1))
        if config.passes else 0
    )
    return changed



def _repair_output_socket_ids(config, node=None):
    """Repair duplicate/stale interface identifiers without breaking a live promoted Add link."""
    changed = 0
    reserved = set()
    for attr in ('beauty_identifier', 'image_identifier'):
        identifier = str(getattr(config, attr, '') or '')
        if not identifier:
            continue
        if identifier in reserved:
            setattr(config, attr, '')
            changed += 1
        else:
            reserved.add(identifier)

    owners = {}
    for item in config.passes:
        identifier = str(getattr(item, 'input_identifier', '') or '')
        if not identifier:
            continue
        linked = False
        if node is not None:
            socket = next((candidate for candidate in getattr(node, 'inputs', ()) if candidate.identifier == identifier), None)
            linked = bool(socket and socket.is_linked)
        previous = owners.get(identifier)
        if identifier in reserved or previous is not None:
            if previous is not None and linked and not previous[1]:
                previous[0].input_identifier = ''
                owners[identifier] = (item, True)
            else:
                item.input_identifier = ''
            changed += 1
            continue
        owners[identifier] = (item, linked)
        reserved.add(identifier)

    add_identifier = str(getattr(config, 'add_identifier', '') or '')
    if add_identifier and add_identifier in reserved:
        # A linked Add socket can transiently become a real pass before the
        # replacement Add socket is created. Keep the pass identity.
        config.add_identifier = ''
        changed += 1
    return changed

def _repair_stack_row_ids(config):
    used_rows = set()
    used_inputs = set()
    changed = 0
    for row in config.rows:
        row_uuid = str(getattr(row, 'row_uuid', '') or '')
        if not row_uuid or row_uuid in used_rows:
            row.row_uuid = _id()
            row_uuid = row.row_uuid
            changed += 1
        used_rows.add(row_uuid)
        identifier = str(getattr(row, 'input_identifier', '') or '')
        if identifier and identifier in used_inputs:
            row.input_identifier = ''
            changed += 1
        elif identifier:
            used_inputs.add(identifier)
    _ensure_stack_rows(config)
    return changed


def fbp_sync_layer_set_nodes(scene, tree=None, source_node=None, sync_file_outputs=False):
    """Synchronize registry and visible nodes without deleting user nodes."""
    if scene is None or not hasattr(scene, "fbp_layer_sets"):
        return {"sets": 0, "outputs": 0, "stacks": 0}
    tree = tree or _root_tree(scene)
    fbp_refresh_source_registry(scene)
    for saved_set in scene.fbp_layer_sets:
        _sync_rows(scene, saved_set)
    for saved_stack in getattr(scene, "fbp_over_stacks", ()):
        _ensure_stack_rows(saved_stack)
    _resolve_exclusive_conflicts(scene)
    _resolve_all_set_rows(scene)
    source_node = source_node or next(
        (node for node in tree.nodes if _node_role_without_idprops(node) in {"layers_package", "legacy_sources"}),
        None,
    )
    if source_node is None:
        source_node = tree.nodes.get("FBP Layers") or tree.nodes.get("FBP Layers & Groups")
    seen = set()
    for node in tuple(tree.nodes):
        if _node_role_without_idprops(node) != ROLE_SET:
            continue
        set_uuid = _controller_uuid(node)
        original = _find(scene.fbp_layer_sets, "set_uuid", set_uuid)
        if not set_uuid or set_uuid in seen:
            new_uuid = _id()
            layer_set = _copy_set(scene, original, new_uuid) if original else None
            if layer_set is None:
                layer_set = scene.fbp_layer_sets.add()
                layer_set.set_uuid = new_uuid
            node["fbp_uuid"] = new_uuid
            if node.node_tree is not None:
                node.node_tree = node.node_tree.copy()
                node.node_tree["fbp_set_uuid"] = new_uuid
            set_uuid = new_uuid
        seen.add(set_uuid)
        layer_set = _find(scene.fbp_layer_sets, "set_uuid", set_uuid)
        if layer_set is None:
            layer_set = scene.fbp_layer_sets.add()
            layer_set.set_uuid = set_uuid
            layer_set.name = node.label or node.name or "Layer Set"
        _sync_rows(scene, layer_set)
        _build_set_tree(scene, layer_set, node, resolve_memberships=False)
        if source_node is not None:
            for row in layer_set.rows:
                record = _find(scene.fbp_compositor_sources, "source_uuid", row.source_uuid)
                target = next((sock for sock in node.inputs if sock.identifier == row.input_identifier), None)
                source = source_node.outputs.get(record.output_socket_name) if record and record.valid else None
                if source is not None and target is not None and not target.is_linked:
                    tree.links.new(source, target)
                if target is not None:
                    try:
                        # Linked group sockets must remain enabled for Blender's
                        # full-frame compositor. Collapsing them via ``hide``
                        # can prune the whole custom group during render.
                        target.hide = False
                    except FBP_DATA_ERRORS:
                        pass
    if _resolve_exclusive_conflicts(scene):
        _resolve_all_set_rows(scene)
        for node in tuple(tree.nodes):
            if _node_role_without_idprops(node) != ROLE_SET:
                continue
            layer_set = _find(
                scene.fbp_layer_sets,
                "set_uuid",
                str(node.get("fbp_uuid", "") or ""),
            )
            if layer_set is not None:
                _build_set_tree(scene, layer_set, node, resolve_memberships=False)
    for layer_set in scene.fbp_layer_sets:
        if layer_set.set_uuid not in seen:
            layer_set.node_name = ""
    seen_outputs = set()
    used_pass_ids = set()
    for node in tuple(tree.nodes):
        if _node_role_without_idprops(node) != ROLE_OUTPUT:
            continue
        output_uuid = _controller_uuid(node)
        original = _find(scene.fbp_output_configs, "output_uuid", output_uuid)
        if not output_uuid or output_uuid in seen_outputs:
            new_uuid = _id()
            config = _copy_output(scene, original, new_uuid) if original else None
            if config is None:
                config = scene.fbp_output_configs.add()
                config.output_uuid = new_uuid
            node["fbp_uuid"] = new_uuid
            node["fbp_default_pipeline"] = False
            if node.node_tree is not None:
                node.node_tree = node.node_tree.copy()
                node.node_tree["fbp_output_uuid"] = new_uuid
            output_uuid = new_uuid
        seen_outputs.add(output_uuid)
        config = _find(scene.fbp_output_configs, "output_uuid", output_uuid)
        if config is None:
            config = scene.fbp_output_configs.add()
            config.output_uuid = output_uuid
        _repair_output_pass_ids(config, used_pass_ids)
        _build_output_tree(scene, config, node, sync_files=sync_file_outputs)
    scene["_fbp_set_signature"] = "|".join(sorted(seen))
    valid_ids = {item.source_uuid for item in scene.fbp_compositor_sources if item.valid}
    membership = {
        source_uuid: sum(
            1 for layer_set in scene.fbp_layer_sets
            if layer_set.special not in {'UNASSIGNED', 'DERIVED'}
            and any(row.source_uuid == source_uuid and row.resolved_eye for row in layer_set.rows)
        )
        for source_uuid in valid_ids
    }
    unassigned = sum(count == 0 for count in membership.values())
    multiple = sum(count > 1 for count in membership.values())
    missing = sum(not item.valid for item in scene.fbp_compositor_sources)
    empty = sum(not any(row.resolved_eye for row in item.rows) for item in scene.fbp_layer_sets)
    seen_stacks = set()
    for node in tuple(tree.nodes):
        if _node_role_without_idprops(node) != ROLE_STACK:
            continue
        stack_uuid = _controller_uuid(node)
        original = _find(scene.fbp_over_stacks, "stack_uuid", stack_uuid)
        if not stack_uuid or stack_uuid in seen_stacks:
            new_uuid = _id()
            config = _copy_stack(scene, original, new_uuid) if original else None
            if config is None:
                config = scene.fbp_over_stacks.add()
                config.stack_uuid = new_uuid
                _add_stack_row(config, placeholder=True)
            node["fbp_uuid"] = new_uuid
            node["fbp_default_pipeline"] = False
            if node.node_tree is not None:
                node.node_tree = node.node_tree.copy()
                node.node_tree["fbp_stack_uuid"] = new_uuid
            stack_uuid = new_uuid
        seen_stacks.add(stack_uuid)
        config = _find(scene.fbp_over_stacks, "stack_uuid", stack_uuid)
        if config is None:
            config = scene.fbp_over_stacks.add()
            config.stack_uuid = stack_uuid
            config.name = node.label or node.name or "Composite Stack"
            _add_stack_row(config, placeholder=True)
        _ensure_stack_rows(config, node=node)
        _build_stack_tree(scene, config, node)
    for config in getattr(scene, "fbp_over_stacks", ()):
        if not str(getattr(config, "stack_uuid", "") or ""):
            config.stack_uuid = _id()
        if config.stack_uuid not in seen_stacks:
            config.node_name = ""
    scene.fbp_composite_coverage = f"{unassigned} Unassigned · {multiple} Multiple · {missing} Missing · {empty} Empty"
    return {"sets": len(seen), "outputs": len(scene.fbp_output_configs), "stacks": len(seen_stacks)}


def _output_root(scene):
    """Resolve the intended output directory, including new folders.

    ``os.path.isdir`` cannot distinguish a not-yet-created directory from a
    filename prefix. Blender's default ``//Render/`` therefore previously fell
    back to the project folder until the Render directory already existed.
    """
    raw = str(getattr(scene.render, "filepath", "") or "//Render/")
    path = str(bpy.path.abspath(raw) or "")
    if raw.rstrip().endswith(("/", "\\")):
        return os.path.normpath(path)
    if os.path.isdir(path):
        return os.path.normpath(path)
    parent = os.path.dirname(path)
    return os.path.normpath(parent or path)


def _short_output_path(path, limit=72):
    value = str(path or "")
    if len(value) <= limit:
        return value
    head = max(10, (limit - 1) // 2)
    tail = max(10, limit - head - 1)
    return f"{value[:head]}…{value[-tail:]}"


def _output_pass_linked(context, item):
    node = getattr(context, "active_node", None) if context is not None else None
    try:
        if _node_role_without_idprops(node) != ROLE_OUTPUT:
            return False
        identifier = str(getattr(item, "input_identifier", "") or "")
        socket = next((candidate for candidate in node.inputs if candidate.identifier == identifier), None)
        return bool(socket is not None and socket.is_linked)
    except FBP_DATA_ERRORS:
        return False


def _safe_subfolder(value, fallback="Layers"):
    parts = [
        safe_path_component(part, "", 63)
        for part in re.split(r"[\\/]+", str(value or ""))
        if str(part or "").strip() not in {"", ".", ".."}
    ]
    return os.path.join(*parts) if parts else safe_path_component(fallback, "Layers")


def _output_add_socket(node, config):
    identifier = str(getattr(config, 'add_identifier', '') or '')
    if identifier:
        socket = next((item for item in getattr(node, 'inputs', ()) if item.identifier == identifier), None)
        if socket is not None:
            return socket
    return next((item for item in getattr(node, 'inputs', ()) if item.name == 'Add'), None)


def _new_output_pass_from_socket(config, socket, identifier):
    existing = ['Beauty', 'Add', *[str(item.name or item.alias or '') for item in config.passes]]
    title = _unique_dynamic_title(_linked_socket_title(socket, "Pass"), existing, "Pass")
    item = config.passes.add()
    item.pass_uuid = _id()
    item.name = title
    item.alias = title
    item.subfolder = _clean(title, "Pass")
    item.prefix = _clean(title, "Pass")
    item.exr_pass_name = title
    item.input_identifier = str(identifier or '')
    config.active_index = len(config.passes) - 1
    return item


def _recover_linked_output_inputs(config, node, tree):
    known = {str(config.beauty_identifier or ''), str(config.add_identifier or '')}
    known.update(str(item.input_identifier or '') for item in config.passes)
    recovered = 0
    for interface_socket in tuple(_iface_sockets(tree, 'INPUT')):
        identifier = str(getattr(interface_socket, 'identifier', '') or '')
        if str(getattr(interface_socket, 'name', '') or '') in {'Beauty', 'Add'}:
            continue
        if not identifier or identifier in known:
            continue
        socket = next((item for item in getattr(node, 'inputs', ()) if item.identifier == identifier), None)
        if socket is None or not socket.is_linked:
            continue
        _new_output_pass_from_socket(config, socket, identifier)
        known.add(identifier)
        recovered += 1
    return recovered


def _promote_output_add_input(config, node, tree):
    if not bool(getattr(config, 'auto_expand', True)):
        return False
    socket = _output_add_socket(node, config)
    if socket is None or not socket.is_linked:
        return False
    identifier = str(getattr(socket, 'identifier', '') or getattr(config, 'add_identifier', '') or '')
    if not identifier:
        return False
    if any(str(item.input_identifier or '') == identifier for item in config.passes):
        config.add_identifier = ''
        return True
    _new_output_pass_from_socket(config, socket, identifier)
    config.add_identifier = ''
    return True


def _build_output_tree_impl(scene, config, node, sync_files=True):
    _repair_output_pass_ids(config)
    _repair_output_socket_ids(config, node=node)
    tree = node.node_tree
    if tree is None or tree.get("fbp_output_uuid", "") != config.output_uuid:
        tree = bpy.data.node_groups.new(f"FBP Output - {_clean(config.name)}", "CompositorNodeTree")
        tree["fbp_owned"] = True
        tree["fbp_role"] = ROLE_OUTPUT
        tree["fbp_output_uuid"] = config.output_uuid
        node.node_tree = tree
    tree["fbp_owned"] = True
    tree["fbp_role"] = ROLE_OUTPUT
    tree["fbp_output_uuid"] = config.output_uuid
    tree["fbp_uuid"] = config.output_uuid
    tree["fbp_version"] = STRUCTURE_VERSION
    tree["fbp_output_mode"] = config.mode

    # Preserve every linked socket first. The permanent Add input is promoted
    # to a real pass without changing its interface identifier, so Blender
    # keeps the artist link intact while a fresh Add socket appears below it.
    _recover_linked_output_inputs(config, node, tree)
    _promote_output_add_input(config, node, tree)

    beauty = _ensure_iface(tree, "Beauty", 'INPUT', 'NodeSocketColor', config.beauty_identifier)
    config.beauty_identifier = beauty.identifier
    pass_sockets = []
    for item in config.passes:
        socket = _ensure_iface(tree, item.name, 'INPUT', 'NodeSocketColor', item.input_identifier)
        item.input_identifier = socket.identifier
        pass_sockets.append(socket)
    add = _ensure_iface(tree, "Add", 'INPUT', 'NodeSocketColor', config.add_identifier)
    image = _ensure_iface(tree, "Image", 'OUTPUT', 'NodeSocketColor', config.image_identifier)
    config.add_identifier = add.identifier
    config.image_identifier = image.identifier

    keep_inputs = {beauty.identifier, add.identifier} | {item.input_identifier for item in config.passes}
    for socket in tuple(_iface_sockets(tree, 'INPUT')):
        if socket.identifier not in keep_inputs:
            external = next((item for item in getattr(node, 'inputs', ()) if item.identifier == socket.identifier), None)
            if external is not None and external.is_linked:
                continue
            tree.interface.remove(socket)
    for socket in tuple(_iface_sockets(tree, 'OUTPUT')):
        if socket.identifier != image.identifier:
            tree.interface.remove(socket)

    # Fixed Beauty first, dynamic passes in UI-list order, Add always last.
    ordered = [beauty, *pass_sockets, add, image]
    for target_index, socket in enumerate(ordered):
        current_index = list(tree.interface.items_tree).index(socket)
        if current_index != target_index:
            tree.interface.move(socket, target_index)

    tree.nodes.clear()
    group_in = _tag(tree.nodes.new("NodeGroupInput"), "output_inputs", config.output_uuid)
    group_out = _tag(tree.nodes.new("NodeGroupOutput"), "output_image", config.output_uuid)
    group_out.is_active_output = True
    group_in.location = (-260, 0)
    group_out.location = (260, 0)
    tree.links.new(
        next(sock for sock in group_in.outputs if sock.identifier == beauty.identifier),
        next(sock for sock in group_out.inputs if sock.identifier == image.identifier),
    )
    node.label = "Export" if bool(node.get('fbp_default_pipeline', False)) else config.name
    config.node_name = node.name
    node.width = max(190, node.width)
    tree.update_tag()
    try:
        tree.interface_update(bpy.context)
        tree.update()
    except (AttributeError, RuntimeError, TypeError):
        pass
    _touch_group_links(node)
    if getattr(node, "id_data", None) is not None:
        node.id_data.update_tag()
    scene.update_tag()
    if sync_files:
        _sync_root_file_outputs(scene, config, node)
    return tree



def _build_output_tree(scene, config, node, sync_files=True):
    key = _scene_runtime_key(scene)
    if key in _FBP_ACTIVE_OUTPUT_SCENES:
        return getattr(node, 'node_tree', None)
    _FBP_ACTIVE_OUTPUT_SCENES.add(key)
    try:
        return _build_output_tree_impl(scene, config, node, sync_files=sync_files)
    finally:
        _FBP_ACTIVE_OUTPUT_SCENES.discard(key)

def _sync_root_file_outputs(scene, config, controller):
    """Build native root-level File Output nodes controlled by FBP Output."""
    root = getattr(controller, "id_data", None)
    if root is None:
        return
    owned_nodes = []
    for candidate in tuple(getattr(root, "nodes", ()) or ()):
        try:
            if str(getattr(candidate, "bl_idname", "") or "") not in {
                "NodeFrame",
                "CompositorNodeOutputFile",
            }:
                continue
            if str(candidate.get("fbp_output_owner", "") or "") == str(config.output_uuid or ""):
                owned_nodes.append(candidate)
        except FBP_DATA_ERRORS:
            continue
    def source_for(identifier):
        socket = next((item for item in controller.inputs if item.identifier == identifier), None)
        return socket.links[0].from_socket if socket is not None and socket.is_linked else None

    resolved = []
    if config.save_beauty:
        beauty_source = source_for(config.beauty_identifier)
        if beauty_source is not None:
            resolved.append({
                "uuid": f"{config.output_uuid}:beauty", "name": "Beauty", "alias": "Beauty",
                "exr": "Beauty", "subfolder": "Beauty", "prefix": "beauty",
                "format": str(scene.render.image_settings.file_format or 'PNG'),
                "color_mode": str(scene.render.image_settings.color_mode or 'RGBA'),
                "color_depth": str(scene.render.image_settings.color_depth or '8'),
                "compression": int(getattr(scene.render.image_settings, "compression", 15) or 0),
                "source": beauty_source,
            })
    for item in config.passes:
        if not item.enabled:
            continue
        source = source_for(item.input_identifier)
        if source is None:
            continue
        settings = scene.render.image_settings
        resolved.append({
            "uuid": item.pass_uuid, "name": item.name, "alias": item.alias or item.name,
            "exr": item.exr_pass_name or item.alias or item.name,
            "subfolder": item.subfolder, "prefix": item.prefix or item.alias or item.name,
            "format": item.file_format if item.format_override else str(settings.file_format or 'PNG'),
            "color_mode": item.color_mode if item.format_override else str(settings.color_mode or 'RGBA'),
            "color_depth": item.color_depth if item.format_override else str(settings.color_depth or '8'),
            "compression": item.compression if item.format_override else int(getattr(settings, "compression", 15) or 0),
            "source": source,
        })
    if not resolved:
        for candidate in owned_nodes:
            root.nodes.remove(candidate)
        return
    frame = next((candidate for candidate in owned_nodes if candidate.get("fbp_role", "") == "output_file_frame"), None)
    if frame is None:
        frame = _tag(root.nodes.new("NodeFrame"), "output_file_frame", config.output_uuid)
    frame["fbp_output_owner"] = config.output_uuid
    frame.name = f"FBP Output Files - {config.output_uuid[:8]}"
    frame.label = f"Export Files - {config.name}"
    frame.hide = True
    frame.location = (controller.location.x + 340, controller.location.y - 420)
    keep = {int(frame.as_pointer())}

    if config.mode == 'MULTILAYER' and resolved:
        file_node = next((candidate for candidate in owned_nodes if candidate.get("fbp_role", "") == "output_multilayer" and candidate.get("fbp_uuid", "") == config.output_uuid), None)
        if file_node is None:
            file_node = _tag(root.nodes.new("CompositorNodeOutputFile"), "output_multilayer", config.output_uuid)
        file_node["fbp_output_owner"] = config.output_uuid
        keep.add(int(file_node.as_pointer()))
        file_node.parent = frame
        file_node.location = (40, -60)
        file_node.directory = _output_root(scene)
        file_node.file_name = safe_path_component(config.name, "Composite", 63) + "_####"
        file_node.format.media_type = 'MULTI_LAYER_IMAGE'
        file_node.format.file_format = 'OPEN_EXR_MULTILAYER'
        file_node.file_output_items.clear()
        used_slot_names = []
        for entry in resolved:
            slot_name = _unique_dynamic_title(
                safe_path_component(entry["exr"], "Pass", 63),
                used_slot_names,
                "Pass",
            )
            used_slot_names.append(slot_name)
            slot = file_node.file_output_items.new('RGBA', slot_name)
            target = file_node.inputs.get(str(getattr(slot, "name", "") or slot_name))
            if target is not None:
                root.links.new(entry["source"], target)
    else:
        for index, entry in enumerate(resolved):
            file_node = next((candidate for candidate in owned_nodes if candidate.get("fbp_role", "") == "output_separate" and candidate.get("fbp_uuid", "") == entry["uuid"]), None)
            if file_node is None:
                file_node = _tag(root.nodes.new("CompositorNodeOutputFile"), "output_separate", entry["uuid"])
            file_node["fbp_output_owner"] = config.output_uuid
            keep.add(int(file_node.as_pointer()))
            file_node.parent = frame
            file_node.location = (40, -60 - index * 170)
            file_node.directory = os.path.join(_output_root(scene), _safe_subfolder(entry["subfolder"]))
            file_node.file_name = safe_path_component(entry["prefix"], "Pass", 63) + "_"
            file_node.format.media_type = 'IMAGE'
            try:
                file_node.format.file_format = entry["format"]
            except (TypeError, ValueError):
                file_node.format.file_format = 'PNG'
            try:
                file_node.format.color_mode = entry["color_mode"]
            except (TypeError, ValueError):
                file_node.format.color_mode = 'RGBA'
            try:
                file_node.format.color_depth = entry["color_depth"]
            except (TypeError, ValueError):
                pass
            if hasattr(file_node.format, "compression"):
                file_node.format.compression = int(entry["compression"])
            file_node.file_output_items.clear()
            slot_name = safe_path_component(entry["alias"], "Image", 63)
            slot = file_node.file_output_items.new('RGBA', slot_name)
            target = file_node.inputs.get(str(getattr(slot, "name", "") or slot_name))
            if target is not None:
                root.links.new(entry["source"], target)
    for candidate in owned_nodes:
        if int(candidate.as_pointer()) not in keep:
            root.nodes.remove(candidate)
    root.update_tag()
    try:
        root.interface_update(bpy.context)
        root.update()
    except (AttributeError, RuntimeError, TypeError):
        pass
    scene.update_tag()


def _add_set(scene, tree, name="Layer Set", special='NONE'):
    node = tree.nodes.new("FBPCompositorLayerSetNode")
    layer_set = _find(scene.fbp_layer_sets, "set_uuid", str(node.get("fbp_uuid", "") or ""))
    if layer_set is None:
        layer_set = scene.fbp_layer_sets.add()
        layer_set.set_uuid = str(node.get("fbp_uuid", "") or _id())
        node["fbp_uuid"] = layer_set.set_uuid
    layer_set.name = name
    layer_set.special = special
    _sync_rows(scene, layer_set)
    node.location = (0, -220 * (len(scene.fbp_layer_sets) - 1))
    _build_set_tree(scene, layer_set, node)
    return layer_set, node


def _add_output(scene, tree, mode='SEPARATE'):
    node = tree.nodes.new("FBPCompositorOutputNode")
    config = _find(scene.fbp_output_configs, "output_uuid", str(node.get("fbp_uuid", "") or ""))
    if config is None:
        config = scene.fbp_output_configs.add()
        config.output_uuid = str(node.get("fbp_uuid", "") or _id())
        node["fbp_uuid"] = config.output_uuid
    config.mode = mode
    node.location = (520, 0)
    _build_output_tree(scene, config, node)
    # Insert the controller in the native Beauty chain. This preserves the
    # source already feeding Blender's true group output and makes Image the
    # authoritative pass-through without changing the rendered result.
    group_output = next((candidate for candidate in tree.nodes if candidate.bl_idname == 'NodeGroupOutput' and candidate.is_active_output and candidate.inputs.get("Image") is not None), None)
    beauty = node.inputs.get("Beauty")
    image = node.outputs.get("Image")
    if group_output is not None and beauty is not None and image is not None:
        target = group_output.inputs["Image"]
        if target.is_linked:
            source = target.links[0].from_socket
            for link in tuple(target.links):
                tree.links.remove(link)
            tree.links.new(source, beauty)
        if not target.is_linked:
            tree.links.new(image, target)
    return config, node


def fbp_ensure_default_output(scene, tree):
    """Return the single Export controller used by the clean pipeline."""
    output_nodes = [
        item for item in tuple(getattr(tree, "nodes", ()) or ())
        if _node_role_without_idprops(item) == ROLE_OUTPUT
    ]
    node = next(
        (
            item for item in output_nodes
            if bool(item.get('fbp_default_pipeline', False))
        ),
        None,
    )
    if node is None:
        candidates = output_nodes
        node = candidates[0] if len(candidates) == 1 else None
    created_node = node is None
    if node is None:
        node = tree.nodes.new('FBPCompositorOutputNode')
    node['fbp_default_pipeline'] = True
    output_uuid = str(node.get('fbp_uuid', '') or '')
    config = _find(scene.fbp_output_configs, 'output_uuid', output_uuid)
    created_config = config is None
    if config is None:
        config = scene.fbp_output_configs.add()
        config.output_uuid = output_uuid or _id()
        node['fbp_uuid'] = config.output_uuid
    if created_node or created_config or not str(config.name or '').strip():
        config.name = 'Export'
    _build_output_tree(scene, config, node, sync_files=False)
    node['fbp_default_pipeline'] = True
    node.label = 'Export'
    node.location = (620, 40)
    return node


def _node_image_input(node):
    return (
        node.inputs.get('Image')
        or node.inputs.get('Color')
        or next((socket for socket in node.inputs if getattr(socket, 'type', '') == 'RGBA'), None)
    )


def _node_image_output(node):
    return (
        node.outputs.get('Image')
        or node.outputs.get('Color')
        or next((socket for socket in node.outputs if getattr(socket, 'type', '') == 'RGBA'), None)
    )


def _insert_effect_stage_node(tree, node):
    """Insert one new effect at the end of the Effects / Masks image chain."""
    group_output = next(
        (
            candidate for candidate in tree.nodes
            if candidate.bl_idname == 'NodeGroupOutput'
            and candidate.is_active_output
            and candidate.inputs.get('Image') is not None
        ),
        None,
    )
    image_input = _node_image_input(node)
    image_output = _node_image_output(node)
    if group_output is None or image_input is None or image_output is None:
        return False
    target = group_output.inputs['Image']
    source = target.links[0].from_socket if target.is_linked else None
    for link in tuple(target.links):
        tree.links.remove(link)
    if source is not None:
        tree.links.new(source, image_input)
        node.location = (source.node.location.x + 220, source.node.location.y)
    else:
        group_input = next((candidate for candidate in tree.nodes if candidate.bl_idname == 'NodeGroupInput'), None)
        source = group_input.outputs.get('Image') if group_input is not None else None
        if source is not None:
            tree.links.new(source, image_input)
            node.location = (0, 0)
    tree.links.new(image_output, target)
    group_output.location.x = max(group_output.location.x, node.location.x + 260)
    tree.update_tag()
    return True


def _draw_derived_set_controls(layout, scene, layer_set, compact=False):
    box = layout.box()
    box.label(text="Live UUID Membership", icon='NODETREE')
    for side, attr in (("A", "operand_a_uuid"), ("B", "operand_b_uuid")):
        operand_uuid = str(getattr(layer_set, attr, "") or "")
        row = box.row(align=False)
        row.label(text=f"{side} · {_layer_set_display_name(scene, operand_uuid)}")
        choose = row.operator("fbp.choose_layer_set_operand", text="", icon='EYEDROPPER')
        choose.set_uuid = layer_set.set_uuid
        choose.side = side
        clear = row.row(align=False)
        clear.enabled = bool(operand_uuid)
        operator = clear.operator("fbp.choose_layer_set_operand", text="", icon='X')
        operator.set_uuid = layer_set.set_uuid
        operator.side = side
        operator.clear = True
    freeze = box.operator(
        "fbp.freeze_derived_layer_set",
        text="Make Manual" if compact else "Convert to Manual Layer Set",
        icon='UNLINKED',
    )
    freeze.set_uuid = layer_set.set_uuid


class FBP_UL_LayerSetRows(UIList):
    bl_idname = "FBP_UL_LayerSetRows"
    _PROFILE = "LAYER_SET_ROWS"

    def filter_items(self, context, data, propname):
        mark_ui_list_draw()
        items = getattr(data, propname, ())
        scene = getattr(context, "scene", None)
        query = str(scene.get("fbp_uilist_filter_layer_set_rows", "") or "").strip().casefold() if scene else ""
        flags = [self.bitflag_filter_item if not query or query in str(getattr(item, "name", "") or "").casefold() else 0 for item in items]
        order = list(range(len(items)))
        if scene and bool(scene.get("fbp_uilist_sort_layer_set_rows", False)):
            order.sort(key=lambda i: str(getattr(items[i], "name", "") or "").casefold())
        if scene and bool(scene.get("fbp_uilist_reverse_layer_set_rows", False)):
            order.reverse()
        return flags, order if order != list(range(len(items))) else []

    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        mark_ui_list_draw()
        row = layout.row(align=True)
        record = _find(context.scene.fbp_compositor_sources, 'source_uuid', item.source_uuid)
        source_icon = 'ERROR' if item.missing else (record.icon if record and record.icon else 'RENDERLAYERS')
        visible = set(fbp_uilist_visible_columns(context, self._PROFILE))
        for key in fbp_uilist_icon_order(context, self._PROFILE):
            if key not in visible:
                continue
            if fbp_uilist_is_spacer(key):
                fbp_draw_uilist_spacer(row)
                continue
            if key == 'set_source':
                row.label(text='', icon=source_icon)
            elif key == 'label':
                row.label(text=item.name or 'Missing Source')
            elif key == 'set_visibility':
                cell = row.row(align=True)
                cell.enabled = data.special != 'DERIVED'
                eye = cell.operator('fbp.layer_set_row_action', text='', icon='HIDE_OFF' if item.resolved_eye else 'HIDE_ON', emboss=False)
                eye.set_uuid = data.set_uuid
                eye.source_uuid = item.source_uuid
                eye.action = 'TOGGLE_EYE'
            elif key == 'set_select':
                row.prop(item, 'selected', text='', icon='CHECKBOX_HLT' if item.selected else 'CHECKBOX_DEHLT', emboss=False)
            elif key == 'set_pin':
                row.prop(item, 'pinned', text='', icon='PINNED' if item.pinned else 'UNPINNED', emboss=False)


class FBP_UL_OutputPasses(UIList):
    bl_idname = "FBP_UL_OutputPasses"
    _PROFILE = "OUTPUT_PASSES"

    def filter_items(self, context, data, propname):
        mark_ui_list_draw()
        items = getattr(data, propname, ())
        scene = getattr(context, "scene", None)
        query = str(scene.get("fbp_uilist_filter_output_passes", "") or "").strip().casefold() if scene else ""
        flags = [self.bitflag_filter_item if not query or query in " ".join((str(getattr(item, "name", "") or ""), str(getattr(item, "subfolder", "") or ""), str(getattr(item, "exr_pass_name", "") or ""))).casefold() else 0 for item in items]
        order = list(range(len(items)))
        if scene and bool(scene.get("fbp_uilist_sort_output_passes", False)):
            order.sort(key=lambda i: str(getattr(items[i], "name", "") or "").casefold())
        if scene and bool(scene.get("fbp_uilist_reverse_output_passes", False)):
            order.reverse()
        return flags, order if order != list(range(len(items))) else []

    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        mark_ui_list_draw()
        row = layout.row(align=True)
        linked = _output_pass_linked(context, item)
        visible = set(fbp_uilist_visible_columns(context, self._PROFILE))
        for key in fbp_uilist_icon_order(context, self._PROFILE):
            if key not in visible:
                continue
            if fbp_uilist_is_spacer(key):
                fbp_draw_uilist_spacer(row)
                continue
            if key == 'label':
                row.prop(item, 'name', text='', emboss=False)
            elif key == 'output_enabled':
                row.prop(item, 'enabled', text='', icon='CHECKBOX_HLT' if item.enabled else 'CHECKBOX_DEHLT', emboss=False)
            elif key == 'output_link':
                row.label(text='', icon='LINKED' if linked else 'UNLINKED')
            elif key == 'output_format':
                if str(getattr(data, 'mode', 'SEPARATE') or 'SEPARATE') == 'MULTILAYER':
                    row.prop(item, 'exr_pass_name', text='', emboss=False, icon='IMAGE_DATA')
                else:
                    row.prop(item, 'subfolder', text='', emboss=False, icon='FILE_FOLDER')
                    row.prop(item, 'format_override', text='', icon='IMAGE_DATA', emboss=False)


class FBP_MT_LayerSetRowActions(Menu):
    bl_idname = "FBP_MT_layer_set_row_actions"
    bl_label = "Layer Set Row Actions"

    def draw(self, context):
        layout = configure_layout(self.layout)
        scene = getattr(context, "scene", None)
        node = getattr(context, "active_node", None)
        layer_set = (
            _find(scene.fbp_layer_sets, "set_uuid", _controller_uuid(node))
            if scene is not None and node is not None else None
        )
        active = (
            layer_set.rows[layer_set.active_index]
            if layer_set is not None and 0 <= layer_set.active_index < len(layer_set.rows)
            else None
        )
        top = layout.row(align=True)
        top.enabled = bool(active is not None and layer_set.active_index > 0)
        op = top.operator("fbp.layer_set_row_action", text="Move to Top", icon="TRIA_UP_BAR")
        op.set_uuid = layer_set.set_uuid if layer_set else ""
        op.source_uuid = active.source_uuid if active else ""
        op.action = "MOVE_TOP"
        bottom = layout.row(align=True)
        bottom.enabled = bool(
            active is not None and layer_set.active_index < len(layer_set.rows) - 1
        )
        op = bottom.operator("fbp.layer_set_row_action", text="Move to Bottom", icon="TRIA_DOWN_BAR")
        op.set_uuid = layer_set.set_uuid if layer_set else ""
        op.source_uuid = active.source_uuid if active else ""
        op.action = "MOVE_BOTTOM"
        layout.separator()
        remove = layout.operator("fbp.layer_set_row_action", text="Remove Missing", icon="TRASH")
        remove.set_uuid = layer_set.set_uuid if layer_set else ""
        remove.action = "REMOVE_MISSING"
        sync = layout.operator("fbp.layer_set_batch", text="Sync Sources", icon="FILE_REFRESH")
        sync.set_uuid = layer_set.set_uuid if layer_set else ""
        sync.action = "SYNC"


class FBP_MT_OutputPassActions(Menu):
    bl_idname = "FBP_MT_output_pass_actions"
    bl_label = "Output Pass Actions"

    def draw(self, context):
        layout = configure_layout(self.layout)
        scene = getattr(context, "scene", None)
        node = getattr(context, "active_node", None)
        config = (
            _find(scene.fbp_output_configs, "output_uuid", _controller_uuid(node))
            if scene is not None and node is not None else None
        )
        active = (
            config.passes[config.active_index]
            if config is not None and 0 <= config.active_index < len(config.passes)
            else None
        )
        for action, label, icon, enabled in (
            ("MOVE_TOP", "Move to Top", "TRIA_UP_BAR", bool(active is not None and config.active_index > 0)),
            ("MOVE_BOTTOM", "Move to Bottom", "TRIA_DOWN_BAR", bool(active is not None and config.active_index < len(config.passes) - 1)),
        ):
            row = layout.row(align=True)
            row.enabled = enabled
            op = row.operator("fbp.output_pass_action", text=label, icon=icon)
            op.output_uuid = config.output_uuid if config else ""
            op.action = action
        layout.separator()
        remove = layout.row(align=True)
        remove.enabled = active is not None
        op = remove.operator("fbp.output_pass_action", text="Remove", icon="TRASH")
        op.output_uuid = config.output_uuid if config else ""
        op.action = "REMOVE"


class FBP_MT_StackRowActions(Menu):
    bl_idname = "FBP_MT_stack_row_actions"
    bl_label = "Composite Stack Actions"

    def draw(self, context):
        layout = configure_layout(self.layout)
        scene = getattr(context, "scene", None)
        node = getattr(context, "active_node", None)
        config = (
            _find(scene.fbp_over_stacks, "stack_uuid", _controller_uuid(node))
            if scene is not None and node is not None else None
        )
        active = (
            config.rows[config.active_index]
            if config is not None and 0 <= config.active_index < len(config.rows)
            else None
        )
        active_placeholder = bool(active and getattr(active, "is_placeholder", False))
        last_real = max(-1, len(config.rows) - 2) if config is not None else -1
        for action, label, icon, enabled in (
            ("MOVE_TOP", "Move to Top", "TRIA_UP_BAR", bool(active is not None and not active_placeholder and config.active_index > 0)),
            ("MOVE_BOTTOM", "Move to Bottom", "TRIA_DOWN_BAR", bool(active is not None and not active_placeholder and config.active_index < last_real)),
        ):
            row = layout.row(align=True)
            row.enabled = enabled
            op = row.operator("fbp.stack_row_action", text=label, icon=icon)
            op.stack_uuid = config.stack_uuid if config else ""
            op.row_uuid = active.row_uuid if active else ""
            op.action = action
        layout.separator()
        remove = layout.row(align=True)
        remove.enabled = bool(active is not None and not active_placeholder and len(config.rows) > 1)
        op = remove.operator("fbp.stack_row_action", text="Remove", icon="TRASH")
        op.stack_uuid = config.stack_uuid if config else ""
        op.row_uuid = active.row_uuid if active else ""
        op.action = "REMOVE"
        clean = layout.operator("fbp.stack_row_action", text="Clean Empty Inputs", icon="BRUSH_DATA")
        clean.stack_uuid = config.stack_uuid if config else ""
        clean.action = "CLEAN_EMPTY"


class FBP_CompositorLayerSetNode(bpy.types.CompositorNodeCustomGroup):
    bl_idname = "FBPCompositorLayerSetNode"
    bl_label = "FBP Layer Set"
    bl_icon = 'RENDERLAYERS'

    @classmethod
    def poll(cls, node_tree):
        return getattr(node_tree, "bl_idname", "") == 'CompositorNodeTree'

    def init(self, context):
        set_uuid = _id()
        _tag(self, ROLE_SET, set_uuid)
        scene = getattr(context, "scene", None)
        if scene is None or not hasattr(scene, "fbp_layer_sets"):
            return
        fbp_refresh_source_registry(scene)
        layer_set = scene.fbp_layer_sets.add()
        layer_set.set_uuid = set_uuid
        layer_set.name = "Layer Set"
        _sync_rows(scene, layer_set)
        _build_set_tree(scene, layer_set, self)

    def draw_buttons(self, context, layout):
        scene = getattr(context, "scene", None)
        layer_set = (
            _find(scene.fbp_layer_sets, "set_uuid", str(self.get("fbp_uuid", "") or ""))
            if scene else None
        )
        if layer_set is None:
            layout.label(text="Sync required", icon='ERROR')
            return

        layout.prop(layer_set, "name", text="")
        header = layout.row(align=False)
        if layer_set.special == 'DERIVED':
            header.prop(layer_set, "set_operation", text="")
        else:
            header.prop(layer_set, "mode", text="")
        header.prop(layer_set, "mask_mode", text="")

        list_box = fbp_draw_uilist_header(
            layout, context, "LAYER_SET_ROWS"
        )
        list_row = list_box.row(align=False)
        list_row.template_list(
            "FBP_UL_LayerSetRows",
            "node",
            layer_set,
            "rows",
            layer_set,
            "active_index",
            rows=max(3, min(7, len(layer_set.rows) or 3)),
        )
        active_row = (
            layer_set.rows[layer_set.active_index]
            if 0 <= layer_set.active_index < len(layer_set.rows)
            else None
        )
        active_index = int(layer_set.active_index) if active_row is not None else -1
        last_index = len(layer_set.rows) - 1
        tools = list_row.column(align=True)
        fbp_set_ui_units_x(tools, 1.0)
        tools.menu("FBP_MT_layer_set_row_actions", text="", icon="COLLAPSEMENU")
        tools.separator()
        movement = tools.column(align=True)
        for action, icon, enabled in (
            ('MOVE_UP', 'SORT_DESC', active_index > 0),
            ('MOVE_DOWN', 'SORT_ASC', 0 <= active_index < last_index),
        ):
            button = movement.row(align=True)
            button.enabled = bool(enabled)
            operator = button.operator("fbp.layer_set_row_action", text="", icon=icon)
            operator.set_uuid = layer_set.set_uuid
            operator.source_uuid = active_row.source_uuid if active_row else ""
            operator.action = action

        active_count = sum(1 for row_item in layer_set.rows if row_item.resolved_eye)
        status = layout.row(align=False)
        status.label(text=f"{active_count} of {len(layer_set.rows)} active")
        status.prop(
            layer_set,
            "follow_layer_list",
            text="Follow Layers",
            toggle=True,
            icon='LINKED' if layer_set.follow_layer_list else 'UNLINKED',
        )
        if layer_set.special == 'DERIVED':
            _draw_derived_set_controls(layout, scene, layer_set, compact=True)
        else:
            membership = layout.row(align=False)
            membership.prop(layer_set, "membership_mode", text="")
            if layer_set.membership_mode == 'EXCLUSIVE':
                membership.prop(layer_set, "exclusive_group", text="")

        has_rows = bool(layer_set.rows)
        has_selected_rows = any(row_item.selected for row_item in layer_set.rows)
        selection = layout.row(align=False)
        selection.enabled = has_rows
        selection.label(text="Select")
        for action, icon in (
            ('SELECT_ALL', 'CHECKBOX_HLT'),
            ('SELECT_NONE', 'CHECKBOX_DEHLT'),
            ('INVERT_SELECTION', 'ARROW_LEFTRIGHT'),
        ):
            operator = selection.operator("fbp.layer_set_batch", text="", icon=icon)
            operator.set_uuid = layer_set.set_uuid
            operator.action = action

        visibility = layout.row(align=False)
        visibility.enabled = has_selected_rows and layer_set.special != 'DERIVED'
        visibility.label(text="Selected")
        for action, icon in (
            ('ENABLE_SELECTED', 'HIDE_OFF'),
            ('DISABLE_SELECTED', 'HIDE_ON'),
        ):
            operator = visibility.operator("fbp.layer_set_batch", text="", icon=icon)
            operator.set_uuid = layer_set.set_uuid
            operator.action = action

        sync_row = layout.row(align=False)
        sync = sync_row.operator("fbp.layer_set_batch", text="Sync", icon='FILE_REFRESH')
        sync.set_uuid = layer_set.set_uuid
        sync.action = 'SYNC'


class FBP_CompositorOutputNode(bpy.types.CompositorNodeCustomGroup):
    bl_idname = "FBPCompositorOutputNode"
    bl_label = "FBP Output"
    bl_icon = 'OUTPUT'

    @classmethod
    def poll(cls, node_tree):
        return getattr(node_tree, "bl_idname", "") == 'CompositorNodeTree'

    def update(self):
        try:
            signature = tuple(
                (
                    str(socket.identifier or ''),
                    bool(socket.is_linked),
                    tuple(
                        (int(link.from_node.as_pointer()), str(link.from_socket.identifier or link.from_socket.name or ''))
                        for link in tuple(socket.links)
                    ),
                )
                for socket in self.inputs
            )
            key = _node_link_signature_key(self)
        except (AttributeError, ReferenceError, RuntimeError, TypeError):
            return
        if _OUTPUT_NODE_LINK_SIGNATURES.get(key) == signature:
            return
        _OUTPUT_NODE_LINK_SIGNATURES[key] = signature
        _queue_output_link_update(self)

    def init(self, context):
        output_uuid = _id()
        _tag(self, ROLE_OUTPUT, output_uuid)
        scene = getattr(context, "scene", None)
        if scene is None or not hasattr(scene, "fbp_output_configs"):
            return
        config = scene.fbp_output_configs.add()
        config.output_uuid = output_uuid
        _build_output_tree(scene, config, self, sync_files=False)

    def draw_buttons(self, context, layout):
        scene = getattr(context, "scene", None)
        config = (
            _find(scene.fbp_output_configs, "output_uuid", str(self.get("fbp_uuid", "") or ""))
            if scene else None
        )
        if config is None:
            layout.label(text="Sync required", icon='ERROR')
            return

        layout.prop(config, "name", text="")
        row = layout.row(align=False)
        row.prop(config, "mode", text="")
        row.prop(config, "save_beauty", text="Beauty", toggle=True, icon='RENDER_STILL')
        row.prop(config, "auto_expand", text="Auto Add", toggle=True, icon='ADD')
        list_box = fbp_draw_uilist_header(
            layout, context, "OUTPUT_PASSES"
        )
        list_row = list_box.row(align=False)
        list_row.template_list(
            "FBP_UL_OutputPasses",
            "node",
            config,
            "passes",
            config,
            "active_index",
            rows=max(3, min(7, len(config.passes) or 3)),
        )
        active_pass = (
            config.passes[config.active_index]
            if 0 <= config.active_index < len(config.passes)
            else None
        )
        active_index = int(config.active_index) if active_pass is not None else -1
        active_pass_linked = bool(active_pass is not None and _output_pass_linked(context, active_pass))
        controls = list_row.column(align=True)
        fbp_set_ui_units_x(controls, 1.0)
        controls.menu("FBP_MT_output_pass_actions", text="", icon="COLLAPSEMENU")
        controls.separator()
        movement = controls.column(align=True)
        for action, icon, enabled in (
            ('MOVE_UP', 'SORT_DESC', active_index > 0),
            ('MOVE_DOWN', 'SORT_ASC', 0 <= active_index < len(config.passes) - 1),
        ):
            button = movement.row(align=True)
            button.enabled = bool(enabled)
            operator = button.operator("fbp.output_pass_action", text="", icon=icon)
            operator.output_uuid = config.output_uuid
            operator.action = action
        controls.separator()
        add = controls.operator("fbp.output_pass_action", text="", icon='ADD')
        add.output_uuid = config.output_uuid
        add.action = 'ADD'
        if not config.passes:
            layout.label(text='Connect Add to create an export pass', icon='INFO')
        elif active_pass_linked:
            layout.label(text='Disconnect the active pass before deleting it', icon='LINKED')


class FBP_UL_StackRows(UIList):
    bl_idname = "FBP_UL_StackRows"
    _PROFILE = "COMPOSITOR_STACK"

    def filter_items(self, context, data, propname):
        mark_ui_list_draw()
        items = getattr(data, propname, ())
        scene = getattr(context, "scene", None)
        query = str(scene.get("fbp_uilist_filter_compositor_stack", "") or "").strip().casefold() if scene else ""
        flags = [self.bitflag_filter_item if bool(getattr(item, 'is_placeholder', False)) or not query or query in str(getattr(item, "name", "") or "").casefold() else 0 for item in items]
        order = list(range(len(items)))
        real = [i for i, item in enumerate(items) if not bool(getattr(item, 'is_placeholder', False))]
        placeholders = [i for i, item in enumerate(items) if bool(getattr(item, 'is_placeholder', False))]
        if scene and bool(scene.get("fbp_uilist_sort_compositor_stack", False)):
            real.sort(key=lambda i: str(getattr(items[i], "name", "") or "").casefold())
            order = real + placeholders
        if scene and bool(scene.get("fbp_uilist_reverse_compositor_stack", False)):
            real.reverse()
            order = real + placeholders
        return flags, order if order != list(range(len(items))) else []

    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        mark_ui_list_draw()
        row = layout.row(align=True)
        if bool(getattr(item, 'is_placeholder', False)):
            row.enabled = False
            row.label(text='Connect Add Input', icon='ADD')
            return
        linked = False
        try:
            node = getattr(context, 'active_node', None)
            socket = _stack_input_socket(node, item) if _node_role_without_idprops(node) == ROLE_STACK else None
            linked = bool(socket is not None and socket.is_linked)
        except FBP_DATA_ERRORS:
            linked = False
        visible = set(fbp_uilist_visible_columns(context, self._PROFILE))
        for key in fbp_uilist_icon_order(context, self._PROFILE):
            if key not in visible:
                continue
            if fbp_uilist_is_spacer(key):
                fbp_draw_uilist_spacer(row)
                continue
            if key == 'label':
                row.prop(item, 'name', text='', emboss=False)
            elif key == 'stack_enabled':
                row.prop(item, 'enabled', text='', icon='CHECKBOX_HLT' if item.enabled else 'CHECKBOX_DEHLT', emboss=False)
            elif key == 'stack_link':
                row.label(text='', icon='ERROR' if item.missing else ('LINKED' if linked else 'UNLINKED'))


class FBP_CompositorStackNode(bpy.types.CompositorNodeCustomGroup):
    bl_idname = 'FBPCompositorStackNode'
    bl_label = 'FBP Composite Stack'
    bl_icon = 'NODETREE'

    @classmethod
    def poll(cls, node_tree):
        return getattr(node_tree, 'bl_idname', '') == 'CompositorNodeTree'

    def update(self):
        try:
            signature = tuple(
                (
                    str(socket.identifier or ''),
                    bool(socket.is_linked),
                    tuple(
                        (int(link.from_node.as_pointer()), str(link.from_socket.identifier or link.from_socket.name or ''))
                        for link in tuple(socket.links)
                    ),
                )
                for socket in self.inputs
            )
            key = _node_link_signature_key(self)
        except (AttributeError, ReferenceError, RuntimeError, TypeError):
            return
        if _STACK_NODE_LINK_SIGNATURES.get(key) == signature:
            return
        _STACK_NODE_LINK_SIGNATURES[key] = signature
        _queue_stack_link_update(self)

    def init(self, context):
        stack_uuid = _id()
        _tag(self, ROLE_STACK, stack_uuid)
        scene = getattr(context, 'scene', None)
        if scene is None or not hasattr(scene, 'fbp_over_stacks'):
            return
        config = scene.fbp_over_stacks.add()
        config.stack_uuid = stack_uuid
        config.name = 'Composite Stack'
        _add_stack_row(config, placeholder=True)
        _build_stack_tree(scene, config, self)

    def draw_buttons(self, context, layout):
        scene = getattr(context, 'scene', None)
        config = (
            _find(scene.fbp_over_stacks, 'stack_uuid', str(self.get('fbp_uuid', '') or ''))
            if scene else None
        )
        if config is None:
            layout.label(text='Sync required', icon='ERROR')
            return
        layout.prop(config, 'name', text='')
        list_box = fbp_draw_uilist_header(
            layout, context, "COMPOSITOR_STACK"
        )
        list_row = list_box.row(align=False)
        list_row.template_list(
            'FBP_UL_StackRows', 'node', config, 'rows', config, 'active_index',
            rows=max(4, min(8, len(config.rows) or 4)),
        )
        active_row = config.rows[config.active_index] if 0 <= config.active_index < len(config.rows) else None
        active_index = int(config.active_index) if active_row is not None else -1
        last_index = max(-1, len(config.rows) - 2)
        active_is_placeholder = bool(active_row and getattr(active_row, 'is_placeholder', False))
        controls = list_row.column(align=True)
        fbp_set_ui_units_x(controls, 1.0)
        controls.menu("FBP_MT_stack_row_actions", text="", icon="COLLAPSEMENU")
        controls.separator()
        movement = controls.column(align=True)
        for action, icon, enabled in (
            ('MOVE_UP', 'SORT_DESC', active_index > 0 and not active_is_placeholder),
            ('MOVE_DOWN', 'SORT_ASC', 0 <= active_index < last_index and not active_is_placeholder),
        ):
            button = movement.row(align=True)
            button.enabled = bool(enabled)
            operator = button.operator('fbp.stack_row_action', text='', icon=icon)
            operator.stack_uuid = config.stack_uuid
            operator.row_uuid = active_row.row_uuid if active_row else ''
            operator.action = action
        controls.separator()
        add = controls.operator('fbp.stack_row_action', text='', icon='ADD')
        add.stack_uuid = config.stack_uuid
        add.action = 'ADD'
        options = layout.row(align=False)
        options.prop(config, 'auto_expand', text='Auto Add', toggle=True, icon='ADD')
        if config.is_default_pipeline:
            options.prop(
                config,
                'follow_layer_list',
                text='Follow Layers',
                toggle=True,
                icon='LINKED' if config.follow_layer_list else 'UNLINKED',
            )
        layout.label(text='Top input = front / nearest to camera', icon='INFO')


class _FBP_CompositorPreviewPoll:
    @classmethod
    def poll(cls, context):
        scene = getattr(context, "scene", None)
        return bool(scene is not None and fbp_feature_enabled(scene, "compositor_layers"))


class FBP_OT_StackRowAction(_FBP_CompositorPreviewPoll, Operator):
    bl_idname = 'fbp.stack_row_action'
    bl_label = 'Edit Composite Stack'
    bl_options = {'REGISTER', 'UNDO'}

    stack_uuid: StringProperty()
    row_uuid: StringProperty()
    action: EnumProperty(items=(
        ('ADD', 'Add', ''),
        ('REMOVE', 'Remove', ''),
        ('MOVE_TOP', 'Move Top', ''),
        ('MOVE_UP', 'Move Up', ''),
        ('MOVE_DOWN', 'Move Down', ''),
        ('MOVE_BOTTOM', 'Move Bottom', ''),
        ('CLEAN_EMPTY', 'Clean Empty Inputs', ''),
    ))

    def execute(self, context):
        scene = context.scene
        config = _find(scene.fbp_over_stacks, 'stack_uuid', self.stack_uuid)
        if config is None:
            return {'CANCELLED'}
        root = _root_tree(scene)
        node = next(
            (
                item for item in tuple(getattr(root, "nodes", ()) or ())
                if _node_role_without_idprops(item) == ROLE_STACK
                and _controller_uuid(item) == str(config.stack_uuid or "")
            ),
            None,
        )
        row = _find(config.rows, 'row_uuid', self.row_uuid) if self.row_uuid else None
        index = next((i for i, item in enumerate(config.rows) if str(item.row_uuid or '') == str(self.row_uuid or '')), -1)
        if self.action == 'ADD':
            row = _add_stack_input_row(config)
            config.active_index = next((index for index, item in enumerate(config.rows) if item.row_uuid == row.row_uuid), 0)
        elif self.action == 'REMOVE':
            if index < 0 or len(config.rows) <= 1 or bool(getattr(row, 'is_placeholder', False)):
                return {'CANCELLED'}
            if node is not None:
                socket = _stack_input_socket(node, row)
                if socket is not None and socket.is_linked:
                    self.report({'WARNING'}, 'Disconnect the input before removing it')
                    return {'CANCELLED'}
            config.rows.remove(index)
            config.active_index = max(0, min(index, len(config.rows) - 1))
        elif self.action == 'CLEAN_EMPTY':
            removed = 0
            for remove_index in range(len(config.rows) - 1, -1, -1):
                candidate = config.rows[remove_index]
                socket = _stack_input_socket(node, candidate) if node is not None else None
                if bool(getattr(candidate, 'is_placeholder', False)) or str(candidate.source_key or '') or (socket is not None and socket.is_linked):
                    continue
                config.rows.remove(remove_index)
                removed += 1
            _ensure_stack_rows(config, node=node)
        elif index >= 0 and not bool(getattr(row, 'is_placeholder', False)):
            last_real = max(0, len(config.rows) - 2)
            target = {
                'MOVE_TOP': 0,
                'MOVE_UP': max(0, index - 1),
                'MOVE_DOWN': min(last_real, index + 1),
                'MOVE_BOTTOM': last_real,
            }.get(self.action, index)
            if target != index:
                config.rows.move(index, target)
                config.active_index = target
                config.follow_layer_list = False
        if node is not None:
            _build_stack_tree(scene, config, node)
        return {'FINISHED'}


class FBP_OT_AddCompositorAsset(_FBP_CompositorPreviewPoll, Operator):
    bl_idname = "fbp.add_compositor_asset"
    bl_label = "Add Frame By Plane Compositor Node"
    bl_options = {'REGISTER', 'UNDO'}
    kind: StringProperty()
    label: StringProperty()
    def execute(self, context):
        scene = context.scene
        if not scene.fbp_compositor_layers:
            call_service("compositor.auto_layers", scene)
        if scene.fbp_compositor_layers and not scene.fbp_compositor_enabled:
            call_service(
                "compositor.sync",
                scene,
                context=context,
                native_group=True,
                activate_compositor=True,
            )
        root_tree = _root_tree(scene)
        registry_item = next(
            (
                item for item in FBP_NODE_REGISTRY
                if item["kind"] == self.kind and item["label"] == self.label
            ),
            None,
        )
        target_category = str(registry_item.get("category", "") or "") if registry_item else ""
        tree = root_tree
        if target_category in {'EFFECTS', 'MASKS'}:
            effects_stage = next(
                (node for node in root_tree.nodes if _node_role_without_idprops(node) == 'effects_stage'),
                None,
            )
            if effects_stage is not None and effects_stage.node_tree is not None:
                tree = effects_stage.node_tree
        fbp_refresh_source_registry(scene)
        dirty_set = None
        dirty_set_node = None
        created_node = None
        selected_set_uuids = [
            _controller_uuid(node)
            for node in getattr(context, "selected_nodes", ())
            if _node_role_without_idprops(node) == ROLE_SET
            and _controller_uuid(node)
        ]
        active_node = getattr(context, "active_node", None)
        active_set_uuid = (
            _controller_uuid(active_node)
            if active_node is not None and _node_role_without_idprops(active_node) == ROLE_SET
            else ""
        )
        if active_set_uuid:
            selected_set_uuids = [active_set_uuid] + [
                value for value in selected_set_uuids if value != active_set_uuid
            ]

        def add_pass(config, name, subfolder="Layers"):
            item = config.passes.add()
            item.pass_uuid = _id()
            item.name = name
            item.alias = name
            item.subfolder = os.path.join(subfolder, name) if subfolder else name
            return item

        def selected_source_records():
            selected_ids = {
                str(getattr(obj, "fbp_compositor_source_id", "") or "")
                for obj in getattr(context, "selected_objects", ())
            }
            return [record for record in scene.fbp_compositor_sources if record.source_uuid in selected_ids]

        if self.kind == 'CLEAN_PIPELINE':
            result = call_service(
                "compositor.sync", scene, context=context, native_group=True,
                activate_compositor=True
            )
            if not isinstance(result, dict):
                self.report(
                    {'ERROR'},
                    "Compositor sync service is unavailable; reload Frame By Plane",
                )
                return {'CANCELLED'}
            self.report(
                {'INFO'},
                f"Clean compositor pipeline · {int(result.get('visible_nodes', 0))} visible stages",
            )
            return {'FINISHED'}
        if self.kind == 'STACK':
            selected_nodes = list(getattr(context, 'selected_nodes', ()))
            config, stack_node = _add_stack(scene, tree, self.label or 'Composite Stack')
            selected_sources = []
            for node in sorted(selected_nodes, key=lambda item: float(getattr(item, 'location', (0.0, 0.0))[1]), reverse=True):
                if node == stack_node:
                    continue
                output = node.outputs.get('TOT') or node.outputs.get('Image') or next((sock for sock in node.outputs if getattr(sock, 'type', '') == 'RGBA'), None)
                if output is None:
                    continue
                selected_sources.append((node, output))
            if selected_sources:
                real_rows = [row for row in config.rows if not bool(getattr(row, 'is_placeholder', False))]
                while len(real_rows) < len(selected_sources):
                    real_rows.append(_add_stack_input_row(config))
                for row, (source_node, _output) in zip(real_rows, selected_sources, strict=False):
                    row.name = _unique_dynamic_title(
                        str(source_node.label or source_node.name or row.name),
                        [item.name for item in real_rows if item.row_uuid != row.row_uuid],
                        'Layer',
                    )
                _build_stack_tree(scene, config, stack_node)
                for row, (_source_node, output) in zip(real_rows, selected_sources, strict=False):
                    target = next((sock for sock in stack_node.inputs if sock.identifier == row.input_identifier), None)
                    if target is not None:
                        try:
                            tree.links.new(output, target)
                        except (AttributeError, RuntimeError, TypeError, ValueError):
                            pass
                _ensure_stack_rows(config, node=stack_node)
                _build_stack_tree(scene, config, stack_node)
                stack_node.location = (
                    max((node.location.x for node, _out in selected_sources), default=0.0) + 260.0,
                    sum(node.location.y for node, _out in selected_sources) / max(1, len(selected_sources)),
                )
            dirty_set = None
            dirty_set_node = None
        elif self.kind.startswith('SET_UUID_'):
            operation = self.kind.removeprefix('SET_UUID_')
            if operation not in {item[0] for item in SET_OPERATION_ITEMS}:
                return {'CANCELLED'}
            name = self.label or f"UUID Set {operation.title()}"
            layer_set, set_node = _add_set(scene, tree, name, 'DERIVED')
            layer_set.set_operation = operation
            operands = [
                value for value in selected_set_uuids
                if value and value != layer_set.set_uuid
                and _find(scene.fbp_layer_sets, "set_uuid", value) is not None
            ]
            if operands:
                layer_set.operand_a_uuid = operands[0]
            if len(operands) > 1:
                layer_set.operand_b_uuid = operands[1]
            dirty_set = layer_set
            dirty_set_node = set_node
        elif self.kind in {'SET', 'UNASSIGNED', 'SET_SELECTED', 'SET_FOLDER', 'SET_TAG', 'SET_TYPE', 'SET_FG', 'SET_MID', 'SET_BG'}:
            template_names = {
                'SET_FG': "Foreground",
                'SET_MID': "Midground",
                'SET_BG': "Background",
            }
            name = template_names.get(self.kind, self.label or "Layer Set")
            layer_set, set_node = _add_set(scene, tree, name, 'UNASSIGNED' if self.kind == 'UNASSIGNED' else 'NONE')
            dirty_set = layer_set
            dirty_set_node = set_node
            selected_records = selected_source_records()
            if self.kind == 'SET_SELECTED':
                selected_ids = {record.source_uuid for record in selected_records}
                for row in layer_set.rows:
                    row.eye = row.source_uuid in selected_ids
                    row.selected = row.eye
            elif self.kind == 'SET_FOLDER':
                folder = getattr(getattr(context, "collection", None), "name", "")
                if not folder and selected_records:
                    folder = selected_records[0].parent_name
                layer_set.mode = 'RULE'
                layer_set.rule_folder = folder
            elif self.kind == 'SET_TAG':
                layer_set.mode = 'RULE'
                layer_set.rule_color_tag = selected_records[0].color_tag if selected_records else ""
            elif self.kind == 'SET_TYPE':
                layer_set.mode = 'RULE'
                layer_set.rule_type = selected_records[0].layer_type if selected_records else ""
        elif self.kind.startswith('OUTPUT'):
            config, output = _add_output(scene, tree, 'MULTILAYER' if self.kind == 'OUTPUT_EXR' else 'SEPARATE')
            if self.kind == 'OUTPUT_BEAUTY':
                config.save_beauty = True
                add_pass(config, "Pass")
                _build_output_tree(scene, config, output)
        elif self.kind in {'PRESET_FMB', 'PRESET_FULL'}:
            sets = [_add_set(scene, tree, name)[1] for name in ("Foreground", "Midground", "Background")]
            config, output = _add_output(scene, tree)
            config.save_beauty = self.kind == 'PRESET_FULL'
            for name in ("Foreground", "Midground", "Background"):
                add_pass(config, name)
            _build_output_tree(scene, config, output)
            for set_node, item in zip(sets, config.passes, strict=False):
                source = set_node.outputs.get("TOT")
                target = next((sock for sock in output.inputs if sock.identifier == item.input_identifier), None)
                if source and target:
                    tree.links.new(source, target)
        elif self.kind == 'PRESET_AUTO_DEPTH':
            thresholds = depth_split_thresholds(
                record.depth
                for record in scene.fbp_compositor_sources
                if record.valid and record.depth_valid
            )
            if thresholds is None:
                self.report(
                    {'WARNING'},
                    "Auto Depth Split needs a camera and at least three distinct source depths",
                )
                return {'CANCELLED'}
            near_mid, mid_far = thresholds
            set_nodes = []
            for name, depth_min, depth_max in (
                ("Foreground", -1.0e20, near_mid),
                ("Midground", near_mid, mid_far),
                ("Background", mid_far, 1.0e20),
            ):
                layer_set, set_node = _add_set(scene, tree, name)
                layer_set.mode = 'RULE'
                layer_set.rule_depth_enabled = True
                layer_set.rule_depth_min = depth_min
                layer_set.rule_depth_max = depth_max
                _build_set_tree(scene, layer_set, set_node)
                set_nodes.append(set_node)
            config, output = _add_output(scene, tree)
            config.name = "Depth Split Output"
            for name in ("Foreground", "Midground", "Background"):
                add_pass(config, name)
            _build_output_tree(scene, config, output)
            for set_node, item in zip(set_nodes, config.passes, strict=False):
                source = set_node.outputs.get("TOT")
                target = next(
                    (socket for socket in output.inputs if socket.identifier == item.input_identifier),
                    None,
                )
                if source is not None and target is not None:
                    tree.links.new(source, target)
        elif self.kind in {'PRESET_CHARACTER', 'PRESET_BG_DEFOCUS', 'PRESET_FG_GRADE'}:
            name, node_type = {
                'PRESET_CHARACTER': ("Characters", None),
                'PRESET_BG_DEFOCUS': ("Background", "CompositorNodeDefocus"),
                'PRESET_FG_GRADE': ("Foreground", "CompositorNodeColorBalance"),
            }[self.kind]
            _layer_set, set_node = _add_set(scene, tree, name)
            if node_type:
                effect_node = tree.nodes.new(node_type)
                effect_node.label = self.label
                set_node.location = (0, set_node.location.y)
                effect_node.location = (300, set_node.location.y)
                source = set_node.outputs.get("TOT")
                target = effect_node.inputs.get("Image") or effect_node.inputs.get("Color")
                if source is not None and target is not None:
                    tree.links.new(source, target)
            else:
                config, output = _add_output(scene, tree)
                item = add_pass(config, name)
                _build_output_tree(scene, config, output)
                target = next((socket for socket in output.inputs if socket.identifier == item.input_identifier), None)
                if target is not None:
                    tree.links.new(set_node.outputs["TOT"], target)
        elif self.kind.startswith('PRESET_'):
            preset_passes = {
                'PRESET_REVIEW': ("Review",),
                'PRESET_DELIVERY': ("Foreground", "Midground", "Background", "Characters", "FX"),
                'PRESET_FINAL': (),
                'PRESET_DEBUG': ("Debug", "Mask", "Depth"),
                'PRESET_BEAUTY_MASKS': ("Masks",),
                'PRESET_BEAUTY_SEPARATE': ("Foreground", "Midground", "Background"),
                'PRESET_BEAUTY_EXR': ("Foreground", "Midground", "Background"),
                'PRESET_EXR_DELIVERY': ("Foreground", "Midground", "Background", "Characters", "FX", "Masks"),
            }
            mode = 'MULTILAYER' if self.kind in {'PRESET_BEAUTY_EXR', 'PRESET_EXR_DELIVERY'} else 'SEPARATE'
            config, output = _add_output(scene, tree, mode)
            config.name = self.label or "FBP Output"
            config.save_beauty = self.kind in {'PRESET_REVIEW', 'PRESET_FINAL', 'PRESET_BEAUTY_MASKS', 'PRESET_BEAUTY_SEPARATE', 'PRESET_BEAUTY_EXR'}
            for name in preset_passes.get(self.kind, ()):
                add_pass(config, name, "Debug" if self.kind == 'PRESET_DEBUG' else "Layers")
            _build_output_tree(scene, config, output)
        elif self.kind.startswith('ASSET_'):
            asset_name = {
                'ASSET_VIGNETTE': "Vignette",
                'ASSET_UNSHARP_MASK': "Unsharp Mask",
                'ASSET_TUNE_IMAGE': "Tune Image",
                'ASSET_FILM_GRAIN': "Film Grain",
                'ASSET_CHROMATIC_ABERRATION': "Chromatic Aberration",
                'ASSET_SEPIA': "Sepia",
            }.get(self.kind, self.label)
            node = tree.nodes.new("CompositorNodeGroup")
            node.node_tree = call_service(
                "compositor.ensure_asset_group",
                asset_name,
            )
            node.label = self.label
            created_node = node
        else:
            node = tree.nodes.new(self.kind)
            node.label = self.label
            created_node = node
            if self.label == "Inverted Mask" and hasattr(node, "operation"):
                node.operation = 'SUBTRACT'
                node.inputs[0].default_value = 1.0
            if self.label == "Edge Mask" and node.inputs.get("Type") is not None: node.inputs["Type"].default_value = 'Sobel'
            if self.label in {"Set Difference", "Image Set Difference"} and hasattr(node, "operation"): node.operation = 'SUBTRACT'
            if self.label in {"Set Intersection", "Image Set Intersection"} and hasattr(node, "operation"): node.operation = 'MULTIPLY'
            if self.label in {"Combined Mask", "Set Union", "Set Combine", "Image Set Union", "Image Set Combine"} and hasattr(node, "operation"): node.operation = 'MAXIMUM'
            if self.label in {"Set XOR", "Image Set XOR"} and hasattr(node, "operation"):
                node.operation = 'COMPARE'
                node.inputs[2].default_value = 0.0
            if self.label == "Premultiply" and hasattr(node, "mapping"): node.mapping = 'STRAIGHT_TO_PREMUL'
            if self.label == "Unpremultiply" and hasattr(node, "mapping"): node.mapping = 'PREMUL_TO_STRAIGHT'
        if created_node is not None and target_category == 'EFFECTS' and tree is not root_tree:
            _insert_effect_stage_node(tree, created_node)
        elif created_node is not None and target_category == 'MASKS' and tree is not root_tree:
            created_node.location = (0, -260 - 180 * len([node for node in tree.nodes if node != created_node]))

        # Do not resync every existing controller after adding one registry
        # entry.  On large compositor graphs that made Shift+A progressively
        # slower and could turn preset insertion into an O(n²) operation.
        # `_add_set`, `_add_output` and every preset builder already construct
        # their own nodes.  Only the set templates modified after `_add_set`
        # need one targeted rebuild here.
        if dirty_set is not None and dirty_set_node is not None:
            _build_set_tree(scene, dirty_set, dirty_set_node)
        return {'FINISHED'}


class FBP_OT_LayerSetRowAction(_FBP_CompositorPreviewPoll, Operator):
    bl_idname = "fbp.layer_set_row_action"
    bl_label = "Edit Layer Set"
    bl_options = {'UNDO'}

    _DESCRIPTIONS = {
        'TOGGLE_EYE': "Show or hide this source in the Layer Set",
        'MOVE_TOP': "Move the source to the top of the Layer Set",
        'MOVE_UP': "Move the source one position up",
        'MOVE_DOWN': "Move the source one position down",
        'MOVE_BOTTOM': "Move the source to the bottom of the Layer Set",
        'REMOVE_MISSING': "Remove unpinned missing sources that have no external links",
    }

    @classmethod
    def description(cls, context, properties):
        return cls._DESCRIPTIONS.get(str(getattr(properties, 'action', '') or ''), cls.bl_label)
    set_uuid: StringProperty()
    source_uuid: StringProperty()
    action: EnumProperty(items=(('TOGGLE_EYE', "Toggle Eye", ""), ('MOVE_TOP', "Move Top", ""), ('MOVE_UP', "Move Up", ""), ('MOVE_DOWN', "Move Down", ""), ('MOVE_BOTTOM', "Move Bottom", ""), ('REMOVE_MISSING', "Remove Missing", "")))
    use_shift: BoolProperty(default=False, options={'HIDDEN'})
    use_ctrl: BoolProperty(default=False, options={'HIDDEN'})
    def invoke(self, context, event):
        return invoke_with_selection_modifiers(self, context, event)
    def execute(self, context):
        layer_set = _find(context.scene.fbp_layer_sets, "set_uuid", self.set_uuid)
        if layer_set is None:
            return {'CANCELLED'}
        row = _find(layer_set.rows, "source_uuid", self.source_uuid)
        active_uuid = identity_at(layer_set.rows, "source_uuid", layer_set.active_index)
        if self.action == 'REMOVE_MISSING':
            removed_uuids = set()
            for index in reversed(range(len(layer_set.rows))):
                candidate = layer_set.rows[index]
                if candidate.missing and not candidate.pinned and not _row_socket_linked(context.scene, layer_set, candidate):
                    removed_uuids.add(str(candidate.source_uuid or ""))
                    layer_set.rows.remove(index)
            if layer_set.rows:
                layer_set.active_index = restore_active_index(
                    layer_set.rows, "source_uuid",
                    "" if active_uuid in removed_uuids else active_uuid,
                    fallback=min(layer_set.active_index, len(layer_set.rows) - 1),
                )
                if str(transient_get(layer_set, "eye_anchor_uid", "") or "") in removed_uuids:
                    store_anchor(
                        layer_set, "eye_anchor", "eye_anchor_uid",
                        layer_set.rows, "source_uuid", layer_set.active_index,
                    )
            else:
                layer_set.active_index = 0
                clear_anchor(layer_set, "eye_anchor", "eye_anchor_uid")
        elif row is None:
            return {'CANCELLED'}
        elif self.action == 'TOGGLE_EYE':
            if layer_set.special == 'DERIVED':
                self.report({'INFO'}, "UUID Set membership is controlled by its operands")
                return {'CANCELLED'}
            value = not bool(row.resolved_eye)
            index = next(i for i, candidate in enumerate(layer_set.rows) if candidate.source_uuid == row.source_uuid)
            targets = []
            if self.use_shift:
                anchor = resolve_anchor_index(
                    layer_set, "eye_anchor", "eye_anchor_uid",
                    layer_set.rows, "source_uuid", fallback=index,
                )
                lo, hi = sorted((anchor, index))
                targets = list(layer_set.rows[lo:hi + 1])
            elif self.use_ctrl:
                targets = [candidate for candidate in layer_set.rows if candidate.selected]
            else:
                targets = [row]
            if layer_set.mode == 'RULE':
                layer_set.mode = 'MIXED'
            for candidate in targets:
                if layer_set.mode == 'MANUAL':
                    candidate.eye = value
                else:
                    candidate.override = 'INCLUDE' if value else 'EXCLUDE'
                candidate.exclusive_excluded = False
            if value:
                _apply_exclusive_membership(
                    context.scene,
                    layer_set,
                    (candidate.source_uuid for candidate in targets),
                )
            store_anchor(
                layer_set, "eye_anchor", "eye_anchor_uid",
                layer_set.rows, "source_uuid", index,
            )
        else:
            index = next(i for i, candidate in enumerate(layer_set.rows) if candidate.source_uuid == row.source_uuid)
            if self.action == 'MOVE_TOP':
                target = 0
            elif self.action == 'MOVE_BOTTOM':
                target = len(layer_set.rows) - 1
            else:
                target = index + (-1 if self.action == 'MOVE_UP' else 1)
            if not 0 <= target < len(layer_set.rows): return {'CANCELLED'}
            if target == index: return {'FINISHED'}
            layer_set.rows.move(index, target)
            layer_set.follow_layer_list = False
            layer_set.active_index = target
        fbp_sync_layer_set_nodes(context.scene)
        return {'FINISHED'}


class FBP_OT_LayerSetBatch(_FBP_CompositorPreviewPoll, Operator):
    bl_idname = "fbp.layer_set_batch"
    bl_label = "Layer Set Batch Action"
    bl_options = {'UNDO'}

    _DESCRIPTIONS = {
        'SELECT_ALL': "Select every source row",
        'SELECT_NONE': "Clear the source-row selection",
        'INVERT_SELECTION': "Invert the source-row selection",
        'ENABLE_SELECTED': "Show every selected source",
        'DISABLE_SELECTED': "Hide every selected source",
        'ENABLE_ALL': "Show every source",
        'DISABLE_ALL': "Hide every source",
        'INVERT_EYES': "Invert source visibility",
        'RESET_ORDER': "Restore Layer List order and resume following it",
        'SYNC': "Refresh source rows and rebuild the Layer Set node",
        'REMOVE_MISSING': "Remove safe missing sources while preserving linked or pinned sockets",
        'SAVE_A': "Save the current Layer Set state to snapshot A",
        'SAVE_B': "Save the current Layer Set state to snapshot B",
        'SAVE_C': "Save the current Layer Set state to snapshot C",
        'LOAD_A': "Restore snapshot A",
        'LOAD_B': "Restore snapshot B",
        'LOAD_C': "Restore snapshot C",
    }

    @classmethod
    def description(cls, context, properties):
        return cls._DESCRIPTIONS.get(str(getattr(properties, 'action', '') or ''), cls.bl_label)
    set_uuid: StringProperty()
    action: EnumProperty(items=tuple((value, value.replace('_', ' ').title(), "") for value in ('SELECT_ALL','SELECT_NONE','INVERT_SELECTION','ENABLE_SELECTED','DISABLE_SELECTED','ENABLE_ALL','DISABLE_ALL','INVERT_EYES','RESET_ORDER','SYNC','REMOVE_MISSING','SAVE_A','SAVE_B','SAVE_C','LOAD_A','LOAD_B','LOAD_C')))
    def execute(self, context):
        layer_set = _find(context.scene.fbp_layer_sets, "set_uuid", self.set_uuid)
        if layer_set is None: return {'CANCELLED'}
        if layer_set.special == 'DERIVED' and self.action in {
            'ENABLE_SELECTED', 'DISABLE_SELECTED', 'ENABLE_ALL', 'DISABLE_ALL', 'INVERT_EYES'
        }:
            self.report({'INFO'}, "UUID Set membership is controlled by its operands")
            return {'CANCELLED'}
        active_uuid = identity_at(layer_set.rows, "source_uuid", layer_set.active_index)
        if self.action == 'SELECT_ALL':
            for row in layer_set.rows: row.selected = True
        elif self.action == 'SELECT_NONE':
            for row in layer_set.rows: row.selected = False
        elif self.action == 'INVERT_SELECTION':
            for row in layer_set.rows: row.selected = not row.selected
        elif self.action in {'ENABLE_SELECTED','DISABLE_SELECTED'}:
            value = self.action == 'ENABLE_SELECTED'
            changed_uuids = set()
            if layer_set.mode == 'RULE':
                layer_set.mode = 'MIXED'
            for row in layer_set.rows:
                if row.selected:
                    if layer_set.mode == 'MANUAL':
                        row.eye = value
                    else:
                        row.override = 'INCLUDE' if value else 'EXCLUDE'
                    row.exclusive_excluded = False
                    changed_uuids.add(row.source_uuid)
            if value:
                _apply_exclusive_membership(context.scene, layer_set, changed_uuids)
        elif self.action in {'ENABLE_ALL','DISABLE_ALL'}:
            value = self.action == 'ENABLE_ALL'
            if layer_set.mode == 'RULE':
                layer_set.mode = 'MIXED'
            for row in layer_set.rows:
                if layer_set.mode == 'MANUAL':
                    row.eye = value
                else:
                    row.override = 'INCLUDE' if value else 'EXCLUDE'
                row.exclusive_excluded = False
            if value:
                _apply_exclusive_membership(
                    context.scene,
                    layer_set,
                    (row.source_uuid for row in layer_set.rows),
                )
        elif self.action == 'INVERT_EYES':
            enabled = set()
            current_values = {
                row.source_uuid: _effective_eye(context.scene, layer_set, row)
                for row in layer_set.rows
            }
            if layer_set.mode == 'RULE':
                layer_set.mode = 'MIXED'
            for row in layer_set.rows:
                value = not current_values[row.source_uuid]
                if layer_set.mode == 'MANUAL':
                    row.eye = value
                else:
                    row.override = 'INCLUDE' if value else 'EXCLUDE'
                row.exclusive_excluded = False
                if value:
                    enabled.add(row.source_uuid)
            _apply_exclusive_membership(context.scene, layer_set, enabled)
        elif self.action == 'RESET_ORDER':
            layer_set.follow_layer_list = True
            _sync_rows(context.scene, layer_set)
            layer_set.active_index = restore_active_index(
                layer_set.rows, "source_uuid", active_uuid,
                fallback=layer_set.active_index,
            )
        elif self.action == 'REMOVE_MISSING':
            removed_uuids = set()
            for index in reversed(range(len(layer_set.rows))):
                candidate = layer_set.rows[index]
                if candidate.missing and not candidate.pinned and not _row_socket_linked(context.scene, layer_set, candidate):
                    removed_uuids.add(str(candidate.source_uuid or ""))
                    layer_set.rows.remove(index)
            if layer_set.rows:
                layer_set.active_index = restore_active_index(
                    layer_set.rows, "source_uuid",
                    "" if active_uuid in removed_uuids else active_uuid,
                    fallback=min(layer_set.active_index, len(layer_set.rows) - 1),
                )
            else:
                layer_set.active_index = 0
                clear_anchor(layer_set, "eye_anchor", "eye_anchor_uid")
        elif self.action.startswith('SAVE_'):
            payload = {
                "mode": layer_set.mode,
                "mask_mode": layer_set.mask_mode,
                "special": layer_set.special,
                "set_operation": layer_set.set_operation,
                "operand_a_uuid": layer_set.operand_a_uuid,
                "operand_b_uuid": layer_set.operand_b_uuid,
                "follow": layer_set.follow_layer_list,
                "membership_mode": layer_set.membership_mode,
                "exclusive_group": layer_set.exclusive_group,
                "depth_enabled": layer_set.rule_depth_enabled,
                "depth_min": layer_set.rule_depth_min,
                "depth_max": layer_set.rule_depth_max,
                "rows": [
                    {
                        "uuid": row.source_uuid,
                        "eye": row.eye,
                        "pin": row.pinned,
                        "override": row.override,
                        "exclusive_excluded": row.exclusive_excluded,
                    }
                    for row in layer_set.rows
                ],
            }
            setattr(layer_set, "snapshot_" + self.action[-1].lower(), json.dumps(payload, separators=(",", ":")))
        elif self.action.startswith('LOAD_'):
            raw = getattr(layer_set, "snapshot_" + self.action[-1].lower(), "")
            if not raw:
                return {'CANCELLED'}
            try:
                payload = json.loads(raw)
            except (TypeError, ValueError, json.JSONDecodeError):
                self.report({'WARNING'}, "The selected Layer Set snapshot is invalid")
                return {'CANCELLED'}
            if not isinstance(payload, dict):
                self.report({'WARNING'}, "The selected Layer Set snapshot has an unsupported format")
                return {'CANCELLED'}
            mode = str(payload.get("mode", layer_set.mode) or layer_set.mode)
            if mode in {item[0] for item in SET_MODE_ITEMS}:
                layer_set.mode = mode
            mask_mode = str(payload.get("mask_mode", layer_set.mask_mode) or layer_set.mask_mode)
            if mask_mode in {item[0] for item in MASK_ITEMS}:
                layer_set.mask_mode = mask_mode
            previous_derived_state = (
                layer_set.special,
                layer_set.set_operation,
                layer_set.operand_a_uuid,
                layer_set.operand_b_uuid,
            )
            special = str(payload.get("special", layer_set.special) or layer_set.special)
            if special in {'NONE', 'UNASSIGNED', 'DERIVED'}:
                layer_set.special = special
            operation = str(payload.get("set_operation", layer_set.set_operation) or layer_set.set_operation)
            if operation in {item[0] for item in SET_OPERATION_ITEMS}:
                layer_set.set_operation = operation
            layer_set.operand_a_uuid = str(payload.get("operand_a_uuid", layer_set.operand_a_uuid) or "")
            layer_set.operand_b_uuid = str(payload.get("operand_b_uuid", layer_set.operand_b_uuid) or "")
            if any(layer_set.set_uuid in cycle for cycle in directed_cycles(_derived_set_graph(context.scene))):
                (
                    layer_set.special,
                    layer_set.set_operation,
                    layer_set.operand_a_uuid,
                    layer_set.operand_b_uuid,
                ) = previous_derived_state
                self.report({'WARNING'}, "Circular UUID Set operands were not restored")
            layer_set.follow_layer_list = bool(payload.get("follow", False))
            membership_mode = str(payload.get("membership_mode", layer_set.membership_mode) or layer_set.membership_mode)
            if membership_mode in {item[0] for item in MEMBERSHIP_ITEMS}:
                layer_set.membership_mode = membership_mode
            layer_set.exclusive_group = str(payload.get("exclusive_group", layer_set.exclusive_group) or "")
            layer_set.rule_depth_enabled = bool(payload.get("depth_enabled", layer_set.rule_depth_enabled))
            try:
                layer_set.rule_depth_min = float(payload.get("depth_min", layer_set.rule_depth_min))
                layer_set.rule_depth_max = float(payload.get("depth_max", layer_set.rule_depth_max))
            except (TypeError, ValueError):
                pass

            row_states = payload.get("rows", [])
            if not isinstance(row_states, list):
                self.report({'WARNING'}, "The selected Layer Set snapshot has invalid row data")
                return {'CANCELLED'}
            by_uuid = {row.source_uuid: row for row in layer_set.rows}
            order = []
            valid_overrides = {item[0] for item in OVERRIDE_ITEMS}
            for state in row_states:
                if not isinstance(state, dict):
                    continue
                row = by_uuid.get(str(state.get("uuid", "") or ""))
                if row is None:
                    continue
                row.eye = bool(state.get("eye", False))
                row.pinned = bool(state.get("pin", False))
                row.exclusive_excluded = bool(state.get("exclusive_excluded", False))
                override = str(state.get("override", 'AUTO') or 'AUTO')
                row.override = override if override in valid_overrides else 'AUTO'
                order.append(row.source_uuid)
            for target, source_uuid in enumerate(order):
                current = next((i for i, row in enumerate(layer_set.rows) if row.source_uuid == source_uuid), -1)
                if current >= 0: layer_set.rows.move(current, target)
            layer_set.active_index = restore_active_index(
                layer_set.rows, "source_uuid", active_uuid,
                fallback=layer_set.active_index,
            )
        elif self.action == 'SYNC':
            pass
        else:
            return {'CANCELLED'}
        fbp_sync_layer_set_nodes(context.scene)
        return {'FINISHED'}


def _layer_set_operand_items(self, context):
    global _LAYER_SET_OPERAND_ITEMS
    scene = getattr(context, "scene", None)
    target_uuid = str(getattr(self, "set_uuid", "") or "")
    side = str(getattr(self, "side", "A") or "A")
    items = []
    if scene is not None:
        for index, candidate in enumerate(scene.fbp_layer_sets):
            candidate_uuid = str(candidate.set_uuid or "")
            if (
                not candidate_uuid
                or candidate_uuid == target_uuid
                or _would_create_derived_cycle(scene, target_uuid, side, candidate_uuid)
            ):
                continue
            description = (
                f"{candidate.special.title()} Layer Set · {candidate_uuid[:8]}"
                if candidate.special != 'NONE'
                else f"Layer Set · {candidate_uuid[:8]}"
            )
            items.append((candidate_uuid, candidate.name or "Layer Set", description, 'RENDERLAYERS', index))
    _LAYER_SET_OPERAND_ITEMS = tuple(items) or (("NONE", "No Compatible Layer Set", "Create another non-circular Layer Set first", 'ERROR', 0),)
    return _LAYER_SET_OPERAND_ITEMS


class FBP_OT_ChooseLayerSetOperand(_FBP_CompositorPreviewPoll, Operator):
    bl_idname = "fbp.choose_layer_set_operand"
    bl_label = "Choose UUID Set Operand"
    bl_description = "Choose another Layer Set by persistent UUID"
    bl_options = {'UNDO'}

    set_uuid: StringProperty(options={'HIDDEN', 'SKIP_SAVE'})
    side: EnumProperty(items=(('A', "A", "Left operand"), ('B', "B", "Right operand")), default='A', options={'HIDDEN', 'SKIP_SAVE'})
    candidate_uuid: EnumProperty(name="Layer Set", items=_layer_set_operand_items)
    clear: BoolProperty(default=False, options={'HIDDEN', 'SKIP_SAVE'})

    def invoke(self, context, event):
        if self.clear:
            return self.execute(context)
        return context.window_manager.invoke_search_popup(self)

    def execute(self, context):
        layer_set = _find(context.scene.fbp_layer_sets, "set_uuid", self.set_uuid)
        if layer_set is None or layer_set.special != 'DERIVED':
            return {'CANCELLED'}
        if self.clear:
            value = ""
        else:
            value = str(self.candidate_uuid or "")
            candidate = _find(context.scene.fbp_layer_sets, "set_uuid", value)
            if value == 'NONE' or candidate is None:
                return {'CANCELLED'}
            if _would_create_derived_cycle(context.scene, layer_set.set_uuid, self.side, value):
                self.report({'WARNING'}, "That operand would create a circular UUID Set dependency")
                return {'CANCELLED'}
        if self.side == 'B':
            layer_set.operand_b_uuid = value
        else:
            layer_set.operand_a_uuid = value
        fbp_sync_layer_set_nodes(context.scene)
        return {'FINISHED'}


class FBP_OT_FreezeDerivedLayerSet(_FBP_CompositorPreviewPoll, Operator):
    bl_idname = "fbp.freeze_derived_layer_set"
    bl_label = "Convert UUID Set to Manual"
    bl_description = "Keep the currently resolved UUID membership and remove live set dependencies"
    bl_options = {'UNDO'}

    set_uuid: StringProperty(options={'HIDDEN', 'SKIP_SAVE'})

    def execute(self, context):
        layer_set = _find(context.scene.fbp_layer_sets, "set_uuid", self.set_uuid)
        if layer_set is None or layer_set.special != 'DERIVED':
            return {'CANCELLED'}
        _resolve_all_set_rows(context.scene)
        for row in layer_set.rows:
            row.eye = bool(row.resolved_eye)
            row.override = 'AUTO'
            row.exclusive_excluded = False
        layer_set.special = 'NONE'
        layer_set.mode = 'MANUAL'
        layer_set.operand_a_uuid = ""
        layer_set.operand_b_uuid = ""
        fbp_sync_layer_set_nodes(context.scene)
        return {'FINISHED'}


def _remap_items(self, context):
    return [
        (record.source_uuid, record.name, record.layer_type)
        for record in context.scene.fbp_compositor_sources if record.valid
    ] or [('NONE', "No valid source", "")]


class FBP_OT_RemapLayerSetSource(_FBP_CompositorPreviewPoll, Operator):
    bl_idname = "fbp.remap_layer_set_source"
    bl_label = "Remap Missing Layer"
    bl_options = {'UNDO'}
    set_uuid: StringProperty(options={'HIDDEN'})
    source_uuid: StringProperty(options={'HIDDEN'})
    target_uuid: EnumProperty(name="New Source", items=_remap_items)
    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self)
    def execute(self, context):
        layer_set = _find(context.scene.fbp_layer_sets, "set_uuid", self.set_uuid)
        row = _find(layer_set.rows, "source_uuid", self.source_uuid) if layer_set else None
        if row is None or self.target_uuid == 'NONE': return {'CANCELLED'}
        active_uuid = identity_at(layer_set.rows, "source_uuid", layer_set.active_index)
        existing = _find(layer_set.rows, "source_uuid", self.target_uuid)
        if existing is not None and existing is not row:
            if existing.pinned or _row_socket_linked(context.scene, layer_set, existing):
                self.report({'WARNING'}, "Target source already has a pinned or linked socket")
                return {'CANCELLED'}
            existing.eye = row.eye
            existing.selected = row.selected
            existing.pinned = row.pinned
            existing.override = row.override
            existing.socket_identifier = row.socket_identifier
            source_index = next(i for i, candidate in enumerate(layer_set.rows) if candidate == row)
            layer_set.rows.remove(source_index)
            layer_set.active_index = restore_active_index(
                layer_set.rows, "source_uuid",
                self.target_uuid if active_uuid == self.source_uuid else active_uuid,
                fallback=min(source_index, len(layer_set.rows) - 1),
            )
            fbp_sync_layer_set_nodes(context.scene)
            return {'FINISHED'}
        record = _find(context.scene.fbp_compositor_sources, "source_uuid", self.target_uuid)
        row.source_uuid = self.target_uuid
        row.name = record.name
        row.missing = False
        # Socket identifier is intentionally retained so external links survive.
        fbp_sync_layer_set_nodes(context.scene)
        return {'FINISHED'}


class FBP_OT_InspectSourceDependencies(_FBP_CompositorPreviewPoll, Operator):
    bl_idname = "fbp.inspect_compositor_source_dependencies"
    bl_label = "Source Dependencies"
    bl_description = "Show where this source UUID is used without relying on its visible name"

    source_uuid: StringProperty(options={'HIDDEN', 'SKIP_SAVE'})
    details: StringProperty(options={'HIDDEN', 'SKIP_SAVE'})

    def invoke(self, context, event):
        self.details = json.dumps(
            fbp_source_dependency_usage(context.scene, self.source_uuid),
            separators=(",", ":"),
        )
        return context.window_manager.invoke_props_dialog(self, width=500)

    def draw(self, context):
        layout = self.layout
        try:
            usage = json.loads(self.details or "{}")
        except (TypeError, ValueError, json.JSONDecodeError):
            usage = {}
        sections = (
            ("source", "Source", 'RENDERLAYERS'),
            ("layer_sets", "Layer Sets", 'NODETREE'),
            ("outputs", "FBP Output", 'OUTPUT'),
            ("artist_nodes", "Connected Artist Nodes", 'NODE_COMPOSITING'),
        )
        populated = False
        for key, label, icon in sections:
            values = tuple(usage.get(key, ()) or ())
            if not values:
                continue
            populated = True
            box = layout.box()
            box.label(text=label, icon=icon)
            for value in values[:12]:
                box.label(text=str(value))
            if len(values) > 12:
                box.label(text=f"+ {len(values) - 12} more", icon='INFO')
        if not populated:
            layout.label(text="No dependencies found", icon='INFO')

    def execute(self, context):
        return {'FINISHED'}


class FBP_OT_LayerSetPreview(_FBP_CompositorPreviewPoll, Operator):
    bl_idname = "fbp.layer_set_preview"
    bl_label = "Preview Layer Set"
    bl_options = {'UNDO'}

    @classmethod
    def description(cls, context, properties):
        labels = {
            'TOT': "Preview the complete Layer Set output",
            'MASK': "Preview the combined Layer Set mask",
            'ACTIVE': "Preview the active source socket",
        }
        return labels.get(str(getattr(properties, 'output', '') or ''), cls.bl_label)
    set_uuid: StringProperty()
    output: EnumProperty(items=(('TOT', "TOT", ""), ('MASK', "MASK", ""), ('ACTIVE', "Active Layer", "")))
    def execute(self, context):
        tree = _root_tree(context.scene)
        node = next(
            (
                item for item in tuple(getattr(tree, "nodes", ()) or ())
                if _node_role_without_idprops(item) == ROLE_SET
                and _controller_uuid(item) == str(self.set_uuid or "")
            ),
            None,
        )
        layer_set = _find(context.scene.fbp_layer_sets, "set_uuid", self.set_uuid)
        if node is None or layer_set is None: return {'CANCELLED'}
        viewer = next(
            (
                item for item in tuple(getattr(tree, "nodes", ()) or ())
                if str(getattr(item, "bl_idname", "") or "") == "CompositorNodeViewer"
                and str(getattr(item, "name", "") or "") == "FBP Layer Set Viewer"
            ),
            None,
        )
        if viewer is None:
            viewer = _tag(tree.nodes.new("CompositorNodeViewer"), "set_viewer", _id())
            viewer.name = "FBP Layer Set Viewer"
        socket = node.outputs.get(self.output)
        if self.output == 'ACTIVE' and 0 <= layer_set.active_index < len(layer_set.rows):
            row = layer_set.rows[layer_set.active_index]
            socket = next((item for item in node.outputs if item.identifier == row.socket_identifier), None)
        if socket is None: return {'CANCELLED'}
        for link in tuple(viewer.inputs["Image"].links): tree.links.remove(link)
        tree.links.new(socket, viewer.inputs["Image"])
        return {'FINISHED'}


class FBP_OT_LayerSetSolo(_FBP_CompositorPreviewPoll, Operator):
    bl_idname = "fbp.layer_set_solo"
    bl_label = "Solo This Set"
    bl_description = "Temporarily send this Layer Set to the main output without changing eyes or View Layers"
    bl_options = {'UNDO'}

    set_uuid: StringProperty()

    def execute(self, context):
        scene = context.scene
        tree = _root_tree(scene)
        output = next(
            (
                node for node in tree.nodes
                if node.bl_idname == 'NodeGroupOutput' and node.is_active_output
            ),
            None,
        )
        set_node = next(
            (
                node for node in tuple(getattr(tree, "nodes", ()) or ())
                if _node_role_without_idprops(node) == ROLE_SET
                and _controller_uuid(node) == str(self.set_uuid or "")
            ),
            None,
        )
        if output is None or set_node is None or output.inputs.get('Image') is None:
            return {'CANCELLED'}

        set_output = set_node.outputs.get('TOT')
        if set_output is None:
            return {'CANCELLED'}

        image_input = output.inputs['Image']
        active_uuid = str(scene.get('_fbp_solo_set_uuid', '') or '')
        if active_uuid == self.set_uuid:
            for link in tuple(image_input.links):
                tree.links.remove(link)
            source_name = str(scene.get('_fbp_solo_source_node', '') or '')
            source_identifier = str(scene.get('_fbp_solo_source_socket', '') or '')
            source_node = tree.nodes.get(source_name)
            source_socket = (
                next(
                    (
                        socket for socket in source_node.outputs
                        if socket.identifier == source_identifier
                    ),
                    None,
                )
                if source_node else None
            )
            if source_socket is not None:
                tree.links.new(source_socket, image_input)
            for key in (
                '_fbp_solo_set_uuid',
                '_fbp_solo_source_node',
                '_fbp_solo_source_socket',
            ):
                scene.pop(key, None)
        else:
            # Switching directly from one solo set to another must keep the
            # original artist connection, not store the previous solo socket.
            if not active_uuid and image_input.is_linked:
                link = image_input.links[0]
                scene['_fbp_solo_source_node'] = link.from_node.name
                scene['_fbp_solo_source_socket'] = link.from_socket.identifier
            for link in tuple(image_input.links):
                tree.links.remove(link)
            tree.links.new(set_output, image_input)
            scene['_fbp_solo_set_uuid'] = self.set_uuid

        tree.update_tag()
        return {'FINISHED'}


class FBP_OT_OutputPassAction(_FBP_CompositorPreviewPoll, Operator):
    bl_idname = "fbp.output_pass_action"
    bl_label = "Edit FBP Output Passes"
    bl_options = {'UNDO'}

    @classmethod
    def description(cls, context, properties):
        action = str(getattr(properties, 'action', '') or '')
        return {
            'ADD': "Add a new output pass",
            'REMOVE': "Remove the active output pass",
            'MOVE_TOP': "Move the active output pass to the top",
            'MOVE_UP': "Move the active output pass up",
            'MOVE_DOWN': "Move the active output pass down",
            'MOVE_BOTTOM': "Move the active output pass to the bottom",
        }.get(action, "Edit the active output pass")
    output_uuid: StringProperty()
    action: EnumProperty(items=(('ADD', "Add", ""), ('REMOVE', "Remove", ""), ('MOVE_TOP', "Move Top", ""), ('MOVE_UP', "Move Up", ""), ('MOVE_DOWN', "Move Down", ""), ('MOVE_BOTTOM', "Move Bottom", "")))
    def execute(self, context):
        config = _find(context.scene.fbp_output_configs, "output_uuid", self.output_uuid)
        if config is None: return {'CANCELLED'}
        tree = _root_tree(context.scene)
        node = next((candidate for candidate in tree.nodes if candidate.get("fbp_uuid", "") == config.output_uuid), None)
        if self.action == 'ADD':
            item = config.passes.add()
            item.pass_uuid = _id()
            item.name = _unique_dynamic_title(
                f"Pass {len(config.passes)}",
                ['Beauty', 'Add', *[candidate.name for candidate in config.passes if candidate is not item]],
                'Pass',
            )
            item.alias = item.name
            item.subfolder = _clean(item.name, 'Pass')
            item.prefix = _clean(item.name, 'Pass')
            item.exr_pass_name = item.name
            config.active_index = len(config.passes) - 1
        elif 0 <= config.active_index < len(config.passes):
            active_index = int(config.active_index)
            active = config.passes[active_index]
            if self.action == 'REMOVE':
                socket = next((candidate for candidate in getattr(node, 'inputs', ()) if candidate.identifier == active.input_identifier), None) if node is not None else None
                if socket is not None and socket.is_linked:
                    self.report({'WARNING'}, 'Disconnect the export input before removing it')
                    return {'CANCELLED'}
                config.passes.remove(active_index)
                config.active_index = min(active_index, len(config.passes) - 1) if len(config.passes) else 0
            else:
                target = {
                    'MOVE_TOP': 0,
                    'MOVE_UP': max(0, active_index - 1),
                    'MOVE_DOWN': min(len(config.passes) - 1, active_index + 1),
                    'MOVE_BOTTOM': len(config.passes) - 1,
                }.get(self.action, active_index)
                if target == active_index:
                    return {'FINISHED'}
                config.passes.move(active_index, target)
                config.active_index = target
        else:
            return {'CANCELLED'}
        if node is not None:
            _build_output_tree(context.scene, config, node, sync_files=True)
        return {'FINISHED'}


def _node_cycle_graph(tree):
    """Build a primitive graph while tolerating a node removed mid-scan."""
    graph = {}
    try:
        nodes = tuple(getattr(tree, "nodes", ()) or ())
        links = tuple(getattr(tree, "links", ()) or ())
    except FBP_DATA_ERRORS:
        return graph
    for node in nodes:
        try:
            graph.setdefault(int(node.as_pointer()), [])
        except FBP_DATA_ERRORS:
            continue
    for link in links:
        try:
            source = int(link.from_node.as_pointer())
            target = int(link.to_node.as_pointer())
        except FBP_DATA_ERRORS:
            continue
        graph.setdefault(source, []).append(target)
        graph.setdefault(target, [])
    return {node: tuple(sorted(targets)) for node, targets in graph.items()}


def _append_path_issues(errors, warnings, label, value, *, required=False):
    components = split_path_components(value)
    if required and not components:
        errors.append(f"Empty {label}")
        return
    for component in components:
        issues = path_component_issues(component)
        if "reserved-name" in issues:
            errors.append(f"Reserved system name in {label}: {component}")
        elif issues:
            warnings.append(f"Unsafe path component in {label}: {component}")


def _active_group_output(tree):
    try:
        nodes = tuple(getattr(tree, "nodes", ()) or ())
    except FBP_DATA_ERRORS:
        return None
    for node in nodes:
        try:
            if (
                node.bl_idname == 'NodeGroupOutput'
                and node.is_active_output
                and node.inputs.get("Image") is not None
            ):
                return node
        except FBP_DATA_ERRORS:
            continue
    return None


def _upstream_contains_role(input_socket, role):
    pending = [link.from_node for link in tuple(input_socket.links)]
    visited = set()
    while pending and len(visited) < 256:
        node = pending.pop()
        pointer = int(node.as_pointer())
        if pointer in visited:
            continue
        visited.add(pointer)
        if _node_role_without_idprops(node) == role:
            return True
        for candidate in node.inputs:
            pending.extend(link.from_node for link in tuple(candidate.links))
    return False


def _remove_duplicate_state_items(collection, identity_attr):
    """Remove only empty/duplicate persistent state rows after node sync."""
    seen = set()
    remove = []
    for index, item in enumerate(collection):
        value = str(getattr(item, identity_attr, "") or "")
        if not value or value in seen:
            remove.append(index)
        else:
            seen.add(value)
    for index in reversed(remove):
        collection.remove(index)
    return len(remove)


def fbp_compositor_artist_node_snapshot(scene):
    """Return primitive identities for user-authored root compositor nodes.

    The snapshot excludes all managed Frame By Plane nodes and contains no RNA
    wrappers, so it is safe to compare across sync, repair and Undo boundaries.
    """
    tree = getattr(scene, "compositing_node_group", None) if scene is not None else None
    if tree is None:
        return ()
    records = []
    try:
        nodes = tuple(getattr(tree, "nodes", ()) or ())
    except FBP_DATA_ERRORS:
        return ()
    for node in nodes:
        try:
            if bool(node.get("fbp_owned", False)) or _node_role_without_idprops(node):
                continue
            records.append((
                str(getattr(node, "name", "") or ""),
                str(getattr(node, "bl_idname", "") or ""),
                int(node.as_pointer()),
            ))
        except FBP_DATA_ERRORS:
            continue
    return tuple(sorted(records))


def _fbp_snapshot_error(errors, path, reason):
    if errors is None:
        return
    try:
        errors.append(f"{str(path or 'snapshot')}:{str(reason or 'unreadable')}")
    except (AttributeError, RuntimeError, TypeError, ValueError):
        pass


def _fbp_compositor_socket_snapshot(node, socket, *, is_output, errors=None, path="socket"):
    """Return a stable primitive socket identity for graph preservation checks.

    Snapshot failures are reported to the caller so Safe Repair can fail closed
    instead of silently comparing an incomplete artist graph.
    """
    try:
        sockets = tuple(getattr(node, "outputs" if is_output else "inputs", ()) or ())
        index = next((i for i, candidate in enumerate(sockets) if candidate == socket), -1)
    except FBP_DATA_IO_ERRORS as exc:
        _fbp_snapshot_error(errors, path, f"collection:{type(exc).__name__}")
        index = -1
    try:
        identifier = str(getattr(socket, "identifier", "") or "")
        name = str(getattr(socket, "name", "") or "")
    except FBP_DATA_IO_ERRORS as exc:
        _fbp_snapshot_error(errors, path, f"identity:{type(exc).__name__}")
        identifier = name = ""
    if index < 0:
        _fbp_snapshot_error(errors, path, "index-missing")
    return ("OUT" if is_output else "IN", identifier, name, int(index))


_FBP_SNAPSHOT_UNSUPPORTED = object()
_FBP_NODE_SNAPSHOT_SKIP = frozenset({
    "rna_type", "name", "label", "location", "width", "height", "dimensions",
    "select", "parent", "inputs", "outputs", "internal_links", "color",
    "use_custom_color", "mute", "hide", "show_options", "show_preview",
    "show_texture", "bl_idname", "bl_label", "bl_description", "type",
})


def _fbp_snapshot_primitive(value, *, max_items=64):
    """Convert a short-lived RNA value into deterministic primitive data."""
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        if math.isnan(value):
            return ("FLOAT", "NAN")
        if math.isinf(value):
            return ("FLOAT", "INF" if value > 0.0 else "-INF")
        return float(value)
    if isinstance(value, set):
        converted = [_fbp_snapshot_primitive(item, max_items=max_items) for item in value]
        if any(item is _FBP_SNAPSHOT_UNSUPPORTED for item in converted):
            return _FBP_SNAPSHOT_UNSUPPORTED
        return tuple(sorted(converted, key=repr))
    if hasattr(value, "to_list"):
        try:
            value = value.to_list()
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            return _FBP_SNAPSHOT_UNSUPPORTED
    elif hasattr(value, "to_tuple"):
        try:
            value = value.to_tuple()
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            return _FBP_SNAPSHOT_UNSUPPORTED
    if isinstance(value, (tuple, list)):
        if len(value) > max(0, int(max_items)):
            return ("TRUNCATED", len(value))
        converted = tuple(_fbp_snapshot_primitive(item, max_items=max_items) for item in value)
        if any(item is _FBP_SNAPSHOT_UNSUPPORTED for item in converted):
            return _FBP_SNAPSHOT_UNSUPPORTED
        return converted
    return _FBP_SNAPSHOT_UNSUPPORTED


def _fbp_compositor_node_property_snapshot(node, *, errors=None, path="node"):
    """Capture editable scalar/enum node settings and artist custom properties.

    Every failed read is surfaced through ``errors``. Safe Repair uses this to
    reject an incomplete snapshot before mutating the compositor.
    """
    records = []
    try:
        properties = tuple(getattr(getattr(node, "bl_rna", None), "properties", ()) or ())
    except FBP_DATA_IO_ERRORS as exc:
        _fbp_snapshot_error(errors, path, f"rna-properties:{type(exc).__name__}")
        properties = ()
    for index, prop in enumerate(properties):
        identifier = f"property[{index}]"
        try:
            identifier = str(getattr(prop, "identifier", "") or "")
            prop_type = str(getattr(prop, "type", "") or "")
            if (
                not identifier
                or identifier in _FBP_NODE_SNAPSHOT_SKIP
                or bool(getattr(prop, "is_readonly", False))
                or prop_type not in {"BOOLEAN", "INT", "FLOAT", "STRING", "ENUM"}
            ):
                continue
            value = _fbp_snapshot_primitive(getattr(node, identifier))
            if value is _FBP_SNAPSHOT_UNSUPPORTED:
                _fbp_snapshot_error(errors, path, f"property-unsupported:{identifier}")
            else:
                records.append((identifier, value))
        except FBP_DATA_IO_ERRORS as exc:
            _fbp_snapshot_error(errors, path, f"property:{identifier}:{type(exc).__name__}")
    custom = []
    try:
        keys = tuple(node.keys())
    except FBP_DATA_IO_ERRORS as exc:
        _fbp_snapshot_error(errors, path, f"custom-keys:{type(exc).__name__}")
        keys = ()
    for index, key in enumerate(keys):
        key_text = str(key)
        try:
            value = _fbp_snapshot_primitive(node[key])
            if value is _FBP_SNAPSHOT_UNSUPPORTED:
                _fbp_snapshot_error(errors, path, f"custom-unsupported:{key_text}")
            else:
                custom.append((key_text, value))
        except FBP_DATA_IO_ERRORS as exc:
            _fbp_snapshot_error(errors, path, f"custom:{index}:{key_text}:{type(exc).__name__}")
    return (tuple(sorted(records, key=repr)), tuple(sorted(custom, key=repr)))


def _fbp_compositor_node_socket_values(node, *, errors=None, path="node"):
    records = []
    for is_output, attr in ((False, "inputs"), (True, "outputs")):
        try:
            sockets = tuple(getattr(node, attr, ()) or ())
        except FBP_DATA_IO_ERRORS as exc:
            _fbp_snapshot_error(errors, path, f"{attr}:{type(exc).__name__}")
            sockets = ()
        for index, socket in enumerate(sockets):
            socket_path = f"{path}.{attr}[{index}]"
            try:
                if not hasattr(socket, "default_value"):
                    continue
                value = _fbp_snapshot_primitive(socket.default_value)
                if value is _FBP_SNAPSHOT_UNSUPPORTED:
                    _fbp_snapshot_error(errors, socket_path, "default-unsupported")
                    continue
                records.append((
                    "OUT" if is_output else "IN",
                    str(getattr(socket, "identifier", "") or ""),
                    str(getattr(socket, "name", "") or ""),
                    int(index),
                    value,
                ))
            except FBP_DATA_IO_ERRORS as exc:
                _fbp_snapshot_error(errors, socket_path, type(exc).__name__)
    return tuple(records)


def _fbp_compositor_group_tree_snapshot(
    tree,
    *,
    _visited=None,
    _depth=0,
    _errors=None,
    _path="group",
    max_nodes=512,
    max_links=2048,
):
    """Capture artist group internals without retaining NodeTree RNA wrappers.

    Nested failures and safety limits propagate to the root snapshot through
    ``_errors``. A Safe Repair operation therefore never treats a partial group
    snapshot as complete.
    """
    if tree is None:
        return ()
    if _visited is None:
        _visited = set()
    if _errors is None:
        _errors = []
    try:
        pointer = int(tree.as_pointer())
        name = str(getattr(tree, "name", "") or "")
    except FBP_DATA_IO_ERRORS as exc:
        _fbp_snapshot_error(_errors, _path, f"identity:{type(exc).__name__}")
        return (("INVALID",), ())
    tree_path = f"{_path}[{name or pointer}]"
    if pointer in _visited:
        return (("CYCLE", name), ())
    if _depth >= 4:
        _fbp_snapshot_error(_errors, tree_path, "depth-limit")
        return (("DEPTH_LIMIT", name), ())
    visited = set(_visited)
    visited.add(pointer)
    try:
        nodes = tuple(getattr(tree, "nodes", ()) or ())
        links = tuple(getattr(tree, "links", ()) or ())
    except FBP_DATA_IO_ERRORS as exc:
        _fbp_snapshot_error(_errors, tree_path, f"tree:{type(exc).__name__}")
        return (("UNREADABLE", name), ())
    if len(nodes) > int(max_nodes):
        _fbp_snapshot_error(_errors, tree_path, f"node-limit:{len(nodes)}")
        return (("NODE_LIMIT", name, len(nodes)), ())
    if len(links) > int(max_links):
        _fbp_snapshot_error(_errors, tree_path, f"link-limit:{len(links)}")
        return (("LINK_LIMIT", name, len(links)), ())
    node_records = []
    identity_by_pointer = {}
    for index, node in enumerate(nodes):
        node_path = f"{tree_path}.node[{index}]"
        try:
            identity = (str(getattr(node, "name", "") or ""), str(getattr(node, "bl_idname", "") or ""))
            identity_by_pointer[int(node.as_pointer())] = identity
            location = tuple(float(value) for value in getattr(node, "location", (0.0, 0.0)))
            nested_tree = getattr(node, "node_tree", None)
            nested = _fbp_compositor_group_tree_snapshot(
                nested_tree,
                _visited=visited,
                _depth=_depth + 1,
                _errors=_errors,
                _path=f"{node_path}.node_tree",
                max_nodes=max_nodes,
                max_links=max_links,
            ) if nested_tree is not None else ()
            node_records.append(identity + (
                str(getattr(node, "label", "") or ""),
                bool(getattr(node, "mute", False)),
                bool(getattr(node, "hide", False)),
                location,
                float(getattr(node, "width", 0.0) or 0.0),
                _fbp_compositor_node_property_snapshot(node, errors=_errors, path=node_path),
                _fbp_compositor_node_socket_values(node, errors=_errors, path=node_path),
                nested,
            ))
        except FBP_DATA_IO_ERRORS as exc:
            _fbp_snapshot_error(_errors, node_path, type(exc).__name__)
    link_records = []
    for index, link in enumerate(links):
        link_path = f"{tree_path}.link[{index}]"
        try:
            from_node = link.from_node
            to_node = link.to_node
            link_records.append((
                identity_by_pointer.get(int(from_node.as_pointer()), ("", "")),
                _fbp_compositor_socket_snapshot(
                    from_node, link.from_socket, is_output=True,
                    errors=_errors, path=f"{link_path}.from",
                ),
                identity_by_pointer.get(int(to_node.as_pointer()), ("", "")),
                _fbp_compositor_socket_snapshot(
                    to_node, link.to_socket, is_output=False,
                    errors=_errors, path=f"{link_path}.to",
                ),
            ))
        except FBP_DATA_IO_ERRORS as exc:
            _fbp_snapshot_error(_errors, link_path, type(exc).__name__)
    return (
        tuple(sorted(node_records, key=repr)),
        tuple(sorted(link_records, key=repr)),
    )


def _fbp_compositor_artist_group_snapshot(node, *, errors=None, path="node"):
    try:
        tree = getattr(node, "node_tree", None)
    except FBP_DATA_IO_ERRORS as exc:
        _fbp_snapshot_error(errors, path, f"node-tree:{type(exc).__name__}")
        tree = None
    return _fbp_compositor_group_tree_snapshot(
        tree, _errors=errors, _path=f"{path}.node_tree"
    ) if tree is not None else ()


def fbp_compositor_artist_graph_snapshot(scene, *, max_nodes=2048, max_links=8192):
    """Snapshot artist nodes and links using primitives, failing closed.

    Safe Repair must not continue when Blender data becomes unreadable or when a
    pathological graph exceeds the bounded snapshot contract.  ``complete`` is
    therefore part of the result rather than silently omitting failed records.
    """
    tree = getattr(scene, "compositing_node_group", None) if scene is not None else None
    if tree is None:
        return {"nodes": (), "links": (), "complete": True, "errors": ()}
    errors = []
    try:
        nodes = tuple(getattr(tree, "nodes", ()) or ())
        links = tuple(getattr(tree, "links", ()) or ())
    except FBP_DATA_IO_ERRORS as exc:
        return {"nodes": (), "links": (), "complete": False, "errors": (f"root:{type(exc).__name__}",)}
    if len(nodes) > int(max_nodes):
        errors.append(f"node-limit:{len(nodes)}")
    if len(links) > int(max_links):
        errors.append(f"link-limit:{len(links)}")
    if errors:
        return {"nodes": (), "links": (), "complete": False, "errors": tuple(errors)}

    artist_by_pointer = {}
    node_records = []
    for index, node in enumerate(nodes):
        try:
            if bool(node.get("fbp_owned", False)) or _node_role_without_idprops(node):
                continue
            pointer = int(node.as_pointer())
            identity = (str(getattr(node, "name", "") or ""), str(getattr(node, "bl_idname", "") or ""), pointer)
            parent = getattr(node, "parent", None)
            parent_identity = (
                str(getattr(parent, "name", "") or ""),
                str(getattr(parent, "bl_idname", "") or ""),
                int(parent.as_pointer()),
            ) if parent is not None else ("", "", 0)
            location = tuple(float(value) for value in getattr(node, "location", (0.0, 0.0)))
            color = tuple(float(value) for value in getattr(node, "color", (0.0, 0.0, 0.0)))
            record = identity + (
                str(getattr(node, "label", "") or ""), bool(getattr(node, "mute", False)),
                bool(getattr(node, "hide", False)), location, float(getattr(node, "width", 0.0) or 0.0),
                bool(getattr(node, "use_custom_color", False)), color, parent_identity,
                _fbp_compositor_node_property_snapshot(
                    node, errors=errors, path=f"root.node[{index}]"
                ),
                _fbp_compositor_node_socket_values(
                    node, errors=errors, path=f"root.node[{index}]"
                ),
                _fbp_compositor_artist_group_snapshot(
                    node, errors=errors, path=f"root.node[{index}]"
                ),
            )
            artist_by_pointer[pointer] = identity
            node_records.append(record)
        except FBP_DATA_IO_ERRORS as exc:
            errors.append(f"node:{index}:{type(exc).__name__}")

    def endpoint(node, path):
        try:
            pointer = int(node.as_pointer())
        except FBP_DATA_IO_ERRORS as exc:
            _fbp_snapshot_error(errors, path, f"pointer:{type(exc).__name__}")
            pointer = 0
        artist = artist_by_pointer.get(pointer)
        if artist is not None:
            return ("ARTIST",) + artist
        try:
            return (
                "FBP", str(_node_role_without_idprops(node) or ""),
                str(node.get("fbp_uuid", "") or ""), str(getattr(node, "name", "") or ""),
                str(getattr(node, "bl_idname", "") or ""),
            )
        except FBP_DATA_IO_ERRORS as exc:
            _fbp_snapshot_error(errors, path, f"identity:{type(exc).__name__}")
            return ("UNKNOWN", "", "", "", "")

    link_records = []
    for index, link in enumerate(links):
        try:
            from_node = link.from_node
            to_node = link.to_node
            from_pointer = int(from_node.as_pointer())
            to_pointer = int(to_node.as_pointer())
            if from_pointer not in artist_by_pointer and to_pointer not in artist_by_pointer:
                continue
            link_records.append((
                endpoint(from_node, f"root.link[{index}].from_node"),
                _fbp_compositor_socket_snapshot(
                    from_node, link.from_socket, is_output=True,
                    errors=errors, path=f"root.link[{index}].from",
                ),
                endpoint(to_node, f"root.link[{index}].to_node"),
                _fbp_compositor_socket_snapshot(
                    to_node, link.to_socket, is_output=False,
                    errors=errors, path=f"root.link[{index}].to",
                ),
            ))
        except FBP_DATA_IO_ERRORS as exc:
            errors.append(f"link:{index}:{type(exc).__name__}")
    return {
        "nodes": tuple(sorted(node_records)),
        "links": tuple(sorted(link_records, key=repr)),
        "complete": not errors,
        "errors": tuple(errors),
    }


def fbp_validate_composite(scene):
    errors, warnings, info = [], [], []
    sources = list(scene.fbp_compositor_sources)
    ids = [item.source_uuid for item in sources]
    if any(not value for value in ids):
        errors.append("Missing source UUID")
    if len(ids) != len(set(ids)):
        errors.append("Duplicate source UUID")

    set_ids = [item.set_uuid for item in scene.fbp_layer_sets]
    if any(not value for value in set_ids):
        errors.append("Missing Layer Set UUID")
    if len(set_ids) != len(set(set_ids)):
        errors.append("Duplicate Layer Set UUID")

    output_ids = [item.output_uuid for item in scene.fbp_output_configs]
    if any(not value for value in output_ids):
        errors.append("Missing FBP Output UUID")
    if len(output_ids) != len(set(output_ids)):
        errors.append("Duplicate FBP Output UUID")

    stack_ids = [item.stack_uuid for item in getattr(scene, 'fbp_over_stacks', ())]
    if any(not value for value in stack_ids):
        errors.append("Missing Composite Stack UUID")
    if len(stack_ids) != len(set(stack_ids)):
        errors.append("Duplicate Composite Stack UUID")

    pass_ids = [item.pass_uuid for config in scene.fbp_output_configs for item in config.passes]
    if any(not value for value in pass_ids):
        errors.append("Missing FBP Output pass UUID")
    if len(pass_ids) != len(set(pass_ids)):
        errors.append("Duplicate FBP Output pass UUID")

    _resolve_all_set_rows(scene)
    derived_graph = _derived_set_graph(scene)
    derived_cycles = directed_cycles(derived_graph)
    if derived_cycles:
        errors.append(f"Circular UUID Set dependency ({len(derived_cycles)})")
    known_set_ids = set(set_ids)
    for layer_set in scene.fbp_layer_sets:
        if layer_set.special != 'DERIVED':
            continue
        operands = (str(layer_set.operand_a_uuid or ""), str(layer_set.operand_b_uuid or ""))
        if not operands[0] or not operands[1]:
            warnings.append(f"UUID Set has an unset operand: {layer_set.name}")
        for side, operand_uuid in zip(('A', 'B'), operands, strict=False):
            if operand_uuid and operand_uuid not in known_set_ids:
                errors.append(f"Missing UUID Set operand {side}: {layer_set.name}")
            if operand_uuid == layer_set.set_uuid:
                errors.append(f"UUID Set references itself: {layer_set.name}")
        if operands[0] and operands[0] == operands[1]:
            warnings.append(f"UUID Set uses the same operand twice: {layer_set.name}")

    if any(not item.valid for item in sources):
        warnings.append("Missing sources")
    if any(row.missing for layer_set in scene.fbp_layer_sets for row in layer_set.rows):
        warnings.append("Layer Sets contain missing source rows")
    if any(not any(row.resolved_eye for row in layer_set.rows) for layer_set in scene.fbp_layer_sets):
        warnings.append("Empty Layer Set")
    if any(
        layer_set.membership_mode == 'EXCLUSIVE' and not str(layer_set.exclusive_group or "").strip()
        for layer_set in scene.fbp_layer_sets
    ):
        warnings.append("One Set Only is enabled without an Exclusive Group")
    if any(
        layer_set.rule_depth_enabled
        and not any(record.valid and record.depth_valid for record in sources)
        for layer_set in scene.fbp_layer_sets
    ):
        warnings.append("Depth rules have no camera-space source depth")

    root = _output_root(scene)
    existing_parent = nearest_existing_parent(root)
    if not existing_parent or not os.access(existing_parent, os.W_OK):
        errors.append("Output path is not writable")

    tree = scene.compositing_node_group
    set_nodes = [node for node in (tree.nodes if tree else ()) if _node_role_without_idprops(node) == ROLE_SET]
    output_nodes = [node for node in (tree.nodes if tree else ()) if _node_role_without_idprops(node) == ROLE_OUTPUT]
    stack_nodes = [node for node in (tree.nodes if tree else ()) if _node_role_without_idprops(node) == ROLE_STACK]

    if tree is not None:
        cycles = directed_cycles(_node_cycle_graph(tree))
        if cycles:
            errors.append(f"Circular compositor dependency ({len(cycles)})")
        for node in tree.nodes:
            safe_role = _node_role_without_idprops(node)
            try:
                node_name = str(getattr(node, "name", "") or "")
                node_type = str(getattr(node, "bl_idname", "") or "")
            except FBP_DATA_ERRORS:
                continue
            technical_candidate = bool(
                safe_role
                or node_name.startswith("FBP ")
                or node_type in _FBP_NODE_ROLE_BY_IDNAME
            )
            if not technical_candidate:
                continue
            try:
                if not bool(node.get("fbp_owned", False)):
                    continue
                role = safe_role or str(node.get("fbp_role", "") or "")
                persistent_id = str(node.get("fbp_uuid", "") or "")
            except FBP_DATA_ERRORS:
                warnings.append(f"Technical node metadata is temporarily unavailable: {node_name}")
                continue
            if not role:
                warnings.append(f"Owned technical node has no role: {node_name}")
            if role not in {"legacy_source_frame", "set_viewer"} and not persistent_id:
                warnings.append(f"Owned technical node has no UUID: {node_name}")

        source_node = next(
            (node for node in tree.nodes if _node_role_without_idprops(node) in {"layers_package", "legacy_sources"}),
            None,
        )
        if any(source.valid for source in sources) and source_node is None:
            errors.append("FBP Layers node is missing")
        elif source_node is not None:
            if source_node.bl_idname != 'CompositorNodeGroup' or source_node.node_tree is None:
                errors.append(f"FBP Layers is not a standard {primary_shortcut_label('G')} node group")
            elif not bool(source_node.get('fbp_native_ctrl_g', False)):
                warnings.append(f"FBP Layers needs native {primary_shortcut_label('G')} conversion")
            elif not any(
                node.bl_idname == 'CompositorNodeRLayers'
                for node in source_node.node_tree.nodes
            ):
                errors.append("FBP Layers contains no Render Layers nodes")
            for source in sources:
                if source.valid and source.output_socket_name and source_node.outputs.get(source.output_socket_name) is None:
                    errors.append(f"Technical source socket is missing: {source.name}")

        root_render_layers = [
            node for node in tree.nodes
            if node.bl_idname == 'CompositorNodeRLayers' and str(getattr(node, 'name', '') or '').startswith('FBP ') and bool(node.get('fbp_owned', False))
        ]
        if root_render_layers:
            errors.append(f"FBP Render Layers remain in the root compositor ({len(root_render_layers)})")
        root_technical_frames = [
            node for node in tree.nodes
            if node.bl_idname == 'NodeFrame'
            and (
                _node_role_without_idprops(node) in {'legacy_source_frame', 'native_group_collector'}
                or node.name in {'FBP Internal Sources', 'FBP Technical Sources'}
            )
        ]
        if root_technical_frames:
            errors.append(f"FBP technical frames remain in the root compositor ({len(root_technical_frames)})")
        root_alpha_overs = [
            node for node in tree.nodes
            if node.bl_idname == 'CompositorNodeAlphaOver' and str(getattr(node, 'name', '') or '').startswith('FBP ') and bool(node.get('fbp_owned', False))
        ]
        if root_alpha_overs:
            errors.append(f"FBP Alpha Over nodes remain in the root compositor ({len(root_alpha_overs)})")

        default_exports = [node for node in output_nodes if bool(node.get('fbp_default_pipeline', False))]
        effects_nodes = [node for node in tree.nodes if _node_role_without_idprops(node) == 'effects_stage']
        layer_nodes = [node for node in tree.nodes if _node_role_without_idprops(node) in {'layers_package', 'legacy_sources'}]
        group_outputs = [
            node for node in tree.nodes
            if node.bl_idname == 'NodeGroupOutput' and bool(node.is_active_output)
        ]
        if bool(getattr(scene, 'fbp_compositor_enabled', False)):
            if len(layer_nodes) != 1:
                errors.append("Layers package is missing or duplicated")
            if len(effects_nodes) != 1:
                errors.append("Effects / Masks stage is missing or duplicated")
            if len(default_exports) != 1:
                errors.append("Export controller is missing or duplicated")
            if len(group_outputs) != 1 or group_outputs[0].inputs.get('Image') is None:
                errors.append("Group Output is missing or invalid")
            if len(layer_nodes) == len(effects_nodes) == len(default_exports) == len(group_outputs) == 1:
                layers_node = layer_nodes[0]
                effects_node = effects_nodes[0]
                export_node = default_exports[0]
                total_output = layers_node.outputs.get('TOT')
                mask_output = layers_node.outputs.get('MASK')
                effects_input = effects_node.inputs.get('Image')
                effects_mask = effects_node.inputs.get('Mask')
                beauty_input = export_node.inputs.get('Beauty')
                export_image = export_node.outputs.get('Image')
                group_input = group_outputs[0].inputs.get('Image')
                if total_output is None or mask_output is None:
                    errors.append("Layers package is missing TOT or MASK")
                if (
                    total_output is not None
                    and (
                        effects_input is None
                        or not effects_input.is_linked
                        or effects_input.links[0].from_socket != total_output
                    )
                ):
                    errors.append("TOT is not connected to Effects / Masks")
                if (
                    mask_output is not None
                    and (
                        effects_mask is None
                        or not effects_mask.is_linked
                        or effects_mask.links[0].from_socket != mask_output
                    )
                ):
                    errors.append("MASK is not connected to Effects / Masks")
                if beauty_input is None or not beauty_input.is_linked or beauty_input.links[0].from_node != effects_node:
                    errors.append("Effects to Export chain is disconnected")
                if (
                    export_image is None
                    or group_input is None
                    or not group_input.is_linked
                    or group_input.links[0].from_socket != export_image
                ):
                    errors.append("Export to Group Output chain is disconnected")

    for layer_set in scene.fbp_layer_sets:
        node = next((candidate for candidate in set_nodes if candidate.get("fbp_uuid", "") == layer_set.set_uuid), None)
        if node is None:
            errors.append(f"Missing Layer Set node: {layer_set.name}")
            continue
        if node.outputs.get("TOT") is None or node.outputs.get("MASK") is None:
            errors.append(f"Invalid fixed sockets: {layer_set.name}")
        identifiers = [socket.identifier for socket in node.outputs]
        if len(identifiers) != len(set(identifiers)):
            errors.append(f"Duplicate Layer Set socket identifiers: {layer_set.name}")

    for config in getattr(scene, 'fbp_over_stacks', ()):
        node = next((candidate for candidate in stack_nodes if str(candidate.get('fbp_uuid', '') or '') == str(config.stack_uuid or '')), None)
        if node is None:
            warnings.append(f"Orphan Composite Stack state: {config.name}")
            continue
        if node.outputs.get('Image') is None or node.outputs.get('Mask') is None:
            errors.append(f"Invalid Composite Stack outputs: {config.name}")
        identifiers = [str(row.input_identifier or '') for row in config.rows if str(row.input_identifier or '')]
        if len(identifiers) != len(set(identifiers)):
            errors.append(f"Duplicate Composite Stack input identifiers: {config.name}")
        if any(row.missing for row in config.rows):
            warnings.append(f"Composite Stack contains missing rows: {config.name}")
        placeholders = [row for row in config.rows if bool(getattr(row, 'is_placeholder', False))]
        if len(placeholders) != 1 or not bool(getattr(config.rows[-1], 'is_placeholder', False)):
            errors.append(f"Composite Stack Add input is missing or not last: {config.name}")
        if config.auto_expand and config.rows:
            last_socket = _stack_input_socket(node, config.rows[-1])
            if last_socket is not None and last_socket.is_linked:
                warnings.append(f"Composite Stack needs a trailing Add sync: {config.name}")

    node_set_ids = {str(node.get("fbp_uuid", "") or "") for node in set_nodes}
    node_output_ids = {str(node.get("fbp_uuid", "") or "") for node in output_nodes}
    if any(identifier not in set_ids for identifier in node_set_ids):
        warnings.append("Orphan Layer Set node state")
    if any(identifier not in output_ids for identifier in node_output_ids):
        warnings.append("Orphan FBP Output node state")

    for config in scene.fbp_output_configs:
        enabled = [item for item in config.passes if item.enabled]
        is_default_export = any(
            str(node.get('fbp_uuid', '') or '') == str(config.output_uuid or '')
            and bool(node.get('fbp_default_pipeline', False))
            for node in output_nodes
        )
        if not enabled and not config.save_beauty and not is_default_export:
            warnings.append(f"No active FBP Output pass: {config.name}")
        names = [str(item.alias or item.name or "").strip().casefold() for item in enabled]
        if any(not name for name in names):
            errors.append(f"Empty output name in {config.name}")
        if len(names) != len(set(names)):
            errors.append(f"Duplicate output name in {config.name}")
        destinations = [
            normalized_destination(item.subfolder, item.prefix or item.alias or item.name)
            for item in enabled
        ]
        if len(destinations) != len(set(destinations)):
            errors.append(f"Duplicate output destination in {config.name}")

        exr_names = [str(item.exr_pass_name or item.alias or item.name or "").strip().casefold() for item in enabled]
        if config.mode == 'MULTILAYER' and len(exr_names) != len(set(exr_names)):
            errors.append(f"Duplicate EXR pass name in {config.name}")
        if config.mode == 'MULTILAYER' and any(item.format_override for item in enabled):
            warnings.append(f"Per-pass format overrides are ignored by multilayer EXR: {config.name}")

        _append_path_issues(errors, warnings, f"output name in {config.name}", config.name, required=True)
        for item in enabled:
            _append_path_issues(errors, warnings, f"subfolder for {item.name}", item.subfolder)
            _append_path_issues(errors, warnings, f"filename for {item.name}", item.prefix or item.alias or item.name, required=True)
            if item.format_override and config.mode == 'SEPARATE':
                format_issues = output_format_issues(item.file_format, item.color_depth, item.color_mode)
                if format_issues:
                    errors.append(f"Incompatible format settings: {config.name} · {item.name}")

        node = next((candidate for candidate in output_nodes if candidate.get("fbp_uuid", "") == config.output_uuid), None)
        if node is None:
            errors.append(f"Missing FBP Output node: {config.name}")
            continue
        beauty = next((socket for socket in node.inputs if socket.identifier == config.beauty_identifier), None)
        if config.save_beauty and (beauty is None or not beauty.is_linked):
            warnings.append(f"Beauty is enabled but not linked: {config.name}")
        add_socket = _output_add_socket(node, config)
        if add_socket is None:
            errors.append(f"Export Add input is missing: {config.name}")
        elif node.inputs[-1] != add_socket:
            errors.append(f"Export Add input is not last: {config.name}")
        elif config.auto_expand and add_socket.is_linked:
            warnings.append(f"Export needs a trailing Add sync: {config.name}")
        identifiers = [str(item.input_identifier or '') for item in config.passes if str(item.input_identifier or '')]
        if len(identifiers) != len(set(identifiers)):
            errors.append(f"Duplicate Export input identifiers: {config.name}")
        for item in config.passes:
            socket = next((candidate for candidate in node.inputs if candidate.identifier == item.input_identifier), None)
            if item.enabled and (socket is None or not socket.is_linked):
                warnings.append(f"Enabled output is not linked: {item.name}")

    if tree is None:
        errors.append("No compositor node tree")
    else:
        group_output = _active_group_output(tree)
        if group_output is None or not group_output.inputs["Image"].is_linked:
            if output_nodes:
                errors.append("Beauty is not connected to the main Group Output")
            else:
                warnings.append("Main composite Image output is not linked")
        elif output_nodes and not _upstream_contains_role(group_output.inputs["Image"], ROLE_OUTPUT):
            warnings.append("Main Beauty chain bypasses FBP Output")

    if not scene.fbp_layer_sets:
        info.append("No Layer Set nodes")
    if not scene.fbp_output_configs:
        info.append("No FBP Output nodes")
    scene.fbp_composite_validation = (
        "Ready to Render" if not errors and not warnings
        else f"{len(errors)} Errors · {len(warnings)} Warnings"
    )
    scene.fbp_composite_validation_details = "\n".join(
        [
            *(f"ERROR: {item}" for item in errors),
            *(f"WARNING: {item}" for item in warnings),
            *(f"INFO: {item}" for item in info),
        ]
    )
    return errors, warnings, info


class FBP_OT_ValidateComposite(_FBP_CompositorPreviewPoll, Operator):
    bl_idname = "fbp.validate_composite"
    bl_label = "Validate Composite"

    def execute(self, context):
        try:
            errors, warnings, _ = fbp_validate_composite(context.scene)
        except FBP_DATA_IO_ERRORS as exc:
            _set_compositor_runtime_status(
                context.scene,
                "Composite validation failed safely · no nodes were changed",
            )
            fbp_warn("Composite validation failed safely", exc)
            self.report({'ERROR'}, "Validation stopped safely; use Safe Repair after saving")
            return {'CANCELLED'}
        self.report(
            {'ERROR'} if errors else {'WARNING'} if warnings else {'INFO'},
            context.scene.fbp_composite_validation,
        )
        return {'FINISHED'}


class _FBPCompositorSafeRepairRollback(RuntimeError):
    pass


def _fbp_clone_safe_repair_artist_groups(root, *, collector=None, max_groups=128, max_depth=8):
    """Deep-copy artist group trees referenced by a rollback root.

    ``NodeTree.copy()`` keeps nested group references shared. A Safe Repair
    rollback would therefore be unable to restore an accidental edit inside an
    artist group. Clone those trees recursively while preserving shared-group
    identity inside the backup graph.
    """
    if root is None:
        return ()
    clones = collector if collector is not None else []
    by_pointer = {}

    def clone_tree(original, depth):
        if original is None:
            return None
        try:
            pointer = int(original.as_pointer())
        except FBP_DATA_ERRORS as exc:
            raise RuntimeError("Artist group tree became unavailable during rollback backup") from exc
        existing = by_pointer.get(pointer)
        if existing is not None:
            return existing
        if depth > int(max_depth) or len(clones) >= int(max_groups):
            raise RuntimeError("Artist compositor group backup exceeded the safe recursion limit")
        duplicate = original.copy()
        duplicate.name = f"{getattr(original, 'name', 'Artist Group')} — Safe Repair Backup"
        duplicate["fbp_safe_repair_nested_backup"] = True
        by_pointer[pointer] = duplicate
        clones.append(duplicate)
        for node in tuple(getattr(duplicate, "nodes", ()) or ()):
            try:
                nested = getattr(node, "node_tree", None)
                if nested is not None:
                    node.node_tree = clone_tree(nested, depth + 1)
            except FBP_DATA_ERRORS as exc:
                raise RuntimeError("Could not clone a nested artist compositor group") from exc
        return duplicate

    for node in tuple(getattr(root, "nodes", ()) or ()):
        try:
            if bool(node.get("fbp_owned", False)) or _node_role_without_idprops(node):
                continue
            nested = getattr(node, "node_tree", None)
            if nested is not None:
                node.node_tree = clone_tree(nested, 1)
        except FBP_DATA_ERRORS as exc:
            raise RuntimeError("Could not inspect artist compositor groups for rollback") from exc
    return tuple(clones)


def _fbp_remove_orphan_safe_repair_groups(groups):
    pending = [group for group in tuple(groups or ()) if group is not None]
    removed = 0
    # Parent backups may own child backups. Repeated passes remove parents first
    # and then any children whose user count dropped to zero.
    for _pass in range(len(pending) + 1):
        changed = False
        for group in tuple(pending):
            try:
                if int(getattr(group, "users", 0) or 0) != 0:
                    continue
                bpy.data.node_groups.remove(group)
                pending.remove(group)
                removed += 1
                changed = True
            except FBP_DATA_ERRORS:
                pending.remove(group)
        if not changed:
            break
    return removed


def _fbp_safe_repair_backup(scene):
    """Copy the current root before Safe Repair mutates any compositor data."""
    if scene is None:
        return None
    # A duplicated Scene must not share the root while a transactional repair is
    # running, otherwise rollback of one Scene could leave the other modified.
    fbp_ensure_scene_copy_independence(scene)
    root = _root_tree(scene)
    backup = None
    nested_backups = []
    try:
        backup = root.copy()
        backup.name = f"{root.name} — Safe Repair Backup"
        backup["fbp_safe_repair_backup"] = True
        _fbp_clone_safe_repair_artist_groups(backup, collector=nested_backups)
        nested_backups = tuple(nested_backups)
    except Exception:
        if backup is not None:
            try:
                if int(getattr(backup, "users", 0) or 0) == 0:
                    bpy.data.node_groups.remove(backup)
            except FBP_DATA_ERRORS:
                pass
        _fbp_remove_orphan_safe_repair_groups(nested_backups)
        raise
    render = getattr(scene, "render", None)
    return {
        "root": root,
        "backup": backup,
        "nested_backups": nested_backups,
        "root_name": str(getattr(root, "name", "") or "FBP Compositor"),
        "use_compositing": bool(getattr(render, "use_compositing", False)) if render is not None else False,
    }


def _fbp_safe_repair_restore(scene, state):
    if scene is None or not state:
        return False
    backup = state.get("backup")
    failed_root = getattr(scene, "compositing_node_group", None)
    if backup is None:
        return False
    render = getattr(scene, "render", None)
    try:
        scene.compositing_node_group = backup
        if render is not None:
            render.use_compositing = bool(state.get("use_compositing", False))
        if failed_root is not None and failed_root is not backup and int(getattr(failed_root, "users", 0) or 0) == 0:
            try:
                bpy.data.node_groups.remove(failed_root)
            except FBP_DATA_ERRORS:
                pass
        try:
            backup.name = str(state.get("root_name", backup.name) or backup.name)
            if "fbp_safe_repair_backup" in backup:
                del backup["fbp_safe_repair_backup"]
            for nested in tuple(state.get("nested_backups", ()) or ()):
                if nested is not None and "fbp_safe_repair_nested_backup" in nested:
                    del nested["fbp_safe_repair_nested_backup"]
        except FBP_DATA_ERRORS:
            pass
        return True
    except FBP_DATA_ERRORS:
        return False


def _fbp_safe_repair_discard(state):
    backup = state.get("backup") if state else None
    nested_backups = tuple(state.get("nested_backups", ()) or ()) if state else ()
    if backup is not None:
        try:
            if int(getattr(backup, "users", 0) or 0) == 0:
                bpy.data.node_groups.remove(backup)
        except FBP_DATA_ERRORS:
            pass
    _fbp_remove_orphan_safe_repair_groups(nested_backups)


class FBP_OT_RepairCompositeSafe(_FBP_CompositorPreviewPoll, Operator):
    bl_idname = "fbp.repair_composite_safe"
    bl_label = "Safe Repair Composite"
    bl_description = "Repair IDs, safe missing rows, technical nodes and an unlinked main output without replacing artist links"
    bl_options = {'UNDO'}

    def execute(self, context):
        scene = getattr(context, "scene", None)
        artist_graph_before = fbp_compositor_artist_graph_snapshot(scene)
        if not bool(artist_graph_before.get("complete", False)):
            self.report({"ERROR"}, "Safe Repair cancelled: artist compositor graph could not be read completely")
            return {"CANCELLED"}
        try:
            backup_state = _fbp_safe_repair_backup(scene)
        except Exception as exc:
            fbp_warn("Could not create the Safe Repair rollback copy", exc)
            self.report({'ERROR'}, "Safe Repair cancelled before changing the compositor")
            return {'CANCELLED'}
        try:
            result = self._execute_safe(context, artist_graph_before=artist_graph_before)
        except Exception as exc:
            restored = _fbp_safe_repair_restore(scene, backup_state)
            _set_compositor_runtime_status(
                scene,
                "Safe Repair rolled back" if restored else "Safe Repair stopped · use Undo",
            )
            fbp_warn("Safe compositor repair rolled back", exc)
            self.report(
                {'ERROR'},
                "Safe Repair detected an unsafe change and restored the previous compositor"
                if restored else "Safe Repair stopped; use Undo before continuing",
            )
            return {'CANCELLED'}
        _fbp_safe_repair_discard(backup_state)
        return result

    def _execute_safe(self, context, *, artist_graph_before):
        scene = context.scene
        tree = _root_tree(scene)
        fbp_sync_layer_set_nodes(scene, tree, sync_file_outputs=False)
        repaired_ids = sum((
            _remove_duplicate_state_items(scene.fbp_compositor_sources, "source_uuid"),
            _remove_duplicate_state_items(scene.fbp_layer_sets, "set_uuid"),
            _remove_duplicate_state_items(scene.fbp_output_configs, "output_uuid"),
            _remove_duplicate_state_items(scene.fbp_over_stacks, "stack_uuid"),
        ))
        fbp_refresh_source_registry(scene)
        removed = 0
        for layer_set in scene.fbp_layer_sets:
            _normalize_layer_set_contract(layer_set)
            _sync_rows(scene, layer_set)
            for index in reversed(range(len(layer_set.rows))):
                row = layer_set.rows[index]
                if row.missing and not row.pinned and not _row_socket_linked(scene, layer_set, row):
                    layer_set.rows.remove(index)
                    removed += 1

        used_pass_ids = set()
        for config in scene.fbp_output_configs:
            _repair_output_pass_ids(config, used_pass_ids)
            used_aliases = []
            used_exr_names = []
            used_destinations = set()
            for index, item in enumerate(config.passes, 1):
                item.name = str(item.name or f"Pass {index}")
                item.alias = _unique_dynamic_title(
                    str(item.alias or item.name),
                    used_aliases,
                    f"Pass {index}",
                )
                used_aliases.append(item.alias)
                item.subfolder = os.path.join(*(
                    safe_path_component(part, "Layer", 63)
                    for part in split_path_components(item.subfolder or "Layers")
                    if str(part or "").strip() not in {"", ".", ".."}
                )) or "Layers"
                item.prefix = safe_path_component(item.prefix or item.alias or item.name, f"pass_{index}", 63)
                destination = normalized_destination(item.subfolder, item.prefix)
                if destination in used_destinations:
                    item.prefix = _unique_dynamic_title(
                        item.prefix,
                        [value.rsplit('/', 1)[-1] for value in used_destinations],
                        f"pass_{index}",
                    )
                    destination = normalized_destination(item.subfolder, item.prefix)
                used_destinations.add(destination)
                item.exr_pass_name = _unique_dynamic_title(
                    safe_path_component(item.exr_pass_name or item.alias or item.name, f"Pass {index}", 63),
                    used_exr_names,
                    f"Pass {index}",
                )
                used_exr_names.append(item.exr_pass_name)

        stack_nodes = {
            str(node.get('fbp_uuid', '') or '')
            for node in tuple(getattr(tree, 'nodes', ()) or ()) if _node_role_without_idprops(node) == ROLE_STACK
        }
        for config in scene.fbp_over_stacks:
            repaired_ids += _repair_stack_row_ids(config)
        for index in reversed(range(len(scene.fbp_over_stacks))):
            config = scene.fbp_over_stacks[index]
            if config.stack_uuid not in stack_nodes and not config.is_default_pipeline:
                scene.fbp_over_stacks.remove(index)
                removed += 1

        if bool(getattr(scene, 'fbp_compositor_enabled', False)):
            try:
                call_service(
                    "compositor.sync",
                    scene,
                    context=context,
                    native_group=True,
                )
                tree = _root_tree(scene)
            except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError) as exc:
                fbp_warn("Clean compositor pipeline repair failed", exc)
        fbp_sync_layer_set_nodes(scene, tree, sync_file_outputs=True)
        group_output = _active_group_output(tree)
        output_nodes = [node for node in tuple(getattr(tree, "nodes", ()) or ()) if _node_role_without_idprops(node) == ROLE_OUTPUT]
        reconnected = False
        if group_output is not None and not group_output.inputs["Image"].is_linked:
            source = None
            if len(output_nodes) == 1 and output_nodes[0].outputs.get("Image") is not None:
                source = output_nodes[0].outputs["Image"]
            else:
                effects = next((node for node in tuple(getattr(tree, 'nodes', ()) or ()) if _node_role_without_idprops(node) == 'effects_stage'), None)
                source = effects.outputs.get('Image') if effects is not None else None
            if source is not None:
                tree.links.new(source, group_output.inputs["Image"])
                reconnected = True
        artist_graph_after = fbp_compositor_artist_graph_snapshot(scene)
        if not bool(artist_graph_after.get("complete", False)):
            raise _FBPCompositorSafeRepairRollback(
                "Artist compositor graph became unreadable during Safe Repair"
            )
        artist_graph_changed = artist_graph_before != artist_graph_after
        changed_artist_nodes = len(
            set(artist_graph_before.get("nodes", ()))
            ^ set(artist_graph_after.get("nodes", ()))
        )
        changed_artist_links = len(
            set(artist_graph_before.get("links", ()))
            ^ set(artist_graph_after.get("links", ()))
        )
        errors, warnings, _ = fbp_validate_composite(scene)
        if artist_graph_changed:
            raise _FBPCompositorSafeRepairRollback(
                f"Artist compositor graph changed: {changed_artist_nodes} node(s), "
                f"{changed_artist_links} link(s)"
            )
        self.report(
            {'ERROR'} if errors else {'WARNING'} if warnings else {'INFO'},
            f"Safe repair: {repaired_ids} state IDs · {removed} missing rows · main output {'reconnected' if reconnected else 'unchanged'}",
        )
        return {'FINISHED'}


class FBP_MT_CompositorCategory(Menu):
    category = ""

    @classmethod
    def poll(cls, context):
        return _FBP_CompositorPreviewPoll.poll(context)

    def draw(self, context):
        layout = self.layout
        for item in FBP_NODE_REGISTRY:
            if item["category"] != self.category:
                continue
            operator = layout.operator(
                "fbp.add_compositor_asset",
                text=item["label"],
                icon=item["icon"],
            )
            operator.kind = item["kind"]
            operator.label = item["label"]


class FBP_MT_CompositorLayers(FBP_MT_CompositorCategory):
    bl_idname = "FBP_MT_compositor_layers"
    bl_label = "Layers"
    category = "LAYERS"


class FBP_MT_CompositorOutput(FBP_MT_CompositorCategory):
    bl_idname = "FBP_MT_compositor_output"
    bl_label = "Output"
    category = "OUTPUT"


class FBP_MT_CompositorEffects(FBP_MT_CompositorCategory):
    bl_idname = "FBP_MT_compositor_effects"
    bl_label = "Effects"
    category = "EFFECTS"


class FBP_MT_CompositorMasks(FBP_MT_CompositorCategory):
    bl_idname = "FBP_MT_compositor_masks"
    bl_label = "Masks"
    category = "MASKS"


class FBP_MT_CompositorUtilities(FBP_MT_CompositorCategory):
    bl_idname = "FBP_MT_compositor_utilities"
    bl_label = "Utilities"
    category = "UTILITIES"


class FBP_MT_CompositorPresets(FBP_MT_CompositorCategory):
    bl_idname = "FBP_MT_compositor_presets"
    bl_label = "Presets"
    category = "PRESETS"


class FBP_MT_CompositorAdd(Menu):
    bl_idname = "FBP_MT_compositor_add"
    bl_label = "Frame By Plane"

    @classmethod
    def poll(cls, context):
        return _FBP_CompositorPreviewPoll.poll(context)

    def draw(self, context):
        layout = self.layout
        entries = (
            (FBP_MT_CompositorLayers, 'RENDERLAYERS'),
            (FBP_MT_CompositorOutput, 'OUTPUT'),
            (FBP_MT_CompositorEffects, 'NODE_COMPOSITING'),
            (FBP_MT_CompositorMasks, 'IMAGE_ALPHA'),
            (FBP_MT_CompositorUtilities, 'TOOL_SETTINGS'),
            (FBP_MT_CompositorPresets, 'PRESET'),
        )
        for menu_type, icon in entries:
            layout.menu(menu_type.bl_idname, icon=icon)


def _draw_add_menu(self, context):
    scene = getattr(context, "scene", None)
    if not bool(scene is not None and fbp_feature_enabled(scene, "compositor_layers")):
        return
    if getattr(context.space_data, "tree_type", "") != 'CompositorNodeTree':
        return
    self.layout.separator()
    self.layout.menu(FBP_MT_CompositorAdd.bl_idname, icon='NODE_COMPOSITING')


_FBP_DRAW_ADD_MENU_CALLBACK = _draw_add_menu


def _validation_status_icon(scene):
    summary = str(getattr(scene, "fbp_composite_validation", "") or "")
    details = str(getattr(scene, "fbp_composite_validation_details", "") or "")
    match = re.search(r"(\d+)\s+Errors?\s*[·|/]\s*(\d+)\s+Warnings?", summary)
    error_count = int(match.group(1)) if match else 0
    warning_count = int(match.group(2)) if match else 0
    if error_count > 0 or any(line.startswith("ERROR") for line in details.splitlines()):
        return 'ERROR'
    if warning_count > 0 or any(line.startswith("WARNING") for line in details.splitlines()):
        return 'INFO'
    if summary:
        return 'CHECKMARK'
    return 'QUESTION'


def _draw_compositor_status(layout, scene, *, detail_limit=2):
    summary = str(getattr(scene, "fbp_composite_validation", "") or "Not validated")
    icon = _validation_status_icon(scene)
    hint_row(
        layout,
        summary,
        icon=icon,
        alert=icon == 'ERROR',
        disabled=icon not in {'ERROR'},
    )
    runtime = str(getattr(scene, "fbp_compositor_status", "") or "")
    if runtime and runtime != summary:
        hint_row(
            layout,
            runtime[:96],
            icon='FILE_REFRESH' if any(word in runtime.casefold() for word in ('sync', 'retry', 'queued')) else 'INFO',
            disabled=True,
        )
    details = str(getattr(scene, "fbp_composite_validation_details", "") or "")
    actionable = [
        line for line in details.splitlines()
        if line.startswith('ERROR') or line.startswith('WARNING')
    ]
    for detail in actionable[:max(0, int(detail_limit))]:
        text = detail if len(detail) <= 92 else f"{detail[:91]}…"
        hint_row(
            layout,
            text,
            icon='ERROR' if detail.startswith('ERROR') else 'INFO',
            alert=detail.startswith('ERROR'),
            disabled=not detail.startswith('ERROR'),
        )

class FBP_PT_LayerSetNode(Panel):
    bl_label = "Composite"
    bl_space_type = 'NODE_EDITOR'
    bl_region_type = 'UI'
    bl_category = 'Frame By Plane'

    @classmethod
    def poll(cls, context):
        if not _FBP_CompositorPreviewPoll.poll(context):
            return False
        node = getattr(context, "active_node", None)
        return node is not None and _node_role_without_idprops(node) in {ROLE_SET, ROLE_OUTPUT, ROLE_STACK}

    def draw_header(self, context):
        role = _node_role_without_idprops(getattr(context, 'active_node', None))
        self.layout.label(
            text="",
            icon={ROLE_SET: 'RENDERLAYERS', ROLE_OUTPUT: 'OUTPUT', ROLE_STACK: 'NODETREE'}.get(role, 'NODE_COMPOSITING'),
        )

    @staticmethod
    def _draw_health(layout, scene, *, detail_limit=2):
        section_gap(layout, 0.2)
        actions = layout.row(align=False)
        actions.operator("fbp.validate_composite", text="Validate", icon='CHECKMARK')
        actions.operator("fbp.repair_composite_safe", text="Safe Repair", icon='TOOL_SETTINGS')
        _draw_compositor_status(layout, scene, detail_limit=detail_limit)

    @staticmethod
    def _draw_output(layout, context, scene, node):
        config = _find(scene.fbp_output_configs, "output_uuid", _controller_uuid(node))
        if config is None:
            empty_state(layout, "Output configuration missing", "Sync the active node to restore its settings", icon='ERROR')
            layout.operator("fbp.compositor_sync", text="Sync Output", icon='FILE_REFRESH')
            return

        section_header(layout, "Output", icon='OUTPUT')
        layout.prop(config, "name", text="Name")
        row = layout.row(align=False)
        row.prop(config, "mode", text="Mode")
        row.prop(config, "save_beauty", text="Save Beauty", toggle=True, icon='RENDER_STILL')
        row.prop(config, "auto_expand", text="Auto Add", toggle=True, icon='ADD')
        hint_row(layout, _short_output_path(_output_root(scene)), icon='FILE_FOLDER', disabled=True)

        enabled_passes = [item for item in config.passes if item.enabled]
        linked_passes = 0
        for item in enabled_passes:
            try:
                socket = next((candidate for candidate in node.inputs if candidate.identifier == item.input_identifier), None)
                linked_passes += int(bool(socket is not None and socket.is_linked))
            except FBP_DATA_ERRORS:
                continue
        status_text = (
            "No enabled passes"
            if not enabled_passes
            else f"{linked_passes} of {len(enabled_passes)} enabled passes linked"
        )
        hint_row(
            layout,
            status_text,
            icon='INFO' if not enabled_passes else 'LINKED' if linked_passes == len(enabled_passes) else 'UNLINKED',
            disabled=True,
        )

        list_box = fbp_draw_uilist_header(
            layout, context, "OUTPUT_PASSES"
        )
        list_row = list_box.row(align=False)
        list_row.template_list(
            "FBP_UL_OutputPasses",
            "",
            config,
            "passes",
            config,
            "active_index",
            rows=list_rows(len(config.passes), minimum=4, maximum=7),
        )
        active_pass = config.passes[config.active_index] if 0 <= config.active_index < len(config.passes) else None
        active_index = int(config.active_index) if active_pass is not None else -1
        active_pass_linked = bool(active_pass is not None and _output_pass_linked(context, active_pass))
        controls = list_row.column(align=True)
        fbp_set_ui_units_x(controls, 1.0)
        controls.menu("FBP_MT_output_pass_actions", text="", icon="COLLAPSEMENU")
        controls.separator()
        movement = controls.column(align=True)
        for action, icon, enabled in (
            ('MOVE_UP', 'SORT_DESC', active_index > 0),
            ('MOVE_DOWN', 'SORT_ASC', 0 <= active_index < len(config.passes) - 1),
        ):
            button = movement.row(align=True)
            button.enabled = bool(enabled)
            operator = button.operator("fbp.output_pass_action", text="", icon=icon)
            operator.output_uuid = config.output_uuid
            operator.action = action
        controls.separator()
        add = controls.operator("fbp.output_pass_action", text="", icon='ADD')
        add.output_uuid = config.output_uuid
        add.action = 'ADD'

        if not config.passes:
            empty_state(
                layout,
                "No export passes",
                "Use + or connect the Add input on the node",
                icon='FILE_IMAGE',
                boxed=False,
            )
        elif active_pass is not None:
            item = active_pass
            section_gap(layout, 0.2)
            box = layout.box()
            configure_layout(box)
            section_header(box, "Pass Settings", icon='FILE_IMAGE')
            hint_row(
                box,
                "Connected · disconnect before removing" if active_pass_linked else "Input not connected",
                icon='LINKED' if active_pass_linked else 'UNLINKED',
                disabled=True,
            )
            box.prop(item, "alias", text="Output Name")
            if config.mode == 'MULTILAYER':
                box.prop(item, "exr_pass_name", text="EXR Pass")
            else:
                box.prop(item, "subfolder", text="Folder")
                box.prop(item, "prefix", text="Prefix")
                box.prop(item, "format_override", text="Custom Format", toggle=True)
                if item.format_override:
                    row = box.row(align=False)
                    row.prop(item, "file_format", text="Format")
                    row.prop(item, "color_mode", text="Color")
                    row = box.row(align=False)
                    row.prop(item, "color_depth", text="Depth")
                    row.prop(item, "compression", text="Compression")

        FBP_PT_LayerSetNode._draw_health(layout, scene, detail_limit=2)

    @staticmethod
    def _draw_batch_button(row, layer_set, action, icon, text=""):
        operator = row.operator("fbp.layer_set_batch", text=text, icon=icon)
        operator.set_uuid = layer_set.set_uuid
        operator.action = action
        return operator

    @classmethod
    def _draw_layer_set(cls, layout, context, scene, node):
        layer_set = _find(scene.fbp_layer_sets, "set_uuid", _controller_uuid(node))
        if layer_set is None:
            empty_state(layout, "Layer Set configuration missing", "Sync the active node to restore its settings", icon='ERROR')
            layout.operator("fbp.compositor_sync", text="Sync Layer Set", icon='FILE_REFRESH')
            return

        section_header(layout, "Layer Set", icon='RENDERLAYERS')
        layout.prop(layer_set, "name", text="Name")
        row = layout.row(align=False)
        if layer_set.special == 'DERIVED':
            row.prop(layer_set, "set_operation", text="Operation")
        else:
            row.prop(layer_set, "mode", text="Mode")
        row.prop(layer_set, "mask_mode", text="Mask")

        active_row = layer_set.rows[layer_set.active_index] if 0 <= layer_set.active_index < len(layer_set.rows) else None
        if layer_set.rows:
            list_box = fbp_draw_uilist_header(
                layout, context, "LAYER_SET_ROWS"
            )
            list_row = list_box.row(align=False)
            list_row.template_list(
                "FBP_UL_LayerSetRows",
                "",
                layer_set,
                "rows",
                layer_set,
                "active_index",
                rows=list_rows(len(layer_set.rows), minimum=6, maximum=10),
            )
            tools = list_row.column(align=True)
            fbp_set_ui_units_x(tools, 1.0)
            tools.menu("FBP_MT_layer_set_row_actions", text="", icon="COLLAPSEMENU")
            tools.separator()
            active_index = int(layer_set.active_index) if active_row is not None else -1
            last_index = len(layer_set.rows) - 1
            movement = tools.column(align=True)
            for action, icon, enabled in (
                ('MOVE_UP', 'SORT_DESC', active_index > 0),
                ('MOVE_DOWN', 'SORT_ASC', 0 <= active_index < last_index),
            ):
                button = movement.row(align=True)
                button.enabled = bool(enabled)
                operator = button.operator("fbp.layer_set_row_action", text="", icon=icon)
                operator.set_uuid = layer_set.set_uuid
                operator.source_uuid = active_row.source_uuid if active_row else ""
                operator.action = action
        else:
            empty_state(layout, "No layer sources", "Sync the set after creating Frame By Plane layers", icon='RENDERLAYERS')

        active_count = sum(1 for row_item in layer_set.rows if row_item.resolved_eye)
        selected_count = sum(1 for row_item in layer_set.rows if row_item.selected)
        missing_count = sum(1 for row_item in layer_set.rows if row_item.missing)
        status = f"{active_count} active · {selected_count} selected"
        if missing_count:
            status += f" · {missing_count} missing"
        hint_row(layout, status, icon='ERROR' if missing_count else 'HIDE_OFF', alert=bool(missing_count), disabled=not missing_count)

        has_rows = bool(layer_set.rows)
        has_selected_rows = selected_count > 0
        has_missing_rows = missing_count > 0

        selection = layout.row(align=False)
        selection.enabled = has_rows
        cls._draw_batch_button(selection, layer_set, 'SELECT_ALL', 'CHECKBOX_HLT')
        cls._draw_batch_button(selection, layer_set, 'SELECT_NONE', 'CHECKBOX_DEHLT')
        cls._draw_batch_button(selection, layer_set, 'INVERT_SELECTION', 'ARROW_LEFTRIGHT')

        selected_visibility = layout.row(align=False)
        selected_visibility.enabled = has_selected_rows and layer_set.special != 'DERIVED'
        cls._draw_batch_button(selected_visibility, layer_set, 'ENABLE_SELECTED', 'HIDE_OFF', "Show Selected")
        cls._draw_batch_button(selected_visibility, layer_set, 'DISABLE_SELECTED', 'HIDE_ON', "Hide Selected")

        all_visibility = layout.row(align=False)
        all_visibility.enabled = has_rows and layer_set.special != 'DERIVED'
        cls._draw_batch_button(all_visibility, layer_set, 'ENABLE_ALL', 'HIDE_OFF')
        cls._draw_batch_button(all_visibility, layer_set, 'DISABLE_ALL', 'HIDE_ON')
        cls._draw_batch_button(all_visibility, layer_set, 'INVERT_EYES', 'ARROW_LEFTRIGHT')

        maintenance = layout.row(align=False)
        cls._draw_batch_button(maintenance, layer_set, 'RESET_ORDER', 'LOOP_BACK')
        remove_missing = maintenance.row(align=False)
        remove_missing.enabled = has_missing_rows
        cls._draw_batch_button(remove_missing, layer_set, 'REMOVE_MISSING', 'TRASH')
        cls._draw_batch_button(maintenance, layer_set, 'SYNC', 'FILE_REFRESH')

        options = layout.row(align=False)
        options.prop(layer_set, "follow_layer_list", text="Follow Layer List", toggle=True)
        if layer_set.special == 'DERIVED':
            _draw_derived_set_controls(layout, scene, layer_set)
        else:
            options.prop(layer_set, "membership_mode", text="Membership")
            if layer_set.membership_mode == 'EXCLUSIVE':
                layout.prop(layer_set, "exclusive_group", text="Exclusive Group")

        if layer_set.special != 'DERIVED' and layer_set.mode != 'MANUAL':
            rules = layout.box()
            configure_layout(rules)
            section_header(rules, "Automatic Rules", icon='FILTER')
            rules.prop(layer_set, "rule_folder", text="Folder")
            rules.prop(layer_set, "rule_color_tag", text="Color Tag")
            rules.prop(layer_set, "rule_type", text="Type")
            row = rules.row(align=False)
            row.prop(layer_set, "rule_name_mode", text="Name Match")
            row.prop(layer_set, "rule_name", text="Name")
            rules.prop(layer_set, "rule_visibility", text="Visibility")
            rules.prop(layer_set, "rule_effect", text="Effect")
            rules.prop(layer_set, "rule_depth_enabled", text="Camera Depth", toggle=True)
            if layer_set.rule_depth_enabled:
                depth = rules.row(align=False)
                depth.prop(layer_set, "rule_depth_min", text="Near")
                depth.prop(layer_set, "rule_depth_max", text="Far")
            if active_row is not None:
                rules.prop(active_row, "override", text="Active Override")

        if active_row is not None:
            source_actions = layout.row(align=False)
            if active_row.missing:
                remap = source_actions.operator("fbp.remap_layer_set_source", text="Remap Missing", icon='FILE_REFRESH')
                remap.set_uuid = layer_set.set_uuid
                remap.source_uuid = active_row.source_uuid
            inspect = source_actions.operator("fbp.inspect_compositor_source_dependencies", text="Dependencies", icon='LINKED')
            inspect.source_uuid = active_row.source_uuid

        section_gap(layout, 0.2)
        preview = layout.row(align=False)
        for output, icon in (('TOT', 'HIDE_OFF'), ('MASK', 'IMAGE_ALPHA'), ('ACTIVE', 'RESTRICT_SELECT_OFF')):
            button = preview.row(align=False)
            button.enabled = output != 'ACTIVE' or active_row is not None
            operator = button.operator("fbp.layer_set_preview", text=output, icon=icon)
            operator.set_uuid = layer_set.set_uuid
            operator.output = output

        solo = layout.operator("fbp.layer_set_solo", text="Solo Set", icon='SOLO_ON')
        solo.set_uuid = layer_set.set_uuid

        snapshots = layout.box()
        configure_layout(snapshots)
        section_header(snapshots, "Snapshots", icon='PRESET')
        for letter in 'ABC':
            row = snapshots.row(align=False)
            row.label(text=letter)
            cls._draw_batch_button(row, layer_set, f'SAVE_{letter}', 'FILE_TICK', "Save")
            load = row.row(align=False)
            load.enabled = bool(getattr(layer_set, f"snapshot_{letter.lower()}", ""))
            cls._draw_batch_button(load, layer_set, f'LOAD_{letter}', 'RECOVER_LAST', "Load")

        coverage = str(getattr(scene, 'fbp_composite_coverage', '') or '')
        if coverage:
            hint_row(layout, coverage, icon='INFO', disabled=True)
        cls._draw_health(layout, scene, detail_limit=3)

    @staticmethod
    def _draw_stack(layout, context, scene, node):
        config = _find(scene.fbp_over_stacks, 'stack_uuid', _controller_uuid(node))
        if config is None:
            empty_state(layout, "Composite Stack configuration missing", "Sync the active node to restore its settings", icon='ERROR')
            layout.operator('fbp.compositor_sync', text='Sync Stack', icon='FILE_REFRESH')
            return

        section_header(layout, "Composite Stack", icon='NODETREE')
        layout.prop(config, 'name', text='Name')
        active_row = config.rows[config.active_index] if 0 <= config.active_index < len(config.rows) else None
        list_box = fbp_draw_uilist_header(
            layout, context, "COMPOSITOR_STACK"
        )
        list_row = list_box.row(align=False)
        list_row.template_list(
            'FBP_UL_StackRows',
            '',
            config,
            'rows',
            config,
            'active_index',
            rows=list_rows(len(config.rows), minimum=5, maximum=9),
        )
        active_index = int(config.active_index) if active_row is not None else -1
        last_index = max(-1, len(config.rows) - 2)
        active_is_placeholder = bool(active_row and getattr(active_row, 'is_placeholder', False))
        controls = list_row.column(align=True)
        fbp_set_ui_units_x(controls, 1.0)
        controls.menu("FBP_MT_stack_row_actions", text="", icon="COLLAPSEMENU")
        controls.separator()
        movement = controls.column(align=True)
        for action, icon, enabled in (
            ('MOVE_UP', 'SORT_DESC', active_index > 0 and not active_is_placeholder),
            ('MOVE_DOWN', 'SORT_ASC', 0 <= active_index < last_index and not active_is_placeholder),
        ):
            button = movement.row(align=True)
            button.enabled = bool(enabled)
            operator = button.operator('fbp.stack_row_action', text='', icon=icon)
            operator.stack_uuid = config.stack_uuid
            operator.row_uuid = active_row.row_uuid if active_row else ''
            operator.action = action
        controls.separator()
        add = controls.operator('fbp.stack_row_action', text='', icon='ADD')
        add.stack_uuid = config.stack_uuid
        add.action = 'ADD'

        options = layout.row(align=False)
        options.prop(config, 'auto_expand', text='Auto Add', toggle=True)
        if config.is_default_pipeline:
            options.prop(config, 'follow_layer_list', text='Follow Layers', toggle=True)

        real_rows = [item for item in config.rows if not bool(getattr(item, 'is_placeholder', False))]
        linked_rows = 0
        for item in real_rows:
            try:
                socket = _stack_input_socket(node, item)
                linked_rows += int(bool(socket is not None and socket.is_linked))
            except FBP_DATA_ERRORS:
                continue
        status = "No inputs · connect Add" if not real_rows else f"{linked_rows} of {len(real_rows)} inputs linked · top is nearest"
        hint_row(
            layout,
            status,
            icon='INFO' if not real_rows else 'LINKED' if linked_rows == len(real_rows) else 'UNLINKED',
            disabled=True,
        )
        FBP_PT_LayerSetNode._draw_health(layout, scene, detail_limit=2)

    def draw(self, context):
        layout = configure_layout(self.layout)
        scene = context.scene
        node = context.active_node
        role = _node_role_without_idprops(node)
        if role == ROLE_OUTPUT:
            self._draw_output(layout, context, scene, node)
        elif role == ROLE_STACK:
            self._draw_stack(layout, context, scene, node)
        else:
            self._draw_layer_set(layout, context, scene, node)

@persistent
def fbp_compositor_sets_load_post(_dummy):
    _FBP_PENDING_NODE_SCENES.clear()
    _FBP_PENDING_STACK_SCENES.clear()
    _FBP_PENDING_OUTPUT_SCENES.clear()
    _FBP_NODE_UPDATE_RETRIES.clear()
    _FBP_ACTIVE_NODE_SCENES.clear()
    _FBP_ACTIVE_STACK_SCENES.clear()
    _FBP_ACTIVE_OUTPUT_SCENES.clear()
    _STACK_NODE_LINK_SIGNATURES.clear()
    _OUTPUT_NODE_LINK_SIGNATURES.clear()
    _NODE_SIGNATURES.clear()
    _SCENE_COPY_INDEX.clear()
    global _SCENE_COPY_INDEX_COUNT
    _SCENE_COPY_INDEX_COUNT = -1
    _rebuild_scene_copy_index()
    for scene in bpy.data.scenes:
        key = _scene_runtime_key(scene)
        _FBP_ACTIVE_NODE_SCENES.add(key)
        try:
            fbp_sync_layer_set_nodes(scene, sync_file_outputs=False)
        except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError) as exc:
            fbp_warn("Layer Set load sync failed", exc)
        finally:
            _FBP_ACTIVE_NODE_SCENES.discard(key)


_NODE_SIGNATURES = {}
_FBP_NODE_SIGNATURE_ROLES = frozenset({ROLE_SET, ROLE_OUTPUT, ROLE_STACK})
_SCENE_COPY_INDEX = {}
_SCENE_COPY_INDEX_COUNT = -1


def _scene_pointer(scene):
    try:
        return int(scene.as_pointer()) if scene is not None else 0
    except FBP_DATA_ERRORS:
        return 0


def _rebuild_scene_copy_index():
    """Index compositor scene IDs without retaining fragile RNA references."""
    global _SCENE_COPY_INDEX_COUNT
    index = {}
    try:
        scenes = tuple(getattr(bpy.data, "scenes", ()) or ())
    except FBP_DATA_ERRORS:
        scenes = ()
    for item in scenes:
        try:
            scene_id = str(getattr(item, "fbp_compositor_scene_id", "") or "")
            if not scene_id:
                continue
            index.setdefault(scene_id, []).append(
                (str(getattr(item, "name", "") or ""), _scene_pointer(item))
            )
        except FBP_DATA_ERRORS:
            continue
    _SCENE_COPY_INDEX.clear()
    _SCENE_COPY_INDEX.update(
        (scene_id, tuple(owners)) for scene_id, owners in index.items()
    )
    _SCENE_COPY_INDEX_COUNT = len(scenes)
    return _SCENE_COPY_INDEX


def _scene_copy_index_owners(scene, scene_id):
    """Return cached owners, rebuilding only after scene topology/ID changes."""
    try:
        scene_count = len(bpy.data.scenes)
    except FBP_DATA_ERRORS:
        scene_count = -1
    pointer = _scene_pointer(scene)
    owners = _SCENE_COPY_INDEX.get(scene_id, ())
    if (
        scene_count != _SCENE_COPY_INDEX_COUNT
        or not owners
        or not any(owner_pointer == pointer for _name, owner_pointer in owners)
    ):
        owners = _rebuild_scene_copy_index().get(scene_id, ())
    return owners


def _fbp_compositor_node_signature(tree):
    """Return a minimal controller signature without probing native nodes.

    This runs from depsgraph observation. Reading ``node.get`` on every node can
    enter invalid IDProperty storage during a concurrent node-tree mutation.
    Filter by the registered custom-node ``bl_idname`` first, then read the UUID
    only from the three Frame By Plane controller classes.
    """
    signature = []
    try:
        nodes = tuple(getattr(tree, "nodes", ()) or ())
    except FBP_DATA_ERRORS:
        return ()
    for node in nodes:
        try:
            role = _node_role_without_idprops(node)
            if role not in _FBP_NODE_SIGNATURE_ROLES:
                continue
            child = getattr(node, "node_tree", None)
            signature.append((
                int(node.as_pointer()),
                role,
                str(node.get("fbp_uuid", "") or ""),
                int(child.as_pointer()) if child is not None else 0,
            ))
        except FBP_DATA_ERRORS:
            continue
    return tuple(sorted(signature))


def _compositor_sets_update_relevant(scene, depsgraph, tree, *, updates=None):
    """Reject unrelated viewport/material depsgraph traffic before node scans."""
    scene_key = _scene_pointer(scene)
    if not scene_key or scene_key not in _NODE_SIGNATURES:
        return True
    try:
        if len(bpy.data.scenes) != _SCENE_COPY_INDEX_COUNT:
            return True
    except FBP_DATA_ERRORS:
        return True
    if updates is None:
        try:
            updates = tuple(getattr(depsgraph, "updates", ()) or ())
        except FBP_DATA_ERRORS:
            return True
    if not updates:
        return False
    tree_pointer = _scene_pointer(tree)
    tracked_trees = {tree_pointer}
    tracked_trees.update(
        int(item[3]) for item in _NODE_SIGNATURES.get(scene_key, ()) if int(item[3])
    )
    scene_rna = bpy.types.Scene
    node_tree_rna = bpy.types.NodeTree
    for update in updates:
        try:
            datablock = getattr(update, "id", None)
            original = getattr(datablock, "original", None)
            if original is not None:
                datablock = original
            if isinstance(datablock, scene_rna):
                if _scene_pointer(datablock) == scene_key:
                    return True
            elif isinstance(datablock, node_tree_rna):
                if _scene_pointer(datablock) in tracked_trees:
                    return True
        except FBP_DATA_ERRORS:
            continue
    return False


def fbp_ensure_scene_copy_independence(scene):
    """Give duplicated scenes their own root and every FBP instance tree."""
    scene_id = str(getattr(scene, "fbp_compositor_scene_id", "") or "")
    if not scene_id:
        return False
    scene_pointer = _scene_pointer(scene)
    duplicate = None
    for name, pointer in _scene_copy_index_owners(scene, scene_id):
        if pointer == scene_pointer:
            continue
        try:
            candidate = _scene_from_runtime_key(pointer)
            if candidate is None and name:
                candidate = bpy.data.scenes.get(name)
            if (
                candidate is not None
                and _scene_pointer(candidate) == pointer
                and str(getattr(candidate, "fbp_compositor_scene_id", "") or "") == scene_id
            ):
                duplicate = candidate
                break
        except FBP_DATA_ERRORS:
            continue
    if duplicate is None:
        return False

    scene.fbp_compositor_scene_id = _id()
    new_scene_id = scene.fbp_compositor_scene_id
    root = scene.compositing_node_group
    if root is None:
        return True
    if int(getattr(root, "users", 0) or 0) > 1:
        copied_root = root.copy()
        copied_root.name = f"FBP Compositor - {_clean(scene.name)}"
        copied_root["fbp_compositor_scene_id"] = new_scene_id
        render = getattr(scene, "render", None)
        use_compositing_before = bool(getattr(render, "use_compositing", False)) if render is not None else False
        scene.compositing_node_group = copied_root
        if render is not None:
            render.use_compositing = use_compositing_before
        root = copied_root
    else:
        root["fbp_compositor_scene_id"] = new_scene_id

    relevant_roles = {
        ROLE_SET, ROLE_OUTPUT, ROLE_STACK,
        "layers_package", "legacy_sources", "effects_stage",
    }
    for node in tuple(getattr(root, "nodes", ()) or ()):
        role = _node_role_without_idprops(node)
        if role not in relevant_roles:
            continue
        try:
            node_tree = getattr(node, "node_tree", None)
            if node_tree is None:
                continue
            owner_id = str(node_tree.get("fbp_compositor_scene_id", "") or "")
            if int(getattr(node_tree, "users", 0) or 0) > 1 or owner_id != new_scene_id:
                node_tree = node_tree.copy()
                node.node_tree = node_tree
            node_tree["fbp_compositor_scene_id"] = new_scene_id
            if role in {"layers_package", "legacy_sources"}:
                for internal in tuple(getattr(node_tree, "nodes", ()) or ()):
                    if str(getattr(internal, "bl_idname", "") or "") == "CompositorNodeRLayers":
                        internal.scene = scene
        except FBP_DATA_ERRORS:
            continue
    return True


@persistent
def fbp_compositor_sets_depsgraph_post(scene, depsgraph, *, updates=None):
    if scene is None or bpy.app.is_job_running('RENDER') or not hasattr(scene, "fbp_layer_sets"):
        return
    tree = scene.compositing_node_group
    if tree is None or not _compositor_sets_update_relevant(
        scene, depsgraph, tree, updates=updates
    ):
        return
    # Group Output deletion changes the node tree but not the custom-controller
    # signature below. Repair it before the early signature return so native
    # Render Image always sees a renderable compositor contract.
    if (
        bool(getattr(scene, "fbp_compositor_enabled", False))
        and bool(getattr(getattr(scene, "render", None), "use_compositing", False))
    ):
        try:
            from .compositor import fbp_ensure_native_render_output
            fbp_ensure_native_render_output(scene, tree)
        except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError) as exc:
            fbp_warn("Could not restore the native compositor output", exc)
    if fbp_ensure_scene_copy_independence(scene):
        tree = scene.compositing_node_group
        if tree is None:
            return
    signature = _fbp_compositor_node_signature(tree)
    key = _scene_pointer(scene)
    if _NODE_SIGNATURES.get(key) == signature:
        return
    _NODE_SIGNATURES[key] = signature
    _purge_link_signature_cache(scene, ROLE_STACK, _STACK_NODE_LINK_SIGNATURES)
    _purge_link_signature_cache(scene, ROLE_OUTPUT, _OUTPUT_NODE_LINK_SIGNATURES)
    scene_key = _scene_runtime_key(scene)
    _FBP_ACTIVE_NODE_SCENES.add(scene_key)
    try:
        fbp_sync_layer_set_nodes(scene, tree, sync_file_outputs=False)
        _NODE_SIGNATURES[key] = _fbp_compositor_node_signature(tree)
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError) as exc:
        fbp_warn("Layer Set duplicate sync failed", exc)
    finally:
        _FBP_ACTIVE_NODE_SCENES.discard(scene_key)


classes = (
    FBP_SourceRecord,
    FBP_LayerSetRow,
    FBP_LayerSet,
    FBP_StackRow,
    FBP_OverStack,
    FBP_OutputPass,
    FBP_OutputConfig,
    FBP_UL_LayerSetRows,
    FBP_UL_OutputPasses,
    FBP_UL_StackRows,
    FBP_CompositorLayerSetNode,
    FBP_CompositorOutputNode,
    FBP_CompositorStackNode,
    FBP_OT_AddCompositorAsset,
    FBP_OT_StackRowAction,
    FBP_OT_LayerSetRowAction,
    FBP_OT_LayerSetBatch,
    FBP_OT_ChooseLayerSetOperand,
    FBP_OT_FreezeDerivedLayerSet,
    FBP_OT_RemapLayerSetSource,
    FBP_OT_InspectSourceDependencies,
    FBP_OT_LayerSetPreview,
    FBP_OT_LayerSetSolo,
    FBP_OT_OutputPassAction,
    FBP_OT_ValidateComposite,
    FBP_OT_RepairCompositeSafe,
    FBP_MT_LayerSetRowActions,
    FBP_MT_OutputPassActions,
    FBP_MT_StackRowActions,
    FBP_MT_CompositorLayers,
    FBP_MT_CompositorOutput,
    FBP_MT_CompositorEffects,
    FBP_MT_CompositorMasks,
    FBP_MT_CompositorUtilities,
    FBP_MT_CompositorPresets,
    FBP_MT_CompositorAdd,
    FBP_PT_LayerSetNode,
)


_SCENE_PROPERTIES = (
    "fbp_compositor_sources",
    "fbp_layer_sets",
    "fbp_output_configs",
    "fbp_over_stacks",
    "fbp_composite_validation",
    "fbp_composite_validation_details",
    "fbp_composite_coverage",
)


def _remove_scene_properties():
    return unregister_type_properties(bpy.types.Scene, _SCENE_PROPERTIES)


def _remove_add_menu_callbacks():
    callbacks = (_draw_add_menu, _PREVIOUS_DRAW_ADD_MENU_CALLBACK)
    seen = set()
    for callback in callbacks:
        if callback is None or id(callback) in seen:
            continue
        seen.add(id(callback))
        try:
            bpy.types.NODE_MT_add.remove(callback)
        except FBP_DATA_IO_ERRORS:
            continue


def _remove_runtime_handlers():
    remove_handlers_by_name(
        bpy.app.handlers.load_post,
        "fbp_compositor_sets_load_post",
        module_suffix="compositor_sets",
    )
    remove_handlers_by_name(
        bpy.app.handlers.depsgraph_update_post,
        "fbp_compositor_sets_depsgraph_post",
        module_suffix="compositor_sets",
    )


def register():
    register_classes(classes)
    menu_registered = False
    try:
        bpy.types.Scene.fbp_compositor_sources = CollectionProperty(type=FBP_SourceRecord)
        bpy.types.Scene.fbp_layer_sets = CollectionProperty(type=FBP_LayerSet)
        bpy.types.Scene.fbp_output_configs = CollectionProperty(type=FBP_OutputConfig)
        bpy.types.Scene.fbp_over_stacks = CollectionProperty(type=FBP_OverStack)
        bpy.types.Scene.fbp_composite_validation = StringProperty(default="", options={'HIDDEN'})
        bpy.types.Scene.fbp_composite_validation_details = StringProperty(default="", options={'HIDDEN'})
        bpy.types.Scene.fbp_composite_coverage = StringProperty(default="", options={'HIDDEN'})

        _rebuild_scene_copy_index()
        _remove_add_menu_callbacks()
        bpy.types.NODE_MT_add.append(_draw_add_menu)
        menu_registered = True

        if not append_handler_once(
            bpy.app.handlers.load_post,
            fbp_compositor_sets_load_post,
            module_suffix="compositor_sets",
        ):
            raise RuntimeError("Could not register the Layer Set load handler")
        # Depsgraph observation is dispatched by scene_sync through the shared
        # immutable update snapshot; keep removing stale standalone generations.
        remove_handlers_by_name(
            bpy.app.handlers.depsgraph_update_post,
            "fbp_compositor_sets_depsgraph_post",
            module_suffix="compositor_sets",
        )
    except Exception:
        _remove_runtime_handlers()
        if menu_registered:
            _remove_add_menu_callbacks()
        _remove_scene_properties()
        unregister_classes(classes)
        raise


def unregister():
    _FBP_PENDING_NODE_SCENES.clear()
    _FBP_PENDING_STACK_SCENES.clear()
    _FBP_PENDING_OUTPUT_SCENES.clear()
    _FBP_NODE_UPDATE_RETRIES.clear()
    _FBP_ACTIVE_NODE_SCENES.clear()
    _FBP_ACTIVE_STACK_SCENES.clear()
    _FBP_ACTIVE_OUTPUT_SCENES.clear()
    _STACK_NODE_LINK_SIGNATURES.clear()
    _OUTPUT_NODE_LINK_SIGNATURES.clear()
    cancel_scheduled_prefixes("compositor_sets.")
    _remove_runtime_handlers()
    _NODE_SIGNATURES.clear()
    _SCENE_COPY_INDEX.clear()
    global _SCENE_COPY_INDEX_COUNT
    _SCENE_COPY_INDEX_COUNT = -1
    _remove_add_menu_callbacks()
    _remove_scene_properties()
    unregister_classes(classes)
