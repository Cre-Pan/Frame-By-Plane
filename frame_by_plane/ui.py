"""Panels, UILists, Shift+A menu entries and render menu hooks."""

import textwrap

import bpy
from bpy.types import Panel, UIList, Menu, Operator
from bpy.props import BoolProperty, EnumProperty, StringProperty

from .geometry_nodes import fbp_active_effect_id, fbp_active_effect_instance_id, fbp_can_move_effect_selection, fbp_draw_effect_settings, fbp_draw_effect_mask_editor, fbp_effect_presence, fbp_effect_source_rig, fbp_focus_lattice_ui, fbp_schedule_effect_items_sync, fbp_selected_effect_instances
from .effect_instances import split_effect_instance_token
from .effects_registry import (
    FBP_EFFECT_CLIPPING_MASK,
    FBP_EFFECT_LAYER_BLEND,
    FBP_EFFECT_SQUARE_MASK,
    FBP_EFFECT_CIRCLE_MASK,
    FBP_EFFECT_TRIANGLE_MASK,
    FBP_EFFECT_LATTICE,
    fbp_effect_definition,
    fbp_normalize_effect_id,
)


from .constants import (
    fbp_collection_color_icon, fbp_layer_blend_label,
    fbp_layer_blend_mode_columns, fbp_layer_blend_short, fbp_strip_icon,
)
from .path_utils import cached_file_exists, natural_sort_key
from .render_output import (
    fbp_find_ffmpeg_executable,
    fbp_render_filename_preview,
    fbp_render_folder_name,
)
from .compositor import (
    FBP_COMPOSITOR_EFFECT_ITEMS,
    FBP_COMPOSITOR_TAG_LABELS,
)
from .runtime import fbp_warn, FBP_DATA_ERRORS, FBP_DATA_IO_ERRORS
from .feature_scope import fbp_feature_enabled
from .project_health import (
    REPORT_NAME as PROJECT_DOCTOR_REPORT_NAME,
    active_project_doctor_issue,
    project_doctor_counts,
)
from .performance_dashboard import (
    cached_performance_report,
    draw_performance_dashboard_ui,
)
from .layer_sets import draw_layer_sets_ui
from .layer_filters import (
    filter_layer_tree_items,
    layer_filter_is_active,
)
from .visibility_snapshots import draw_visibility_snapshots_ui
from .effect_stack_presets import draw_effect_stack_presets_ui
from .mask_stack import draw_mask_source_library_ui
from .registration import register_classes, unregister_classes
from .shortcut_runtime import alt_shortcut_label, primary_shortcut_label
from .service_registry import register_service, unregister_service
from .fbp_index import iter_scene_fbp_rigs, iter_scene_gp_canvases, scene_has_gp_canvas
from .grease_pencil_bridge import (
    gp_canvas_owner,
    gp_canvas_solo_active,
    gp_internal_layer_icon,
    gp_internal_layer_native_mask_active,
    gp_internal_layer_selected,
    is_gp_drawing_canvas,
)
from .layers import fbp_build_canonical_collection_tree, fbp_collection_icon, fbp_active_work_collection, fbp_color_plane_type_icon, fbp_layer_depth_value_from_cache, fbp_layer_row_type_icon, fbp_layer_tag_backend_icon_value, fbp_layer_backend_label, fbp_layer_backend_type, fbp_layer_clipping_active_hint, fbp_make_depth_context_cache, fbp_procedural_kind_for_item, fbp_procedural_layer_type, fbp_select_plane_icon, fbp_select_rig_icon, fbp_set_ui_units_x, get_layer_item_for_rig, get_primary_fbp_collection, get_selected_fbp_roots, get_selected_rigs, fbp_resolve_rig_from_any_object, is_fbp_layer_object, is_layer_item_visible_in_collections, load_preview
from .core import (
    draw_native_fbp_color_ramp,
    fbp_color_plane_can_have_frames,
    fbp_rig_native_sequence_needs_rename,
    fbp_sequence_index_at_frame,
    pending_collection_is_open,
)
from .ui_icons import (
    clipping_mask_icon_kwargs,
    layer_custom_icon_value,
    register_custom_icons,
    unregister_custom_icons,
    ui_icon,
    ui_icon_kwargs,
    ui_label_icon_kwargs,
    ui_icon_value,
)
from .interface_preferences import UILIST_COLUMN_DEFINITIONS, clear_interface_preferences_cache, fbp_get_addon_preferences, fbp_draw_uilist_header, fbp_draw_uilist_profile_preview, fbp_clear_uilist_drag_preview, fbp_set_uilist_drag_preview, fbp_uilist_column_icon_kwargs, fbp_set_uilist_profile_order, fbp_set_uilist_profile_visibility, fbp_uilist_icon_flags, fbp_uilist_icon_order, fbp_uilist_label_alignment, fbp_uilist_fixed_row_layouts, fbp_uilist_row_layouts, fbp_uilist_profile_definition, fbp_uilist_profile_columns, fbp_uilist_is_spacer, fbp_draw_uilist_spacer, fbp_uilist_visible_columns
from .ui_style import FBP_UI_EFFECT_MAX_ROWS, FBP_UI_EFFECT_MIN_ROWS, FBP_UI_LIST_MIN_ROWS, adaptive_row, configure_layout, empty_state, hint_row, is_compact, list_rows, section_gap, section_header, selection_status


_FBP_UILIST_DRAG_ACTIVE = {"profile": "", "column_key": ""}


def _fbp_ui_preferences(context):
    try:
        return fbp_get_addon_preferences(context)
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        return None


def _fbp_properties_panel_enabled(context):
    """Return whether the standard 3D View Tool-tab control panels are enabled."""
    prefs = _fbp_ui_preferences(context)
    return bool(getattr(prefs, 'show_control_panel_properties', True)) if prefs else True


def _fbp_n_panel_enabled(context):
    """Return whether the dedicated Frame By Plane N-Panel is enabled."""
    prefs = _fbp_ui_preferences(context)
    return bool(getattr(prefs, 'show_control_panel_n_panel', False)) if prefs else False


def _fbp_panel_section_enabled(context, section):
    prefs = _fbp_ui_preferences(context)
    if prefs is None:
        return True
    attr = {
        'LAYERS': 'show_panel_layers',
        'GP': 'show_panel_grease_pencil',
        'SETTINGS': 'show_panel_layer_settings',
    }.get(str(section or '').upper(), '')
    return bool(getattr(prefs, attr, True)) if attr else True


def _fbp_properties_tool_enabled(context, section):
    return bool(
        _fbp_properties_panel_enabled(context)
        and _fbp_panel_section_enabled(context, section)
    )


def _fbp_scene_has_drawing_gp(context):
    """Return whether the scene contains a real FBP drawing canvas.

    Technical Grease Pencil collections and mask-only helpers must not make the
    dedicated Grease Pencil panel appear. The panel becomes available as soon as
    the first drawing canvas is created and disappears again after the last one
    is removed.
    """
    scene = getattr(context, "scene", None) if context else None
    if scene is None:
        return False
    try:
        return scene_has_gp_canvas(scene, kind="DRAWING")
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        return False


def _fbp_sidebar_has_visible_sections(context, *, dedicated=False):
    """Return whether a 3D View sidebar anchor has at least one visible child."""
    if dedicated:
        if not _fbp_n_panel_enabled(context):
            return False
    elif not _fbp_properties_panel_enabled(context):
        return False

    if _fbp_panel_section_enabled(context, "LAYERS"):
        return True
    if _fbp_panel_section_enabled(context, "SETTINGS"):
        return True
    return bool(
        _fbp_panel_section_enabled(context, "GP")
        and _fbp_scene_has_drawing_gp(context)
    )


def _fbp_active_plane_context(context):
    """Return the active FBP rig from a rig, plane or generated helper.

    Spatial effect controls, object-mask helpers and lattice cages are valid
    editing handles for a layer.  Treating them as dead context made the Effects
    panel disappear exactly when the user selected the interactive null.  Resolve
    through the shared ownership helper instead of accepting only rig/plane
    objects here.
    """
    active = getattr(context, "object", None) if context is not None else None
    if active is None:
        return None
    try:
        rig = fbp_resolve_rig_from_any_object(active, context)
        return rig if rig and getattr(rig, "is_fbp_control", False) else None
    except FBP_DATA_ERRORS:
        return None


def _fbp_collapsible_box(layout, owner, prop_name, label, icon='TRIA_DOWN'):
    """Draw a thin global collapsible section header and return its body box."""
    box = layout.box()
    opened = bool(getattr(owner, prop_name, True))
    row = box.row(align=True)
    row.alignment = "LEFT"
    row.scale_y = 0.72
    row.prop(
        owner,
        prop_name,
        text='',
        icon='DOWNARROW_HLT' if opened else 'RIGHTARROW_THIN',
        emboss=False,
    )
    row.label(text=label, icon=icon)
    return box if opened else None


from .drawing_plane import fbp_is_drawing_rig, draw_drawing_plane_ui
from .ui_layout import (
    draw_creation_ui,
    draw_layer_tree_uilist,
    draw_gp_layer_tree_uilist,
    fbp_layer_tree_row_visible_for_mode,
)
from .ui_list_state import mark_ui_list_draw, transient_get


# SECTION 00B - Quick UI icon map #
# Change icons globally in constants.py > FBP_ICONS.
_FBP_CLIPPING_ENABLED_KEY = str(
    fbp_effect_definition(FBP_EFFECT_CLIPPING_MASK).get(
        'enabled_key', 'fbp_effect_clipping_mask'
    ) or 'fbp_effect_clipping_mask'
)
_FBP_LAYER_BLEND_ENABLED_KEY = str(
    fbp_effect_definition(FBP_EFFECT_LAYER_BLEND).get(
        'enabled_key', 'fbp_effect_layer_blend'
    ) or 'fbp_effect_layer_blend'
)


def _fbp_layer_blend_mode_for_ui(rig):
    """Read the persistent layer-feature hint without traversing shader nodes."""
    try:
        if not bool(rig.get(_FBP_LAYER_BLEND_ENABLED_KEY, False)):
            return 'NORMAL'
        return str(getattr(rig, 'fbp_layer_blend_mode', 'MULTIPLY') or 'MULTIPLY').upper()
    except FBP_DATA_ERRORS:
        return 'NORMAL'


def _fbp_common_layer_blend_mode(rigs):
    """Return the shared mode, or an empty string for a mixed selection."""
    modes = {_fbp_layer_blend_mode_for_ui(rig) for rig in rigs if rig}
    return next(iter(modes)) if len(modes) == 1 else ""


def _fbp_draw_layer_blend_choices(layout, rigs, *, rig_name=""):
    """Draw a hover-friendly multi-column blend mode chooser."""
    common_mode = _fbp_common_layer_blend_mode(rigs)
    if common_mode:
        layout.label(
            text=f"Current: {fbp_layer_blend_short(common_mode)}  {fbp_layer_blend_label(common_mode)}",
            icon="CHECKMARK",
        )
    else:
        layout.label(text="Mixed blend modes", icon="BLANK1")

    grid = layout.row(align=False)
    for definitions in fbp_layer_blend_mode_columns():
        column = grid.column(align=False)
        for definition in definitions:
            mode = str(definition.get("id", "NORMAL") or "NORMAL")
            short = str(definition.get("short", "N") or "N")
            label = str(definition.get("label", mode.title()) or mode.title())
            icon = (
                "CHECKMARK" if common_mode == mode
                else str(definition.get("icon", "NODE_MATERIAL") or "NODE_MATERIAL")
            )
            op = column.operator(
                "fbp.set_layer_blend_mode",
                text=f"{short}   {label}",
                icon=icon,
            )
            op.mode = mode
            op.rig_name = str(rig_name or "")


class FBP_MT_LayerBlendDropdown(Menu):
    bl_idname = "FBP_MT_layer_blend_dropdown"
    bl_label = "Blend"
    bl_description = "Choose a blend mode; the current mode is marked with a check"

    def draw(self, context):
        rigs = get_selected_rigs(context)
        if not rigs:
            self.layout.label(text="Select a Frame By Plane layer", icon="INFO")
            return
        _fbp_draw_layer_blend_choices(self.layout, rigs)


def _fbp_draw_plane_layer_options(layout, context):
    """Draw the plane-layer options without depending on Menu RNA state."""
    layout.operator_context = 'EXEC_DEFAULT'
    sc = getattr(context, 'scene', None)
    if sc is None:
        layout.label(text="No active scene", icon='INFO')
        return

    if hasattr(sc, 'fbp_sort_layers_alpha'):
        layout.prop(sc, 'fbp_sort_layers_alpha', text='Sort A-Z', icon='SORTALPHA')
    if hasattr(sc, 'fbp_show_previews'):
        preview_icon = 'RESTRICT_VIEW_OFF' if bool(getattr(sc, 'fbp_show_previews', False)) else 'RESTRICT_VIEW_ON'
        layout.prop(sc, 'fbp_show_previews', text='Show Plane Previews', icon=preview_icon)

    layout.separator()
    group = layout.operator(
        'fbp.create_layer_collection',
        text='Add Collection / Move Selected',
        icon='COLLECTION_NEW',
    )
    group.name = 'FBP Collection'
    group.mode = 'PLANES'
    duplicate = layout.row(align=False)
    duplicate.enabled = bool(get_selected_rigs(context))
    duplicate.operator(
        'fbp.duplicate_selected_layers',
        text='Duplicate Layer',
        icon=ui_icon('layer.duplicate'),
    )

    active_collection, can_move_in, can_move_out = _fbp_collection_nesting_availability(context, 'PLANES')
    if active_collection is not None:
        move_out = layout.row()
        move_out.enabled = can_move_out
        op = move_out.operator(
            'fbp.move_layer_collection',
            text='Move Collection Out',
            icon='TRIA_LEFT',
        )
        op.action = 'OUT'
        op.collection_name = active_collection.name
        op.list_mode = 'PLANES'
        move_in = layout.row()
        move_in.enabled = can_move_in
        op = move_in.operator(
            'fbp.move_layer_collection',
            text='Move Into Previous Collection',
            icon='TRIA_RIGHT',
        )
        op.action = 'IN'
        op.collection_name = active_collection.name
        op.list_mode = 'PLANES'
        layout.menu(
            'FBP_MT_move_layer_collection_to',
            text='Move To Collection',
            icon='FILE_PARENT',
        )

    layout.operator(
        'fbp.select_all_layers',
        text='Select All Plane Layers',
        icon='PROP_ON',
    )

    try:
        selected_rigs = tuple(get_selected_rigs(context) or ())
    except FBP_DATA_ERRORS:
        selected_rigs = ()
    reverse = layout.row(align=False)
    reverse.enabled = len(selected_rigs) >= 2
    reverse.operator(
        'fbp.reverse_selected_layer_order',
        text='Reverse Selected Plane Order',
        icon='ARROW_LEFTRIGHT',
    )

    layout.separator()
    layout.operator(
        'fbp.sync_collection_colors',
        text='Sync Plane Collection Colors',
        icon='OUTLINER_COLLECTION',
    )
    layout.operator(
        'fbp.repair_all_layer_relations',
        text='Repair Plane Layer Relations',
        icon='FILE_REFRESH',
    )


class FBP_MT_PlaneLayerStackMore(Menu):
    bl_idname = "FBP_MT_plane_layer_stack_more"
    bl_label = "Layer Options"
    bl_description = "Secondary options for Frame By Plane plane layers"

    def draw(self, context):
        _fbp_draw_plane_layer_options(self.layout, context)


def _fbp_draw_gp_layer_options(layout, context):
    layout.operator_context = 'EXEC_DEFAULT'
    group = layout.operator("fbp.create_layer_collection", text="Add Grease Pencil Collection", icon=ui_icon('setup.collection_new'))
    group.name = "FBP GP Collection"
    group.mode = "GP"
    active_collection, can_move_in, can_move_out = _fbp_collection_nesting_availability(context, 'GP')
    if active_collection is not None:
        move_out = layout.row()
        move_out.enabled = can_move_out
        op = move_out.operator("fbp.move_layer_collection", text="Move Collection Out", icon='TRIA_LEFT')
        op.action = 'OUT'
        op.collection_name = active_collection.name
        op.list_mode = 'GP'
        move_in = layout.row()
        move_in.enabled = can_move_in
        op = move_in.operator("fbp.move_layer_collection", text="Move Into Previous Collection", icon='TRIA_RIGHT')
        op.action = 'IN'
        op.collection_name = active_collection.name
        op.list_mode = 'GP'
        layout.menu(
            'FBP_MT_move_layer_collection_to',
            text='Move To Collection',
            icon='FILE_PARENT',
        )
    layout.separator()
    layout.operator("fbp.collapse_gp_canvases_to_one", text="Collapse Selected Canvases", icon=ui_icon('menu.gp_layer'))
    layout.operator("fbp.split_gp_canvas_layers", text="Split Active Grease Pencil Layers", icon=ui_icon("sequence.split"))
    layout.operator("fbp.use_grease_pencil_as_mask", text="Use Active Grease Pencil as Mask", icon='CLIPUV_HLT')

    layout.separator()
    layout.operator("fbp.duplicate_selected_gp_canvases", text="Duplicate Selected Grease Pencil", icon=ui_icon("layer.duplicate"))
    layout.operator("fbp.delete_grease_pencil_canvas", text="Delete Selected Grease Pencil", icon=ui_icon("generic.delete"))

    layout.separator()
    layout.operator("fbp.repair_all_layer_relations", text="Repair Grease Pencil Relations", icon=ui_icon("settings.repair"))


class FBP_MT_GreasePencilLayerStackMore(Menu):
    bl_idname = "FBP_MT_gp_layer_stack_more"
    bl_label = "Grease Pencil Options"
    bl_description = "Secondary options for Frame By Plane Grease Pencil layers"

    def draw(self, context):
        _fbp_draw_gp_layer_options(self.layout, context)


class FBP_MT_MoveLayerCollectionTo(Menu):
    bl_idname = "FBP_MT_move_layer_collection_to"
    bl_label = "Move To Collection"
    bl_description = "Move the active Layer List collection directly below another collection"

    def draw(self, context):
        layout = self.layout
        layout.operator_context = 'EXEC_DEFAULT'
        source, _can_in, _can_out = _fbp_collection_nesting_availability(context)
        scene = getattr(context, 'scene', None)
        root = getattr(scene, 'collection', None) if scene is not None else None
        if source is None or root is None:
            layout.label(text='Select a collection row', icon='INFO')
            return

        tree = fbp_build_canonical_collection_tree(scene)
        child_map = tree.get('children', {}) or {}
        parent_by_key = tree.get('parent_by_key', {}) or {}
        try:
            source_key = int(source.as_pointer())
            root_key = int(root.as_pointer())
        except FBP_DATA_ERRORS:
            layout.label(text='Collection hierarchy unavailable', icon='ERROR')
            return

        descendant_keys = set()
        stack = [source_key]
        while stack:
            current_key = stack.pop()
            if current_key in descendant_keys:
                continue
            descendant_keys.add(current_key)
            for child in child_map.get(current_key, ()):
                try:
                    stack.append(int(child.as_pointer()))
                except FBP_DATA_ERRORS:
                    continue

        current_parent_key = parent_by_key.get(source_key)
        if current_parent_key != root_key:
            op = layout.operator(
                'fbp.move_layer_collection_to',
                text='Top Level',
                icon='SCENE_DATA',
            )
            op.collection_name = source.name
            op.destination_name = ''

        destinations = []

        def collect(parent_key, depth=0):
            for child in child_map.get(parent_key, ()):
                try:
                    child_key = int(child.as_pointer())
                except FBP_DATA_ERRORS:
                    continue
                if child_key not in descendant_keys and child_key != current_parent_key:
                    destinations.append((child, depth))
                collect(child_key, depth + 1)

        collect(root_key, 0)
        if destinations and current_parent_key != root_key:
            layout.separator()
        for destination, depth in destinations:
            label = ('    ' * max(0, min(8, int(depth)))) + destination.name
            op = layout.operator(
                'fbp.move_layer_collection_to',
                text=label,
                icon=fbp_collection_icon(destination, context),
            )
            op.collection_name = source.name
            op.destination_name = destination.name

        if current_parent_key == root_key and not destinations:
            layout.label(text='No other destination is available', icon='INFO')


class FBP_OT_LayerOptionsPopup(Operator):
    """Stable icon-only popup used by both layer lists.

    This deliberately avoids ``layout.menu``/``wm.call_menu`` because stale Menu
    RNA after an in-place add-on reload could create a blank floating popup.
    """

    bl_idname = 'fbp.layer_options_popup'
    bl_label = 'Layer Options'
    bl_description = 'Open secondary layer-list options'
    bl_options = {'INTERNAL'}

    grease_pencil: BoolProperty(
        name='Grease Pencil',
        default=False,
        options={'HIDDEN', 'SKIP_SAVE'},
    )

    def invoke(self, context, _event):
        draw_gp = bool(self.grease_pencil)

        def _draw_popup(popup, popup_context):
            layout = popup.layout
            try:
                if draw_gp:
                    _fbp_draw_gp_layer_options(layout, popup_context)
                else:
                    _fbp_draw_plane_layer_options(layout, popup_context)
            except FBP_DATA_ERRORS as exc:
                fbp_warn('Could not draw Layer Options popup', exc)
                layout.label(text='Layer options are unavailable', icon='ERROR')
                layout.operator('fbp.repair_all_layer_relations', text='Repair Layer Relations', icon='FILE_REFRESH')

        context.window_manager.popup_menu(
            _draw_popup,
            title='Grease Pencil Options' if draw_gp else 'Layer Options',
            icon='NONE',
        )
        return {'FINISHED'}


class FBP_MT_LayerStackMore(FBP_MT_PlaneLayerStackMore):
    # Backward-compatible alias for old calls/add-on state.
    bl_idname = "FBP_MT_layer_stack_more"
    bl_label = "Layer List Options"


# The markers below identify the relevant UI locations.
# ###ICON Panel Layer Stack, Function Preview/Color Tag: preview.icon_id, fbp_strip_icon(rig.fbp_color_tag)
# ###ICON Panel Layer Stack, Function Solo: OUTLINER_OB_LIGHT / LIGHT
# ###ICON Panel Layer Stack, Function Select: CHECKBOX_HLT / CHECKBOX_DEHLT
# ###ICON Panel Layer Stack, Function Clipping Mask: dedicated custom clipping icon
# ###ICON Panel Layer Stack, Function Visibility: HIDE_OFF / HIDE_ON
# ###ICON Panel Layer Stack, Function Lock: LOCKED / UNLOCKED
# ###ICON Panel Sequence, Function Current Frame: RECORD_ON
# ###ICON Panel Sequence, Function Normal Frame: DOT
# ###ICON Panel Sequence, Function Missing File: ERROR
# ###ICON Panel Sequence, Function Transparent Frame: TEXTURE_DATA
# ###ICON Panel Sequence, Function Import/Replace: FILE_FOLDER / FOLDER_REDIRECT
# ###ICON Panel Multiplane Setup, Function Collection: OUTLINER_COLLECTION
# ###ICON Panel Multiplane Setup, Function Collapse: RIGHTARROW / DOWNARROW_HLT
# ###ICON Panel Multiplane Setup, Function Add/Remove: ADD / REMOVE / TRASH
# ###ICON Panel Settings, Function Project Folder: FILE_FOLDER
# ###ICON Panel Settings, Function Import Project: IMPORT
# ###ICON Panel Settings, Function Build Direct: OUTLINER_COLLECTION
# ###ICON Panel Settings, Function Diagnostics: LINKED / ERROR / CHECKMARK / TIME
# ###ICON Panel Settings, Function Background Render: RENDER_ANIMATION
# ###ICON Panel Create, Function Color Plane: MATERIAL / IMAGE
# ###ICON Panel Create, Function Emission: LIGHT_SUN
# ###ICON Panel Create, Function Camera/Fit: RESTRICT_VIEW_ON / FULLSCREEN_ENTER
# ###ICON Menu Shift+A, Function Color Plane: IMAGE
# ###ICON Menu Shift+A, Function Gradient Plane: COLOR
# ###ICON Menu Shift+A, Function Holdout Plane: GHOST_DISABLED
# ###ICON Menu Shift+A, Function Image Plane: IMAGE_DATA
# ###ICON Menu Shift+A, Function Multiplane: RENDER_RESULT


def fbp_layer_backend_icon(rig):
    """Return one stable icon per plane backend for layer-list recognition."""
    backend = fbp_layer_backend_type(rig)
    return {
        'NATIVE_IMAGE': ui_icon('menu.image_plane'),
        'NATIVE_SEQUENCE': ui_icon('sequence.frames'),
        'NATIVE_MOVIE': 'FILE_MOVIE',
        'CUTOUT': ui_icon('menu.cutout_plane'),
        'PROCEDURAL_COLOR': ui_icon('menu.color_plane'),
        'PROCEDURAL_GRADIENT': ui_icon('menu.gradient_plane'),
        'PROCEDURAL_HOLDOUT': ui_icon('menu.holdout_plane'),
    }.get(backend, ui_icon('sequence.normal_frame'))
# ###ICON Menu Render, Function Background Render: RENDER_ANIMATION
#
# Main icon aliases live in ui_icons.py.


_FBP_SHAPE_MASK_EFFECTS = (
    FBP_EFFECT_SQUARE_MASK,
    FBP_EFFECT_CIRCLE_MASK,
    FBP_EFFECT_TRIANGLE_MASK,
)
_FBP_SHAPE_TO_EFFECT = {
    "SQUARE": FBP_EFFECT_SQUARE_MASK,
    "CIRCLE": FBP_EFFECT_CIRCLE_MASK,
    "TRIANGLE": FBP_EFFECT_TRIANGLE_MASK,
}


def _fbp_context_shape_mask_effect(context, rig, listed_effects, active_effect):
    """Return the Shape Mask whose controls should remain immediately visible.

    Selecting the helper should never require manually changing the Effects tab
    or finding the corresponding stack row. Selecting its plane also exposes
    controls automatically when that layer owns a single Shape Mask. The
    function uses the already-built effect list, so it does not rescan shader
    nodes during a UI redraw.
    """
    # ``listed_effects`` is already the synchronized stack mirror. Rechecking
    # each mask through material/modifier presence scans duplicated work during
    # every sidebar redraw and could temporarily disagree during Undo.
    available = tuple(
        effect_id for effect_id in listed_effects
        if effect_id in _FBP_SHAPE_MASK_EFFECTS
    )
    if not available:
        return ""

    active_obj = getattr(context, "active_object", None) if context else None
    selected_objects = tuple(getattr(context, "selected_objects", ()) or ()) if context else ()
    candidates = ([active_obj] if active_obj is not None else []) + [
        obj for obj in selected_objects if obj is not active_obj
    ]
    try:
        from .object_masks import (
            find_object_mask_controller_owner,
            is_object_mask_controller,
            object_mask_controller_shape,
        )
        for candidate in candidates:
            if not is_object_mask_controller(candidate):
                continue
            owner = find_object_mask_controller_owner(candidate)
            effect_id = _FBP_SHAPE_TO_EFFECT.get(
                object_mask_controller_shape(candidate), ""
            )
            if owner is rig and effect_id in available:
                return effect_id
    except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        pass

    if active_effect in available:
        return active_effect
    # A plane can own more than one Shape Mask. Keep at least one set of
    # controls visible, choosing the first mask in the actual stack order; the
    # user can select another helper or stack row to change the context.
    return available[0]

def fbp_draw_procedural_frame_swatch(row, rig, index):
    """Draw a live per-frame procedural preview chip in the Frames UIList."""
    if not rig or not getattr(rig, 'fbp_is_color_plane', False):
        return
    try:
        item = rig.fbp_images[int(index)]
    except (AttributeError, IndexError, ReferenceError, RuntimeError, TypeError, ValueError):
        return
    try:
        chips = row.row(align=True)
        # One-icon procedural types are right-aligned inside the same two-unit
        # preview cell used by solid and gradient chips.  The following name
        # therefore begins immediately after the visible icon on every row.
        chips.alignment = 'RIGHT'
        # UIList redraws are frequent; avoid inspecting the material node tree just
        # to decide which chip to draw.  Frame metadata is the source of truth
        # after the Color/Gradient rewrite. AUTO remains a compact material
        # inference mode for rows without an explicit procedural type.
        kind = str(getattr(item, 'procedural_kind', 'AUTO') or 'AUTO').upper()
        if kind == 'AUTO':
            kind = fbp_procedural_kind_for_item(rig, index, 'SOLID')
        if kind == 'GRADIENT':
            chip_a = chips.row(align=False)
            fbp_set_ui_units_x(chip_a, 1.0)
            chip_a.prop(item, 'preview_color_a', text='')
            chip_b = chips.row(align=False)
            fbp_set_ui_units_x(chip_b, 1.0)
            chip_b.prop(item, 'preview_color_b', text='')
            return
        if kind == 'HOLDOUT':
            chips.label(text='', icon=ui_icon('menu.holdout_plane'))
            return
        chip = chips.row(align=False)
        fbp_set_ui_units_x(chip, 2.0)
        chip.prop(item, 'preview_color_a', text='')
    except FBP_DATA_IO_ERRORS:
        pass


def fbp_draw_layer_tag_and_preview(row, rig, context, inactive=False):
    """Draw thumbnail, otherwise a single overlaid Color Tag + plane type icon."""
    if not rig:
        return

    if (
        not inactive
        and bool(getattr(context.scene, 'fbp_show_previews', False))
        and not bool(getattr(rig, 'fbp_is_color_plane', False))
    ):
        try:
            _type_icon, preview_icon = fbp_layer_row_type_icon(rig, context)
            if preview_icon:
                row.label(text='', icon_value=preview_icon)
                return
        except FBP_DATA_IO_ERRORS:
            pass

    try:
        overlay_icon = fbp_layer_tag_backend_icon_value(rig, inactive=inactive)
        if overlay_icon:
            row.label(text='', icon_value=overlay_icon)
            return
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        pass
    try:
        row.label(text='', icon=fbp_strip_icon(getattr(rig, 'fbp_color_tag', 'NONE')))
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        row.label(text='', icon=ui_icon('layer.color_tag_fallback'))


def _fbp_short_ui_name(name, limit=28):
    """Return a compact UIList label while keeping original datablock names unchanged."""
    value = str(name or "")
    try:
        limit = max(8, int(limit))
    except (TypeError, ValueError, OverflowError):
        limit = 28
    if len(value) <= limit:
        return value
    return value[:max(1, limit - 1)].rstrip() + "…"


def _fbp_draw_icon_placeholder(layout):
    """Reserve one disabled icon cell so UIList action columns stay aligned."""
    cell = layout.row(align=True)
    cell.enabled = False
    cell.label(text='', icon=ui_icon('generic.blank'))
    return cell


def _fbp_tag_all_ui_areas_redraw(context=None):
    """Redraw regular editors and the temporary popup region.

    UIList drag previews live in a temporary region. Tagging only screen areas
    updated the real list behind the dialog but left its own preview frozen.
    """
    current = context or bpy.context
    current_region = getattr(current, "region", None)
    popup_region = getattr(current, "region_popup", None)
    stored_popup_region = globals().get("_FBP_UILIST_POPUP_REGION")
    try:
        if current_region is not None:
            current_region.tag_redraw()
    except (AttributeError, ReferenceError, RuntimeError):
        pass
    try:
        if (
            stored_popup_region is not None
            and stored_popup_region is not current_region
            and stored_popup_region is not popup_region
        ):
            stored_popup_region.tag_redraw()
    except (AttributeError, ReferenceError, RuntimeError):
        globals()["_FBP_UILIST_POPUP_REGION"] = None
    try:
        if popup_region is not None and popup_region is not current_region:
            popup_region.tag_redraw()
    except (AttributeError, ReferenceError, RuntimeError):
        pass
    wm = getattr(current, "window_manager", None)
    for window in tuple(getattr(wm, "windows", ()) or ()):
        screen = getattr(window, "screen", None)
        for area in tuple(getattr(screen, "areas", ()) or ()):
            try:
                area.tag_redraw()
            except (AttributeError, ReferenceError, RuntimeError):
                continue
            # ``area.tag_redraw`` already covers its regular regions. Only
            # temporary regions need an explicit tag (popup/dialog previews).
            for region in tuple(getattr(area, "regions", ()) or ()):
                if str(getattr(region, "type", "") or "") != "TEMPORARY":
                    continue
                if region is current_region:
                    continue
                try:
                    region.tag_redraw()
                except (AttributeError, ReferenceError, RuntimeError):
                    continue
def _fbp_uilist_filter_property(profile_id):
    profile_id = str(profile_id or "").strip().lower()
    return f"fbp_uilist_filter_{profile_id}"


def _fbp_uilist_filter_sort_property(profile_id):
    profile_id = str(profile_id or "").strip().lower()
    return f"fbp_uilist_sort_{profile_id}"


def _fbp_uilist_filter_reverse_property(profile_id):
    profile_id = str(profile_id or "").strip().lower()
    return f"fbp_uilist_reverse_{profile_id}"


def _fbp_ensure_uilist_filter_state(scene, profile_id):
    if scene is None:
        return
    defaults = (
        (_fbp_uilist_filter_property(profile_id), ""),
        (_fbp_uilist_filter_sort_property(profile_id), False),
        (_fbp_uilist_filter_reverse_property(profile_id), False),
    )
    for key, default in defaults:
        try:
            if key not in scene:
                scene[key] = default
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            pass


def fbp_uilist_filter_text(context, profile_id):
    scene = getattr(context, "scene", None)
    if scene is None:
        return ""
    try:
        return str(scene.get(_fbp_uilist_filter_property(profile_id), "") or "").strip().casefold()
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        return ""


def fbp_uilist_sort_options(context, profile_id):
    scene = getattr(context, "scene", None)
    if scene is None:
        return False, False
    try:
        alphabetical = bool(scene.get(_fbp_uilist_filter_sort_property(profile_id), False))
        reverse = bool(scene.get(_fbp_uilist_filter_reverse_property(profile_id), False))
        return alphabetical, reverse
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        return False, False


class FBP_OT_UIListFilterPopup(Operator):
    bl_idname = "fbp.uilist_filter_popup"
    bl_label = "Filter List"
    bl_description = "Search and sort this UI list"
    bl_options = {'INTERNAL'}

    profile: StringProperty(options={'HIDDEN'})

    def invoke(self, context, _event):
        _fbp_ensure_uilist_filter_state(getattr(context, "scene", None), self.profile)
        return context.window_manager.invoke_popup(self, width=300)

    def draw(self, context):
        layout = self.layout
        profile = fbp_uilist_profile_definition(self.profile) or {}
        scene = getattr(context, "scene", None)
        _fbp_ensure_uilist_filter_state(scene, self.profile)
        layout.label(text=str(profile.get("label", "List Filter")), icon="FILTER")
        if scene is None:
            return
        if str(self.profile or "").upper() == "PROJECT_DOCTOR":
            layout.prop(scene, "fbp_health_filter", text="Severity")
        search_key = _fbp_uilist_filter_property(self.profile)
        sort_key = _fbp_uilist_filter_sort_property(self.profile)
        reverse_key = _fbp_uilist_filter_reverse_property(self.profile)
        layout.prop(scene, f'["{search_key}"]', text="", icon="VIEWZOOM")
        row = layout.row(align=True)
        row.prop(scene, f'["{sort_key}"]', text="Alphabetical", toggle=True, icon="SORTALPHA")
        row.prop(scene, f'["{reverse_key}"]', text="Reverse", toggle=True, icon="SORT_DESC")
        reset = layout.operator("fbp.reset_uilist_filter", text="Reset Filter", icon="LOOP_BACK")
        reset.profile = self.profile

    def execute(self, _context):
        return {'FINISHED'}


class FBP_OT_ResetUIListFilter(Operator):
    bl_idname = "fbp.reset_uilist_filter"
    bl_label = "Reset List Filter"
    bl_options = {'INTERNAL'}

    profile: StringProperty(options={'HIDDEN'})

    def execute(self, context):
        scene = getattr(context, "scene", None)
        if scene is not None:
            for key, value in (
                (_fbp_uilist_filter_property(self.profile), ""),
                (_fbp_uilist_filter_sort_property(self.profile), False),
                (_fbp_uilist_filter_reverse_property(self.profile), False),
            ):
                try:
                    scene[key] = value
                except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
                    pass
        _fbp_tag_all_ui_areas_redraw(context)
        return {'FINISHED'}


def _fbp_reopen_uilist_customizer(context, *, restore_cursor=None):
    """Open the temporary customizer block at its original anchor.

    This is used only for the initial open. Subsequent changes refresh the
    existing temporary region in place, so one user action never spawns a
    second popup.
    """
    profile_id = str(
        globals().get("_FBP_UILIST_POPUP_PROFILE", "") or ""
    ).upper()
    if not fbp_uilist_profile_definition(profile_id):
        return False
    window = getattr(context, "window", None)
    anchor = globals().get("_FBP_UILIST_POPUP_ANCHOR")
    if window is not None and anchor:
        try:
            window.cursor_warp(int(anchor[0]), int(anchor[1]))
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            pass
    try:
        result = bpy.ops.wm.call_panel(
            'INVOKE_DEFAULT',
            name="FBP_PT_uilist_columns_popover",
            keep_open=True,
        )
    except (AttributeError, RuntimeError, TypeError, ValueError):
        result = {'CANCELLED'}
    finally:
        if window is not None and restore_cursor:
            try:
                window.cursor_warp(
                    int(restore_cursor[0]), int(restore_cursor[1])
                )
            except (
                AttributeError,
                ReferenceError,
                RuntimeError,
                TypeError,
                ValueError,
            ):
                pass
    # Popup operators commonly return ``INTERFACE`` rather than
    # ``RUNNING_MODAL``; only an explicit cancellation means opening failed.
    return bool(result) and 'CANCELLED' not in result


def _fbp_refresh_uilist_customizer(context):
    """Rebuild the open customizer in its existing TEMPORARY region."""
    candidates = (
        getattr(context, "region_popup", None),
        globals().get("_FBP_UILIST_POPUP_REGION"),
        getattr(context, "region", None),
    )
    refreshed = False
    seen = set()
    for region in candidates:
        if region is None or id(region) in seen:
            continue
        seen.add(id(region))
        if str(getattr(region, "type", "") or "") != "TEMPORARY":
            continue
        try:
            region.tag_refresh_ui()
            region.tag_redraw()
            refreshed = True
        except (AttributeError, ReferenceError, RuntimeError):
            if region is globals().get("_FBP_UILIST_POPUP_REGION"):
                globals()["_FBP_UILIST_POPUP_REGION"] = None
    _fbp_tag_all_ui_areas_redraw(context)
    return refreshed


class FBP_OT_UIListColumnVisibility(Operator):
    bl_idname = "fbp.uilist_column_visibility"
    bl_label = "Toggle List Column"
    bl_options = {'INTERNAL'}

    profile: StringProperty(options={'HIDDEN'})
    column_key: StringProperty(options={'HIDDEN'})

    @classmethod
    def description(cls, _context, properties):
        key = str(getattr(properties, "column_key", "") or "")
        label = UILIST_COLUMN_DEFINITIONS.get(key, (key or "control", ""))[0]
        return f"Show or hide {label} in this list row"

    def _apply(self, context, restore_cursor=None):
        if self.column_key == "label":
            return {'FINISHED'}
        prefs = fbp_get_addon_preferences(context)
        flags = fbp_uilist_icon_flags(context, self.profile)
        visible = {
            key for key in fbp_uilist_profile_columns(self.profile)
            if bool(flags.get(key, True))
        }
        if self.column_key in visible:
            visible.discard(self.column_key)
        else:
            visible.add(self.column_key)
        fbp_set_uilist_profile_visibility(prefs, self.profile, visible)
        _fbp_refresh_uilist_customizer(context)
        return {'FINISHED'}

    def invoke(self, context, event):
        return self._apply(
            context,
            restore_cursor=(int(event.mouse_x), int(event.mouse_y)),
        )

    def execute(self, context):
        return self._apply(context)


def _fbp_reorder_visible_uilist_columns(
    original_order,
    original_visible_order,
    origin_index,
    target_index,
):
    """Move one visible column while preserving hidden-column positions."""
    original_order = tuple(original_order or ())
    visible_order = list(original_visible_order or ())
    if not visible_order:
        return original_order
    origin_index = max(0, min(len(visible_order) - 1, int(origin_index)))
    target_index = max(0, min(len(visible_order) - 1, int(target_index)))
    key = visible_order.pop(origin_index)
    visible_order.insert(target_index, key)
    moved_visible = iter(visible_order)
    visible_keys = set(original_visible_order or ())
    return tuple(
        next(moved_visible) if item in visible_keys else item
        for item in original_order
    )


class FBP_OT_UIListColumnDrag(Operator):
    bl_idname = "fbp.uilist_column_drag"
    bl_label = "Drag List Column"
    bl_options = {'INTERNAL'}

    profile: StringProperty(options={'HIDDEN'})
    column_key: StringProperty(options={'HIDDEN'})

    @classmethod
    def description(cls, _context, properties):
        key = str(getattr(properties, "column_key", "") or "")
        label = UILIST_COLUMN_DEFINITIONS.get(key, (key or "item", ""))[0]
        return f"Drag {label} left or right to move it in this row"

    def _redraw(self, context):
        # Modal mouse events may leave the dialog and make ``context.region``
        # point back to the editor. Keep the original temporary region alive
        # so the concrete popup preview continues to move under the cursor.
        popup_region = getattr(self, "_popup_region", None)
        if popup_region is not None:
            try:
                popup_region.tag_refresh_ui()
                popup_region.tag_redraw()
            except (AttributeError, ReferenceError, RuntimeError):
                self._popup_region = None
        _fbp_tag_all_ui_areas_redraw(context)

    def _finish(self, context, *, commit):
        preview_order = tuple(fbp_uilist_icon_order(context, self.profile))
        fbp_clear_uilist_drag_preview(self.profile)
        prefs = fbp_get_addon_preferences(context)
        if commit:
            fbp_set_uilist_profile_order(prefs, self.profile, preview_order)
        _FBP_UILIST_DRAG_ACTIVE["profile"] = ""
        _FBP_UILIST_DRAG_ACTIVE["column_key"] = ""
        try:
            context.window.cursor_modal_restore()
        except (AttributeError, RuntimeError):
            pass
        self._redraw(context)

    def invoke(self, context, event):
        full_order = list(fbp_uilist_icon_order(context, self.profile))
        flags = fbp_uilist_icon_flags(context, self.profile)
        visible_order = [
            key for key in full_order
            if key == "label" or bool(flags.get(key, True))
        ]
        if self.column_key not in visible_order:
            return {'CANCELLED'}
        self._original_order = tuple(full_order)
        self._original_visible_order = tuple(visible_order)
        self._origin_index = visible_order.index(self.column_key)
        self._start_x = int(event.mouse_x)
        self._last_mouse = (
            int(getattr(event, "mouse_x", 0)),
            int(getattr(event, "mouse_y", 0)),
        )
        self._last_target = self._origin_index
        region_popup = (
            getattr(context, "region_popup", None)
            or globals().get("_FBP_UILIST_POPUP_REGION")
        )
        current_region = getattr(context, "region", None)
        self._popup_region = region_popup or (
            current_region
            if str(getattr(current_region, "type", "") or "") == "TEMPORARY"
            else None
        )
        _FBP_UILIST_DRAG_ACTIVE["profile"] = str(self.profile or "").upper()
        _FBP_UILIST_DRAG_ACTIVE["column_key"] = str(self.column_key or "")
        fbp_set_uilist_drag_preview(self.profile, full_order)
        try:
            context.window.cursor_modal_set("SCROLL_X")
        except (AttributeError, RuntimeError, TypeError, ValueError):
            pass
        context.window_manager.modal_handler_add(self)
        self._redraw(context)
        return {'RUNNING_MODAL'}

    def modal(self, context, event):
        if event.type == 'MOUSEMOVE':
            self._last_mouse = (
                int(getattr(event, "mouse_x", 0)),
                int(getattr(event, "mouse_y", 0)),
            )
            delta = int(round((int(event.mouse_x) - self._start_x) / 28.0))
            target = max(
                0,
                min(
                    len(self._original_visible_order) - 1,
                    self._origin_index + delta,
                ),
            )
            if target != self._last_target:
                merged_order = _fbp_reorder_visible_uilist_columns(
                    self._original_order,
                    self._original_visible_order,
                    self._origin_index,
                    target,
                )
                fbp_set_uilist_drag_preview(self.profile, merged_order)
                self._last_target = target
                self._redraw(context)
            return {'RUNNING_MODAL'}
        if event.type in {'LEFTMOUSE', 'RET', 'NUMPAD_ENTER'} and event.value == 'RELEASE':
            self._finish(context, commit=True)
            return {'FINISHED'}
        if event.type in {'RIGHTMOUSE', 'ESC'}:
            fbp_clear_uilist_drag_preview(self.profile)
            self._finish(context, commit=False)
            return {'CANCELLED'}
        return {'RUNNING_MODAL'}


class FBP_OT_UIListColumnsReset(Operator):
    bl_idname = "fbp.uilist_columns_reset"
    bl_label = "Reset List Columns"
    bl_options = {'INTERNAL'}

    profile: StringProperty(options={'HIDDEN'})

    def _apply(self, context, restore_cursor=None):
        profile = fbp_uilist_profile_definition(self.profile) or {}
        columns = tuple(profile.get("columns", ()))
        prefs = fbp_get_addon_preferences(context)
        fbp_set_uilist_profile_order(prefs, self.profile, columns)
        fbp_set_uilist_profile_visibility(prefs, self.profile, columns)
        _fbp_refresh_uilist_customizer(context)
        return {'FINISHED'}

    def invoke(self, context, event):
        return self._apply(
            context,
            restore_cursor=(int(event.mouse_x), int(event.mouse_y)),
        )

    def execute(self, context):
        return self._apply(context)


class FBP_OT_UIListLabelAlignment(Operator):
    bl_idname = "fbp.uilist_label_alignment"
    bl_label = "Align List Name"
    bl_options = {'INTERNAL'}

    profile: StringProperty(options={'HIDDEN'})
    alignment: EnumProperty(
        items=(
            ('LEFT', "Left", "Align the row name left"),
            ('CENTER', "Center", "Align the row name to the center"),
            ('RIGHT', "Right", "Align the row name right"),
        ),
        options={'HIDDEN'},
    )

    def _apply(self, context, restore_cursor=None):
        prefs = fbp_get_addon_preferences(context)
        if prefs is None:
            return {'CANCELLED'}
        prefs.uilist_label_alignment = str(self.alignment or "LEFT")
        clear_interface_preferences_cache()
        _fbp_refresh_uilist_customizer(context)
        return {'FINISHED'}

    def invoke(self, context, event):
        return self._apply(
            context,
            restore_cursor=(int(event.mouse_x), int(event.mouse_y)),
        )

    def execute(self, context):
        return self._apply(context)


def _fbp_draw_uilist_columns_customizer(layout, context, profile_id):
    """Draw the shared, live UIList-row customizer inside a keep-open panel."""
    profile_id = str(profile_id or "").upper()
    profile = fbp_uilist_profile_definition(profile_id) or {}
    layout.label(
        text=str(profile.get("label", "List Row")),
        icon=str(profile.get("icon", "PRESET")),
    )
    flags = fbp_uilist_icon_flags(context, profile_id)
    visible = {
        key for key in fbp_uilist_profile_columns(profile_id)
        if bool(flags.get(key, True))
    }
    order = tuple(fbp_uilist_icon_order(context, profile_id))

    toggle_box = layout.box()
    toggle_box.label(text="Visible controls", icon="HIDE_OFF")
    toggle_row = toggle_box.row(align=True)
    toggle_row.alignment = "LEFT"
    for key in order:
        if key == "label":
            continue
        toggle = toggle_row.operator(
            "fbp.uilist_column_visibility",
            text="",
            emboss=True,
            depress=key in visible,
            **fbp_uilist_column_icon_kwargs(
                key,
                active=key in visible,
                profile_id=profile_id,
            ),
        )
        toggle.profile = profile_id
        toggle.column_key = key

    fbp_draw_uilist_profile_preview(
        layout, context, profile_id, draggable=True
    )

    settings = layout.row(align=True)
    settings.label(text="Name")
    active_alignment = fbp_uilist_label_alignment(context)
    for identifier, label in (
        ('LEFT', "Left"),
        ('CENTER', "Center"),
        ('RIGHT', "Right"),
    ):
        align = settings.operator(
            "fbp.uilist_label_alignment",
            text=label,
            depress=active_alignment == identifier,
        )
        align.profile = profile_id
        align.alignment = identifier
    reset = settings.operator(
        "fbp.uilist_columns_reset", text="", icon="LOOP_BACK"
    )
    reset.profile = profile_id


class FBP_PT_UIListColumnsPopover(Panel):
    """Dynamically redrawn popover so drag previews move under the cursor."""

    bl_idname = "FBP_PT_uilist_columns_popover"
    bl_label = "Customize List Row"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'WINDOW'
    bl_ui_units_x = 24

    @classmethod
    def poll(cls, _context):
        return bool(
            fbp_uilist_profile_definition(
                globals().get("_FBP_UILIST_POPUP_PROFILE", "")
            )
        )

    def draw(self, context):
        popup_region = getattr(context, "region_popup", None)
        if popup_region is None:
            candidate = getattr(context, "region", None)
            if str(getattr(candidate, "type", "") or "") == "TEMPORARY":
                popup_region = candidate
        if popup_region is not None:
            globals()["_FBP_UILIST_POPUP_REGION"] = popup_region
        _fbp_draw_uilist_columns_customizer(
            self.layout,
            context,
            globals().get("_FBP_UILIST_POPUP_PROFILE", ""),
        )


class FBP_OT_UIListColumnsPopup(Operator):
    bl_idname = "fbp.uilist_columns_popup"
    bl_label = "Customize List Row"
    bl_description = "Reorder the label and visible row controls"
    bl_options = {'INTERNAL'}

    profile: StringProperty(options={'HIDDEN'})

    def _open(self, context, event=None):
        profile_id = str(self.profile or "").upper()
        if not fbp_uilist_profile_definition(profile_id):
            return {'CANCELLED'}
        globals()["_FBP_UILIST_POPUP_PROFILE"] = profile_id
        globals()["_FBP_UILIST_POPUP_REGION"] = None
        if event is not None:
            globals()["_FBP_UILIST_POPUP_ANCHOR"] = (
                int(event.mouse_x),
                int(event.mouse_y),
            )
        if not _fbp_reopen_uilist_customizer(context):
            globals()["_FBP_UILIST_POPUP_PROFILE"] = ""
            return {'CANCELLED'}
        return {'FINISHED'}

    def invoke(self, context, event):
        return self._open(context, event)

    def execute(self, context):
        return self._open(context)


def _fbp_draw_uilist_header_controls(header, context, profile_id, *, native_layer_filter=False):
    """Draw the shared Filter and THREE_DOTS controls used by sidebar UILists."""
    controls = header.row(align=True)
    controls.alignment = "RIGHT"
    filter_cell = controls.row(align=True)
    fbp_set_ui_units_x(filter_cell, 5.75)
    if native_layer_filter:
        filter_cell.popover(
            panel="FBP_PT_layer_filters_popover",
            text="Filter",
            icon="FILTER",
        )
    else:
        filter_op = filter_cell.operator(
            "fbp.uilist_filter_popup",
            text="Filter",
            icon="FILTER",
        )
        filter_op.profile = profile_id
    columns = controls.operator(
        "fbp.uilist_columns_popup",
        text="",
        icon="THREE_DOTS",
    )
    columns.profile = profile_id


# SECTION 01 - UIList: Layer Stack #
# ###ICON Panel Layer Stack, Functions: thumbnail, color tag, solo, select, holdout, visibility, lock.
class FBP_UL_LayerStack(UIList):
    def filter_items(self, context, data, propname):
        mark_ui_list_draw()
        objs = getattr(data, propname)
        flt_flags = []
        flt_neworder = list(range(len(objs)))
        if getattr(context.scene, 'fbp_sort_layers_alpha', False):
            flt_neworder.sort(key=lambda i: natural_sort_key(getattr(getattr(objs[i], 'obj', None), 'name', '')))
        else:
            depth_ctx = fbp_make_depth_context_cache(context)
            depth_cache = {}
            for i, item in enumerate(objs):
                rig = getattr(item, 'obj', None)
                depth_cache[i] = fbp_layer_depth_value_from_cache(rig, depth_ctx)
            # Physical depth is the only real ordering criterion.  Equal-depth
            # layers keep Scene.fbp_layers order instead of jumping alphabetically.
            flt_neworder.sort(key=lambda i: (depth_cache.get(i, 0.0), i))
        for item in objs:
            visible = is_layer_item_visible_in_collections(context, item)
            flt_flags.append(self.bitflag_filter_item if visible else 0)
        return flt_flags, flt_neworder

    def draw_item(self, context, layout, data, item, icon, _active_data, _active_propname, index):
        mark_ui_list_draw()
        try:
            rig = item.obj
            if not rig or not is_fbp_layer_object(rig):
                layout.label(text="<Deleted Layer>")
                return
            flags = fbp_uilist_icon_flags(context, 'LAYER_PLANES')
            order = fbp_uilist_icon_order(context, 'LAYER_PLANES')
            row = layout.row(align=True)
            for key in order:
                if not flags.get(key, False):
                    continue
                if fbp_uilist_is_spacer(key):
                    fbp_draw_uilist_spacer(row)
                    continue
                if key == 'preview':
                    fbp_draw_layer_tag_and_preview(
                        row, rig, context,
                        inactive=(not bool(getattr(rig, 'fbp_is_visible', True)) or bool(getattr(item, 'rig_locked', False))),
                    )
                elif key == 'clipping':
                    clipping = row.operator(
                        'fbp.toggle_clipping_mask', text='', emboss=False,
                        **clipping_mask_icon_kwargs(fbp_layer_clipping_active_hint(rig)),
                    )
                    clipping.rig_name = rig.name
                elif key == 'label':
                    label = row.operator('fbp.ui_list_name_action', text=rig.name, emboss=False)
                    label.target_type = 'LAYER'
                    label.rig_name = rig.name
                    label.index = index
                elif key == 'solo':
                    row.prop(item, 'solo_view', text='', icon=ui_icon('layer.solo_on') if item.solo_view else ui_icon('layer.solo_off'), emboss=False)
                elif key == 'select':
                    row.prop(item, 'selected', text='', icon=ui_icon('layer.select_on') if item.selected else ui_icon('layer.select_off'), emboss=False)
                elif key == 'holdout':
                    op = row.operator('fbp.toggle_layer_holdout', text='', emboss=False, depress=bool(item.holdout), **ui_icon_kwargs('menu.holdout_plane', fallback='CLIPUV_HLT'))
                    op.rig_name = rig.name
                elif key == 'motion':
                    try:
                        has_motion = len(getattr(rig, 'fbp_motions', ())) > 0 or bool(rig.get('fbp_motion_effect_container', False))
                    except Exception:
                        has_motion = False
                    if has_motion and hasattr(rig, 'fbp_motion_master_enabled'):
                        row.prop(rig, 'fbp_motion_master_enabled', text='', icon='HIDE_OFF' if getattr(rig, 'fbp_motion_master_enabled', True) else 'HIDE_ON', icon_only=True, emboss=False)
                    else:
                        _fbp_draw_icon_placeholder(row)
                elif key == 'visibility':
                    row.prop(rig, 'fbp_is_visible', text='', icon=ui_icon('layer.visible_on') if rig.fbp_is_visible else ui_icon('layer.visible_off'), icon_only=True, emboss=False)
                elif key == 'lock':
                    row.prop(item, 'rig_locked', text='', icon=ui_icon('layer.lock_on') if item.rig_locked else ui_icon('layer.lock_off'), emboss=False)
        except ReferenceError:
            layout.label(text="<Deleted Layer>")


def _fbp_layer_tree_uilist_mode(uilist):
    name = type(uilist).__name__
    if name == 'FBP_UL_LayerTreePlanesList':
        return 'PLANES'
    if name == 'FBP_UL_GreasePencilLayerList':
        return 'GP'
    return 'ALL'


_FBP_LAYER_REORDER_PREVIEW_KEY = "fbp.layer_reorder_preview"


def _fbp_preview_display_item(context, item, index, list_mode):
    """Resolve a shadow UI row while a modal drag is active.

    The backing CollectionProperty is never reordered during MOUSEMOVE. Only
    the datablock represented by this draw slot and its indentation are swapped
    through primitive transient data.
    """
    scene = getattr(context, "scene", None)
    preview = transient_get(scene, _FBP_LAYER_REORDER_PREVIEW_KEY, None) if scene is not None else None
    if not isinstance(preview, dict):
        return item, None
    if str(preview.get("mode", "") or "").upper() != str(list_mode or "").upper():
        return item, None
    overrides = preview.get("row_overrides", {})
    if not isinstance(overrides, dict):
        return item, None
    override = overrides.get(str(int(index)))
    if not isinstance(override, dict):
        return item, None
    try:
        source_index = int(override.get("source_tree_index", index))
        rows = getattr(scene, "fbp_layer_tree_rows", ()) or ()
        if not (0 <= source_index < len(rows)):
            return item, None
        source_item = rows[source_index]
        depth = max(0, min(10, int(override.get("depth", getattr(source_item, "depth", 0)) or 0)))
        return source_item, depth
    except FBP_DATA_ERRORS:
        return item, None



def _fbp_collection_state_button(layout, item, state, *, icon, enabled=True):
    cell = layout.row(align=True)
    cell.enabled = bool(enabled)
    op = cell.operator('fbp.toggle_collection_state', text='', icon=icon, emboss=False)
    op.collection_name = str(getattr(item, 'collection_name', '') or '')
    op.state = str(state)
    return op


def _fbp_collection_snapshot_icon(item):
    return fbp_collection_color_icon(
        str(getattr(item, 'collection_color_tag', 'NONE') or 'NONE')
    )


class FBP_UL_LayerTreeList(UIList):
    """True Blender UIList tree for the Layers panel.

    Layer and collection names stay left-aligned; action icons sit in a fixed
    right-side strip. This gives a stable
    visual column for Solo/Holdout/Plane Lock/Lock/Select while keeping the eye
    as the first icon on every row. Clipping Mask control sits immediately before the layer name, while
    mask/blend badges stay compact after the name.
    """

    def draw_item(self, context, layout, data, item, icon, _active_data, _active_propname, index):
        mark_ui_list_draw()
        if item is None:
            return

        list_mode = _fbp_layer_tree_uilist_mode(self)
        item, preview_depth = _fbp_preview_display_item(context, item, index, list_mode)
        row_type = getattr(item, 'row_type', 'LAYER')
        depth = (
            preview_depth
            if preview_depth is not None
            else max(0, min(10, int(getattr(item, 'depth', 0))))
        )
        profile_id = 'LAYER_GP' if list_mode == 'GP' else 'LAYER_PLANES'
        flags = fbp_uilist_icon_flags(context, profile_id)
        profile_order = fbp_uilist_icon_order(context, profile_id)
        unsupported_columns = (
            {'clipping', 'motion'}
            if row_type == 'GROUP'
            else (
                {'clipping', 'holdout', 'motion'}
                if row_type == 'GP_CANVAS'
                else set()
            )
        )
        row_order = tuple(
            key
            for key in profile_order
            if key not in unsupported_columns or fbp_uilist_is_spacer(key)
        )
        zones = fbp_uilist_row_layouts(
            layout,
            context,
            profile_id,
            order=row_order,
            leading_units=depth + (1 if row_type == 'GROUP' else 0),
        )
        row = zones["row"]
        targets = zones["targets"]

        if row_type == 'GROUP':
            coll_name = str(
                getattr(item, 'collection_name', '')
                or getattr(item, 'name', '')
                or ''
            )
            if not coll_name:
                row.label(text='', icon=ui_icon('generic.error'))
                row.label(text=getattr(item, 'name', '') or 'Missing Collection')
                return

            drag_cell = zones["left"].row(align=True)
            drag_cell.enabled = not layer_filter_is_active(context.scene)
            drag = drag_cell.operator(
                'fbp.drag_layer_collection', text='', icon='GRIP_V', emboss=False,
            )
            drag.tree_index = index
            drag.collection_name = coll_name
            drag.list_mode = list_mode

            for _ in range(depth):
                zones["left"].label(text='', icon=ui_icon('generic.blank'))

            fold = zones["left"].operator(
                'fbp.toggle_collection_collapse',
                text='',
                icon=(
                    ui_icon('setup.collapsed')
                    if bool(getattr(item, 'collection_collapsed', False))
                    else ui_icon('setup.expanded')
                ),
                emboss=False,
            )
            fold.collection_name = coll_name

            for key in row_order:
                if not flags.get(key, False):
                    continue
                target = targets.get(key, zones["right"])
                if fbp_uilist_is_spacer(key):
                    fbp_draw_uilist_spacer(target)
                    continue
                if key == 'preview':
                    target.label(text='', icon=_fbp_collection_snapshot_icon(item))
                elif key == 'label':
                    op_sel = target.operator(
                        'fbp.ui_list_name_action', text=coll_name, emboss=False,
                    )
                    op_sel.target_type = 'COLLECTION'
                    op_sel.collection_name = coll_name
                    op_sel.tree_index = index
                    op_sel.list_mode = list_mode
                elif key == 'visibility':
                    _fbp_collection_state_button(
                        target, item, 'VISIBLE',
                        icon=(
                            ui_icon('layer.visible_on')
                            if bool(getattr(item, 'collection_visible', True))
                            else ui_icon('layer.visible_off')
                        ),
                    )
                elif key == 'solo':
                    _fbp_collection_state_button(
                        target, item, 'SOLO',
                        icon=(
                            ui_icon('layer.solo_on')
                            if bool(getattr(item, 'collection_solo', False))
                            else ui_icon('layer.solo_off')
                        ),
                    )
                elif key == 'holdout':
                    _fbp_collection_state_button(
                        target, item, 'HOLDOUT',
                        icon=(
                            ui_icon('layer.clipping_on')
                            if bool(getattr(item, 'collection_holdout', False))
                            else ui_icon('layer.clipping_off')
                        ),
                    )
                elif key == 'plane':
                    _fbp_collection_state_button(
                        target, item, 'PLANE_LOCK',
                        icon=(
                            'RESTRICT_SELECT_ON'
                            if bool(getattr(item, 'collection_plane_locked', True))
                            else 'RESTRICT_SELECT_OFF'
                        ),
                    )
                elif key == 'lock':
                    _fbp_collection_state_button(
                        target, item, 'LOCK',
                        icon=(
                            ui_icon('layer.lock_on')
                            if bool(getattr(item, 'collection_locked', False))
                            else ui_icon('layer.lock_off')
                        ),
                    )
                elif key == 'select':
                    locked = bool(getattr(item, 'collection_locked', False))
                    _fbp_collection_state_button(
                        target, item, 'SELECT', enabled=not locked,
                        icon=(
                            ui_icon('layer.select_on')
                            if bool(getattr(item, 'collection_selected', False))
                            else ui_icon('layer.select_off')
                        ),
                    )
            return

        if row_type == 'GP_CANVAS':
            canvas_name = getattr(item, 'canvas_name', '') or getattr(item, 'name', '')
            canvas = bpy.data.objects.get(canvas_name) if canvas_name else None
            if not is_gp_drawing_canvas(canvas):
                row.label(text='', icon=ui_icon('generic.error'))
                row.label(text=getattr(item, 'name', '') or '<Deleted Grease Pencil>')
                return

            visible = bool(getattr(canvas, 'fbp_gp_canvas_visible', True))
            locked = bool(getattr(canvas, 'hide_select', False))
            selected = bool(canvas.select_get())
            owner = gp_canvas_owner(canvas)

            drag_cell = zones["left"].row(align=True)
            drag_cell.enabled = not layer_filter_is_active(context.scene)
            drag = drag_cell.operator(
                'fbp.drag_layer_tree', text='', icon='GRIP_V', emboss=False,
            )
            drag.tree_index = index
            drag.rig_name = canvas.name
            drag.list_mode = list_mode

            for _ in range(depth):
                zones["left"].label(text='', icon=ui_icon('generic.blank'))

            for key in row_order:
                if not flags.get(key, False):
                    continue
                target = targets.get(key, zones["right"])
                if fbp_uilist_is_spacer(key):
                    fbp_draw_uilist_spacer(target)
                    continue
                if key == 'preview':
                    preview_cell = target.row(align=True)
                    preview_cell.active = visible and not locked
                    gp_color_tag = str(
                        getattr(canvas, 'fbp_color_tag', '')
                        or getattr(owner, 'fbp_color_tag', '')
                        or ''
                    )
                    gp_icon_value = layer_custom_icon_value(
                        'GP_CANVAS',
                        gp_color_tag,
                        inactive=not (visible and not locked),
                    )
                    if gp_icon_value:
                        preview_cell.label(text='', icon_value=gp_icon_value)
                    else:
                        preview_cell.label(text='', **ui_label_icon_kwargs('menu.gp_layer'))
                elif key == 'label':
                    target.active = visible and not locked
                    name = target.operator(
                        'fbp.ui_list_name_action',
                        text=canvas.name,
                        emboss=False,
                    )
                    name.target_type = 'GP_CANVAS'
                    name.rig_name = canvas.name
                    name.tree_index = index
                    name.list_mode = list_mode
                elif key == 'visibility':
                    target.prop(
                        canvas, 'fbp_gp_canvas_visible', text='',
                        icon=ui_icon('layer.visible_on') if visible else ui_icon('layer.visible_off'),
                        icon_only=True, emboss=False,
                    )
                elif key == 'solo':
                    solo = target.operator(
                        'fbp.toggle_gp_canvas_solo', text='',
                        icon=ui_icon('layer.solo_on') if gp_canvas_solo_active(canvas) else ui_icon('layer.solo_off'),
                        emboss=False,
                    )
                    solo.canvas_name = canvas.name
                elif key == 'plane':
                    link = target.operator(
                        'fbp.link_grease_pencil_canvas', text='',
                        icon='LINKED' if owner is not None else 'UNLINKED',
                        emboss=False,
                    )
                    link.canvas_name = canvas.name
                elif key == 'lock':
                    target.prop(
                        canvas, 'fbp_gp_canvas_locked', text='',
                        icon=ui_icon('layer.lock_on') if locked else ui_icon('layer.lock_off'),
                        icon_only=True, emboss=False,
                    )
                elif key == 'select':
                    select_cell = target.row(align=True)
                    select_cell.enabled = not locked
                    select_cell.prop(
                        canvas, 'fbp_gp_canvas_selected', text='',
                        icon=fbp_select_rig_icon(locked, selected),
                        icon_only=True, emboss=False,
                    )
            return

        rig_name = getattr(item, 'rig_name', '') or getattr(item, 'name', '')
        rig = bpy.data.objects.get(rig_name) if rig_name else None
        layer_item = None
        try:
            layer_index = int(getattr(item, 'layer_index', -1))
            scene_layers = context.scene.fbp_layers
            if 0 <= layer_index < len(scene_layers):
                indexed_item = scene_layers[layer_index]
                indexed_rig = getattr(indexed_item, 'obj', None)
                if rig is not None and indexed_rig == rig:
                    layer_item = indexed_item
                elif rig is None and indexed_rig and is_fbp_layer_object(indexed_rig):
                    rig = indexed_rig
                    layer_item = indexed_item
        except FBP_DATA_ERRORS:
            layer_item = None
        if rig is not None and layer_item is None:
            layer_item = get_layer_item_for_rig(context, rig)
        if not rig or not layer_item or not is_fbp_layer_object(rig):
            row.label(text='', icon=ui_icon('generic.error'))
            row.label(text=getattr(item, 'name', '') or '<Deleted Layer>')
            return

        drag_cell = zones["left"].row(align=True)
        drag_cell.enabled = not layer_filter_is_active(context.scene)
        drag = drag_cell.operator(
            'fbp.drag_layer_tree', text='', icon='GRIP_V', emboss=False,
        )
        drag.tree_index = index
        drag.rig_name = rig.name
        drag.list_mode = list_mode

        for _ in range(depth):
            zones["left"].label(text='', icon=ui_icon('generic.blank'))

        try:
            content_enabled = (
                bool(getattr(rig, 'fbp_is_visible', True))
                and not bool(layer_item.rig_locked)
            )
        except FBP_DATA_IO_ERRORS:
            content_enabled = True

        for key in row_order:
            if not flags.get(key, False):
                continue
            target = targets.get(key, zones["right"])
            if fbp_uilist_is_spacer(key):
                fbp_draw_uilist_spacer(target)
                continue
            if key == 'preview':
                preview_cell = target.row(align=True)
                preview_cell.active = content_enabled
                fbp_draw_layer_tag_and_preview(
                    preview_cell, rig, context, inactive=not content_enabled
                )
            elif key == 'clipping':
                clipping_active = fbp_layer_clipping_active_hint(rig)
                clipping = target.operator(
                    'fbp.toggle_clipping_mask',
                    text='',
                    emboss=False,
                    **clipping_mask_icon_kwargs(clipping_active),
                )
                clipping.rig_name = rig.name
            elif key == 'label':
                target.active = content_enabled
                op_name = target.operator(
                    'fbp.ui_list_name_action',
                    text=rig.name,
                    emboss=False,
                )
                op_name.target_type = 'LAYER'
                op_name.rig_name = rig.name
                op_name.tree_index = index
                op_name.list_mode = list_mode
            elif key == 'visibility':
                vis_icon = (
                    ui_icon('layer.visible_on')
                    if getattr(rig, 'fbp_is_visible', True)
                    else ui_icon('layer.visible_off')
                )
                target.prop(
                    rig, 'fbp_is_visible', text='',
                    icon=vis_icon, icon_only=True, emboss=False,
                )
            elif key == 'solo':
                solo_icon = (
                    ui_icon('layer.solo_on')
                    if layer_item.solo_view else ui_icon('layer.solo_off')
                )
                target.prop(
                    layer_item, 'solo_view', text='',
                    icon=solo_icon, icon_only=True, emboss=False,
                )
            elif key == 'holdout':
                target.prop(
                    layer_item, 'holdout', text='',
                    icon_only=True, emboss=False,
                    **ui_icon_kwargs("menu.holdout_plane", fallback="CLIPUV_HLT"),
                )
            elif key == 'motion':
                try:
                    has_motion = (
                        len(getattr(rig, 'fbp_motions', ())) > 0
                        or bool(rig.get('fbp_motion_effect_container', False))
                    )
                except Exception:
                    has_motion = False
                if has_motion and hasattr(rig, 'fbp_motion_master_enabled'):
                    target.prop(
                        rig, 'fbp_motion_master_enabled', text='',
                        icon='HIDE_OFF' if getattr(rig, 'fbp_motion_master_enabled', True) else 'HIDE_ON',
                        icon_only=True, emboss=False,
                    )
                else:
                    _fbp_draw_icon_placeholder(target)
            elif key == 'plane':
                op_plane = target.operator(
                    'fbp.select_linked_plane', text='',
                    icon=fbp_select_plane_icon(rig, context), emboss=False,
                )
                op_plane.rig_name = rig.name
            elif key == 'lock':
                lock_icon = (
                    ui_icon('layer.lock_on')
                    if layer_item.rig_locked else ui_icon('layer.lock_off')
                )
                target.prop(
                    layer_item, 'rig_locked', text='',
                    icon=lock_icon, icon_only=True, emboss=False,
                )
            elif key == 'select':
                select_cell = target.row(align=True)
                select_cell.enabled = not layer_item.rig_locked
                select_cell.prop(
                    layer_item, 'selected', text='',
                    icon=fbp_select_rig_icon(layer_item.rig_locked, rig.select_get()),
                    icon_only=True, emboss=False,
                )


class FBP_UL_LayerTreePlanesList(UIList):
    """Layer tree UIList that shows only FBP plane rows and collections.

    Grease Pencil rows now have their own UIList so GP-specific controls do not
    have to pretend to support every mesh-plane column. Blender RNA classes
    cannot safely derive from another registered Python UIList, so this class
    delegates row drawing instead of inheriting from FBP_UL_LayerTreeList.
    """

    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        mark_ui_list_draw()
        return FBP_UL_LayerTreeList.draw_item(
            self, context, layout, data, item, icon, active_data, active_propname, index
        )

    def filter_items(self, context, data, propname):
        mark_ui_list_draw()
        items = getattr(data, propname)
        flags = filter_layer_tree_items(
            context,
            items,
            "PLANES",
            self.bitflag_filter_item,
        )
        return flags, []


class FBP_UL_GreasePencilLayerList(UIList):
    """Grease Pencil rows with a fixed left grip and ordered columns."""

    def filter_items(self, context, data, propname):
        mark_ui_list_draw()
        items = getattr(data, propname)
        flags = filter_layer_tree_items(context, items, "GP", self.bitflag_filter_item)
        return flags, []

    def draw_item(self, context, layout, data, item, icon, _active_data, _active_propname, index):
        mark_ui_list_draw()
        if item is None:
            return
        flags = fbp_uilist_icon_flags(context, 'LAYER_GP')
        order = fbp_uilist_icon_order(context, 'LAYER_GP')
        row_type = str(getattr(item, 'row_type', '') or '')
        depth = max(0, int(getattr(item, 'depth', 0) or 0))
        zones = fbp_uilist_row_layouts(
            layout,
            context,
            'LAYER_GP',
            order=order,
            leading_units=(
                depth + 1
                if row_type == 'GROUP'
                else (depth if row_type == 'GP_LAYER' else 1)
            ),
            trailing_units=1 if row_type == 'GP_LAYER' else 0,
        )
        row = zones["row"]
        targets = zones["targets"]

        if row_type == 'GROUP':
            coll_name = str(
                getattr(item, 'collection_name', '')
                or getattr(item, 'name', '')
                or ''
            )
            grip_cell = zones["left"].row(align=True)
            grip_cell.enabled = bool(coll_name) and not layer_filter_is_active(context.scene)
            if not coll_name:
                grip_cell.label(text='', icon='GRIP_V')
                row.label(
                    text=_fbp_short_ui_name(
                        getattr(item, 'name', '') or 'Missing Collection', 30
                    ),
                    icon=ui_icon('generic.error'),
                )
                return
            drag = grip_cell.operator(
                'fbp.drag_layer_collection', text='', icon='GRIP_V', emboss=False,
            )
            drag.tree_index = index
            drag.collection_name = coll_name
            drag.list_mode = 'GP'
            for _ in range(depth):
                zones["left"].label(text='', icon=ui_icon('generic.blank'))
            fold = zones["left"].operator(
                'fbp.toggle_collection_collapse',
                text='',
                emboss=False,
                icon=(
                    ui_icon('setup.collapsed')
                    if bool(getattr(item, 'collection_collapsed', False))
                    else ui_icon('setup.expanded')
                ),
            )
            fold.collection_name = coll_name
            for key in order:
                if not flags.get(key, False):
                    continue
                target = targets.get(key, zones["right"])
                if fbp_uilist_is_spacer(key):
                    fbp_draw_uilist_spacer(target)
                    continue
                if key == 'preview':
                    target.label(text='', icon=_fbp_collection_snapshot_icon(item))
                elif key == 'label':
                    name = target.operator(
                        'fbp.ui_list_name_action', text=coll_name, emboss=False,
                    )
                    name.target_type = 'COLLECTION'
                    name.collection_name = coll_name
                    name.tree_index = index
                    name.list_mode = 'GP'
                elif key == 'visibility':
                    _fbp_collection_state_button(
                        target, item, 'VISIBLE',
                        icon=(
                            ui_icon('layer.visible_on')
                            if bool(getattr(item, 'collection_visible', True))
                            else ui_icon('layer.visible_off')
                        ),
                    )
                elif key == 'solo':
                    _fbp_collection_state_button(
                        target, item, 'SOLO',
                        icon=(
                            ui_icon('layer.solo_on')
                            if bool(getattr(item, 'collection_solo', False))
                            else ui_icon('layer.solo_off')
                        ),
                    )
                elif key == 'lock':
                    _fbp_collection_state_button(
                        target, item, 'LOCK',
                        icon=(
                            ui_icon('layer.lock_on')
                            if bool(getattr(item, 'collection_locked', False))
                            else ui_icon('layer.lock_off')
                        ),
                    )
                elif key == 'select':
                    locked = bool(getattr(item, 'collection_locked', False))
                    _fbp_collection_state_button(
                        target, item, 'SELECT', enabled=not locked,
                        icon=(
                            ui_icon('layer.select_on')
                            if bool(getattr(item, 'collection_selected', False))
                            else ui_icon('layer.select_off')
                        ),
                    )
            return

        if row_type == 'GP_LAYER':
            canvas_name = getattr(item, 'canvas_name', '') or ''
            layer_name = getattr(item, 'gp_layer_name', '') or getattr(item, 'name', '') or 'Layer'
            canvas = bpy.data.objects.get(canvas_name) if canvas_name else None
            # Internal GP layers cannot change tree depth; reserve the fixed grip
            # slot so every row remains aligned with draggable rows.
            zones["left"].label(text='', icon=ui_icon('generic.blank'))
            for _ in range(depth):
                zones["left"].label(text='', icon=ui_icon('generic.blank'))
            for key in order:
                if not flags.get(key, False):
                    continue
                target = targets.get(key, zones["right"])
                if fbp_uilist_is_spacer(key):
                    fbp_draw_uilist_spacer(target)
                    continue
                if key == 'preview':
                    target.label(text='', icon=gp_internal_layer_icon(canvas, layer_name))
                elif key == 'label':
                    op = target.operator('fbp.select_gp_internal_layer', text=layer_name, emboss=False, depress=gp_internal_layer_selected(canvas, layer_name))
                    op.canvas_name = canvas_name
                    op.layer_name = layer_name
                elif key == 'clipping':
                    mask_op = target.operator('fbp.toggle_gp_internal_layer_mask', text='', emboss=False, **clipping_mask_icon_kwargs(bool(gp_internal_layer_native_mask_active(canvas, layer_name))))
                    mask_op.canvas_name = canvas_name
                    mask_op.layer_name = layer_name
            try:
                row.operator_context = 'INVOKE_DEFAULT'
            except FBP_DATA_IO_ERRORS:
                pass
            split = zones["right"].operator('fbp.split_gp_single_layer', text='', icon=ui_icon('sequence.split'), emboss=False)
            split.canvas_name = canvas_name
            split.layer_name = layer_name
            return

        canvas_name = getattr(item, 'canvas_name', '') or getattr(item, 'name', '')
        canvas = bpy.data.objects.get(canvas_name) if canvas_name else None
        if not is_gp_drawing_canvas(canvas):
            row.label(text=getattr(item, 'name', '') or '<Deleted Grease Pencil>', icon=ui_icon('generic.error'))
            return
        visible = bool(getattr(canvas, 'fbp_gp_canvas_visible', True))
        locked = bool(getattr(canvas, 'hide_select', False))
        selected = bool(canvas.select_get())
        owner = gp_canvas_owner(canvas)
        grip_cell = zones["left"].row(align=True)
        grip_cell.enabled = not layer_filter_is_active(context.scene)
        drag = grip_cell.operator('fbp.drag_layer_tree', text='', icon='GRIP_V', emboss=False)
        drag.tree_index = index
        drag.rig_name = canvas.name
        drag.list_mode = 'GP'
        fold = zones["left"].operator('fbp.toggle_gp_layers_expanded', text='', icon=ui_icon('setup.expanded') if bool(getattr(canvas, 'fbp_gp_layers_expanded', False)) else ui_icon('setup.collapsed'), emboss=False)
        fold.canvas_name = canvas.name
        for key in order:
            if not flags.get(key, False):
                continue
            target = targets.get(key, zones["right"])
            if fbp_uilist_is_spacer(key):
                fbp_draw_uilist_spacer(target)
                continue
            if key == 'preview':
                color_tag = str(getattr(canvas, 'fbp_color_tag', '') or getattr(owner, 'fbp_color_tag', '') or '')
                icon_value = layer_custom_icon_value('GP_CANVAS', color_tag, inactive=not (visible and not locked))
                if icon_value:
                    target.label(text='', icon_value=icon_value)
                else:
                    target.label(text='', **ui_label_icon_kwargs('menu.gp_layer'))
            elif key == 'label':
                name = target.operator('fbp.ui_list_name_action', text=canvas.name, emboss=False)
                name.target_type = 'GP_CANVAS'
                name.rig_name = canvas.name
                name.tree_index = index
                name.list_mode = 'GP'
            elif key == 'visibility':
                target.prop(canvas, 'fbp_gp_canvas_visible', text='', icon=ui_icon('layer.visible_on') if visible else ui_icon('layer.visible_off'), icon_only=True, emboss=False)
            elif key == 'solo':
                solo = target.operator('fbp.toggle_gp_canvas_solo', text='', icon=ui_icon('layer.solo_on') if gp_canvas_solo_active(canvas) else ui_icon('layer.solo_off'), emboss=False)
                solo.canvas_name = canvas.name
            elif key == 'plane':
                link = target.operator('fbp.link_grease_pencil_canvas', text='', icon='LINKED' if owner is not None else 'UNLINKED', emboss=False)
                link.canvas_name = canvas.name
            elif key == 'lock':
                target.prop(canvas, 'fbp_gp_canvas_locked', text='', icon=ui_icon('layer.lock_on') if locked else ui_icon('layer.lock_off'), icon_only=True, emboss=False)
            elif key == 'select':
                cell = target.row(align=True)
                cell.enabled = not locked
                cell.prop(canvas, 'fbp_gp_canvas_selected', text='', icon=fbp_select_rig_icon(locked, selected), icon_only=True, emboss=False)


# SECTION 02 - UIList: Frames / Images #
# ###ICON Panel Sequence, Functions: current frame, empty frame, missing file, image preview.
class FBP_UL_ImageList(UIList):
    """Stable compact sequence-frame row for the 7.1 interface."""

    def draw_item(self, context, layout, data, item, icon, _active_data, _active_propname, index):
        mark_ui_list_draw()
        rig = data
        is_empty = bool(getattr(item, "is_empty", False))
        is_missing = False
        try:
            current_index = fbp_sequence_index_at_frame(rig, getattr(context.scene, 'frame_current', None))
        except Exception:
            current_index = getattr(rig, 'fbp_images_index', -1)
        is_active = index == current_index
        is_color_plane = bool(getattr(rig, "fbp_is_color_plane", False))

        custom_icon = ui_icon_value("menu.image_plane") or ui_icon("menu.image_plane")
        if is_empty:
            custom_icon = ui_icon("sequence.empty_frame")
        elif is_color_plane:
            procedural_type = fbp_procedural_kind_for_item(rig, index, fbp_procedural_layer_type(rig))
            custom_key = (
                "menu.gradient_plane" if procedural_type == 'GRADIENT'
                else ("menu.holdout_plane" if procedural_type == 'HOLDOUT' else "menu.color_plane")
            )
            custom_icon = ui_icon_value(custom_key) or fbp_color_plane_type_icon(rig) or ui_icon("sequence.empty_frame")
        else:
            try:
                img_path = getattr(item, "filepath", "") or ""
                if img_path and not cached_file_exists(bpy.path.abspath(img_path)):
                    is_missing = True
                if img_path and context.scene.fbp_show_previews:
                    thumb = load_preview(img_path, scene=context.scene)
                    if thumb:
                        custom_icon = thumb.icon_id
            except FBP_DATA_IO_ERRORS:
                pass

        zones = fbp_uilist_fixed_row_layouts(
            layout,
            context,
            left_units=4.0,
            right_units=4.0,
            label_alignment="LEFT",
        )
        left = zones["left"]
        name_cell = zones["name"]
        right = zones["right"]

        drag = left.operator(
            "fbp.drag_sequence_frame",
            text="",
            icon='GRIP_V',
            emboss=False,
        )
        drag.rig_name = rig.name
        drag.index = index

        op = left.operator(
            "fbp.select_image_exclusive",
            text="",
            icon=(
                ui_icon("sequence.current_frame")
                if is_active else ui_icon("sequence.normal_frame")
            ),
            emboss=False,
        )
        op.rig_name = rig.name
        op.index = index

        show_proc_preview = bool(
            getattr(context.scene, 'fbp_show_color_previews', False)
            and is_color_plane
            and not is_empty
        )
        can_relink_media = bool(
            not is_color_plane
            and fbp_layer_backend_type(rig)
            in {'NATIVE_IMAGE', 'NATIVE_SEQUENCE', 'NATIVE_MOVIE'}
        )
        preview_cell = left.row(align=True)
        preview_cell.ui_units_x = 2.0
        preview_cell.alignment = "RIGHT"
        if is_missing and can_relink_media:
            relink = preview_cell.operator(
                "fbp.link_image_frame",
                text="",
                icon=ui_icon("generic.error"),
                emboss=False,
            )
            relink.rig_name = rig.name
            relink.index = index
        elif show_proc_preview:
            fbp_draw_procedural_frame_swatch(preview_cell, rig, index)
        elif can_relink_media:
            relink = preview_cell.operator(
                "fbp.link_image_frame",
                text="",
                icon_value=custom_icon if isinstance(custom_icon, int) else 0,
                icon='NONE' if isinstance(custom_icon, int) else custom_icon,
                emboss=False,
            )
            relink.rig_name = rig.name
            relink.index = index
        elif is_empty:
            preview_cell.label(text="", icon=ui_icon("sequence.empty_frame"))
        elif isinstance(custom_icon, int):
            preview_cell.label(text='', icon_value=custom_icon)
        else:
            preview_cell.label(text='', icon=custom_icon)

        display_name = item.name if not is_empty else "Alpha"
        name_op = name_cell.operator(
            "fbp.ui_list_name_action",
            text=(
                f"{index + 1} - ({display_name})"
                if is_empty
                else f"{index + 1} - {display_name}"
            ),
            emboss=False,
        )
        name_op.target_type = 'FRAME'
        name_op.rig_name = rig.name
        name_op.index = index

        compact = right.row(align=True)
        compact.ui_units_x = 3.0
        compact.prop(item, "duration", text="", slider=True, emboss=False)
        selected = bool(getattr(item, "is_selected", False))
        right.prop(
            item,
            "is_selected",
            text="",
            icon="CHECKBOX_HLT" if selected else "CHECKBOX_DEHLT",
            icon_only=True,
            emboss=False,
        )


# SECTION 03 - UIList: Multiplane Setup #
# ###ICON Panel Multiplane Setup, Functions: collection, folder, remove, file count.
class FBP_UL_PendingList(UIList):
    """Scrollable preview list for the Multiplane Setup import."""

    _PROFILE = "PENDING_SETUP"

    def filter_items(self, context, data, propname):
        mark_ui_list_draw()
        items = getattr(data, propname)
        flags = [self.bitflag_filter_item] * len(items)
        if not getattr(context.scene, 'fbp_sort_layers_alpha', False):
            return flags, []
        order = list(range(len(items)))
        order.sort(key=lambda i: natural_sort_key(getattr(items[i], 'collection_name', '') + ' / ' + getattr(items[i], 'name', '')))
        return flags, order

    def _collection_parts(self, item):
        raw = (getattr(item, 'collection_name', '') or '').strip()
        if not raw:
            return []
        return [part.strip() for part in raw.split('/') if part.strip()]

    def _file_count(self, item):
        try:
            return sum(1 for value in str(getattr(item, 'files_str', '') or '').split('|') if value)
        except FBP_DATA_IO_ERRORS:
            return 0

    def _row_icon(self, context, item, file_count, parts):
        # ###ICON Panel Multiplane Setup, Function Folder/Collection: setup.folder
        # ###ICON Panel Multiplane Setup, Function Sequence: setup.sequence
        # ###ICON Panel Multiplane Setup, Function Static Image: setup.image
        if parts:
            return ui_icon('setup.folder')
        return ui_icon('setup.sequence') if file_count > 1 else ui_icon('setup.image')

    def draw_item(self, context, layout, data, item, icon, _active_data, _active_propname, index):
        mark_ui_list_draw()
        if item is None:
            return

        parts = self._collection_parts(item)
        depth = min(8, len(parts))
        file_count = self._file_count(item)
        row_icon = self._row_icon(context, item, file_count, parts)
        is_sequence = file_count > 1

        order = fbp_uilist_icon_order(context, self._PROFILE)
        zones = fbp_uilist_row_layouts(
            layout,
            context,
            self._PROFILE,
            order=order,
            leading_units=depth,
        )
        row = zones["row"]
        targets = zones["targets"]
        zones["left"].label(text="", icon="GRIP_V")
        for _ in range(depth):
            zones["left"].label(text='', icon=ui_icon('generic.blank'))

        visible = set(fbp_uilist_visible_columns(context, self._PROFILE))
        for key in order:
            if key not in visible:
                continue
            target = targets.get(key, zones["right"])
            if fbp_uilist_is_spacer(key):
                fbp_draw_uilist_spacer(target)
                continue
            if key == "pending_color":
                target.prop(item, 'fbp_color_tag', text='', icon_only=True)
            elif key == "pending_status":
                if is_sequence:
                    target.label(text=f"F {file_count}")
                elif file_count == 1:
                    target.label(text="F 1")
                else:
                    target.label(text="empty", icon=ui_icon('generic.error'))
            elif key == "label":
                if parts:
                    target.label(text=f"{parts[-1]} /", icon=row_icon)
                name_op = target.operator(
                    'fbp.ui_list_name_action',
                    text=item.name,
                    icon=row_icon if not parts else 'NONE',
                    emboss=False,
                )
                name_op.target_type = 'PENDING'
                name_op.index = index
            elif key == "pending_edit":
                edit = target.operator(
                    'fbp.edit_pending_plane', text='', icon=ui_icon('setup.edit'), emboss=False
                )
                edit.index = index


class FBP_UL_PendingTreeList(UIList):
    """True Blender UIList used as a collapsible tree for Multiplane Setup.

    Rows are virtual display items rebuilt from Scene.fbp_pending_planes.
    Group rows use TRIA_RIGHT / TRIA_DOWN; layer rows keep edit/remove controls.
    """

    _PROFILE = "PENDING_SETUP"

    def filter_items(self, context, data, propname):
        mark_ui_list_draw()
        items = getattr(data, propname, ())
        flags = [self.bitflag_filter_item] * len(items)
        query = fbp_uilist_filter_text(context, self._PROFILE)
        if query:
            matching_paths = set()
            for item in items:
                haystack = " ".join((
                    str(getattr(item, "name", "") or ""),
                    str(getattr(item, "collection_path", "") or ""),
                )).casefold()
                if query in haystack:
                    path = str(getattr(item, "collection_path", "") or "")
                    while path:
                        matching_paths.add(path.casefold())
                        path = path.rsplit(" / ", 1)[0] if " / " in path else ""
            for index, item in enumerate(items):
                haystack = " ".join((
                    str(getattr(item, "name", "") or ""),
                    str(getattr(item, "collection_path", "") or ""),
                )).casefold()
                path = str(getattr(item, "collection_path", "") or "").casefold()
                if query not in haystack and path not in matching_paths:
                    flags[index] = 0
        alphabetical, reverse = fbp_uilist_sort_options(context, self._PROFILE)
        order = list(range(len(items)))
        if alphabetical:
            order.sort(key=lambda i: natural_sort_key(" / ".join((
                str(getattr(items[i], "collection_path", "") or ""),
                "0" if str(getattr(items[i], "row_type", "LAYER") or "LAYER") == "GROUP" else "1",
                str(getattr(items[i], "name", "") or ""),
            ))))
        if reverse:
            order.reverse()
        return flags, order if order != list(range(len(items))) else []

    def draw_item(self, context, layout, data, item, icon, _active_data, _active_propname, index):
        mark_ui_list_draw()
        if item is None:
            return

        scene = context.scene
        depth = max(0, min(10, int(getattr(item, 'depth', 0))))
        row_type = getattr(item, 'row_type', 'LAYER')
        visible = set(fbp_uilist_visible_columns(context, self._PROFILE))
        order = fbp_uilist_icon_order(context, self._PROFILE)

        if row_type == 'GROUP':
            zones = fbp_uilist_row_layouts(
                layout,
                context,
                self._PROFILE,
                order=order,
                leading_units=depth + 1,
            )
            row = zones["row"]
            targets = zones["targets"]
            # Group rows are not draggable, but keep the fixed grip slot so
            # their foldout and names align with the layer rows below.
            zones["left"].label(text="", icon=ui_icon("generic.blank"))
            for _ in range(depth):
                zones["left"].label(text='', icon=ui_icon('generic.blank'))
            path = getattr(item, 'collection_path', '') or getattr(item, 'name', '') or 'Unsorted'
            is_open = pending_collection_is_open(scene, path)
            fold_icon = ui_icon('setup.expanded') if is_open else ui_icon('setup.collapsed')
            op = zones["left"].operator(
                'fbp.toggle_pending_collection_collapse',
                text='',
                icon=fold_icon,
                emboss=False,
            )
            op.collection_name = path

            has_children = int(getattr(item, 'child_count', 0)) > 0
            color_editable = bool(getattr(item, 'collection_color_editable', True))
            for key in order:
                if key not in visible:
                    continue
                target = targets.get(key, zones["right"])
                if fbp_uilist_is_spacer(key):
                    fbp_draw_uilist_spacer(target)
                    continue
                if key == 'pending_color':
                    if has_children or not color_editable:
                        target.label(text='', icon=fbp_collection_color_icon('NONE'))
                    else:
                        target.prop(item, 'collection_color_tag', text='', icon_only=True)
                elif key == 'label':
                    name_op = target.operator(
                        'fbp.ui_list_name_action',
                        text=getattr(item, 'name', '') or 'Unsorted',
                        icon='NONE',
                        emboss=False,
                    )
                    name_op.target_type = 'PENDING_GROUP'
                    name_op.collection_name = path
                    name_op.tree_index = index
            return

        pending_index = int(getattr(item, 'pending_index', -1))
        pending = None
        try:
            if 0 <= pending_index < len(scene.fbp_pending_planes):
                pending = scene.fbp_pending_planes[pending_index]
        except Exception:
            pending = None

        file_count = int(getattr(item, 'file_count', 0))
        layer_icon = ui_icon('setup.animated') if file_count > 1 else ui_icon('setup.image')
        timeline_frames = file_count
        if pending is not None and str(getattr(pending, 'source_preset', '') or '') == 'TOON_BOOM_EXPORT':
            try:
                prepared_durations = [
                    max(1, int(value))
                    for value in str(getattr(pending, 'source_durations_str', '') or '').split('|')
                    if value
                ]
            except (TypeError, ValueError):
                prepared_durations = []
            if len(prepared_durations) == file_count:
                timeline_frames = sum(prepared_durations)
        timing_text = (
            f'F {file_count} / T {timeline_frames}'
            if timeline_frames != file_count else f'F {file_count}'
        )

        zones = fbp_uilist_row_layouts(
            layout,
            context,
            self._PROFILE,
            order=order,
            leading_units=depth,
        )
        row = zones["row"]
        targets = zones["targets"]

        # Fixed structural grip. It never appears in preferences and cannot be
        # moved or hidden; every other cell can move around the label.
        drag_row = zones["left"].row(align=True)
        drag_row.enabled = bool(
            pending is not None
            and (getattr(item, 'can_move_up', False) or getattr(item, 'can_move_down', False))
        )
        drag = drag_row.operator('fbp.drag_pending_plane', text='', icon='GRIP_V', emboss=False)
        drag.index = pending_index

        for _ in range(depth):
            zones["left"].label(text='', icon=ui_icon('generic.blank'))

        for key in order:
            if key not in visible:
                continue
            target = targets.get(key, zones["right"])
            if fbp_uilist_is_spacer(key):
                fbp_draw_uilist_spacer(target)
                continue
            if key == 'pending_color':
                if pending is not None:
                    target.prop(pending, 'fbp_color_tag', text='', icon_only=True)
            elif key == 'pending_status':
                if pending is not None and bool(getattr(pending, 'source_from_layered', False)):
                    warnings = bool(str(getattr(pending, 'source_warnings', '') or '').strip())
                    if warnings:
                        target.label(text='', icon=ui_icon('ERROR'))
                    elif bool(getattr(pending, 'source_flattened_group', False)):
                        target.label(text='', icon=ui_icon('OUTLINER_COLLECTION'))
                    elif bool(getattr(pending, 'source_is_clipping', False)):
                        target.label(text='', **clipping_mask_icon_kwargs(True))
                    elif str(getattr(pending, 'source_mask_file', '') or ''):
                        target.label(text='', icon=ui_icon('MOD_MASK'))
                    elif not bool(getattr(pending, 'source_layer_visible', True)):
                        target.label(text='', icon=ui_icon('HIDE_ON'))
                target.label(
                    text=timing_text if file_count else '',
                    icon='NONE' if file_count else ui_icon('generic.error'),
                )
            elif key == 'label':
                if pending is not None:
                    name_op = target.operator(
                        'fbp.ui_list_name_action',
                        text=pending.name,
                        icon=layer_icon,
                        emboss=False,
                    )
                    name_op.target_type = 'PENDING'
                    name_op.index = pending_index
                    name_op.tree_index = index
                else:
                    target.label(
                        text=getattr(item, 'name', '') or 'Missing Layer',
                        icon=ui_icon('generic.error'),
                    )
            elif key == 'pending_reverse' and file_count > 1:
                reverse_sequence = target.operator(
                    'fbp.reverse_pending_sequence',
                    text='',
                    icon=ui_icon('sequence.reverse'),
                    emboss=False,
                )
                reverse_sequence.index = pending_index
            elif key == 'pending_select' and pending is not None:
                target.prop(
                    pending,
                    'is_selected',
                    text='',
                    icon='CHECKBOX_HLT' if bool(getattr(pending, 'is_selected', False)) else 'CHECKBOX_DEHLT',
                    icon_only=True,
                    emboss=False,
                )
            elif key == 'pending_edit':
                edit = target.operator(
                    'fbp.edit_pending_plane',
                    text='',
                    icon=ui_icon('setup.edit'),
                    emboss=False,
                )
                edit.index = pending_index
            elif key == 'pending_delete':
                remove = target.operator(
                    'fbp.remove_pending_plane_at_index',
                    text='',
                    icon=ui_icon('generic.delete'),
                    emboss=False,
                )
                remove.index = pending_index


# SECTION 04 - Helper UI: Pending Setup and Tree View #
# Layout helper lives in ui_layout.py.
# ###ICON Tree View, Functions: collection collapse, visibility, solo, holdout, select rigs/planes, lock.

# SECTION 05 - Panel: Settings / Project / Camera / Render / Maintenance #
# Settings tabs avoid project scans and draw only cached or direct scene data.


class FBP_UL_CompositorLayers(UIList):
    """Compact hierarchical mirror of the managed compositor layer stack."""

    bl_idname = "FBP_UL_CompositorLayers"

    def filter_items(self, context, data, propname):
        mark_ui_list_draw()
        items = getattr(data, propname, ())
        flags = [self.bitflag_filter_item] * len(items)
        folders = {
            str(getattr(item, "layer_id", "") or ""): item
            for item in items
            if str(getattr(item, "row_type", 'LAYER') or 'LAYER') == 'FOLDER'
        }
        query = fbp_uilist_filter_text(context, "COMPOSITOR_LAYERS")
        matching_folders = set()
        if query:
            for item in items:
                haystack = " ".join((
                    str(getattr(item, "name", "") or ""),
                    str(getattr(item, "source_kind", "") or ""),
                    str(getattr(item, "source_key", "") or ""),
                )).casefold()
                if query in haystack:
                    parent_id = str(getattr(item, "parent_folder_id", "") or "")
                    while parent_id:
                        matching_folders.add(parent_id)
                        parent = folders.get(parent_id)
                        parent_id = str(getattr(parent, "parent_folder_id", "") or "") if parent else ""
        for index, item in enumerate(items):
            parent_id = str(getattr(item, "parent_folder_id", "") or "")
            visited = ()
            while parent_id and parent_id not in visited:
                visited += (parent_id,)
                parent = folders.get(parent_id)
                if parent is None:
                    break
                if not bool(getattr(parent, "expanded", True)):
                    flags[index] = 0
                    break
                parent_id = str(getattr(parent, "parent_folder_id", "") or "")
            if query and flags[index]:
                haystack = " ".join((
                    str(getattr(item, "name", "") or ""),
                    str(getattr(item, "source_kind", "") or ""),
                    str(getattr(item, "source_key", "") or ""),
                )).casefold()
                layer_id = str(getattr(item, "layer_id", "") or "")
                if query not in haystack and layer_id not in matching_folders:
                    flags[index] = 0
        alphabetical, reverse = fbp_uilist_sort_options(context, "COMPOSITOR_LAYERS")
        order = list(range(len(items)))
        if alphabetical:
            order.sort(key=lambda i: natural_sort_key(" / ".join((
                str(getattr(items[i], "parent_folder_id", "") or ""),
                "0" if str(getattr(items[i], "row_type", "LAYER") or "LAYER") == "FOLDER" else "1",
                str(getattr(items[i], "name", "") or ""),
            ))))
        if reverse:
            order.reverse()
        return flags, order if order != list(range(len(items))) else []

    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        mark_ui_list_draw()
        if self.layout_type == 'GRID':
            layout.alignment = 'CENTER'
            layout.label(text='', icon='RENDERLAYERS')
            return
        row = layout.row(align=True)
        is_folder = str(getattr(item, 'row_type', 'LAYER') or 'LAYER') == 'FOLDER'
        parent_id = str(getattr(item, 'parent_folder_id', '') or '')
        compact = is_compact(context)
        if is_folder:
            row.prop(item, 'expanded', text='', icon='DISCLOSURE_TRI_DOWN' if bool(getattr(item, 'expanded', True)) else 'DISCLOSURE_TRI_RIGHT', emboss=False)
        elif parent_id:
            row.label(text='', icon='BLANK1')

        icon_kwargs = {'icon': 'FILE_FOLDER' if is_folder else 'RENDERLAYERS'}
        if not is_folder and str(getattr(item, 'source_kind', '') or '') == 'LAYER':
            source_id = str(getattr(item, 'source_key', '') or '')
            rig = next((getattr(layer_row, 'obj', None) for layer_row in getattr(context.scene, 'fbp_layers', ()) if str(getattr(getattr(layer_row, 'obj', None), 'fbp_compositor_source_id', '') or '') == source_id), None)
            icon_value = fbp_layer_tag_backend_icon_value(rig) if rig is not None else 0
            if icon_value:
                icon_kwargs = {'icon_value': icon_value}
        display_name = str(getattr(item, 'name', '') or ('Folder' if is_folder else 'Layer'))
        if is_folder:
            child_count = sum(1 for child in getattr(data, 'fbp_compositor_layers', ()) if str(getattr(child, 'parent_folder_id', '') or '') == str(getattr(item, 'layer_id', '') or ''))
            if child_count:
                display_name = f'{display_name} ({child_count})'

        visible = set(fbp_uilist_visible_columns(context, 'COMPOSITOR_LAYERS'))
        for key in fbp_uilist_icon_order(context, 'COMPOSITOR_LAYERS'):
            if key not in visible:
                continue
            if fbp_uilist_is_spacer(key):
                fbp_draw_uilist_spacer(row)
                continue
            if key == 'label':
                select = row.operator('fbp.compositor_select_row', text=_fbp_short_ui_name(display_name, 24 if compact else 32), emboss=False, depress=bool(getattr(item, 'selected', False)), **icon_kwargs)
                select.index = index
            elif key == 'compositor_visibility':
                row.prop(item, 'enabled', text='', icon='HIDE_OFF' if item.enabled else 'HIDE_ON', emboss=False)
            elif key == 'compositor_holdout':
                row.prop(item, 'holdout', text='', emboss=False, **ui_icon_kwargs('menu.holdout_plane', fallback='CLIPUV_HLT'))
            elif key == 'compositor_indirect' and not compact:
                row.prop(item, 'indirect_only', text='', icon='INDIRECT_ONLY_ON' if item.indirect_only else 'INDIRECT_ONLY_OFF', emboss=False)


class FBP_UL_CompositorEffects(UIList):
    """Ordered Blender 5.2 compositor effects for one managed View Layer."""

    bl_idname = "FBP_UL_CompositorEffects"

    def filter_items(self, context, data, propname):
        mark_ui_list_draw()
        items = getattr(data, propname, ())
        flags = [self.bitflag_filter_item] * len(items)
        query = fbp_uilist_filter_text(context, "COMPOSITOR_EFFECTS")
        if query:
            for index, item in enumerate(items):
                haystack = " ".join((
                    str(getattr(item, "effect_type", "") or "").replace('_', ' '),
                    str(getattr(item, "name", "") or ""),
                )).casefold()
                if query not in haystack:
                    flags[index] = 0
        alphabetical, reverse = fbp_uilist_sort_options(context, "COMPOSITOR_EFFECTS")
        order = list(range(len(items)))
        if alphabetical:
            order.sort(key=lambda i: natural_sort_key(str(getattr(items[i], "effect_type", "") or "")))
        if reverse:
            order.reverse()
        return flags, order if order != list(range(len(items))) else []

    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        mark_ui_list_draw()
        icons = {
            'GLOW': 'LIGHT_SUN', 'BLUR': 'MOD_SMOOTH', 'DEFOCUS': 'CAMERA_DATA',
            'COLOR_GRADE': 'COLOR', 'PIXELATE': 'ALIASED', 'VIGNETTE': 'SHADING_RENDERED',
            'UNSHARP_MASK': 'SHARPCURVE', 'TUNE_IMAGE': 'IMAGE_RGB_ALPHA',
            'FILM_GRAIN': 'RNDCURVE', 'CHROMATIC_ABERRATION': 'SEQ_CHROMA_SCOPE',
            'SEPIA': 'COLOR',
        }
        labels = {identifier: label for identifier, label, _description in FBP_COMPOSITOR_EFFECT_ITEMS}
        if self.layout_type == 'GRID':
            layout.alignment = 'CENTER'
            layout.label(text='', icon=icons.get(item.effect_type, 'NODE_COMPOSITING'))
            return
        row = layout.row(align=True)
        visible = set(fbp_uilist_visible_columns(context, 'COMPOSITOR_EFFECTS'))
        for key in fbp_uilist_icon_order(context, 'COMPOSITOR_EFFECTS'):
            if key not in visible:
                continue
            if fbp_uilist_is_spacer(key):
                fbp_draw_uilist_spacer(row)
                continue
            if key == 'label':
                select = row.operator(
                    'fbp.compositor_effect_select_row',
                    text=labels.get(item.effect_type, item.effect_type.replace('_', ' ').title()),
                    icon=icons.get(item.effect_type, 'NODE_COMPOSITING'),
                    emboss=False, depress=bool(getattr(item, 'selected', False)),
                )
                select.layer_id = str(getattr(data, 'layer_id', '') or '')
                select.index = index
            elif key == 'compositor_enabled':
                row.prop(item, 'enabled', text='', icon='CHECKBOX_HLT' if item.enabled else 'CHECKBOX_DEHLT', emboss=False)
            elif key == 'compositor_mix' and item.effect_mix < 0.999:
                row.label(text=f'{round(item.effect_mix * 100):d}%')


def _fbp_output_collapsible_box(layout, scene, property_name, title, icon):
    box = layout.box()
    configure_layout(box)
    opened = bool(getattr(scene, property_name, True))
    row = box.row(align=False)
    row.prop(
        scene,
        property_name,
        text=title,
        icon=('DOWNARROW_HLT' if opened else 'RIGHTARROW'),
        emboss=False,
    )
    row.label(text="", icon=icon)
    return box if opened else None


class FBP_MT_RenderFolderTag(Menu):
    bl_idname = "FBP_MT_render_folder_tag"
    bl_label = "Generated Folder Tag"

    def draw(self, context):
        layout = configure_layout(self.layout)
        layout.use_property_split = False
        layout.use_property_decorate = False
        scene = context.scene
        current = str(getattr(scene, "fbp_render_folder_tag", 'NONE') or 'NONE')
        layout.label(text="Folder Tag", icon='TAG')
        choices = layout.column(align=True)
        for value, label, icon in (
            ('NONE', "No Tag", 'X'),
            ('TEST', "TEST", 'EXPERIMENTAL'),
            ('ANIM', "ANIM", 'ANIM'),
            ('FINAL', "FINAL", 'CHECKMARK'),
            ('PREV', "PREV", 'RENDER_RESULT'),
        ):
            op = choices.operator(
                "wm.context_set_enum",
                text=label,
                icon=('RADIOBUT_ON' if current == value else icon),
                depress=(current == value),
            )
            op.data_path = "scene.fbp_render_folder_tag"
            op.value = value


class FBP_OT_SetRenderToken(Operator):
    bl_idname = "fbp.set_render_token"
    bl_label = "Set Filename Token"
    bl_description = "Choose the optional letter/number token and where it is placed"
    bl_options = {'REGISTER', 'UNDO'}

    mode: StringProperty(default='NONE', options={'SKIP_SAVE'})
    position: StringProperty(default='BEFORE', options={'SKIP_SAVE'})

    def execute(self, context):
        scene = context.scene
        scene.fbp_render_token_position = self.position
        scene.fbp_render_token_mode = self.mode
        return {'FINISHED'}


def _fbp_draw_render_token_menu(layout, context, position):
    layout = configure_layout(layout)
    layout.use_property_split = False
    layout.use_property_decorate = False
    scene = context.scene
    current_position = str(
        getattr(scene, "fbp_render_token_position", 'BEFORE') or 'BEFORE'
    )
    current_mode = str(getattr(scene, "fbp_render_token_mode", 'NONE') or 'NONE')
    active_mode = current_mode if current_position == position else 'NONE'
    layout.label(
        text="Before Prefix" if position == 'BEFORE' else "After Suffix",
        icon='SORTALPHA' if position == 'BEFORE' else 'LINENUMBERS_ON',
    )
    choices = layout.column(align=True)
    for mode, label, icon in (
        ('NONE', "None", 'X'),
        ('LETTER', "Letter", 'FONT_DATA'),
        ('NUMBER', "Number", 'LINENUMBERS_ON'),
        ('LETTER_NUMBER', "Letter + Number", 'SORTALPHA'),
    ):
        active = mode == active_mode
        op = choices.operator(
            "fbp.set_render_token",
            text=label,
            icon=('RADIOBUT_ON' if active else icon),
            depress=active,
        )
        op.mode = mode
        op.position = position
    if active_mode != 'NONE':
        settings = layout.column(align=True)
        settings.use_property_split = False
        settings.use_property_decorate = False
        if active_mode in {'LETTER', 'LETTER_NUMBER'}:
            settings.prop(scene, "fbp_render_letter", text="Start Letter")
        if active_mode in {'NUMBER', 'LETTER_NUMBER'}:
            settings.prop(scene, "fbp_render_number", text="Start Number")
            settings.prop(scene, "fbp_render_number_digits", text="Digits")


class FBP_MT_RenderTokenBefore(Menu):
    bl_idname = "FBP_MT_render_token_before"
    bl_label = "Token Before Prefix"

    def draw(self, context):
        _fbp_draw_render_token_menu(self.layout, context, 'BEFORE')


class FBP_MT_RenderTokenAfter(Menu):
    bl_idname = "FBP_MT_render_token_after"
    bl_label = "Token After Suffix"

    def draw(self, context):
        _fbp_draw_render_token_menu(self.layout, context, 'AFTER')


class FBP_PT_OutputAnchor(Panel):
    """Invisible top-of-context anchor for Frame By Plane Output panels."""

    bl_label = ""
    bl_idname = "FBP_PT_output_anchor"
    bl_space_type = 'PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_context = 'output'
    bl_options = {'HIDE_HEADER'}
    bl_order = 0

    @classmethod
    def poll(cls, context):
        return getattr(context, "scene", None) is not None

    def draw(self, _context):
        pass


class FBP_PT_OutputRender(Panel):
    bl_label = "Frame By Plane Render"
    bl_description = "Background render and alpha output controls for Frame By Plane"
    bl_idname = "FBP_PT_output_render"
    bl_space_type = 'PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_context = 'output'
    bl_parent_id = 'FBP_PT_output_anchor'
    bl_options = {"DEFAULT_CLOSED"}
    bl_order = 0

    def draw_header(self, context):
        self.layout.label(text="", icon=ui_icon("settings.render_tab"))

    def draw(self, context):
        layout = configure_layout(self.layout)
        sc = context.scene
        content = layout.column(align=False)

        project = content.box()
        configure_layout(project)
        section_header(
            project,
            "Project Folder",
            icon=ui_icon("settings.project_folder"),
        )
        row = project.row(align=False)
        row.scale_y = 1.05
        row.prop(sc, "fbp_project_path", text="")

        section_gap(content)
        folder = _fbp_output_collapsible_box(
            content, sc, "fbp_render_show_folder", "Folder", 'FILE_FOLDER'
        )
        if folder is not None:
            selector = folder.row(align=True)
            selector.prop_enum(sc, "fbp_render_folder_builder_mode", 'SELECT', text="Select Folder")
            selector.prop_enum(sc, "fbp_render_folder_builder_mode", 'GENERATE', text="Generate Folder")
            if sc.fbp_render_folder_builder_mode == 'SELECT':
                row = folder.row(align=False)
                row.prop(sc, "fbp_render_output_dir", text="")
                row.operator("fbp.open_render_output_folder", text="", icon='FILE_FOLDER')
            elif is_compact(context):
                row = folder.row(align=True)
                row.prop(sc, "fbp_render_folder_prefix", text="Prefix")
                row = folder.row(align=True)
                row.prop(sc, "fbp_render_folder_name", text="+ Name")
                row.menu("FBP_MT_render_folder_tag", text="", icon='TAG')
                row = folder.row(align=True)
                row.prop(sc, "fbp_render_folder_builder_suffix", text="+ Suffix")
            else:
                row = folder.row(align=True)
                row.prop(sc, "fbp_render_folder_prefix", text="Prefix")
                name = row.row(align=True)
                name.prop(sc, "fbp_render_folder_name", text="+ Name")
                name.menu("FBP_MT_render_folder_tag", text="", icon='TAG')
                row.prop(sc, "fbp_render_folder_builder_suffix", text="+ Suffix")
            folder_preview = fbp_render_folder_name(sc)
            if folder_preview:
                hint_row(folder, folder_preview, icon='FILE_FOLDER', disabled=False)

        section_gap(content)
        naming = _fbp_output_collapsible_box(
            content, sc, "fbp_render_show_file_naming", "File Naming", ui_icon("layer.sort_alpha")
        )
        if naming is not None:
            if is_compact(context):
                row = naming.row(align=True)
                row.prop(sc, "fbp_render_prefix", text="Prefix")
                row.menu("FBP_MT_render_token_before", text="", icon='SORTALPHA')
                row = naming.row(align=True)
                row.prop(sc, "fbp_render_custom_name", text="+ Name")
                row = naming.row(align=True)
                row.prop(sc, "fbp_render_suffix", text="+ Suffix")
                row.menu("FBP_MT_render_token_after", text="", icon='LINENUMBERS_ON')
            else:
                row = naming.row(align=True)
                prefix = row.row(align=True)
                prefix.prop(sc, "fbp_render_prefix", text="Prefix")
                prefix.menu("FBP_MT_render_token_before", text="", icon='SORTALPHA')
                row.prop(sc, "fbp_render_custom_name", text="+ Name")
                suffix = row.row(align=True)
                suffix.prop(sc, "fbp_render_suffix", text="+ Suffix")
                suffix.menu("FBP_MT_render_token_after", text="", icon='LINENUMBERS_ON')
            if is_compact(context):
                row = naming.row(align=False)
                row.prop(sc, "fbp_render_separator", text="Separator")
                row = naming.row(align=False)
                row.prop(sc, "fbp_render_frame_digits", text="Frame Digits")
            else:
                row = naming.row(align=False)
                row.prop(sc, "fbp_render_separator", text="Separator")
                row.prop(sc, "fbp_render_frame_digits", text="Frame Digits")
            hint_row(
                naming,
                "Empty Name = .blend Project File Name · Empty Prefix/Suffix = skip",
                icon='INFO',
            )
            preview = fbp_render_filename_preview(sc)
            if preview:
                hint_row(naming, preview, icon='FILE_IMAGE', disabled=False)

        section_gap(content)
        extension = _fbp_output_collapsible_box(
            content, sc, "fbp_render_show_file_extension", "File Extension", 'OUTPUT'
        )
        if extension is not None:
            kind = extension.row(align=True)
            kind.prop(sc, "fbp_render_output_kind", expand=True)
            if sc.fbp_render_output_kind == 'VIDEO':
                row = extension.row(align=False)
                row.label(text="PNG sequence → MP4", icon='FILE_MOVIE')
                ffmpeg = fbp_find_ffmpeg_executable(sc)
                if ffmpeg:
                    hint_row(extension, ffmpeg, icon='CHECKMARK')
                else:
                    row = extension.row(align=False)
                    row.alert = True
                    row.prop(sc, "fbp_render_ffmpeg_executable", text="FFmpeg")
            else:
                row = extension.row(align=False)
                row.prop(sc.render.image_settings, "file_format", text="Format")
            row = extension.row(align=False)
            row.prop(
                sc,
                "fbp_compositor_transparent",
                text="Transparency",
                toggle=True,
                icon='TEXTURE_DATA',
            )
            if hasattr(sc.render, 'anisotropic_filter'):
                row.prop(sc.render, 'anisotropic_filter', text='Image Sampling')

        section_gap(content)
        row = content.row(align=False)
        if hasattr(sc.render, "use_overwrite"):
            row.prop(sc.render, "use_overwrite", text="Overwrite", toggle=True, icon='FILE_REFRESH')
        if hasattr(sc.render, "use_placeholder"):
            row.prop(sc.render, "use_placeholder", text="Placeholders", toggle=True, icon='FILE_TICK')
        hint_row(
            content,
            "Placeholders reserve frames for parallel renders; with Overwrite off, completed files are skipped.",
            icon='INFO',
        )

        section_gap(content)
        range_box = _fbp_output_collapsible_box(
            content, sc, "fbp_render_show_frame_range", "Frame Range", 'TIME'
        )
        if range_box is not None:
            row = adaptive_row(range_box, context, align=False, scale=1.05, threshold=300.0)
            row.prop(sc, "frame_start", text="Start")
            row.prop(sc, "frame_end", text="End")
            row.prop(sc, "frame_step", text="Step")
            row.operator("fbp.repair_render_state", icon=ui_icon("settings.repair"), text="")

        section_gap(content)
        actions = content.box()
        configure_layout(actions)
        section_header(actions, "Background Render", icon=ui_icon("settings.render_sequence"))
        row = adaptive_row(actions, context, align=False, scale=1.08)
        row.operator("fbp.save_file", text="Save", icon=ui_icon("settings.save"))
        if getattr(sc, 'fbp_background_render_running', False):
            row.operator("fbp.stop_background_render", icon='CANCEL', text="Stop")
            row.operator("fbp.background_render_status", icon='INFO', text="Status")
        else:
            row.operator("fbp.background_render_frames", icon=ui_icon("settings.render_sequence"), text="Render")
            row.operator("fbp.background_render_status", icon='INFO', text="Status")
        actions.prop(sc, "fbp_background_render_keep_log", text="Keep Successful Log", toggle=True, icon='TEXT')

        if str(getattr(sc.render, 'engine', '') or '') == 'CYCLES' and hasattr(sc.render, 'use_texture_cache'):
            section_gap(content)
            cache = content.box()
            configure_layout(cache)
            section_header(cache, "Cycles Media Cache 5.2", icon="TEXTURE")
            row = cache.row(align=False)
            row.prop(sc.render, 'use_texture_cache', text='Texture Cache', toggle=True, icon='TEXTURE')
            auto = row.row(align=False)
            auto.enabled = bool(sc.render.use_texture_cache)
            if hasattr(sc.render, 'use_auto_generate_texture_cache'):
                auto.prop(sc.render, 'use_auto_generate_texture_cache', text='Auto Generate', toggle=True, icon='FILE_REFRESH')

        status = str(getattr(sc, 'fbp_background_render_status', '') or '')
        progress = int(getattr(sc, 'fbp_background_render_progress', 0) or 0)
        if status and status != 'Idle':
            row = actions.row(align=False)
            row.scale_y = 0.95
            row.label(text=status, icon='INFO')
            if progress > 0:
                row.label(text=f"{progress}%", icon='RENDER_RESULT')

        section_gap(content)
        project_actions = content.box()
        configure_layout(project_actions)
        section_header(project_actions, "Project Actions", icon="TOOL_SETTINGS")
        row = adaptive_row(project_actions, context, align=False, scale=1.05)
        row.operator("fbp.scan_project_to_setup", text="Scan to Setup", icon='IMPORT')
        row.operator("fbp.import_folder_hierarchy", text="Read Folder", icon='OUTLINER_COLLECTION')
        row.operator("fbp.import_folder_multiplane", text="Choose Folder", icon='FOLDER_REDIRECT')
        row = adaptive_row(project_actions, context, align=False, scale=1.05)
        op = row.operator("fbp.import_folder_multiplane", text="Paste Path", **ui_icon_kwargs("menu.clipboard"))
        op.from_clipboard = True
        op = row.operator("fbp.import_folder_multiplane", text="Reuse Last", icon='FILE_REFRESH')
        op.use_last_folder = True
        row.operator("fbp.refresh_all_media", text="", icon=ui_icon("action.refresh"))
        row.operator("fbp.apply_preferences_to_scene", text="", icon='CHECKMARK')


class FBP_PT_ProjectDoctor(Panel):
    bl_label = "Project Doctor"
    bl_description = "Scan, navigate and safely repair Frame By Plane project problems"
    bl_idname = "FBP_PT_project_doctor"
    bl_space_type = "PROPERTIES"
    bl_region_type = "WINDOW"
    bl_context = "output"
    bl_parent_id = "FBP_PT_output_anchor"
    bl_options = {"DEFAULT_CLOSED"}
    bl_order = 1

    def draw_header(self, context):
        status = str(getattr(context.scene, "fbp_health_last_status", "NOT_RUN") or "NOT_RUN").upper()
        icon = "CHECKMARK" if status == "PASS" else "ERROR" if status == "ERROR" else "INFO" if status == "WARNING" else "QUESTION"
        self.layout.label(text="", icon=icon)

    def draw(self, context):
        layout = configure_layout(self.layout)
        scene = context.scene
        counts = project_doctor_counts(scene)
        issue_count = sum(counts.values())

        actions = layout.row(align=True)
        scan = actions.operator("fbp.project_health_check", text="Scan", icon="VIEWZOOM")
        scan.repair = False
        repair = actions.operator("fbp.project_health_check", text="Safe Repair", icon="RECOVER_LAST")
        repair.repair = True
        actions.operator("fbp.clear_project_doctor_results", text="", icon="X")

        fixable_count = sum(
            1
            for item in tuple(getattr(scene, "fbp_health_issues", ()) or ())
            if str(getattr(item, "fix_action", "") or "")
        )
        summary = layout.row(align=True)
        summary.label(text=f"Errors {counts['ERROR']}", icon="ERROR")
        summary.label(text=f"Warnings {counts['WARNING']}", icon="INFO")
        summary.label(text=f"Info {counts['INFO']}", icon="DOT")
        if fixable_count:
            summary.label(text=f"Fixable {fixable_count}", icon="TOOL_SETTINGS")

        list_box = fbp_draw_uilist_header(
            layout, context, "PROJECT_DOCTOR", title="Issues"
        )
        last_run = str(getattr(scene, "fbp_health_last_run", "") or "")
        if last_run:
            timestamp = last_run.replace("T", " ").replace("+00:00", " UTC")
            hint_row(list_box, f"Last scan · {timestamp}", icon="TIME", disabled=True)

        if issue_count:
            list_box.template_list(
                "FBP_UL_ProjectDoctorIssues",
                "project_doctor",
                scene,
                "fbp_health_issues",
                scene,
                "fbp_health_issue_index",
                rows=max(4, min(8, issue_count)),
            )
            issue = active_project_doctor_issue(scene)
            if issue is not None:
                detail = layout.box()
                severity = str(getattr(issue, "severity", "INFO") or "INFO").upper()
                icon = "ERROR" if severity == "ERROR" else "INFO" if severity == "WARNING" else "DOT"
                header = detail.row(align=True)
                header.label(text=str(getattr(issue, "code", "GENERAL") or "GENERAL").replace("_", " ").title(), icon=icon)
                location = str(getattr(issue, "object_name", "") or getattr(issue, "data_name", "") or "")
                if location:
                    header.label(text=location)
                message = str(getattr(issue, "message", "") or "")
                for line in textwrap.wrap(message, width=58) or (message,):
                    detail.label(text=line)
                hint = str(getattr(issue, "repair_hint", "") or "")
                if hint:
                    detail.separator(factor=0.25)
                    hint_lines = textwrap.wrap(hint, width=58) or [hint]
                    for line_index, line in enumerate(hint_lines):
                        hint_line = detail.row(align=False)
                        hint_line.enabled = False
                        hint_line.label(text=line, icon="TOOL_SETTINGS" if line_index == 0 else "BLANK1")
                fix_action = str(getattr(issue, "fix_action", "") or "")
                fix_description = str(
                    getattr(issue, "fix_description", "") or ""
                )
                if fix_action:
                    detail.separator(factor=0.25)
                    action_box = detail.box()
                    action_header = action_box.row(align=True)
                    action_header.label(
                        text=str(
                            getattr(issue, "fix_label", "Fix Issue")
                            or "Fix Issue"
                        ),
                        icon="TOOL_SETTINGS",
                    )
                    for line in (
                        textwrap.wrap(fix_description, width=56)
                        or [fix_description]
                    ):
                        description_row = action_box.row(align=False)
                        description_row.enabled = False
                        description_row.label(text=line)
                    fix = action_box.operator(
                        "fbp.fix_project_health_issue",
                        text=str(
                            getattr(issue, "fix_label", "Fix Issue")
                            or "Fix Issue"
                        ),
                        icon="CHECKMARK",
                    )
                    fix.index = int(
                        getattr(scene, "fbp_health_issue_index", -1) or -1
                    )
                navigation_action = str(
                    getattr(issue, "navigation_action", "") or ""
                )
                if navigation_action:
                    navigate = detail.operator(
                        "fbp.navigate_project_health_issue",
                        text=str(
                            getattr(
                                issue,
                                "navigation_label",
                                "Open Problem",
                            )
                            or "Open Problem"
                        ),
                        icon=(
                            "RESTRICT_SELECT_OFF"
                            if navigation_action == "SELECT_OBJECT"
                            else "FILE_FOLDER"
                            if navigation_action == "REVEAL_PATH"
                            else "TEXT"
                        ),
                    )
                    navigate.index = int(
                        getattr(scene, "fbp_health_issue_index", -1) or -1
                    )
        else:
            status = str(getattr(scene, "fbp_health_last_status", "NOT_RUN") or "NOT_RUN").upper()
            if status == "PASS":
                empty_state(layout, "No project problems found", icon="CHECKMARK")
            else:
                empty_state(layout, "Run Project Doctor to inspect this scene", icon="VIEWZOOM")

        report = layout.row(align=True)
        report_tools = report.row(align=True)
        try:
            report_tools.enabled = bpy.data.texts.get(PROJECT_DOCTOR_REPORT_NAME) is not None
        except FBP_DATA_ERRORS:
            report_tools.enabled = False
        open_report = report_tools.operator("fbp.open_diagnostic_report", text="", icon="TEXT")
        open_report.report_name = PROJECT_DOCTOR_REPORT_NAME
        copy_report = report_tools.operator("fbp.copy_diagnostic_messages", text="", icon="COPYDOWN")
        copy_report.report_name = PROJECT_DOCTOR_REPORT_NAME
        copy_report.full_report = False
        report_tools.operator("fbp.export_project_doctor_report", text="", icon="EXPORT")


class FBP_PT_PerformanceDashboard(Panel):
    bl_label = "Performance Dashboard"
    bl_description = (
        "Compare per-layer media estimates, effect cost and observed "
        "Geometry Nodes timing"
    )
    bl_idname = "FBP_PT_performance_dashboard"
    bl_space_type = "PROPERTIES"
    bl_region_type = "WINDOW"
    bl_context = "output"
    bl_parent_id = "FBP_PT_output_anchor"
    bl_options = {"DEFAULT_CLOSED"}
    bl_order = 2

    def draw_header(self, context):
        status = (
            str(
                getattr(
                    context.window_manager,
                    "fbp_performance_status",
                    "NOT_RUN",
                )
                or "NOT_RUN"
            ).upper()
            if cached_performance_report(context.scene) is not None
            else "NOT_RUN"
        )
        icon = (
            "CHECKMARK"
            if status == "GOOD"
            else "INFO"
            if status == "ATTENTION"
            else "TIME"
        )
        self.layout.label(text="", icon=icon)

    def draw(self, context):
        draw_performance_dashboard_ui(self.layout, context)


class FBP_MT_PendingSetupActions(Menu):
    bl_idname = "FBP_MT_pending_setup_actions"
    bl_label = "Multiplane Setup Actions"

    def draw(self, context):
        layout = configure_layout(self.layout)
        scene = context.scene
        items = tuple(getattr(scene, "fbp_pending_planes", ()) or ())
        rows = getattr(scene, "fbp_pending_tree_rows", ())
        index = int(getattr(scene, "fbp_pending_tree_rows_idx", -1) or -1)
        active = rows[index] if 0 <= index < len(rows) else None

        if any(bool(getattr(item, "source_from_layered", False)) for item in items):
            layout.operator("fbp.layered_import_report", text="Layered Import Report", icon="INFO")
            layout.separator()

        toggle = layout.row(align=True)
        toggle.enabled = bool(active is not None and getattr(active, "can_toggle_structure", False))
        toggle.operator(
            "fbp.toggle_pending_sequence_collection",
            text="Toggle Sequence / Collection",
            icon=ui_icon("sequence.split"),
        )

        checked_by_collection = {}
        for item in items:
            if not bool(getattr(item, "is_selected", False)):
                continue
            name = str(getattr(item, "collection_name", "") or "")
            checked_by_collection[name] = checked_by_collection.get(name, 0) + 1
        reverse = layout.row(align=True)
        reverse.enabled = any(count >= 2 for count in checked_by_collection.values())
        reverse.operator(
            "fbp.reverse_pending_selected_order",
            text="Reverse Selected Order",
            icon=ui_icon("sequence.reverse"),
        )
        layout.separator()
        remove = layout.row(align=True)
        remove.enabled = active is not None
        remove.operator(
            "fbp.remove_pending_tree_selection",
            text="Remove",
            icon=ui_icon("generic.delete"),
        )


class FBP_MT_PendingSetupAdd(Menu):
    bl_idname = "FBP_MT_pending_setup_add"
    bl_label = "Add to Multiplane Setup"

    def draw(self, _context):
        layout = configure_layout(self.layout)
        layout.operator("fbp.add_pending_plane", text="Add Layer", icon=ui_icon("generic.add"))
        layout.operator("fbp.add_pending_collection", text="Add Collection", icon=ui_icon("setup.collection_new"))


class FBP_MT_CompositorLayerListActions(Menu):
    bl_idname = "FBP_MT_compositor_layer_list_actions"
    bl_label = "Compositor Layer Actions"

    def draw(self, context):
        layout = configure_layout(self.layout)
        add_folder = layout.operator(
            "fbp.compositor_layer_action", text="Add Folder", icon="NEWFOLDER"
        )
        add_folder.action = "ADD_FOLDER"
        group = layout.operator(
            "fbp.compositor_layer_action", text="Group Selected", icon="FILE_FOLDER"
        )
        group.action = "GROUP_SELECTED"
        ungroup = layout.operator(
            "fbp.compositor_layer_action", text="Ungroup Selected", icon="UNLINKED"
        )
        ungroup.action = "UNGROUP_SELECTED"
        layout.separator()
        remove = layout.operator(
            "fbp.compositor_layer_action", text="Remove", icon="TRASH"
        )
        remove.action = "REMOVE"


class FBP_MT_CompositorEffectListActions(Menu):
    bl_idname = "FBP_MT_compositor_effect_list_actions"
    bl_label = "Compositor Effect Actions"

    def draw(self, _context):
        layout = configure_layout(self.layout)
        remove = layout.operator(
            "fbp.compositor_effect_action", text="Remove", icon="TRASH"
        )
        remove.action = "REMOVE"


def _fbp_draw_preview_scope_badge(layout, label):
    """Draw the shared, non-marketing Preview scope notice and diagnostics."""
    badge = layout.row(align=True)
    badge.alert = True
    badge.label(text=f"{label} · Preview", icon="INFO")
    badge.label(text="Outside the 7.1 LTS stability promise")
    badge.operator("fbp.copy_preview_diagnostics", text="Copy Diagnostics", icon="COPYDOWN")


class FBP_PT_OutputCompositor(Panel):
    bl_label = "Frame By Plane Compositor"
    bl_description = f"Generate isolated View Layers from tags, layers, {primary_shortcut_label('G')} groups or collections and build per-layer compositor effects"
    bl_idname = "FBP_PT_output_compositor"
    bl_space_type = 'PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_context = 'view_layer'
    bl_parent_id = 'VIEWLAYER_PT_context_layer'
    bl_order = 0

    @classmethod
    def poll(cls, context):
        return getattr(context, "scene", None) is not None

    def draw_header(self, context):
        self.layout.label(text="", icon='NODE_COMPOSITING')

    def draw(self, context):
        layout = configure_layout(self.layout)
        sc = context.scene
        content = layout.column(align=False)
        _fbp_draw_preview_scope_badge(content, "Compositor Layers")

        if not fbp_feature_enabled(sc, "compositor_layers"):
            empty_state(
                content,
                "Compositor Preview Disabled",
                "Enable the compositor workflow for this .blend file.",
                icon='NODE_COMPOSITING',
            )
            enable = content.row(align=False)
            enable.scale_y = 1.1
            enable.prop(
                sc,
                "fbp_experimental_compositor",
                text="Enable Compositor",
                toggle=True,
                icon='NODE_COMPOSITING',
            )
            return

        section_header(content, "Render", icon='IMAGE_ALPHA')
        row = content.row(align=False)
        row.prop(sc, "fbp_compositor_transparent", text="Transparent", toggle=True, icon='IMAGE_ALPHA')
        row.prop(sc, "fbp_compositor_disable_unmanaged_layers", text="Managed Only", toggle=True, icon='RENDERLAYERS')
        content.prop(sc, "fbp_alpha_render_method", text="Alpha Rendering", icon='IMAGE_ALPHA')
        if any(
            str(getattr(item, "source_kind", 'MANUAL') or 'MANUAL') == 'MANUAL'
            and str(getattr(item, "row_type", 'LAYER') or 'LAYER') != 'FOLDER'
            for item in sc.fbp_compositor_layers
        ):
            content.prop(sc, "fbp_compositor_include_unassigned", text="Share Unassigned Groups", toggle=True)

        section_gap(content)
        layer_count = len(sc.fbp_compositor_layers)
        section_header(content, "Layers", icon='RENDERLAYERS', count=layer_count)
        content.prop(sc, "fbp_compositor_generation_mode", text="Source", icon='OUTLINER_COLLECTION')
        actions = content.row(align=False)
        actions.operator("fbp.compositor_auto_layers", text="Generate Layers", icon='OUTLINER_COLLECTION')
        sync = actions.operator("fbp.sync_compositor_layer_node_prototype", text="Sync Node", icon='FILE_REFRESH')
        sync.native_group = True

        index = int(getattr(sc, "fbp_compositor_layer_index", -1))
        item = sc.fbp_compositor_layers[index] if 0 <= index < layer_count else None
        selected_layers = [
            layer for layer in sc.fbp_compositor_layers
            if bool(getattr(layer, "selected", False))
            and str(getattr(layer, "row_type", 'LAYER') or 'LAYER') != 'FOLDER'
        ]
        can_group = bool(selected_layers) or (
            item is not None and str(getattr(item, "row_type", 'LAYER') or 'LAYER') != 'FOLDER'
        )
        can_ungroup = any(str(getattr(layer, "parent_folder_id", "") or "") for layer in selected_layers) or (
            item is not None
            and str(getattr(item, "row_type", 'LAYER') or 'LAYER') != 'FOLDER'
            and bool(str(getattr(item, "parent_folder_id", "") or ""))
        )

        if layer_count:
            list_box = fbp_draw_uilist_header(
                content, context, "COMPOSITOR_LAYERS"
            )
            list_row = list_box.row(align=False)
            list_row.template_list(
                "FBP_UL_CompositorLayers",
                "",
                sc,
                "fbp_compositor_layers",
                sc,
                "fbp_compositor_layer_index",
                rows=list_rows(layer_count, minimum=6, maximum=10),
            )
            controls = list_row.column(align=True)
            fbp_set_ui_units_x(controls, 1.0)
            controls.menu(
                "FBP_MT_compositor_layer_list_actions",
                text="",
                icon="COLLAPSEMENU",
            )
            controls.separator()
            moves = controls.column(align=True)
            button = moves.row(align=True)
            button.enabled = index > 0
            op = button.operator("fbp.compositor_layer_action", text="", icon="SORT_DESC")
            op.action = 'UP'
            button = moves.row(align=True)
            button.enabled = 0 <= index < layer_count - 1
            op = button.operator("fbp.compositor_layer_action", text="", icon="SORT_ASC")
            op.action = 'DOWN'
            controls.separator()
            op = controls.operator("fbp.compositor_layer_action", text="", icon="ADD")
            op.action = 'ADD'
        else:
            empty_state(content, "No compositor layers", "Choose a source and press Generate", icon='RENDERLAYERS')

        if len(selected_layers) > 1:
            hint_row(content, f"{len(selected_layers)} layers selected", icon='RESTRICT_SELECT_OFF', disabled=True)

        if item is not None:
            is_folder = str(getattr(item, "row_type", 'LAYER') or 'LAYER') == 'FOLDER'
            section_gap(content)
            settings = content.box()
            configure_layout(settings)
            section_header(settings, "Folder" if is_folder else "Layer", icon='FILE_FOLDER' if is_folder else 'RENDERLAYERS')
            row = adaptive_row(settings, context, scale=1.0)
            row.prop(item, "name", text="Name")
            if not is_folder:
                row.prop(item, "view_layer_name", text="View Layer")
            row = settings.row(align=False)
            row.prop(item, "enabled", text="Visible", toggle=True, icon='HIDE_OFF')
            row.prop(item, "holdout", text="Holdout", toggle=True, **ui_icon_kwargs("menu.holdout_plane", fallback="CLIPUV_HLT"))
            row.prop(item, "indirect_only", text="Indirect Only", toggle=True, icon='OUTLINER_OB_LIGHT')
            row = adaptive_row(settings, context, scale=1.0)
            if not is_folder:
                row.prop(item, "use_depth", text="Depth", toggle=True, icon='IMAGE_ZDEPTH')
            row.prop(item, "expose_output", text="Output", toggle=True, icon='OUTPUT')
            row.prop(item, "opacity", text="Opacity")

            source_kind = str(getattr(item, "source_kind", 'MANUAL') or 'MANUAL')
            source_labels = {
                'TAG': "Layer List color tag",
                'LAYER': "Single Layer List layer",
                'GROUP': f"Editable {primary_shortcut_label('G')} layer group",
                'COLLECTION': "Collection",
                'MANUAL': "Manual collection assignment",
            }
            if is_folder:
                child_count = sum(
                    1 for child in sc.fbp_compositor_layers
                    if str(getattr(child, "parent_folder_id", "") or "")
                    == str(getattr(item, "layer_id", "") or "")
                )
                hint_row(
                    settings,
                    f"Compositor folder · {child_count} layer{'s' if child_count != 1 else ''}",
                    icon='FILE_FOLDER',
                    disabled=True,
                )
            else:
                hint_row(settings, source_labels.get(source_kind, "Compositor source"), icon='INFO', disabled=True)

            if source_kind == 'MANUAL' and not is_folder:
                try:
                    active_group = fbp_active_work_collection(context)
                except FBP_DATA_ERRORS:
                    active_group = None
                assignment = settings.row(align=False)
                assignment.label(
                    text=active_group.name if active_group is not None else "Select a Layer Stack collection",
                    icon='OUTLINER_COLLECTION',
                )
                assignment.operator("fbp.compositor_assign_group", text="Assign", icon='FORWARD').clear = False
                assignment.operator("fbp.compositor_assign_group", text="", icon='X').clear = True

            section_gap(settings, 0.25)
            effect_count = len(item.effects)
            section_header(settings, "Effects", icon='SHADERFX', count=effect_count)

            effect_index = int(getattr(item, "effects_index", -1))
            effect = item.effects[effect_index] if 0 <= effect_index < effect_count else None
            if effect_count:
                list_box = fbp_draw_uilist_header(
                    settings, context, "COMPOSITOR_EFFECTS"
                )
                effects_row = list_box.row(align=False)
                effects_row.template_list(
                    "FBP_UL_CompositorEffects",
                    "",
                    item,
                    "effects",
                    item,
                    "effects_index",
                    rows=list_rows(effect_count, minimum=3, maximum=6),
                )
                effect_controls = effects_row.column(align=True)
                fbp_set_ui_units_x(effect_controls, 1.0)
                effect_controls.menu(
                    "FBP_MT_compositor_effect_list_actions",
                    text="",
                    icon="COLLAPSEMENU",
                )
                effect_controls.separator()
                moves = effect_controls.column(align=True)
                button = moves.row(align=True)
                button.enabled = effect_index > 0
                op = button.operator("fbp.compositor_effect_action", text="", icon="SORT_DESC")
                op.action = 'UP'
                button = moves.row(align=True)
                button.enabled = 0 <= effect_index < effect_count - 1
                op = button.operator("fbp.compositor_effect_action", text="", icon="SORT_ASC")
                op.action = 'DOWN'
                effect_controls.separator()
                add_effect = effect_controls.operator_menu_enum(
                    "fbp.compositor_effect_action",
                    "effect_type",
                    text="",
                    icon="ADD",
                )
                add_effect.action = 'ADD'
            else:
                empty_state(settings, "No effects", "Use Add to build the compositor chain", icon='NODE_COMPOSITING', boxed=False)

            if effect is not None:
                effect_settings = settings.column(align=False)
                row = effect_settings.row(align=False)
                row.prop(effect, "effect_type", text="Effect")
                row.prop(effect, "effect_mix", text="Mix")
                if effect.effect_type == 'GLOW':
                    row = adaptive_row(effect_settings, context, scale=1.0)
                    row.prop(effect, "glow_threshold")
                    row.prop(effect, "glow_strength")
                    row.prop(effect, "glow_size")
                elif effect.effect_type == 'BLUR':
                    effect_settings.prop(effect, "blur_size")
                elif effect.effect_type == 'DEFOCUS':
                    row = adaptive_row(effect_settings, context, scale=1.0)
                    row.prop(effect, "defocus_f_stop")
                    row.prop(effect, "defocus_blur_max")
                elif effect.effect_type == 'COLOR_GRADE':
                    row = adaptive_row(effect_settings, context, scale=1.0)
                    row.prop(effect, "color_temperature")
                    row.prop(effect, "color_tint")
                elif effect.effect_type == 'PIXELATE':
                    effect_settings.prop(effect, "pixel_size")
                elif effect.effect_type == 'VIGNETTE':
                    row = adaptive_row(effect_settings, context, scale=1.0)
                    row.prop(effect, "vignette_factor")
                    row.prop(effect, "vignette_feather")
                    row.prop(effect, "vignette_roundness")
                    effect_settings.prop(effect, "vignette_scale")
                elif effect.effect_type == 'UNSHARP_MASK':
                    row = adaptive_row(effect_settings, context, scale=1.0)
                    row.prop(effect, "unsharp_radius")
                    row.prop(effect, "unsharp_factor")
                    row.prop(effect, "unsharp_threshold")
                elif effect.effect_type == 'TUNE_IMAGE':
                    row = adaptive_row(effect_settings, context, scale=1.0)
                    row.prop(effect, "tune_contrast")
                    row.prop(effect, "tune_color_boost")
                    row.prop(effect, "tune_clarity")
                    row = adaptive_row(effect_settings, context, scale=1.0)
                    row.prop(effect, "tune_detail")
                    row.prop(effect, "tune_sharpen")
                elif effect.effect_type == 'FILM_GRAIN':
                    row = adaptive_row(effect_settings, context, scale=1.0)
                    row.prop(effect, "film_grain_factor")
                    row.prop(effect, "film_grain_iso")
                    row.prop(effect, "film_grain_animated", toggle=True)
                    row = adaptive_row(effect_settings, context, scale=1.0)
                    row.prop(effect, "film_grain_softness")
                    row.prop(effect, "film_grain_coarseness")
                elif effect.effect_type == 'CHROMATIC_ABERRATION':
                    row = adaptive_row(effect_settings, context, scale=1.0)
                    row.prop(effect, "chromatic_factor")
                    row.prop(effect, "chromatic_samples")
                    row.prop(effect, "chromatic_fit", toggle=True)
                elif effect.effect_type == 'SEPIA':
                    row = adaptive_row(effect_settings, context, scale=1.0)
                    row.prop(effect, "sepia_contrast")
                    row.prop(effect, "sepia_tone")
                    row.prop(effect, "sepia_saturation")

        uses_depth = any(
            layer.use_depth
            or any(effect.enabled and effect.effect_type == 'DEFOCUS' for effect in getattr(layer, "effects", ()))
            for layer in sc.fbp_compositor_layers
        )
        if uses_depth:
            hint_row(content, "Depth pass enabled for Defocus or layer depth", icon='IMAGE_ZDEPTH', disabled=True)

        status = str(getattr(sc, "fbp_compositor_status", "") or "")
        if status:
            hint_row(content, status, icon='FILE_REFRESH' if 'sync' in status.casefold() else 'INFO', disabled=True)
        if bool(getattr(sc, "fbp_compositor_enabled", False)):
            section_gap(content, 0.2)
            content.operator("fbp.compositor_restore", text="Restore Native Compositor", icon='LOOP_BACK')

class FBP_PT_CompositorNodeSidebar(Panel):
    bl_label = "Layer Effects"
    bl_description = "Quick controls for the active Frame By Plane compositor layer"
    bl_idname = "FBP_PT_compositor_node_sidebar"
    bl_space_type = 'NODE_EDITOR'
    bl_region_type = 'UI'
    bl_category = "Frame By Plane"

    @classmethod
    def poll(cls, context):
        scene = getattr(context, "scene", None)
        space = getattr(context, "space_data", None)
        return bool(
            scene is not None
            and str(getattr(space, "tree_type", "") or "") == 'CompositorNodeTree'
        )

    def draw(self, context):
        layout = configure_layout(self.layout)
        scene = context.scene
        _fbp_draw_preview_scope_badge(layout, "Compositor Layers")
        if not fbp_feature_enabled(scene, "compositor_layers"):
            empty_state(
                layout,
                "Compositor Preview Disabled",
                "Enable the compositor workflow for this .blend file.",
                icon='NODE_COMPOSITING',
            )
            enable = layout.row(align=False)
            enable.scale_y = 1.1
            enable.prop(
                scene,
                "fbp_experimental_compositor",
                text="Enable Compositor",
                toggle=True,
                icon='NODE_COMPOSITING',
            )
            return
        items = scene.fbp_compositor_layers
        index = int(getattr(scene, "fbp_compositor_layer_index", -1))
        active = items[index] if 0 <= index < len(items) else None
        selected_count = sum(1 for item in items if bool(getattr(item, "selected", False)))

        if active is None:
            empty_state(layout, "No active compositor layer", "Generate layers or select one in View Layer Properties", icon='RENDERLAYERS')
            layout.operator("fbp.compositor_auto_layers", text="Generate Layers", icon='OUTLINER_COLLECTION')
            return

        is_folder = str(getattr(active, "row_type", 'LAYER') or 'LAYER') == 'FOLDER'
        section_header(
            layout,
            active.name or ("Folder" if is_folder else "Layer"),
            icon='FILE_FOLDER' if is_folder else 'RENDERLAYERS',
            suffix=f"· {selected_count} selected" if selected_count > 1 else "",
        )
        row = layout.row(align=False)
        row.prop(active, "enabled", text="Visible", toggle=True, icon='HIDE_OFF')
        row.prop(active, "holdout", text="Holdout", toggle=True, **ui_icon_kwargs("menu.holdout_plane", fallback="CLIPUV_HLT"))
        row.prop(active, "indirect_only", text="Indirect Only", toggle=True, icon='OUTLINER_OB_LIGHT')
        row = adaptive_row(layout, context, scale=1.0)
        if not is_folder:
            row.prop(active, "use_depth", text="Depth", toggle=True, icon='IMAGE_ZDEPTH')
        row.prop(active, "expose_output", text="Output", toggle=True, icon='OUTPUT')
        row.prop(active, "opacity", text="Opacity")

        actions = layout.row(align=False)
        add_effect = actions.operator_menu_enum(
            "fbp.compositor_effect_action",
            "effect_type",
            text="Add Effect",
            icon='ADD',
        )
        add_effect.action = 'ADD'
        actions.operator("fbp.compositor_repair_rebuild", text="Sync", icon='FILE_REFRESH')

class FBP_PT_CameraSettings(Panel):
    bl_label = "Frame By Plane Camera"
    bl_description = "Camera settings used by Frame By Plane generation and camera fitting"
    bl_idname = "FBP_PT_camera_settings"
    bl_space_type = 'PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_context = 'data'
    bl_parent_id = 'DATA_PT_context_camera'
    bl_order = 0

    @classmethod
    def poll(cls, context):
        obj = getattr(context, "object", None)
        return bool(obj and getattr(obj, "type", None) == 'CAMERA')

    def draw_header(self, context):
        self.layout.label(text="", icon=ui_icon("settings.camera_tab"))

    def draw(self, context):
        layout = configure_layout(self.layout)
        sc = context.scene

        camera = layout.box()
        configure_layout(camera)
        section_header(camera, "Lens and Framing", icon=ui_icon("settings.camera_tab"))
        row = adaptive_row(camera, context)
        row.prop(sc, "fbp_camera_projection", text="Projection", icon=ui_icon("settings.projection"))
        if sc.fbp_camera_projection == 'ORTHO':
            row.prop(sc, "fbp_camera_ortho_scale", text="Scale", icon='VIEW_CAMERA_UNSELECTED')
        else:
            row.prop(sc, "fbp_camera_lens", text="Lens", icon='CAMERA_DATA')

        row = adaptive_row(camera, context)
        row.prop(sc, "fbp_cam_ratio", text="Aspect", icon=ui_icon("settings.camera_frame"))
        row.prop(sc, "fbp_camera_fit_source_aspect", text="Source Aspect", toggle=True, icon='IMAGE_DATA')

        resolution = adaptive_row(camera, context)
        resolution.active = sc.fbp_cam_ratio == 'CUSTOM' and not bool(getattr(sc, "fbp_camera_fit_source_aspect", False))
        resolution.prop(sc.render, "resolution_x", text="X")
        resolution.prop(sc.render, "resolution_y", text="Y")

        section_gap(layout)
        setup = layout.box()
        configure_layout(setup)
        section_header(setup, "Clipping and Generation", icon="TOOL_SETTINGS")
        row = adaptive_row(setup, context)
        row.prop(sc, "fbp_camera_clip_start", text="Clip Start")
        row.prop(sc, "fbp_camera_clip_end", text="Clip End")

        row = adaptive_row(setup, context)
        row.prop(sc, "fbp_gen_camera", text="Create Camera", toggle=True, icon='CAMERA_DATA')
        row.prop(sc, "fbp_cam_pivot", text="Cursor Pivot", toggle=True, icon='PIVOT_CURSOR')
        setup.prop(sc, "fbp_auto_scale", text="Fit Layers to Camera", toggle=True, icon='FULLSCREEN_ENTER')


def fbp_scene_has_cached_rigs(context):
    """Use the bounded scene index instead of rebuilding UI object lists."""
    scene = getattr(context, "scene", None) if context else None
    if not scene:
        return False
    try:
        if next(iter_scene_fbp_rigs(scene, fallback=True), None) is not None:
            return True
    except FBP_DATA_ERRORS:
        pass
    try:
        active = getattr(context, "active_object", None)
        return bool(active and is_fbp_layer_object(active))
    except FBP_DATA_ERRORS:
        return False


# SECTION 06 - Panel: Layer Stack #
# ###ICON Panel Layer Stack, Functions: sort, add, color plane, duplicate, delete, select all.
class FBP_PT_FrameByPlaneSidebarAnchor(Panel):
    """Invisible top anchor for the dedicated Frame By Plane sidebar tab."""

    bl_label = ""
    bl_idname = "FBP_PT_frame_by_plane_sidebar_anchor"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Frame By Plane"
    bl_options = {'HIDE_HEADER'}
    bl_order = 0

    @classmethod
    def poll(cls, context):
        return _fbp_sidebar_has_visible_sections(context, dedicated=True)

    def draw(self, _context):
        pass


class FBP_PT_ToolSidebarAnchor(Panel):
    """Invisible top anchor for Frame By Plane panels mirrored in Tool."""

    bl_label = ""
    bl_idname = "FBP_PT_tool_sidebar_anchor"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Tool"
    bl_options = {'HIDE_HEADER'}
    bl_order = 0

    @classmethod
    def poll(cls, context):
        return _fbp_sidebar_has_visible_sections(context, dedicated=False)

    def draw(self, _context):
        pass


def _fbp_layer_stack_context_available(context):
    """Return True when the Plane Layer List has real plane-rig content."""
    return fbp_scene_has_cached_rigs(context)


def _fbp_gp_stack_context_available(context):
    """Return True when the Grease Pencil Layer List has a drawing canvas."""
    try:
        return scene_has_gp_canvas(
            getattr(context, "scene", None),
            kind="DRAWING",
        )
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        return False


def _fbp_sequence_context_available(context):
    """Return True when a selected FBP/GP object can expose layer settings."""
    try:
        from .grease_pencil_bridge import is_gp_canvas
        if is_gp_canvas(getattr(context, "object", None)):
            return True
    except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        pass
    return _fbp_active_plane_context(context) is not None


def _fbp_tool_ui_context_available(context):
    """Keep the primary Tool/Properties workflow visible for every valid scene."""
    return bool(context and getattr(context, "scene", None))


def _fbp_draw_tool_layer_stack_or_create(panel, context):
    """Draw the plane stack, or a compact create/recovery UI when no rig is cached."""
    if _fbp_layer_stack_context_available(context):
        FBP_PT_LayerStack.draw(panel, context)
        return
    layout = configure_layout(panel.layout)
    empty_state(
        layout,
        "No Frame By Plane layers",
        "Create or import a plane to populate the layer stack.",
        icon="INFO",
    )
    draw_creation_ui(layout, context)


def _fbp_draw_tool_gp_stack_or_hint(panel, context):
    """Draw the Grease Pencil stack mirror only for real drawing canvases."""
    layout = configure_layout(panel.layout)
    if _fbp_gp_stack_context_available(context):
        FBP_PT_GreasePencilStack.draw(panel, context)
        return
    empty_state(
        layout,
        "No Grease Pencil layers",
        "Create or select a Frame By Plane Grease Pencil canvas.",
        icon="GREASEPENCIL",
    )


def _fbp_draw_tool_sequence_or_hint(panel, context):
    """Draw selected-layer settings, or keep the panel visible with guidance."""
    if _fbp_sequence_context_available(context):
        FBP_PT_Sequence.draw(panel, context)
        return
    layout = configure_layout(panel.layout)
    empty_state(
        layout,
        "Select a Frame By Plane layer",
        "Timing, frames, appearance and transform controls will appear here.",
        icon="RESTRICT_SELECT_OFF",
    )


def _fbp_active_layer_tree_row_type(context, list_mode='ALL'):
    sc = getattr(context, 'scene', None)
    if sc is None:
        return ''
    try:
        tree_index = int(getattr(sc, 'fbp_layer_tree_rows_idx', -1))
        rows = getattr(sc, 'fbp_layer_tree_rows', ())
        if 0 <= tree_index < len(rows):
            row = rows[tree_index]
            if not fbp_layer_tree_row_visible_for_mode(row, list_mode):
                return ''
            return str(getattr(row, 'row_type', '') or '')
    except FBP_DATA_ERRORS:
        pass
    return ''


def _fbp_collection_nesting_availability(context, list_mode='ALL'):
    """Return (collection, can_move_in, can_move_out) for the active GROUP row."""
    scene = getattr(context, 'scene', None)
    if scene is None:
        return None, False, False
    try:
        rows = getattr(scene, 'fbp_layer_tree_rows', ()) or ()
        index = int(getattr(scene, 'fbp_layer_tree_rows_idx', -1))
        if not (0 <= index < len(rows)):
            return None, False, False
        row = rows[index]
        if str(getattr(row, 'row_type', '') or '') != 'GROUP':
            return None, False, False
        if not fbp_layer_tree_row_visible_for_mode(row, list_mode):
            return None, False, False
        name = str(getattr(row, 'collection_name', '') or '')
        collection = bpy.data.collections.get(name)
        if collection is None:
            return None, False, False
        tree = fbp_build_canonical_collection_tree(scene)
        parent_by_key = tree.get('parent_by_key', {}) or {}
        try:
            collection_key = int(collection.as_pointer())
        except FBP_DATA_ERRORS:
            collection_key = id(collection)
        current_parent_key = parent_by_key.get(collection_key)
        depth = int(getattr(row, 'depth', 0) or 0)
        can_move_in = False
        for previous_index in range(index - 1, -1, -1):
            previous = rows[previous_index]
            previous_depth = int(getattr(previous, 'depth', 0) or 0)
            if previous_depth < depth:
                break
            if (
                previous_depth == depth
                and str(getattr(previous, 'row_type', '') or '') == 'GROUP'
                and fbp_layer_tree_row_visible_for_mode(previous, list_mode)
            ):
                previous_name = str(getattr(previous, 'collection_name', '') or '')
                previous_collection = bpy.data.collections.get(previous_name)
                if previous_collection is None:
                    continue
                try:
                    previous_key = int(previous_collection.as_pointer())
                except FBP_DATA_ERRORS:
                    previous_key = id(previous_collection)
                if parent_by_key.get(previous_key) == current_parent_key:
                    can_move_in = True
                    break
        root_key = tree.get('root_key')
        can_move_out = current_parent_key not in {None, root_key}
        return collection, can_move_in, can_move_out
    except FBP_DATA_ERRORS:
        return None, False, False


def _fbp_draw_layer_side_toolbar(layout, context, *, mode='PLANES'):
    is_gp_mode = str(mode).upper() == 'GP'
    selected_rigs = [] if is_gp_mode else get_selected_rigs(context)
    active_type = _fbp_active_layer_tree_row_type(
        context, 'GP' if is_gp_mode else 'PLANES'
    )
    col = layout.column(align=True)
    fbp_set_ui_units_x(col, 1.0)
    # Icon-only operator popup. Unlike Menu RNA this remains valid after an
    # in-place extension reload and cannot open the stale blank menu reported by users.
    options = col.operator('fbp.layer_options_popup', text='', icon='COLLAPSEMENU')
    options.grease_pencil = is_gp_mode
    col.separator()

    active_collection, can_move_collection_in, can_move_collection_out = (
        _fbp_collection_nesting_availability(
            context, 'GP' if is_gp_mode else 'PLANES'
        )
    )
    if active_type == 'GROUP' and active_collection is not None:
        move = col.row(align=True)
        move.enabled = can_move_collection_out
        op = move.operator('fbp.move_layer_collection', text='', icon='TRIA_LEFT')
        op.action = 'OUT'
        op.collection_name = active_collection.name
        op.list_mode = 'GP' if is_gp_mode else 'PLANES'
        move = col.row(align=True)
        move.enabled = can_move_collection_in
        op = move.operator('fbp.move_layer_collection', text='', icon='TRIA_RIGHT')
        op.action = 'IN'
        op.collection_name = active_collection.name
        op.list_mode = 'GP' if is_gp_mode else 'PLANES'
    else:
        can_move = active_type in ({'GP_CANVAS'} if is_gp_mode else {'LAYER'})
        if not is_gp_mode:
            can_move = bool(len(selected_rigs) == 1 or (active_type == 'LAYER' and not selected_rigs))
        move = col.row(align=True)
        move.enabled = can_move
        move.operator('fbp.move_layer_stack', text='', icon=ui_icon('generic.up')).direction = 'UP'
        move = col.row(align=True)
        move.enabled = can_move
        move.operator('fbp.move_layer_stack', text='', icon=ui_icon('generic.down')).direction = 'DOWN'

    if not is_gp_mode:
        selected_by_collection = {}
        reverse_available = False
        for rig in selected_rigs:
            collection = get_primary_fbp_collection(rig)
            if collection is None:
                continue
            try:
                key = int(collection.as_pointer())
            except FBP_DATA_ERRORS:
                continue
            selected_by_collection[key] = selected_by_collection.get(key, 0) + 1
            if selected_by_collection[key] >= 2:
                reverse_available = True
                break
        reverse_order = col.row(align=False)
        reverse_order.enabled = reverse_available
        reverse_order.operator('fbp.reverse_selected_layer_order', text='', icon=ui_icon('sequence.reverse'))
    else:
        collapse = col.row(align=True)
        collapse.enabled = True
        collapse.operator('fbp.collapse_gp_canvases_to_one', text='', icon=ui_icon('menu.gp_layer'))

    col.separator()
    delete = col.row(align=True)
    if active_type == 'GROUP' and active_collection is not None:
        delete.enabled = True
        op = delete.operator('fbp.delete_layer_collection', text='', icon=ui_icon('generic.delete'))
        op.collection_name = active_collection.name
    elif is_gp_mode:
        delete.enabled = True
        delete.operator('fbp.delete_grease_pencil_canvas', text='', icon=ui_icon('generic.delete'))
    else:
        delete.enabled = bool(selected_rigs)
        delete.operator('fbp.delete_sequence', text='', icon=ui_icon('generic.delete'))


def _fbp_draw_layer_list_header_filter(header, context, profile_id):
    """Place the shared filter and icon-layout controls in the title row."""
    scene = getattr(context, "scene", None)
    if scene is None or not hasattr(scene, "fbp_layer_filter_search"):
        return
    _fbp_draw_uilist_header_controls(
        header, context, profile_id, native_layer_filter=True
    )


def _fbp_draw_layer_sets_and_snapshots(layout, context):
    """Draw Layer Sets and Visibility Snapshots side by side in one foldout."""
    try:
        header, body = layout.panel(
            "FBP_layer_sets_visibility_snapshots",
            default_closed=True,
        )
    except (AttributeError, RuntimeError, TypeError, ValueError):
        header = layout.row(align=False)
        body = layout.column(align=False)
    header.label(text="Sets & Snapshots", icon="BOOKMARKS")
    if body is None:
        return
    split = body.split(factor=0.5, align=False)
    draw_layer_sets_ui(split.column(align=False), context)
    draw_visibility_snapshots_ui(split.column(align=False), context)


class FBP_PT_LayerStack(Panel):
    bl_label       = "Layers"
    bl_description = "Manage Frame By Plane image, video, color and gradient layers"
    bl_idname      = "FBP_PT_layer_stack"
    bl_space_type  = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category    = "Frame By Plane"
    bl_parent_id   = "FBP_PT_frame_by_plane_sidebar_anchor"
    bl_order       = 0

    @classmethod
    def poll(cls, context):
        return bool(
            _fbp_tool_ui_context_available(context)
            and _fbp_n_panel_enabled(context)
            and _fbp_panel_section_enabled(context, 'LAYERS')
        )

    def draw_header(self, context):
        self.layout.label(text="", icon=ui_icon("layer.header"))

    def draw(self, context):
        layout = configure_layout(self.layout)
        row = layout.row(align=False)
        box = row.box()
        configure_layout(box)
        rig_count = sum(1 for _rig in iter_scene_fbp_rigs(context.scene, fallback=True))
        selected_count = len(get_selected_rigs(context))
        header = section_header(
            box,
            "Plane Layers",
            icon=ui_icon("layer.header"),
            count=rig_count,
            suffix=(f"({selected_count} selected)" if selected_count > 1 else ""),
        )
        _fbp_draw_layer_list_header_filter(header, context, "LAYER_PLANES")
        draw_layer_tree_uilist(box, context, min_rows=FBP_UI_LIST_MIN_ROWS, list_type='PLANES')
        _fbp_draw_layer_side_toolbar(row, context, mode='PLANES')
        section_gap(layout)
        _fbp_draw_layer_sets_and_snapshots(layout, context)


class FBP_PT_GreasePencilStack(Panel):
    bl_label       = "Grease Pencil"
    bl_description = "Manage Grease Pencil drawing planes, internal layers and layer tools"
    bl_idname      = "FBP_PT_grease_pencil_stack"
    bl_space_type  = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category    = "Frame By Plane"
    bl_parent_id   = "FBP_PT_frame_by_plane_sidebar_anchor"
    bl_order       = 1

    @classmethod
    def poll(cls, context):
        return bool(
            _fbp_tool_ui_context_available(context)
            and _fbp_n_panel_enabled(context)
            and _fbp_panel_section_enabled(context, 'GP')
            and _fbp_scene_has_drawing_gp(context)
        )

    def draw_header(self, context):
        self.layout.label(text="", **ui_label_icon_kwargs("menu.gp_layer"))

    def draw(self, context):
        layout = configure_layout(self.layout)
        row = layout.row(align=False)
        box = row.box()
        configure_layout(box)
        gp_count = sum(
            1
            for _canvas in iter_scene_gp_canvases(
                context.scene,
                kind="DRAWING",
                fallback=True,
            )
        )
        gp_icon = ui_label_icon_kwargs("menu.gp_layer")
        header = section_header(
            box,
            "Grease Pencil Layers",
            icon=gp_icon.get("icon", "GREASEPENCIL"),
            icon_value=gp_icon.get("icon_value", 0),
            count=gp_count,
        )
        _fbp_draw_layer_list_header_filter(header, context, "LAYER_GP")
        draw_gp_layer_tree_uilist(box, context, min_rows=FBP_UI_LIST_MIN_ROWS)
        _fbp_draw_layer_side_toolbar(row, context, mode='GP')

        # Keep advanced GP operations in the same compact three-button pattern
        # used by the other Frame By Plane tool strips.
        tools = layout.box()
        configure_layout(tools)
        section_header(tools, "Grease Pencil Tools", icon="TOOL_SETTINGS")
        tool_row = adaptive_row(tools, context)
        tool_row.operator('fbp.collapse_gp_canvases_to_one', text='Collapse', icon=ui_icon('menu.gp_layer'))
        tool_row.operator('fbp.split_gp_canvas_layers', text='Split', icon=ui_icon('sequence.split'))
        tool_row.operator('fbp.use_grease_pencil_as_mask', text='Use as Mask', icon='CLIPUV_HLT')


def _fbp_draw_blend_control(layout, selected_rigs):
    """Draw Layer Blend as a first-class control above the effects stack."""
    if not selected_rigs:
        return
    common_mode = _fbp_common_layer_blend_mode(selected_rigs)
    row = layout.row(align=True)
    row.scale_y = 1.0
    row.label(text="Blend", icon="NODE_MATERIAL")
    if common_mode:
        menu_text = f"{fbp_layer_blend_short(common_mode)}   {fbp_layer_blend_label(common_mode)}"
    else:
        menu_text = "Mixed"
    row.menu(
        FBP_MT_LayerBlendDropdown.bl_idname,
        text=menu_text,
        icon="DOWNARROW_HLT",
    )

    if len(selected_rigs) == 1 and common_mode and common_mode != "NORMAL":
        rig = selected_rigs[0]
        factor = layout.row(align=True)
        factor.prop(rig, "fbp_layer_blend_factor", text="Opacity", slider=True, icon="IMAGE_ALPHA")
        source = getattr(rig, "fbp_layer_blend_source", None)
        if source is None:
            warning = layout.row(align=False)
            warning.alert = True
            warning.label(text="No compatible image layer below", icon="ERROR")
        else:
            source_row = layout.row(align=False)
            source_row.label(text="Source", icon="NODE_MATERIAL")
            select_source = source_row.operator(
                "fbp.select_layer_relation_source",
                text=getattr(source, "name", "Layer"),
                icon="RESTRICT_SELECT_OFF",
            )
            select_source.rig_name = rig.name
            select_source.relation = 'BLEND'

    layout.separator(factor=0.35)


def draw_effects_ui(layout, context, *, force_view=None):
    """Draw Image, Mask and Mesh stacks without replacing the main controls.

    Shape Mask helpers expose contextual settings, but those settings are
    deliberately drawn *after* the unified stack. This keeps the effect list
    and side toolbar visible at all times.
    """
    configure_layout(layout)
    selected_rigs = get_selected_rigs(context)
    if not selected_rigs:
        empty_state(
            layout,
            "Select a Frame By Plane layer",
            "Image effects, masks and mesh effects are edited here.",
            icon="RESTRICT_SELECT_OFF",
        )
        return

    sc = context.scene
    rig = selected_rigs[0]
    active_object = getattr(context, "object", None)
    force_lattice_mesh_view = False
    try:
        if active_object is not None and str(getattr(active_object, "type", "") or "") == "LATTICE":
            owner = fbp_resolve_rig_from_any_object(active_object, context)
            if owner is not None and owner in selected_rigs:
                rig = owner
                force_lattice_mesh_view = True
                # Never mutate Scene/UI state directly from a Panel.draw call.
                # Queue the category and row focus for the next safe timer tick,
                # while this draw already renders the contextual Mesh stack.
                from .safe_tasks import schedule_once
                helper_name = str(getattr(active_object, "name", "") or "")
                owner_name = str(getattr(owner, "name", "") or "")

                def _focus_lattice_from_panel():
                    current = getattr(bpy.context, "active_object", None)
                    if (
                        current is None
                        or str(getattr(current, "type", "") or "") != "LATTICE"
                        or str(getattr(current, "name", "") or "") != helper_name
                    ):
                        return None
                    current_owner = bpy.data.objects.get(owner_name)
                    if current_owner is not None:
                        fbp_focus_lattice_ui(bpy.context, current_owner)
                    return None

                schedule_once(
                    f"lattice.selection_focus.{owner_name}",
                    _focus_lattice_from_panel,
                    first_interval=0.0,
                )
    except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        pass

    selection_status(layout, len(selected_rigs), noun="layer")
    _fbp_draw_blend_control(layout, selected_rigs)
    listed_effects = fbp_schedule_effect_items_sync(rig, selected_rigs)
    effect_definitions = {
        effect_id: (fbp_effect_definition(effect_id) or {})
        for effect_id in listed_effects
    }
    active_effect = fbp_active_effect_id(rig) if listed_effects else ""
    if force_lattice_mesh_view and FBP_EFFECT_LATTICE in listed_effects:
        active_effect = FBP_EFFECT_LATTICE
    if active_effect == FBP_EFFECT_LAYER_BLEND:
        active_effect = ""
    active_definition = effect_definitions.get(active_effect, {}) if active_effect else {}
    presence_cache = {}

    def effect_presence(effect_id):
        effect_id = str(effect_id or "")
        if not effect_id:
            return (0, len(selected_rigs))
        cached = presence_cache.get(effect_id)
        if cached is None:
            cached = fbp_effect_presence(selected_rigs, effect_id)
            presence_cache[effect_id] = cached
        return cached

    present_count, selected_count = effect_presence(active_effect)
    contextual_shape_effect = _fbp_context_shape_mask_effect(
        context, rig, listed_effects, active_effect
    )
    active_category = str(
        active_definition.get("category", "2D") or "2D"
    ).upper()
    effects_view = (
        "3D" if force_lattice_mesh_view
        else ("MASK" if active_category == "MASK" else (
            "3D" if active_category == "3D" else "2D"
        ))
    )
    visible_categories = {"BASE", "2D", "MASK", "3D"}

    visible_effects = [
        effect_id for effect_id in listed_effects
        if effect_id != FBP_EFFECT_LAYER_BLEND
    ]
    stack_row = layout.row(align=False)
    stack_box = stack_row.box()
    configure_layout(stack_box)
    stack_header = section_header(
        stack_box,
        "Effect Stack",
        icon="SHADERFX",
        count=len(visible_effects),
    )
    _fbp_draw_uilist_header_controls(
        stack_header, context, "EFFECT_IMAGE"
    )

    # The stack UIList is part of the Modifiers workflow even when the current
    # category is empty. Showing the empty list keeps Effects and Masks editable
    # from one stable place instead of replacing it with a plain message.
    list_type = "FBP_UL_EffectStackUnified"
    list_id = "STACK"
    # Keep the Effects UIList at least as tall as the adjacent toolbar.
    # Count buttons plus visual separators: move x2, Add, Actions, and the
    # spacer rows between them. This prevents the list from ending above the
    # icon column in compact stacks.
    stack_rows = list_rows(
        len(visible_effects),
        minimum=FBP_UI_EFFECT_MIN_ROWS,
        maximum=FBP_UI_EFFECT_MAX_ROWS,
    )
    stack_box.template_list(
        list_type, list_id,
        rig, "fbp_effects",
        rig, "fbp_effects_index",
        rows=stack_rows,
    )

    selected_effect_instances = tuple(
        (effect_id, instance_id)
        for effect_id, instance_id in fbp_selected_effect_instances(
            rig,
            fallback_active=True,
            movable_only=True,
            categories=visible_categories,
        )
        if effect_id != FBP_EFFECT_LAYER_BLEND
    )
    selected_effect_refs = tuple(
        f"{effect_id}::{instance_id}" if instance_id else effect_id
        for effect_id, instance_id in selected_effect_instances
    )
    selected_effect_ids = tuple(dict.fromkeys(
        effect_id for effect_id, _instance_id in selected_effect_instances
    ))
    shared_selection = bool(
        selected_effect_refs
        and all(
            effect_presence(effect_id)[0] == selected_count
            for effect_id in selected_effect_ids
        )
    )

    # One compact, modular side bar shared by every stack category:
    # extras, movement, delete, then add. Infrequent actions remain in the
    # COLLAPSEMENU menu instead of lengthening the permanent strip.
    controls = stack_row.column(align=True)
    fbp_set_ui_units_x(controls, 1.0)

    extras = controls.operator(
        "fbp.open_effect_toolbar_menu", text="", icon="COLLAPSEMENU"
    )
    extras.menu = "ACTIONS"

    controls.separator()
    move_group = controls.column(align=True)
    for direction, icon_name in (
        ("UP", "SORT_DESC"),
        ("DOWN", "SORT_ASC"),
    ):
        move = move_group.row(align=True)
        move.enabled = bool(
            shared_selection
            and fbp_can_move_effect_selection(
                selected_rigs, selected_effect_refs, direction
            )
        )
        op = move.operator(
            "fbp.move_active_effect", text="", icon=icon_name
        )
        op.direction = direction

    controls.separator()
    remove = controls.row(align=True)
    remove.enabled = bool(selected_effect_instances)
    remove.operator(
        "fbp.remove_selected_effects", text="", icon="TRASH"
    )
    add = controls.operator(
        "fbp.open_effect_toolbar_menu", text="", icon="ADD"
    )
    add.menu = "ADD"

    if active_effect:
        source_rig = fbp_effect_source_rig(selected_rigs, active_effect)
        if source_rig:
            fbp_draw_effect_settings(
                layout, source_rig, active_effect,
                selected_count=selected_count,
                present_count=present_count,
                context=context,
                instance_id=fbp_active_effect_instance_id(rig),
            )
    if not visible_effects:
        hint_row(
            layout,
            "No effects. Use + to add one.",
            icon="INFO",
            disabled=True,
        )

    if effects_view == "MASK":
        section_gap(layout)
        draw_mask_source_library_ui(layout, context, selected_rigs)

    section_gap(layout)
    draw_effect_stack_presets_ui(layout, context, selected_rigs)

    mask_edit_target, mask_edit_instance = split_effect_instance_token(
        getattr(sc, "fbp_effect_mask_edit_target", "") or ""
    )
    mask_edit_target = fbp_normalize_effect_id(mask_edit_target)

    def _schedule_mask_editor_clear():
        """Clear stale mask-editor state outside Panel.draw()."""
        from .safe_tasks import schedule_once
        scene_name = str(getattr(sc, "name", "") or "")

        def _clear_stale_mask_editor():
            scene = bpy.data.scenes.get(scene_name) if scene_name else None
            if scene is not None:
                try:
                    scene.fbp_effect_mask_edit_target = ""
                except FBP_DATA_ERRORS:
                    pass
            return None

        schedule_once(
            f"ui.clear_mask_editor.{scene_name}",
            _clear_stale_mask_editor,
            first_interval=0.0,
        )

    if effects_view == "2D" and mask_edit_target:
        if mask_edit_target in visible_effects:
            section_gap(layout)
            if not fbp_draw_effect_mask_editor(
                layout, context, selected_rigs, mask_edit_target, mask_edit_instance
            ):
                _schedule_mask_editor_clear()
        else:
            _schedule_mask_editor_clear()

    # Keep the selected Shape Mask immediately editable without ever replacing
    # the regular Effects stack. When it is already the active row in Masks,
    # its settings were drawn above and are not duplicated.
    if contextual_shape_effect and not (
        effects_view == "MASK" and active_effect == contextual_shape_effect
    ):
        contextual_source = fbp_effect_source_rig(
            selected_rigs, contextual_shape_effect
        ) or rig
        contextual_present, contextual_selected = effect_presence(
            contextual_shape_effect
        )
        section_gap(layout)
        context_header = layout.row(align=True)
        context_header.label(text="Selected Shape Mask", **ui_label_icon_kwargs("menu.holdout_plane", fallback="MOD_MASK"))
        show = context_header.operator(
            "fbp.select_effect",
            text="Show in Masks",
            icon="IMAGE_ALPHA",
        )
        show.effect_id = contextual_shape_effect
        fbp_draw_effect_settings(
            layout, contextual_source, contextual_shape_effect,
            selected_count=contextual_selected,
            present_count=contextual_present,
            context=context,
        )


# SECTION 07 - Panel: Sequence / Selected Layer #
# ###ICON Panel Sequence, Functions: replace, visibility, emission, fit, transform and frames.
class FBP_OT_RigShapePopup(Operator):
    bl_idname = "fbp.rig_shape_popup"
    bl_label = "Rig Shape"
    bl_description = "Choose a live controller shape and how it fits the selected plane"
    bl_options = {'INTERNAL'}

    rig_name: StringProperty(default="", options={'SKIP_SAVE'})

    def invoke(self, context, _event):
        rig = _fbp_active_plane_context(context)
        if rig is None:
            return {'CANCELLED'}
        self.rig_name = rig.name
        return context.window_manager.invoke_popup(self, width=300)

    def execute(self, _context):
        return {'FINISHED'}

    def draw(self, _context):
        layout = configure_layout(self.layout)
        rig = bpy.data.objects.get(self.rig_name)
        if rig is None:
            layout.label(text="Layer no longer exists", icon='ERROR')
            return
        layout.prop(rig, "fbp_rig_shape", text="Shape")
        layout.prop(rig, "fbp_rig_shape_fit_mode", text="Fit")
        layout.prop(rig, "fbp_rig_shape_expand", text="Expand", slider=True)
        if str(getattr(rig, "fbp_rig_shape", "DEFAULT")) == 'CUSTOM':
            edit = layout.operator("fbp.edit_rig_shape", text="Edit Rig Mesh", icon='EDITMODE_HLT')
            edit.rig_name = rig.name


class FBP_OT_EditRigShape(Operator):
    bl_idname = "fbp.edit_rig_shape"
    bl_label = "Edit Rig Shape"
    bl_description = "Enter Edit Mode on the non-rendering control rig mesh"
    bl_options = {'REGISTER', 'UNDO'}

    rig_name: StringProperty(default="", options={'SKIP_SAVE'})

    def execute(self, context):
        rig = bpy.data.objects.get(self.rig_name) if self.rig_name else _fbp_active_plane_context(context)
        if rig is None or not bool(getattr(rig, "is_fbp_control", False)) or rig.type != 'MESH':
            self.report({'WARNING'}, "Select a Frame By Plane control rig")
            return {'CANCELLED'}
        if getattr(context.object, "mode", 'OBJECT') != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
        for obj in tuple(getattr(context, "selected_objects", ()) or ()):
            obj.select_set(False)
        rig.select_set(True)
        context.view_layer.objects.active = rig
        rig.fbp_rig_shape = 'CUSTOM'
        bpy.ops.object.mode_set(mode='EDIT')
        return {'FINISHED'}


class FBP_OT_OpenEffectsMasks(Operator):
    bl_idname = "fbp.open_effects_masks"
    bl_label = "Effects & Masks"
    bl_description = "Open the selected layer's Effects and Masks in Modifiers"
    bl_options = {'REGISTER'}

    view: EnumProperty(
        name="View",
        description="Effect stack section to reveal in the Modifiers panel",
        items=(
            ('2D', "Image", "Open Image Effects"),
            ('MASK', "Masks", "Open Masks"),
            ('3D', "Mesh", "Open Mesh Effects"),
        ),
        default='2D',
        options={'SKIP_SAVE'},
    )

    def execute(self, context):
        rig = _fbp_active_plane_context(context)
        if rig is None:
            return {'CANCELLED'}
        if getattr(context.object, "mode", 'OBJECT') != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
        for obj in tuple(getattr(context, "selected_objects", ()) or ()):
            obj.select_set(False)
        rig.select_set(True)
        context.view_layer.objects.active = rig
        context.scene.fbp_effects_view = str(self.view or '2D')
        try:
            from .live_tutorial import fbp_notify_tutorial_action
            if self.view == 'MASK':
                fbp_notify_tutorial_action(context, "image_open_masks", "multi_open_masks")
            elif self.view == '3D':
                fbp_notify_tutorial_action(context, "color_open_mesh_effects")
            else:
                fbp_notify_tutorial_action(context, "image_open_effects", "multi_open_effects")
        except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            pass
        for area in tuple(getattr(context.screen, "areas", ()) or ()):
            if area.type != 'PROPERTIES':
                continue
            try:
                area.spaces.active.context = 'MODIFIER'
                area.tag_redraw()
                return {'FINISHED'}
            except FBP_DATA_ERRORS:
                continue
        self.report({'INFO'}, "Open a Properties editor to show Effects & Masks")
        return {'CANCELLED'}


class FBP_MT_SequenceFrameActions(Menu):
    bl_idname = "FBP_MT_sequence_frame_actions"
    bl_label = "Frame List Actions"

    def draw(self, context):
        layout = configure_layout(self.layout)
        rigs = list(get_selected_rigs(context) or ())
        rig = rigs[0] if rigs else None

        def can_move_to_boundary(candidate, *, top):
            items = list(getattr(candidate, "fbp_images", ()) or ())
            if len(items) < 2:
                return False
            indices = [
                index for index, item in enumerate(items)
                if bool(getattr(item, "is_selected", False))
            ]
            if not indices:
                active_index = int(getattr(candidate, "fbp_images_index", -1) or 0)
                if 0 <= active_index < len(items):
                    indices = [active_index]
            if not indices:
                return False
            if top:
                return indices != list(range(len(indices)))
            trailing_start = len(items) - len(indices)
            return indices != list(range(trailing_start, len(items)))

        top_row = layout.row()
        top_row.enabled = any(can_move_to_boundary(candidate, top=True) for candidate in rigs)
        top = top_row.operator("fbp.list_action", text="Bring First", icon="TRIA_UP_BAR")
        top.action = "MOVE_TOP"
        bottom_row = layout.row()
        bottom_row.enabled = any(can_move_to_boundary(candidate, top=False) for candidate in rigs)
        bottom = bottom_row.operator("fbp.list_action", text="Bring Last", icon="TRIA_DOWN_BAR")
        bottom.action = "MOVE_BOTTOM"
        layout.separator()
        if rig is not None and not bool(getattr(rig, "fbp_is_color_plane", False)):
            refresh = layout.operator(
                "fbp.refresh_media", text="Refresh Media", icon=ui_icon("action.refresh")
            )
            refresh.rig_name = str(getattr(rig, "name", "") or "")
            layout.operator(
                "fbp.insert_linked_image_after_selected",
                text="Import Frame",
                icon=ui_icon("settings.project_folder"),
            )


class FBP_MT_SequenceFrameAdd(Menu):
    bl_idname = "FBP_MT_sequence_frame_add"
    bl_label = "Add Frame"

    def draw(self, context):
        layout = configure_layout(self.layout)
        rigs = list(get_selected_rigs(context) or ())
        rig = rigs[0] if rigs else None
        if rig is not None and bool(getattr(rig, "fbp_is_color_plane", False)):
            op = layout.operator("fbp.insert_images_after_selected", text="Solid Color", **ui_icon_kwargs("menu.color_plane", fallback="COLOR"))
            op.frame_mode = "COLOR"
            op = layout.operator("fbp.insert_images_after_selected", text="Gradient", **ui_icon_kwargs("menu.gradient_plane", fallback="COLOR"))
            op.frame_mode = "GRADIENT"
        else:
            layout.operator("fbp.insert_linked_image_after_selected", text="Image", icon=ui_icon("settings.project_folder"))
        layout.operator("fbp.insert_transparent_frame", text="Transparent", icon=ui_icon("sequence.add_transparent"))


class FBP_PT_Sequence(Panel):
    bl_label       = "Layer Settings"
    bl_description = "Edit the selected Frame By Plane layer, timing, frames, color, transform and tools"
    bl_idname      = "FBP_PT_sequence"
    bl_space_type  = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category    = "Frame By Plane"
    bl_parent_id   = "FBP_PT_frame_by_plane_sidebar_anchor"
    bl_order       = 2

    @classmethod
    def poll(cls, context):
        return bool(
            _fbp_tool_ui_context_available(context)
            and _fbp_n_panel_enabled(context)
            and _fbp_panel_section_enabled(context, 'SETTINGS')
        )

    def draw_header(self, context):
        self.layout.label(text="", **ui_label_icon_kwargs("menu.image_plane", fallback="sequence.header"))

    def draw(self, context):
        layout = configure_layout(self.layout)
        try:
            from .grease_pencil_bridge import is_gp_canvas, draw_gp_canvas_layer_ui
            active_object = getattr(context, "object", None)
            if is_gp_canvas(active_object):
                draw_gp_canvas_layer_ui(layout, context, active_object)
                return
        except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError) as exc:
            fbp_warn("Could not draw integrated Grease Pencil layer settings", exc)

        active_rig = _fbp_active_plane_context(context)
        selected_rigs = get_selected_rigs(context) if active_rig is not None else []
        if active_rig is not None and active_rig not in selected_rigs:
            selected_rigs.insert(0, active_rig)
        if not selected_rigs:
            empty_state(
                layout,
                "No Layer Selected",
                "Select a Frame By Plane layer to edit its settings.",
                icon="RESTRICT_SELECT_OFF",
            )
            return

        rig = selected_rigs[0]
        backend_type = fbp_layer_backend_type(rig)
        backend_types = {fbp_layer_backend_type(item) for item in selected_rigs}
        mixed_backends = len(backend_types) > 1
        is_movie = backend_type == 'NATIVE_MOVIE'
        selection_status(layout, len(selected_rigs), noun="layer")
        if mixed_backends:
            hint_row(
                layout,
                "Mixed layer types: only shared controls are available",
                icon="INFO",
                disabled=True,
            )

        if not mixed_backends and fbp_is_drawing_rig(rig):
            draw_drawing_plane_ui(layout, context, rig)
            return

        box = layout.box()
        configure_layout(box)

        identity = box.row(align=False)
        split = identity.split(factor=0.58, align=False)
        left = split.row(align=False)
        tag = left.row(align=False)
        fbp_set_ui_units_x(tag, 5.25)
        tag.prop(rig, "fbp_color_tag", text="")
        shape = left.row(align=False)
        fbp_set_ui_units_x(shape, 4.25)
        shape.operator("fbp.rig_shape_popup", text="Rig Shape")
        name = split.row(align=False)
        name.scale_x = 0.90
        if len(selected_rigs) == 1:
            name.prop(rig, "fbp_layer_name", text="", icon=ui_icon("sequence.header"))
        else:
            name.label(text=f"Primary: {rig.name}", icon=ui_icon("sequence.header"))

        row = box.row(align=False)
        vis_icon=ui_icon("layer.visible_on") if rig.fbp_is_visible else ui_icon("layer.visible_off")
        row.prop(rig, "fbp_is_visible", text="", icon=vis_icon)
        is_holdout_plane = bool(
            not mixed_backends
            and getattr(rig, "fbp_is_color_plane", False)
            and getattr(rig, "fbp_color_plane_mode", 'SOLID') == 'HOLDOUT'
        )
        if not is_holdout_plane:
            row.prop(rig, "fbp_opacity", text="Opacity", slider=True)
            if not mixed_backends:
                emiss_icon='LIGHT_SUN'
                if getattr(rig, "fbp_is_color_plane", False):
                    row.prop(rig, "fbp_color_plane_emission", text="", icon=emiss_icon, toggle=True)
                else:
                    row.prop(rig, "fbp_use_emission", text="", icon=emiss_icon, toggle=True)

        row = box.row(align=False)
        if len(selected_rigs) > 1:
            row.operator("fbp.multi_fit_camera", text="Fit", icon=ui_icon("sequence.fit"))
        else:
            row.operator("fbp.fit_camera", icon=ui_icon("sequence.fit"), text="Fit")
        row.operator("fbp.popup_transform", text="Transform", icon=ui_icon("sequence.transform"))
        row.operator("fbp.open_effects_masks", text="Effects & Masks", icon='SHADERFX')
        if mixed_backends:
            summary = layout.box()
            configure_layout(summary)
            summary.alert = True
            section_header(summary, "Mixed Layer Types", icon="INFO")
            hint_row(summary, "Type-specific controls are hidden for mixed selections", icon="INFO", alert=True, disabled=False)
            counts = {}
            for selected in selected_rigs:
                label = fbp_layer_backend_label(selected)
                counts[label] = counts.get(label, 0) + 1
            for label, count in sorted(counts.items()):
                summary.label(text=f"{label}: {count}")
            summary.label(text="Visibility, opacity, camera fit and transform remain available")
            return

        show_animation_panel = (
            is_movie
            or backend_type == 'NATIVE_SEQUENCE'
            or (getattr(rig, "fbp_is_color_plane", False) and len(rig.fbp_images) > 0)
        )
        if show_animation_panel:
            section_gap(layout)
            box = layout.box()
            configure_layout(box)
            section_header(
                box,
                "Movie Playback" if is_movie else "Animation",
                icon=ui_icon("sequence.frames"),
            )
            row = adaptive_row(box, context)
            sub1 = row.row(align=True)
            sub1.prop(rig, "fbp_start_frame")
            sub1.operator("fbp.set_current_frame", text="", icon=ui_icon("sequence.set_current"))
            if is_movie:
                playback = row.row(align=True)
                playback.prop_enum(rig, "fbp_loop_mode", 'NONE', text="One Shot")
                playback.prop_enum(rig, "fbp_loop_mode", 'REPEAT', text="Loop")
            else:
                row.prop(rig, "fbp_loop_mode", text="")
                row.prop(rig, "fbp_global_duration", text="Frame Hold")

        if len(selected_rigs) <= 1 and not is_movie:
            show_frame_tools = not getattr(rig, "fbp_is_color_plane", False) or len(rig.fbp_images) > 0
            can_add_frames = not getattr(rig, "fbp_is_color_plane", False) or fbp_color_plane_can_have_frames(rig)

            if not (getattr(rig, "fbp_is_color_plane", False) and not fbp_color_plane_can_have_frames(rig)):
                is_color_plane = bool(getattr(rig, "fbp_is_color_plane", False))
                box = _fbp_collapsible_box(
                    layout, rig, "fbp_sequence_show_frames",
                    "Color Plane Frames" if is_color_plane else "Frames",
                    icon=ui_icon("layer.header"),
                )
                if box is not None and show_frame_tools:
                    frame_count = len(rig.fbp_images)
                    checked_indices = [
                        index for index, item in enumerate(rig.fbp_images)
                        if bool(getattr(item, "is_selected", False))
                    ]
                    active_frame_index = max(
                        0,
                        min(int(getattr(rig, "fbp_images_index", 0) or 0), frame_count - 1),
                    ) if frame_count else -1
                    action_indices = checked_indices or (
                        [active_frame_index] if active_frame_index >= 0 else []
                    )
                    action_index_set = set(action_indices)
                    can_move_up = any(
                        index > 0 and (index - 1) not in action_index_set
                        for index in action_indices
                    )
                    can_move_down = any(
                        index < frame_count - 1 and (index + 1) not in action_index_set
                        for index in action_indices
                    )
                    can_duplicate = bool(checked_indices)
                    can_reverse_sequence = frame_count > 1
                    can_remove = frame_count > 1 or bool(getattr(rig, "fbp_is_color_plane", False))

                    row = box.row(align=False)
                    row.template_list("FBP_UL_ImageList", "",
                                      rig, "fbp_images",
                                      rig, "fbp_images_index", rows=14)
                    col = row.column(align=False)

                    col.menu(
                        "FBP_MT_sequence_frame_actions",
                        text="",
                        icon="COLLAPSEMENU",
                    )
                    is_color_frames = bool(
                        getattr(rig, "fbp_is_color_plane", False)
                    )
                    if not is_color_frames:
                        col.menu(
                            "FBP_MT_sequence_frame_add",
                            text="",
                            icon="ADD",
                        )
                    col.separator()

                    moves = col.column(align=True)
                    control = moves.row(align=True)
                    control.enabled = can_move_up
                    control.operator(
                        "fbp.list_action",
                        icon=ui_icon("sequence.move_up"),
                        text="",
                    ).action = 'MOVE_UP'
                    control = moves.row(align=True)
                    control.enabled = can_move_down
                    control.operator(
                        "fbp.list_action",
                        icon=ui_icon("sequence.move_down"),
                        text="",
                    ).action = 'MOVE_DOWN'
                    col.separator()

                    control = col.row(align=False)
                    control.enabled = can_reverse_sequence
                    control.operator(
                        "fbp.reverse_sequence",
                        icon=ui_icon("sequence.reverse"),
                        text="",
                        depress=bool(
                            getattr(rig, "fbp_sequence_reversed", False)
                        ),
                    )

                    control = col.row(align=False)
                    control.enabled = can_remove
                    control.operator(
                        "fbp.list_action",
                        icon=ui_icon("sequence.delete"),
                        text="",
                    ).action = 'REMOVE'

                    col.separator()
                    col.separator()
                    control = col.row(align=False)
                    control.enabled = can_duplicate
                    control.operator(
                        "fbp.list_action",
                        icon=ui_icon("sequence.duplicate"),
                        text="",
                    ).action = 'DUPLICATE_SELECTED'

                    if is_color_frames:
                        op = col.operator(
                            "fbp.insert_images_after_selected",
                            text="",
                            **ui_icon_kwargs(
                                "menu.color_plane", fallback="COLOR"
                            ),
                        )
                        op.frame_mode = "COLOR"
                        op = col.operator(
                            "fbp.insert_images_after_selected",
                            text="",
                            **ui_icon_kwargs(
                                "menu.gradient_plane", fallback="COLOR"
                            ),
                        )
                        op.frame_mode = "GRADIENT"
                    col.operator(
                        "fbp.insert_transparent_frame",
                        icon=ui_icon("sequence.add_transparent"),
                        text="",
                    )

                    if fbp_rig_native_sequence_needs_rename(rig):
                        warn = box.box()
                        warn.alert = True
                        warn.label(text="Native sequence filenames may show pink in Blender.", icon=ui_icon("generic.error"))
                        warn.operator("fbp.rename_sequence_for_blender", text="Rename Original Files for Blender", icon=ui_icon("sequence.replace"))

                    row = box.row(align=True)
                    all_selected = len(rig.fbp_images) > 0 and all(bool(item.is_selected) for item in rig.fbp_images)
                    row.operator("fbp.select_all", text="None" if all_selected else "All", icon=ui_icon("sequence.select_none") if all_selected else ui_icon("sequence.select_all")).action = 'TOGGLE'
                    row.operator("fbp.select_all", text="Invert", icon=ui_icon("sequence.select_invert")).action = 'INVERT'
                    if not getattr(rig, "fbp_is_color_plane", False):
                        optimize = box.row(align=True)
                        optimize.operator(
                            "fbp.optimize_sequence_frames",
                            text="Analyze / Consolidate Holds",
                            icon=ui_icon("sequence.optimize"),
                        )
                elif box is not None and can_add_frames:
                    if is_color_plane:
                        state = box.row(align=True)
                        state.alignment = "LEFT"
                        state.label(
                            text="Single Color Plane",
                            **ui_label_icon_kwargs(
                                "menu.color_plane", fallback="COLOR"
                            ),
                        )
                        animate = box.operator(
                            "fbp.insert_images_after_selected",
                            text="Make Multi Color Plane",
                            icon=ui_icon("sequence.frames"),
                        )
                        animate.frame_mode = "AUTO"
                    else:
                        row = box.row(align=True)
                        row.operator("fbp.insert_linked_image_after_selected", text="Import Image Frame", icon=ui_icon("settings.project_folder"))

        if getattr(rig, "fbp_is_color_plane", False):
            section_gap(layout)
            details_box = layout.box()
            configure_layout(details_box)
            section_header(details_box, "Frame Appearance", icon=ui_icon("sequence.node_texture"))
            current_mode = str(getattr(rig, "fbp_color_plane_mode", 'SOLID') or 'SOLID')
            if current_mode in {'SOLID', 'GRADIENT'}:
                mode_row = details_box.row(align=True)
                solid = mode_row.operator(
                    "fbp.set_color_plane_mode",
                    text="Color",
                    icon=ui_icon("menu.color_plane"),
                    depress=current_mode == 'SOLID',
                )
                solid.mode = 'SOLID'
                gradient = mode_row.operator(
                    "fbp.set_color_plane_mode",
                    text="Gradient",
                    icon=ui_icon("menu.gradient_plane"),
                    depress=current_mode == 'GRADIENT',
                )
                gradient.mode = 'GRADIENT'

            if current_mode == 'GRADIENT':
                grad_col = details_box.column(align=False)
                draw_native_fbp_color_ramp(grad_col, rig)
                transform_box = grad_col.box()
                is_open = bool(getattr(rig, 'fbp_show_gradient_transform', True))
                row = transform_box.row(align=True)
                row.prop(rig, 'fbp_show_gradient_transform', text='Position', icon=(ui_icon("setup.expanded") if is_open else ui_icon("setup.collapsed")), emboss=False)
                row.operator(
                    "fbp.gradient_controller",
                    text="",
                    icon="EMPTY_AXIS",
                    depress=getattr(rig, "fbp_gradient_controller", None) is not None,
                )
                if is_open:
                    row = adaptive_row(transform_box, context)
                    row.prop(rig, "fbp_gradient_offset_x", text="X")
                    row.prop(rig, "fbp_gradient_offset_y", text="Y")
                    row = adaptive_row(transform_box, context)
                    row.prop(rig, "fbp_gradient_scale_x", text="Scale X")
                    row.prop(rig, "fbp_gradient_scale_y", text="Scale Y")
                    transform_box.prop(rig, "fbp_gradient_rotation", text="Rotation")
            elif current_mode == 'SOLID':
                color_row = details_box.row(align=False)
                color_row.prop(rig, "fbp_color_plane_color", text="Color")


def _fbp_draw_properties_modifier_effects(layout, context):
    """Draw the real Frame By Plane effect stack/settings in Modifiers."""
    active = getattr(context, "object", None)
    try:
        from .grease_pencil_bridge import (
            draw_gp_mask_settings_ui,
            draw_gp_native_effects_ui,
            is_gp_drawing_canvas,
            is_gp_mask_canvas,
        )
        if is_gp_mask_canvas(active):
            owner = fbp_resolve_rig_from_any_object(active, context)
            if owner is not None:
                try:
                    active_mode = str(getattr(active, "mode", "OBJECT") or "OBJECT").upper()
                    context_mode = str(getattr(context, "mode", "OBJECT") or "OBJECT").upper()
                except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
                    active_mode = context_mode = "OBJECT"
                if (
                    active_mode in {"EDIT", "SCULPT", "WEIGHT_PAINT", "VERTEX_PAINT"}
                    or context_mode in {
                        "EDIT_GREASE_PENCIL",
                        "SCULPT_GREASE_PENCIL",
                        "WEIGHT_GREASE_PENCIL",
                        "VERTEX_GREASE_PENCIL",
                    }
                ):
                    # Do not draw the full effect stack while GP Edit Mode is
                    # changing selections/radii.
                    # Blender 5.2 can crash in UI redraws after Select All/Alt+S
                    # if the panel touches GP-derived settings during that window.
                    box = layout.box()
                    configure_layout(box)
                    section_header(box, "Grease Pencil Edit Mode", icon="GREASEPENCIL")
                    hint_row(box, "Mask refresh is deferred until Object Mode.", icon="PAUSE")
                    hint_row(box, f"Stroke Type updates after leaving Edit Mode; {alt_shortcut_label('S')} is disabled.", icon="BLANK1")
                    return
                draw_effects_ui(layout, context)
                return
            draw_gp_mask_settings_ui(layout, context, active, embedded=False, header_actions=True)
            return
        if is_gp_drawing_canvas(active):
            draw_gp_native_effects_ui(layout, context, active)
            return
    except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError) as exc:
        fbp_warn("Could not draw Frame By Plane Grease Pencil modifiers UI", exc)

    draw_effects_ui(layout, context)


class FBP_PT_ToolLayerStack(FBP_PT_LayerStack):
    """Layers panel shown in the standard 3D View Tool tab.

    The Preferences label calls this location "Properties" to match the
    established Frame By Plane wording, while Blender exposes it as the Tool
    category of the 3D View sidebar.
    """

    bl_label = "Layers"
    bl_description = "Manage Frame By Plane layers from the 3D View Tool tab"
    bl_idname = "FBP_PT_tool_layer_stack"
    bl_category = "Tool"
    bl_parent_id = "FBP_PT_tool_sidebar_anchor"
    bl_order = 0

    @classmethod
    def poll(cls, context):
        return bool(
            _fbp_tool_ui_context_available(context)
            and _fbp_properties_tool_enabled(context, 'LAYERS')
        )

    def draw(self, context):
        _fbp_draw_tool_layer_stack_or_create(self, context)


class FBP_PT_ToolGreasePencilStack(FBP_PT_GreasePencilStack):
    """Grease Pencil panel shown in the standard 3D View Tool tab."""

    bl_label = "Grease Pencil"
    bl_description = "Manage Frame By Plane Grease Pencil layers from the 3D View Tool tab"
    bl_idname = "FBP_PT_tool_grease_pencil_stack"
    bl_category = "Tool"
    bl_parent_id = "FBP_PT_tool_sidebar_anchor"
    bl_order = 1

    @classmethod
    def poll(cls, context):
        return bool(
            _fbp_tool_ui_context_available(context)
            and _fbp_properties_tool_enabled(context, 'GP')
            and _fbp_scene_has_drawing_gp(context)
        )

    def draw(self, context):
        _fbp_draw_tool_gp_stack_or_hint(self, context)


class FBP_PT_ToolSequence(FBP_PT_Sequence):
    """Selected-layer settings shown in the standard 3D View Tool tab."""

    bl_label = "Layer Settings"
    bl_description = "Edit the selected Frame By Plane layer from the 3D View Tool tab"
    bl_idname = "FBP_PT_tool_sequence"
    bl_category = "Tool"
    bl_parent_id = "FBP_PT_tool_sidebar_anchor"
    bl_order = 2

    @classmethod
    def poll(cls, context):
        return bool(
            _fbp_tool_ui_context_available(context)
            and _fbp_properties_tool_enabled(context, 'SETTINGS')
        )

    def draw(self, context):
        _fbp_draw_tool_sequence_or_hint(self, context)


class FBP_PT_ModifierShortcuts(Panel):
    bl_label = "Frame By Plane Effects"
    bl_description = "Edit Frame By Plane image effects, masks and mesh effects from Blender's Modifiers tab"
    bl_idname = "FBP_PT_modifier_shortcuts"
    bl_space_type = 'PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_context = 'modifier'
    bl_parent_id = 'DATA_PT_modifiers'
    bl_order = 0

    @classmethod
    def poll(cls, context):
        active = getattr(context, "object", None)
        if active is None:
            return False
        try:
            from .grease_pencil_bridge import is_gp_canvas
            if is_gp_canvas(active):
                return True
        except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            pass
        if str(getattr(active, "type", "") or "").upper() == "GREASEPENCIL":
            return True
        return fbp_resolve_rig_from_any_object(active, context) is not None

    def draw_header(self, _context):
        self.layout.label(text="", **ui_label_icon_kwargs("menu.multiplane", fallback="MODIFIER"))

    def draw(self, context):
        layout = configure_layout(self.layout)
        # Add Effect / Add Mask live in the stack UI itself.  The Modifiers tab
        # should open directly on the real Frame By Plane lists/settings.
        _fbp_draw_properties_modifier_effects(layout, context)


# SECTION 10 - Menu: Shift+A > Frame By Plane #
# ###ICON Menu Shift+A, Functions: Color Plane, Gradient, Holdout, Image Plane, Multiplane, Clipboard.
class FBP_MT_FrameByPlaneMore(Menu):
    bl_idname = "FBP_MT_frame_by_plane_more"
    bl_label = "More"
    bl_description = "Secondary import workflows and reusable folder sources"

    def draw(self, context):
        layout = configure_layout(self.layout)
        layout.operator_context = 'INVOKE_DEFAULT'

        layout.operator(
            "fbp.import_folder_multiplane",
            text="Import a Folder",
            icon='FOLDER_REDIRECT',
        )
        op = layout.operator(
            "fbp.import_folder_multiplane",
            text="Import Folder Path from Clipboard",
            **ui_icon_kwargs("menu.clipboard"),
        )
        op.from_clipboard = True
        op = layout.operator("fbp.import_folder_multiplane", text="Reimport Last Folder", icon='FILE_REFRESH')
        op.use_last_folder = True

        layout.separator(factor=0.45)
        layout.operator("fbp.import_psd", text="Import PSD / PSB", icon='FILE')
        if fbp_feature_enabled(getattr(context, "scene", None), "procreate_import"):
            layout.operator("fbp.import_procreate", text="Import Procreate · Preview", icon='BRUSH_DATA')
        layout.operator("fbp.import_toon_boom_export", text="Import Toon Boom Export", icon=ui_icon("action.export"))


class FBP_MT_FrameByPlaneAdd(Menu):
    bl_idname = "FBP_MT_frame_by_plane_add"
    bl_label = "Frame By Plane"
    bl_description = "Create Frame By Plane layers and multiplane projects"

    def draw(self, context):
        del context
        layout = configure_layout(self.layout)
        # Every primary entry opens a popup or file browser. Force invoke
        # context so Shift+A never bypasses the operator's setup dialog.
        layout.operator_context = 'INVOKE_DEFAULT'

        layout.operator(
            "fbp.popup_single_plane",
            text="Single Plane",
            **ui_icon_kwargs("menu.image_plane", fallback="FILE_IMAGE"),
        )
        op = layout.operator(
            "fbp.popup_multiplane",
            text="Multi Plane",
            **ui_icon_kwargs("menu.multiplane"),
        )
        op.animation = True

        layout.separator(factor=0.45)
        op = layout.operator("fbp.popup_color_plane", text="Color Plane", **ui_icon_kwargs("menu.color_plane"))
        op.preset_type = 'CUSTOM'
        op = layout.operator("fbp.popup_color_plane", text="Gradient Plane", **ui_icon_kwargs("menu.gradient_plane"))
        op.preset_type = 'GRADIENT'
        op = layout.operator("fbp.popup_color_plane", text="Holdout Plane", **ui_icon_kwargs("menu.holdout_plane"))
        op.preset_type = 'HOLDOUT'

        layout.separator(factor=0.45)
        layout.operator(
            "fbp.popup_video_plane",
            text="Video Plane",
            **ui_icon_kwargs("menu.video_plane", fallback="FILE_MOVIE"),
        )
        layout.operator(
            "fbp.add_grease_pencil_canvas",
            text="Grease Pencil Drawing",
            **ui_icon_kwargs("menu.gp_layer"),
        )
        layout.operator(
            "fbp.import_drawing_plane",
            text="Cutout Drawing Library",
            **ui_icon_kwargs("menu.cutout_plane"),
        )

        layout.separator(factor=0.45)
        layout.operator(
            "fbp.import_single_image_from_clipboard",
            text="Paste Image as Plane",
            **ui_icon_kwargs("menu.clipboard"),
        )
        layout.operator("fbp.create_color_plane_from_hex", text="Color Plane from Hex", icon=ui_icon("menu.hex"))

        layout.separator(factor=0.45)
        layout.menu(FBP_MT_FrameByPlaneMore.bl_idname, text="More Import Workflows", icon="COLLAPSEMENU")


def _fbp_context_selected_gp_canvases(context):
    """Return selected Frame By Plane Grease Pencil canvases once."""
    try:
        from .grease_pencil_bridge import is_gp_canvas
        return tuple(
            obj
            for obj in tuple(getattr(context, "selected_objects", ()) or ())
            if is_gp_canvas(obj)
        )
    except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        return ()


def _fbp_context_has_addon_selection(context):
    """Show native context entries only for objects owned by Frame By Plane."""
    return bool(get_selected_fbp_roots(context) or _fbp_context_selected_gp_canvases(context))


def _fbp_object_mask_context(context):
    """Resolve the active object-mask helper and its owning layer."""
    active = getattr(context, "active_object", None) or getattr(context, "object", None)
    if active is None:
        return None
    try:
        from .object_masks import (
            find_object_mask_controller_owner,
            is_object_mask_controller,
            object_mask_controller_shape,
        )
        if not is_object_mask_controller(active):
            return None
        owner = find_object_mask_controller_owner(active)
        if owner is None or not bool(getattr(owner, "is_fbp_control", False)):
            return None
        return active, owner, str(object_mask_controller_shape(active) or "SQUARE").upper()
    except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        return None


class FBP_MT_ObjectMaskContext(Menu):
    bl_idname = "FBP_MT_object_mask_context"
    bl_label = "Shape Mask"

    def draw(self, context):
        layout = configure_layout(self.layout)
        resolved = _fbp_object_mask_context(context)
        if resolved is None:
            layout.label(text="Select a Frame By Plane mask helper", icon="INFO")
            return

        _helper, owner, shape = resolved
        try:
            from .object_masks import (
                object_mask_label,
                object_mask_lock_property,
                object_mask_show_property,
            )
            label = object_mask_label(shape)
            layout.label(text=f"{label} Shape Mask", icon="MOD_MASK")

            edit = layout.operator(
                "fbp.edit_object_mask_helper",
                text="Edit Shape",
                icon="EDITMODE_HLT",
            )
            edit.rig_name = owner.name
            edit.shape = shape

            recreate = layout.operator(
                "fbp.recreate_object_mask_helper",
                text="Recreate Helper",
                icon="FILE_REFRESH",
            )
            recreate.rig_name = owner.name
            recreate.shape = shape

            layout.separator()
            show_prop = object_mask_show_property(shape)
            lock_prop = object_mask_lock_property(shape)
            if hasattr(owner, show_prop):
                visible = bool(getattr(owner, show_prop, True))
                layout.prop(
                    owner,
                    show_prop,
                    text="Show Helper",
                    toggle=True,
                    icon="HIDE_OFF" if visible else "HIDE_ON",
                )
            if hasattr(owner, lock_prop):
                locked = bool(getattr(owner, lock_prop, True))
                layout.prop(
                    owner,
                    lock_prop,
                    text="Lock 3D",
                    toggle=True,
                    icon="LOCKED" if locked else "UNLOCKED",
                )
        except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            layout.label(text="Mask helper controls unavailable", icon="ERROR")


class FBP_MT_ObjectLayerContext(Menu):
    bl_idname = "FBP_MT_object_layer_context"
    bl_label = "Layer"

    def draw(self, context):
        layout = configure_layout(self.layout)
        rigs = tuple(get_selected_fbp_roots(context) or ())
        gp_canvases = _fbp_context_selected_gp_canvases(context)

        try:
            from .grease_pencil_bridge import is_gp_drawing_canvas
            drawing_gp_canvases = tuple(
                canvas for canvas in gp_canvases if is_gp_drawing_canvas(canvas)
            )
        except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            drawing_gp_canvases = ()

        group_targets = tuple(rigs) + drawing_gp_canvases
        if group_targets:
            group = layout.operator(
                "fbp.create_layer_collection",
                text=f"Move Selected to Collection ({primary_shortcut_label('G')})",
                icon=ui_icon("setup.collection_new"),
            )
            group.mode = "AUTO" if rigs and drawing_gp_canvases else ("PLANES" if rigs else "GP")
            group.name = "FBP Collection" if rigs else "FBP GP Collection"

            ungroup_row = layout.row()
            ungroup_row.enabled = any(
                (collection := get_primary_fbp_collection(target)) is not None
                and collection != getattr(context.scene, "collection", None)
                for target in group_targets
            )
            ungroup_row.operator(
                "fbp.ungroup_selected_layers",
                text=f"Move Selected Out ({primary_shortcut_label('G', shift=True)})",
                icon="UNLINKED",
            )

        if rigs:
            layout.separator()
            layout.operator(
                "fbp.merge_selected_to_active_sequence",
                text="Convert to Single Animated Plane",
                icon=ui_icon("layer.duplicate"),
            )
            layout.operator(
                "fbp.delete_sequence",
                text="Delete Layer + Plane",
                icon=ui_icon("generic.delete"),
            )

        if gp_canvases:
            if rigs:
                layout.separator()
            layout.operator(
                "fbp.delete_grease_pencil_canvas",
                text="Delete Grease Pencil Layer",
                icon=ui_icon("generic.delete"),
            )

        if not rigs and not gp_canvases:
            layout.label(text="Select a Frame By Plane layer", icon="INFO")


class FBP_OT_SetSelectedLayerTag(Operator):
    bl_idname = "fbp.set_selected_layer_tag"
    bl_label = "Set Selected Layer Tag"
    bl_description = "Assign this color tag to every selected Frame By Plane layer"
    bl_options = {'REGISTER', 'UNDO'}

    tag: StringProperty(default='NONE', options={'SKIP_SAVE'})

    def execute(self, context):
        rigs = tuple(get_selected_fbp_roots(context) or ())
        if not rigs:
            return {'CANCELLED'}
        tag = str(self.tag or 'NONE').upper()
        if tag not in FBP_COMPOSITOR_TAG_LABELS:
            return {'CANCELLED'}
        # The property callback already applies one edit to the complete current
        # selection, including collection color variants, so assign only once.
        rigs[0].fbp_color_tag = tag
        self.report({'INFO'}, f"Tagged {len(rigs)} layer(s): {FBP_COMPOSITOR_TAG_LABELS[tag]}")
        return {'FINISHED'}


def _fbp_selected_color_tag_backends(rigs):
    """Return the selected layer backend set used to choose tag artwork."""
    backends = set()
    for rig in tuple(rigs or ()):
        try:
            backend = str(fbp_layer_backend_type(rig) or 'UNKNOWN').upper()
        except FBP_DATA_ERRORS:
            backend = 'UNKNOWN'
        if backend:
            backends.add(backend)
    return frozenset(backends)


def _fbp_color_tag_menu_icon_kwargs(rigs, tag):
    """Return a valid UILayout icon for one Color Tags menu entry.

    A homogeneous selection uses the bundled icon family for its layer type.
    Mixed layer types use Blender's STRIP_COLOR swatches, which remain readable
    without privileging one selected backend. None / Default uses
    STRIP_COLOR_09 for mixed selections.
    """
    tag = str(tag or 'NONE').upper()
    backends = _fbp_selected_color_tag_backends(rigs)
    homogeneous_backend = next(iter(backends)) if len(backends) == 1 else ''

    if homogeneous_backend:
        try:
            icon_value = int(
                layer_custom_icon_value(
                    homogeneous_backend,
                    tag,
                    inactive=False,
                ) or 0
            )
        except FBP_DATA_ERRORS:
            icon_value = 0
        if icon_value > 0:
            return {'icon_value': icon_value}

    icon = 'STRIP_COLOR_09' if tag == 'NONE' else f'STRIP_{tag}'
    return {'icon': fbp_strip_icon(tag, fallback=icon) if tag != 'NONE' else 'STRIP_COLOR_09'}


class FBP_MT_ObjectLayerTags(Menu):
    bl_idname = "FBP_MT_object_layer_tags"
    bl_label = "Color Tags"

    def draw(self, context):
        layout = configure_layout(self.layout)
        rigs = tuple(get_selected_fbp_roots(context) or ())
        for tag, label in FBP_COMPOSITOR_TAG_LABELS.items():
            op = layout.operator(
                "fbp.set_selected_layer_tag",
                text=label,
                **_fbp_color_tag_menu_icon_kwargs(rigs, tag),
            )
            op.tag = tag


class FBP_MT_ObjectContext(Menu):
    bl_idname = "FBP_MT_object_context"
    bl_label = "Frame By Plane"

    def draw(self, context):
        layout = configure_layout(self.layout)
        rigs = tuple(get_selected_fbp_roots(context) or ())
        gp_canvases = _fbp_context_selected_gp_canvases(context)
        mask_context = _fbp_object_mask_context(context)

        if not rigs and not gp_canvases:
            layout.label(text="Select a Frame By Plane element", icon="INFO")
            return

        if rigs:
            layout.menu(
                FBP_MT_ObjectLayerTags.bl_idname,
                text="Color Tags",
                icon="RESTRICT_COLOR_OFF",
            )
            layout.separator()

        if mask_context is not None:
            _helper, _owner, shape = mask_context
            try:
                from .object_masks import object_mask_label
                mask_label = f"{object_mask_label(shape)} Shape Mask"
            except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
                mask_label = "Shape Mask"
            layout.menu(
                FBP_MT_ObjectMaskContext.bl_idname,
                text=mask_label,
                icon="MOD_MASK",
            )
            layout.separator()

        layout.menu(
            FBP_MT_ObjectLayerContext.bl_idname,
            text="Layer",
            icon="RENDERLAYERS",
        )

        if rigs:
            layout.menu(
                FBP_MT_LayerBlendDropdown.bl_idname,
                text="Blend",
                icon="NODE_MATERIAL",
            )
            layout.menu(
                "FBP_MT_object_effects",
                text="Effects",
                icon="SHADERFX",
            )
            layout.menu(
                FBP_MT_ObjectHoldout.bl_idname,
                text="Holdout",
                **ui_icon_kwargs("menu.holdout_plane"),
            )


class FBP_MT_ObjectHoldout(Menu):
    bl_idname = "FBP_MT_object_holdout"
    bl_label = "Frame By Plane Holdout"

    def draw(self, context):
        layout = configure_layout(self.layout)
        if not get_selected_fbp_roots(context):
            layout.label(text="Select a Frame By Plane layer", icon="BLANK1")
            return
        layout.operator(
            "fbp.set_selected_holdout",
            text="Set Selected as Holdout",
            **ui_icon_kwargs("menu.holdout_plane"),
        )
        layout.operator(
            "fbp.holdout_all_except_selected",
            text="Holdout All Except Selected",
            **ui_icon_kwargs("menu.holdout_plane"),
        )
        layout.separator()
        layout.operator(
            "fbp.restore_holdout_materials",
            text="Restore Frame By Plane Holdouts",
            icon=ui_icon("action.reset"),
        )


# SECTION 11 - Native menus: Add / Context / Delete / Render #
# ###ICON Menu Render, Function: Background Render at the top of the Topbar.


def _fbp_button_operator_identifier(properties):
    """Return searchable RNA identity text for a hovered operator button."""
    try:
        rna = getattr(properties, 'bl_rna', None)
        parts = (
            getattr(rna, 'identifier', ''),
            getattr(rna, 'name', ''),
            getattr(properties, 'bl_idname', ''),
        )
        return ' '.join(str(value or '') for value in parts).lower()
    except FBP_DATA_ERRORS:
        return ''


def _fbp_context_rename_operator(layout, *, target_type, text, icon=None,
                                 rig_name='', collection_name='', index=-1,
                                 tree_index=-1):
    """Draw one reusable rename entry backed by the normal UIList operator."""
    if icon is None:
        icon = ui_icon('action.rename')
    op = layout.operator('fbp.ui_list_name_action', text=text, icon=icon)
    op.target_type = target_type
    op.rig_name = rig_name
    op.collection_name = collection_name
    op.index = index
    op.tree_index = tree_index
    op.rename_mode = True
    return op


def _fbp_context_select_operator(layout, *, target_type, text, icon,
                                 rig_name='', collection_name='', index=-1,
                                 tree_index=-1):
    """Draw one target-specific selection entry without scanning the full tree."""
    op = layout.operator('fbp.ui_list_name_action', text=text, icon=icon)
    op.target_type = target_type
    op.rig_name = rig_name
    op.collection_name = collection_name
    op.index = index
    op.tree_index = tree_index
    return op


def _fbp_layer_move_availability(context, rig):
    """Return (can_move_up, can_move_down) using the same physical order as the toolbar."""
    collection = get_primary_fbp_collection(rig)
    if collection is None:
        return False, False

    stable_order = {}
    candidates = []
    try:
        for stable_index, layer_item in enumerate(context.scene.fbp_layers):
            candidate = getattr(layer_item, 'obj', None)
            if not candidate or not is_fbp_layer_object(candidate):
                continue
            stable_order[candidate] = stable_index
            if get_primary_fbp_collection(candidate) != collection:
                continue
            try:
                visible = bool(candidate.visible_get(view_layer=context.view_layer))
            except TypeError:
                visible = bool(candidate.visible_get())
            if visible:
                candidates.append(candidate)
    except FBP_DATA_ERRORS:
        return False, False

    depth_context = fbp_make_depth_context_cache(context)
    candidates.sort(
        key=lambda candidate: (
            fbp_layer_depth_value_from_cache(candidate, depth_context),
            stable_order.get(candidate, 1 << 30),
        )
    )
    try:
        position = candidates.index(rig)
    except ValueError:
        return False, False
    return position > 0, position + 1 < len(candidates)


def _fbp_can_reverse_selected_layer_context(context):
    """Return True once two selected layers share a canonical collection."""
    counts = {}
    for rig in get_selected_fbp_roots(context):
        if not is_fbp_layer_object(rig):
            continue
        collection = get_primary_fbp_collection(rig)
        if collection is None:
            continue
        try:
            key = int(collection.as_pointer())
        except FBP_DATA_ERRORS:
            continue
        counts[key] = counts.get(key, 0) + 1
        if counts[key] >= 2:
            return True
    return False


def _fbp_can_reverse_pending_context(scene):
    """Return True once two checked setup layers share a direct collection."""
    counts = {}
    try:
        items = scene.fbp_pending_planes
    except FBP_DATA_ERRORS:
        return False
    for item in items:
        try:
            if not bool(getattr(item, 'is_selected', False)):
                continue
            key = str(getattr(item, 'collection_name', '') or '')
        except FBP_DATA_ERRORS:
            continue
        counts[key] = counts.get(key, 0) + 1
        if counts[key] >= 2:
            return True
    return False


def _fbp_draw_layer_button_context(layout, context, rig_name):
    rig = bpy.data.objects.get(str(rig_name or ''))
    if not rig or not is_fbp_layer_object(rig):
        return False

    try:
        clipping_active = bool(rig.get(_FBP_CLIPPING_ENABLED_KEY, False))
    except FBP_DATA_ERRORS:
        clipping_active = False
    identity_icon = fbp_layer_backend_icon(rig)

    layout.separator()
    layout.label(text='Frame By Plane Layer', icon=identity_icon)
    _fbp_context_rename_operator(
        layout,
        target_type='LAYER',
        text='Rename Layer',
        rig_name=rig.name,
    )
    _fbp_context_select_operator(
        layout,
        target_type='LAYER',
        text='Select Layer',
        icon=ui_icon('layer.select_all'),
        rig_name=rig.name,
    )
    blend_mode = _fbp_layer_blend_mode_for_ui(rig)
    blend = layout.operator(
        'fbp.show_layer_blend_menu',
        text=f"Blend: {fbp_layer_blend_label(blend_mode)} ({fbp_layer_blend_short(blend_mode)})",
        icon='NODE_MATERIAL',
    )
    blend.rig_name = rig.name
    blend_source = getattr(rig, "fbp_layer_blend_source", None)
    if blend_mode != "NORMAL" and blend_source is not None:
        select_blend_source = layout.operator(
            'fbp.select_layer_relation_source',
            text=f"Select Blend Source: {getattr(blend_source, 'name', 'Layer')}",
            icon='RESTRICT_SELECT_OFF',
        )
        select_blend_source.rig_name = rig.name
        select_blend_source.relation = 'BLEND'

    clipping = layout.operator(
        'fbp.toggle_clipping_mask',
        text='Disable Clipping Mask' if clipping_active else 'Enable Clipping Mask',
        **clipping_mask_icon_kwargs(clipping_active),
    )
    clipping.rig_name = rig.name
    clipping_source = getattr(rig, "fbp_clipping_mask_source", None)
    if clipping_active and clipping_source is not None:
        select_clipping_source = layout.operator(
            'fbp.select_layer_relation_source',
            text=f"Select Clipping Source: {getattr(clipping_source, 'name', 'Layer')}",
            icon='RESTRICT_SELECT_OFF',
        )
        select_clipping_source.rig_name = rig.name
        select_clipping_source.relation = 'CLIPPING'
    plane = layout.operator(
        'fbp.select_linked_plane',
        text='Select Linked Plane',
        icon=fbp_select_plane_icon(rig, context),
    )
    plane.rig_name = rig.name

    layout.separator()
    can_move_up, can_move_down = _fbp_layer_move_availability(context, rig)
    move_row = layout.row()
    move_row.enabled = can_move_up
    move = move_row.operator('fbp.move_layer_stack', text='Move Up', icon=ui_icon('generic.up'))
    move.direction = 'UP'
    move.rig_name = rig.name
    move_row = layout.row()
    move_row.enabled = can_move_down
    move = move_row.operator('fbp.move_layer_stack', text='Move Down', icon=ui_icon('generic.down'))
    move.direction = 'DOWN'
    move.rig_name = rig.name

    reverse = layout.row()
    reverse.enabled = _fbp_can_reverse_selected_layer_context(context)
    reverse.operator(
        'fbp.reverse_selected_layer_order',
        text='Reverse Selected Layer Order',
        icon=ui_icon('sequence.reverse'),
    )

    layout.separator()
    group = layout.operator(
        'fbp.create_layer_collection',
        text=f"Move Selected to Collection ({primary_shortcut_label('G')})",
        icon=ui_icon('setup.collection_new'),
    )
    group.mode = 'PLANES'
    group.name = 'FBP Collection'
    ungroup_row = layout.row()
    selected_for_group = get_selected_rigs(context)
    ungroup_row.enabled = bool(
        any(
            (collection := get_primary_fbp_collection(item)) is not None
            and collection != getattr(context.scene, 'collection', None)
            for item in selected_for_group
        )
        or (
            (collection := get_primary_fbp_collection(rig)) is not None
            and collection != getattr(context.scene, 'collection', None)
        )
    )
    ungroup = ungroup_row.operator(
        'fbp.ungroup_selected_layers',
        text=f"Move Selected Out ({primary_shortcut_label('G', shift=True)})",
        icon='UNLINKED',
    )
    ungroup.rig_name = rig.name

    layout.separator()
    duplicate = layout.operator(
        'fbp.duplicate_selected_layers',
        text='Duplicate Layer',
        icon=ui_icon('layer.duplicate'),
    )
    duplicate.rig_name = rig.name
    delete = layout.operator(
        'fbp.delete_sequence',
        text='Delete Layer',
        icon=ui_icon('generic.delete'),
    )
    delete.rig_name = rig.name
    return True



def _fbp_collection_runtime_row(scene, collection_name):
    name = str(collection_name or '')
    if scene is None or not name:
        return None
    try:
        for item in getattr(scene, 'fbp_layer_tree_rows', ()) or ():
            if (
                str(getattr(item, 'row_type', '') or '') == 'GROUP'
                and str(getattr(item, 'collection_name', '') or '') == name
            ):
                return item
    except FBP_DATA_ERRORS:
        return None
    return None


def _fbp_draw_collection_button_context(layout, context, collection_name, tree_index=-1):
    collection = bpy.data.collections.get(str(collection_name or ''))
    if collection is None:
        return False

    snapshot = _fbp_collection_runtime_row(getattr(context, 'scene', None), collection.name)
    layout.separator()
    layout.label(
        text='Frame By Plane Collection',
        icon=(
            _fbp_collection_snapshot_icon(snapshot)
            if snapshot is not None
            else 'OUTLINER_COLLECTION'
        ),
    )
    _fbp_context_rename_operator(
        layout,
        target_type='COLLECTION',
        text='Rename Collection',
        collection_name=collection.name,
        tree_index=tree_index,
    )
    _fbp_context_select_operator(
        layout,
        target_type='COLLECTION',
        text='Select Collection Layers',
        icon=ui_icon('layer.select_all'),
        collection_name=collection.name,
        tree_index=tree_index,
    )

    collapsed = bool(getattr(snapshot, 'collection_collapsed', False)) if snapshot else False
    collapse = layout.operator(
        'fbp.toggle_collection_collapse',
        text='Expand Collection' if collapsed else 'Collapse Collection',
        icon=ui_icon('setup.collapsed') if collapsed else ui_icon('setup.expanded'),
    )
    collapse.collection_name = collection.name
    visible = bool(getattr(snapshot, 'collection_visible', True)) if snapshot else True
    visibility = layout.operator(
        'fbp.toggle_collection_state',
        text='Collection Visible',
        icon=ui_icon('layer.visible_on') if visible else ui_icon('layer.visible_off'),
    )
    visibility.collection_name = collection.name
    visibility.state = 'VISIBLE'
    locked = bool(getattr(snapshot, 'collection_locked', False)) if snapshot else False
    lock = layout.operator(
        'fbp.toggle_collection_state',
        text='Collection Locked',
        icon=ui_icon('layer.lock_on') if locked else ui_icon('layer.lock_off'),
    )
    lock.collection_name = collection.name
    lock.state = 'LOCK'
    layout.menu(
        'FBP_MT_move_layer_collection_to',
        text='Move To Collection',
        icon='FILE_PARENT',
    )

    layout.separator()
    delete = layout.operator(
        'fbp.delete_collection_layers',
        text='Delete Collection Contents',
        icon=ui_icon('generic.delete'),
    )
    delete.collection_name = collection.name
    remove = layout.operator(
        'fbp.delete_layer_collection',
        text='Delete Collection',
        icon='X',
    )
    remove.collection_name = collection.name
    return True


def _fbp_pending_tree_row(scene, tree_index):
    try:
        rows = scene.fbp_pending_tree_rows
        index = int(tree_index)
        if 0 <= index < len(rows):
            return rows[index]
    except FBP_DATA_ERRORS:
        pass
    return None


def _fbp_draw_pending_layer_button_context(layout, context, pending_index, tree_index=-1):
    scene = context.scene
    try:
        index = int(pending_index)
        if not (0 <= index < len(scene.fbp_pending_planes)):
            return False
        pending = scene.fbp_pending_planes[index]
    except FBP_DATA_ERRORS:
        return False

    files = [name for name in str(getattr(pending, 'files_str', '') or '').split('|') if name]
    file_count = len(files)
    tree_row = _fbp_pending_tree_row(scene, tree_index)

    layout.separator()
    layout.label(
        text='Multiplane Setup Layer',
        icon=ui_icon('setup.animated') if file_count > 1 else ui_icon('setup.image'),
    )
    _fbp_context_rename_operator(
        layout,
        target_type='PENDING',
        text='Rename Setup Layer',
        rig_name='',
        index=index,
        tree_index=tree_index,
    )
    edit = layout.operator('fbp.edit_pending_plane', text='Edit Setup Layer', icon=ui_icon('setup.edit'))
    edit.index = index

    reverse = layout.row()
    reverse.enabled = file_count > 1
    op = reverse.operator('fbp.reverse_pending_sequence', text='Reverse Sequence', icon=ui_icon('sequence.reverse'))
    op.index = index

    split = layout.row()
    split.enabled = file_count > 1
    op = split.operator('fbp.toggle_pending_sequence_collection', text='Split into Frame Collection', icon=ui_icon('sequence.split'))
    op.pending_index = index
    op.collection_path = str(getattr(pending, 'collection_name', '') or '')
    op.row_type = 'LAYER'

    layout.separator()
    move = layout.row()
    move.enabled = bool(tree_row is None or getattr(tree_row, 'can_move_up', False))
    op = move.operator('fbp.move_pending_plane', text='Move Up', icon=ui_icon('generic.up'))
    op.direction = 'UP'
    op.index = index
    move = layout.row()
    move.enabled = bool(tree_row is None or getattr(tree_row, 'can_move_down', False))
    op = move.operator('fbp.move_pending_plane', text='Move Down', icon=ui_icon('generic.down'))
    op.direction = 'DOWN'
    op.index = index

    reverse_checked = layout.row()
    reverse_checked.enabled = _fbp_can_reverse_pending_context(scene)
    reverse_checked.operator(
        'fbp.reverse_pending_selected_order',
        text='Reverse Checked Layer Order',
        icon=ui_icon('sequence.reverse'),
    )

    layout.separator()
    remove = layout.operator('fbp.remove_pending_plane_at_index', text='Remove Setup Layer', icon=ui_icon('generic.delete'))
    remove.index = index
    return True


def _fbp_draw_pending_group_button_context(layout, context, collection_path, tree_index=-1):
    path = str(collection_path or '').strip()
    if not path:
        return False
    scene = context.scene
    tree_row = _fbp_pending_tree_row(scene, tree_index)
    is_open = pending_collection_is_open(scene, path)

    layout.separator()
    layout.label(text='Multiplane Setup Collection', icon=ui_icon('setup.collection'))
    _fbp_context_rename_operator(
        layout,
        target_type='PENDING_GROUP',
        text='Rename Setup Collection',
        collection_name=path,
        tree_index=tree_index,
    )

    collapse = layout.operator(
        'fbp.toggle_pending_collection_collapse',
        text='Collapse Collection' if is_open else 'Expand Collection',
        icon=ui_icon('setup.expanded') if is_open else ui_icon('setup.collapsed'),
    )
    collapse.collection_name = path

    merge = layout.row()
    merge.enabled = bool(tree_row is None or getattr(tree_row, 'can_toggle_structure', False))
    op = merge.operator(
        'fbp.toggle_pending_sequence_collection',
        text='Merge Collection into Animated Plane',
        icon=ui_icon('sequence.split'),
    )
    op.pending_index = -1
    op.collection_path = path
    op.row_type = 'GROUP'
    return True


def draw_fbp_button_context_menu(self, context):
    """Append Photoshop-style Frame By Plane actions to UI button menus."""
    try:
        properties = getattr(context, 'button_operator', None)
    except FBP_DATA_ERRORS:
        properties = None
    if properties is None:
        return

    identifier = _fbp_button_operator_identifier(properties)
    layout = self.layout

    if (
        'toggleclippingmask' in identifier
        or 'toggle_clipping_mask' in identifier
        or 'showlayerblendmenu' in identifier
        or 'show_layer_blend_menu' in identifier
    ):
        _fbp_draw_layer_button_context(
            layout,
            context,
            getattr(properties, 'rig_name', ''),
        )
        return

    if not ('uilistnameaction' in identifier or 'ui_list_name_action' in identifier):
        return

    target_type = str(getattr(properties, 'target_type', '') or '')
    if target_type == 'LAYER':
        _fbp_draw_layer_button_context(layout, context, getattr(properties, 'rig_name', ''))
    elif target_type == 'COLLECTION':
        _fbp_draw_collection_button_context(
            layout,
            context,
            getattr(properties, 'collection_name', ''),
            getattr(properties, 'tree_index', -1),
        )
    elif target_type == 'PENDING':
        _fbp_draw_pending_layer_button_context(
            layout,
            context,
            getattr(properties, 'index', -1),
            getattr(properties, 'tree_index', -1),
        )
    elif target_type == 'PENDING_GROUP':
        _fbp_draw_pending_group_button_context(
            layout,
            context,
            getattr(properties, 'collection_name', ''),
            getattr(properties, 'tree_index', -1),
        )

def draw_fbp_image_add_menu(self, context):
    layout = self.layout
    prefs = _fbp_ui_preferences(context)
    position = str(getattr(prefs, 'shift_a_menu_position', 'TOP') or 'TOP').upper()
    if position == 'TOP':
        layout.menu("FBP_MT_frame_by_plane_add", icon="RENDERLAYERS")
        layout.separator()
        return
    layout.separator()
    layout.menu("FBP_MT_frame_by_plane_add", icon="RENDERLAYERS")
def draw_fbp_object_context_menu(self, context):
    """Prepend one compact submenu only for selected Frame By Plane elements."""
    if not _fbp_context_has_addon_selection(context):
        return
    self.layout.menu(
        FBP_MT_ObjectContext.bl_idname,
        text="Frame By Plane",
        icon="RENDERLAYERS",
    )
    self.layout.separator()
def draw_fbp_delete_menu(self, context):
    try:
        from .grease_pencil_bridge import is_gp_canvas
        if is_gp_canvas(getattr(context, "object", None)):
            self.layout.separator()
            self.layout.operator(
                "fbp.delete_grease_pencil_canvas",
                text="Frame By Plane: Delete Grease Pencil Layer",
                icon=ui_icon("generic.delete"),
            )
            return
    except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        pass
    if get_selected_fbp_roots(context):
        self.layout.separator()
        self.layout.operator("fbp.delete_sequence", text="Frame By Plane: Delete Layer + Plane", icon=ui_icon("generic.delete"))

def fbp_blender_menu_draw(self, context):
    """Add Frame By Plane splash entries to Blender's top-left app menu."""
    layout = self.layout
    layout.operator_context = 'INVOKE_DEFAULT'
    layout.separator()
    op = layout.operator(
        "fbp.whats_new_prompt",
        text="Frame By Plane: What's New",
        icon='PRESET',
    )
    op.force = True
    op.start_tutorial = False
    op = layout.operator(
        "fbp.live_tutorial",
        text="Frame By Plane Tutorial",
        icon=ui_icon("menu.gp_layer"),
    )


def fbp_blender_menu_class():
    """Return Blender's top-left application menu."""
    return getattr(bpy.types, "TOPBAR_MT_blender", None)


def fbp_render_menu_draw(self, context):
    """Place Frame By Plane background render at the top of Blender's Render menu."""
    layout = self.layout
    layout.operator(
        "fbp.background_render_frames",
        text="Frame By Plane: Background Render",
        icon=ui_icon("settings.render"),
    )
    layout.separator()
def fbp_render_menu_class():
    """Return Blender 5.2's Topbar Render menu."""
    return getattr(bpy.types, "TOPBAR_MT_render", None)


_FBP_REGISTERED_MENU_CALLBACKS = globals().get("_FBP_REGISTERED_MENU_CALLBACKS", [])


def _fbp_remove_registered_menu_callbacks():
    """Remove callbacks from previous module generations by their stored identity."""
    for menu_cls, callback in reversed(list(_FBP_REGISTERED_MENU_CALLBACKS)):
        try:
            menu_cls.remove(callback)
        except FBP_DATA_ERRORS:
            pass
    _FBP_REGISTERED_MENU_CALLBACKS.clear()


def _fbp_register_menu_callback(menu_cls, callback, method='append'):
    if not menu_cls:
        return False
    try:
        getattr(menu_cls, method)(callback)
        _FBP_REGISTERED_MENU_CALLBACKS.append((menu_cls, callback))
        return True
    except FBP_DATA_ERRORS as exc:
        fbp_warn(f"Could not register Frame By Plane menu callback on {getattr(menu_cls, '__name__', menu_cls)}", exc)
        return False


def _fbp_shift_a_menu_registration():
    prefs = _fbp_ui_preferences(getattr(bpy, 'context', None))
    position = str(getattr(prefs, 'shift_a_menu_position', 'TOP') or 'TOP').upper()
    if position == 'IMAGE':
        target = getattr(bpy.types, "VIEW3D_MT_image_add", None)
        if target is not None:
            return target, 'append'
        position = 'TOP'
    target = getattr(bpy.types, "VIEW3D_MT_add", None)
    return target, ('append' if position == 'BOTTOM' else 'prepend')


def refresh_fbp_shift_a_menu_registration():
    """Apply a changed Shift+A preference immediately without reopening Blender."""
    register_fbp_menus()


def register_fbp_menus():
    # Remove callbacks kept by an older module generation before adding the
    # current functions. Blender's Menu.remove() compares function identity.
    _fbp_remove_registered_menu_callbacks()

    shift_a_menu, shift_a_method = _fbp_shift_a_menu_registration()
    _fbp_register_menu_callback(
        shift_a_menu,
        draw_fbp_image_add_menu,
        method=shift_a_method,
    )
    _fbp_register_menu_callback(
        fbp_blender_menu_class(),
        fbp_blender_menu_draw,
        method='prepend',
    )
    _fbp_register_menu_callback(
        fbp_render_menu_class(),
        fbp_render_menu_draw,
        method='prepend',
    )
    _fbp_register_menu_callback(
        getattr(bpy.types, "WM_MT_button_context", None),
        draw_fbp_button_context_menu,
        method='append',
    )
    for menu_name in ("VIEW3D_MT_object_context_menu", "OUTLINER_MT_context_menu"):
        _fbp_register_menu_callback(
            getattr(bpy.types, menu_name, None),
            draw_fbp_object_context_menu,
            method='prepend',
        )
    for menu_name in ("VIEW3D_MT_object_delete", "OUTLINER_MT_object_delete"):
        _fbp_register_menu_callback(
            getattr(bpy.types, menu_name, None),
            draw_fbp_delete_menu,
            method='prepend',
        )


def unregister_fbp_menus():
    _fbp_remove_registered_menu_callbacks()


# SECTION 12 - UI registration #
# Add or remove panels/UILists here without changing core.py.
ui_classes = (
    FBP_OT_UIListFilterPopup,
    FBP_OT_ResetUIListFilter,
    FBP_OT_UIListColumnVisibility,
    FBP_OT_UIListColumnDrag,
    FBP_OT_UIListColumnsReset,
    FBP_OT_UIListLabelAlignment,
    FBP_PT_UIListColumnsPopover,
    FBP_OT_UIListColumnsPopup,
    FBP_OT_LayerOptionsPopup,
    FBP_OT_RigShapePopup,
    FBP_OT_EditRigShape,
    FBP_OT_OpenEffectsMasks,
    FBP_MT_LayerBlendDropdown,
    FBP_MT_PlaneLayerStackMore,
    FBP_MT_GreasePencilLayerStackMore,
    FBP_MT_MoveLayerCollectionTo,
    FBP_MT_LayerStackMore,
    FBP_MT_RenderFolderTag,
    FBP_OT_SetRenderToken,
    FBP_MT_RenderTokenBefore,
    FBP_MT_RenderTokenAfter,
    FBP_MT_FrameByPlaneMore,
    FBP_UL_LayerStack,
    FBP_UL_LayerTreeList,
    FBP_UL_LayerTreePlanesList,
    FBP_UL_GreasePencilLayerList,
    FBP_UL_ImageList,
    FBP_UL_PendingList,
    FBP_UL_PendingTreeList,
    FBP_UL_CompositorLayers,
    FBP_UL_CompositorEffects,
    FBP_PT_OutputAnchor,
    FBP_PT_OutputRender,
    FBP_PT_ProjectDoctor,
    FBP_PT_PerformanceDashboard,
    FBP_MT_PendingSetupActions,
    FBP_MT_PendingSetupAdd,
    FBP_MT_CompositorLayerListActions,
    FBP_MT_CompositorEffectListActions,
    FBP_PT_OutputCompositor,
    FBP_PT_CompositorNodeSidebar,
    FBP_PT_CameraSettings,
    FBP_PT_FrameByPlaneSidebarAnchor,
    FBP_PT_ToolSidebarAnchor,
    FBP_PT_LayerStack,
    FBP_PT_GreasePencilStack,
    FBP_MT_SequenceFrameActions,
    FBP_MT_SequenceFrameAdd,
    FBP_PT_Sequence,
    FBP_PT_ToolLayerStack,
    FBP_PT_ToolGreasePencilStack,
    FBP_PT_ToolSequence,
    FBP_PT_ModifierShortcuts,
    FBP_MT_FrameByPlaneAdd,
    FBP_MT_ObjectMaskContext,
    FBP_MT_ObjectLayerContext,
    FBP_OT_SetSelectedLayerTag,
    FBP_MT_ObjectLayerTags,
    FBP_MT_ObjectContext,
    FBP_MT_ObjectHoldout,
)


_PROPERTIES_ORDER_CLASSES = (
    FBP_PT_OutputAnchor,
    FBP_PT_OutputRender,
    FBP_PT_ProjectDoctor,
    FBP_PT_PerformanceDashboard,
    FBP_PT_OutputCompositor,
    FBP_PT_ModifierShortcuts,
)


def _all_properties_order_classes():
    """Return all Properties panels in strict parent-before-child order."""
    external = {}
    for module_name, class_name in (
        ('.projector', 'FBP_PT_ProjectorLight'),
        ('.compositor_layer_node', 'FBP_PT_CompositorLayerNodePrototype'),
    ):
        try:
            module = __import__(f"{__package__}{module_name}", fromlist=(class_name,))
            panel_cls = getattr(module, class_name, None)
            if panel_cls is not None:
                external[class_name] = panel_cls
        except (ImportError, AttributeError, RuntimeError):
            continue

    ordered = [
        FBP_PT_OutputAnchor,
        FBP_PT_OutputRender,
        FBP_PT_ProjectDoctor,
        FBP_PT_PerformanceDashboard,
        FBP_PT_OutputCompositor,
    ]
    layer_status = external.get('FBP_PT_CompositorLayerNodePrototype')
    if layer_status is not None:
        ordered.append(layer_status)
    ordered.append(FBP_PT_CameraSettings)
    projector = external.get('FBP_PT_ProjectorLight')
    if projector is not None:
        ordered.append(projector)
    ordered.append(FBP_PT_ModifierShortcuts)
    return tuple(dict.fromkeys(ordered))



def _set_properties_panel_orders(_always_on_top=True):
    """Normalize registered panel orders without using invalid negative values.

    Blender defines ``Panel.bl_order`` as an unsigned integer. Output uses an
    add-on anchor; View Layer, Camera, Light and Modifier panels attach directly
    to Blender's native top headerless context panels with non-negative order.
    """
    for cls in _all_properties_order_classes():
        cls.bl_order = max(0, int(getattr(cls, 'bl_order', 0) or 0))


def refresh_properties_panel_order():
    """Atomically re-register the Properties panels after a preference change."""
    if bool(getattr(bpy.app, "background", False)):
        return None
    prefs = _fbp_ui_preferences(getattr(bpy, "context", None))
    active = tuple(
        cls for cls in _all_properties_order_classes()
        if getattr(bpy.types, cls.__name__, None) is not None
    )
    if not active:
        _set_properties_panel_orders(True)
        return None

    previous_orders = {cls: int(getattr(cls, "bl_order", 0) or 0) for cls in active}
    removed = []
    try:
        for cls in reversed(active):
            bpy.utils.unregister_class(cls)
            removed.append(cls)
    except FBP_DATA_IO_ERRORS as exc:
        for cls in reversed(removed):
            try:
                bpy.utils.register_class(cls)
            except FBP_DATA_IO_ERRORS:
                continue
        fbp_warn("Could not refresh Frame By Plane panel order", exc)
        return None

    _set_properties_panel_orders(True)
    restored = []
    try:
        removed_set = set(removed)
        for cls in _all_properties_order_classes():
            if cls not in removed_set:
                continue
            bpy.utils.register_class(cls)
            restored.append(cls)
    except FBP_DATA_IO_ERRORS as exc:
        unregister_classes(restored)
        for cls, order in previous_orders.items():
            cls.bl_order = int(order)
        for cls in _all_properties_order_classes():
            if cls not in removed_set:
                continue
            try:
                bpy.utils.register_class(cls)
            except FBP_DATA_IO_ERRORS as rollback_exc:
                fbp_warn(f"Could not restore panel {cls.__name__}", rollback_exc)
        fbp_warn("Could not apply the new Frame By Plane panel order", exc)
    return None


def register():
    if bool(getattr(bpy.app, "background", False)):
        return
    icons_registered = False
    try:
        register_custom_icons()
        icons_registered = True
        prefs = _fbp_ui_preferences(getattr(bpy, "context", None))
        _set_properties_panel_orders(True)
        register_classes(ui_classes)
        register_fbp_menus()
        register_service(
            "ui.refresh_properties_panel_order",
            refresh_properties_panel_order,
            owner=__name__,
        )
        register_service(
            "ui.refresh_shift_a_menu",
            refresh_fbp_shift_a_menu_registration,
            owner=__name__,
        )
    except Exception:
        unregister_service("ui.refresh_shift_a_menu")
        unregister_service("ui.refresh_properties_panel_order")
        unregister_fbp_menus()
        unregister_classes(ui_classes)
        if icons_registered:
            unregister_custom_icons()
        raise


def unregister():
    unregister_service("ui.refresh_shift_a_menu")
    unregister_service("ui.refresh_properties_panel_order")
    unregister_fbp_menus()
    unregister_classes(ui_classes)
    unregister_custom_icons()
