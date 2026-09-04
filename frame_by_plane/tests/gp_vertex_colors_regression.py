import importlib
import os
import sys
import traceback
from pathlib import Path
from types import SimpleNamespace

import bpy
import bl_ui.properties_paint_common as paint_common
import bl_ui.space_view3d as space_view3d


INSTALLED_PACKAGE = os.environ.get("FBP_TEST_INSTALLED") == "1"
PACKAGE_NAME = os.environ.get(
    "FBP_TEST_PACKAGE",
    "bl_ext.fbp_audit.frame_by_plane" if INSTALLED_PACKAGE else "frame_by_plane",
)
if not INSTALLED_PACKAGE:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
addon = importlib.import_module(PACKAGE_NAME)


def close_color(actual, expected, epsilon=1.0e-5):
    return all(abs(float(a) - float(b)) <= epsilon for a, b in zip(actual, expected))


try:
    if not INSTALLED_PACKAGE:
        addon.register()
    module = addon.gp_vertex_colors
    assert module._HEADER_REGISTERED is True
    assert bpy.app.timers.is_registered(module.fbp_gp_brush_color_timer)
    assert len(module._ADDON_KEYMAPS) == 3
    sample_items = [
        item
        for _keymap, item in module._ADDON_KEYMAPS
        if item.idname == "fbp.sample_gp_stroke_color"
    ]
    assert len(sample_items) == 2
    assert all(
        item.idname == "fbp.sample_gp_stroke_color"
        and item.type == "X"
        and item.value == "PRESS"
        and item.shift
        for item in sample_items
    )
    close_items = [
        (keymap, item)
        for keymap, item in module._ADDON_KEYMAPS
        if item.idname == "fbp.toggle_gp_close_gap"
    ]
    assert len(close_items) == 1
    assert close_items[0][0].name == "Grease Pencil Draw Mode"
    assert close_items[0][1].type == "G"
    assert not close_items[0][1].shift and not close_items[0][1].ctrl

    data = bpy.data.grease_pencils.new("FBP Dual Color Test")
    obj = bpy.data.objects.new("FBP Dual Color Test", data)
    bpy.context.scene.collection.objects.link(obj)
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    layer = data.layers.new("Layer", set_active=True)
    drawing = layer.frames.new(1).drawing
    drawing.add_strokes([3, 2])

    material = bpy.data.materials.new("FBP Dual Color Ink")
    bpy.data.materials.create_gpencil_data(material)
    data.materials.append(material)

    point_colors = (
        (1.0, 0.0, 0.0, 1.0),
        (0.0, 1.0, 0.0, 0.5),
        (0.0, 0.0, 1.0, 0.25),
        (1.0, 1.0, 0.0, 1.0),
        (1.0, 0.0, 1.0, 1.0),
    )
    for index, point in enumerate(point for stroke in drawing.strokes for point in stroke.points):
        point.vertex_color = point_colors[index]
    drawing.strokes[0].fill_color = (0.1, 0.2, 0.3, 0.4)
    drawing.strokes[1].fill_color = (0.7, 0.6, 0.5, 0.4)

    bpy.ops.object.mode_set(mode="EDIT")
    bpy.context.scene.tool_settings.gpencil_selectmode_edit = "POINT"
    bpy.ops.grease_pencil.select_all(action="DESELECT")
    drawing.strokes[0].points[0].select = True
    drawing.strokes[0].points[1].select = True
    drawing.strokes[1].points[0].select = True
    selection_values = module._drawing_selection_values(drawing, "POINT")
    assert selection_values is not module._MISSING
    assert tuple(selection_values) == (1, 1, 0, 1, 0)

    assert module._sync_edit_state(bpy.context, force=True)
    state = obj.fbp_gp_vertex_color_state
    assert state.selected_points == 3
    assert state.selected_curves == 2
    assert state.stroke_mixed is True
    assert state.fill_mixed is True
    assert len(module._RUNTIME["stroke_swatches"]) == 3
    assert len(module._RUNTIME["fill_swatches"]) == 2
    assert module._RUNTIME["edit_point_count"] == 3
    assert len(module._RUNTIME["edit_point_targets"]) == 1
    assert len(module._RUNTIME["edit_point_targets"][0][3]) == 2
    assert module._RUNTIME["edit_fill_count"] == 2
    assert len(module._RUNTIME["edit_fill_targets"]) == 1
    assert len(module._RUNTIME["edit_fill_targets"][0][3]) == 2

    # Native Stroke Select marks every point in a selected stroke. The fast
    # path reads one selection bit per stroke and still builds full targets.
    bpy.context.scene.tool_settings.gpencil_selectmode_edit = "STROKE"
    bpy.ops.grease_pencil.select_all(action="SELECT")
    assert module._drawing_selection_values(drawing, "CURVE") is None
    assert module._sync_edit_state(bpy.context, force=True)
    assert state.selected_points == 5
    assert state.selected_curves == 2
    assert all(
        selector is None
        for _stroke, selector, _offset, _count in module._RUNTIME["edit_point_targets"][0][3]
    )
    bpy.context.scene.tool_settings.gpencil_selectmode_edit = "POINT"
    bpy.ops.grease_pencil.select_all(action="DESELECT")
    drawing.strokes[0].points[0].select = True
    drawing.strokes[0].points[1].select = True
    drawing.strokes[1].points[0].select = True
    module._sync_edit_state(bpy.context, force=True)

    assert module._apply_selected_cyclic(bpy.context, True) == 2
    assert all(stroke.cyclic for stroke in drawing.strokes)
    assert module._apply_selected_cyclic(bpy.context, False) == 2
    assert not any(stroke.cyclic for stroke in drawing.strokes)

    # Unrelated or transform-only depsgraph traffic must not invalidate the
    # expensive Edit selection cache. GP geometry/selection updates must.
    unrelated_data = bpy.data.meshes.new("FBP Unrelated Depsgraph Data")
    module._RUNTIME["edit_suppress_dirty_until"] = 0.0
    module._RUNTIME["edit_dirty"] = False
    unrelated_graph = SimpleNamespace(
        updates=(SimpleNamespace(id=unrelated_data, is_updated_geometry=True),)
    )
    module.fbp_gp_vertex_brush_color_sync(None, unrelated_graph)
    assert module._RUNTIME["edit_dirty"] is False
    transform_graph = SimpleNamespace(
        updates=(SimpleNamespace(id=obj, is_updated_geometry=False),)
    )
    module.fbp_gp_vertex_brush_color_sync(None, transform_graph)
    assert module._RUNTIME["edit_dirty"] is False
    geometry_graph = SimpleNamespace(
        updates=(SimpleNamespace(id=data, is_updated_geometry=True),)
    )
    module.fbp_gp_vertex_brush_color_sync(None, geometry_graph)
    assert module._RUNTIME["edit_dirty"] is True

    unique_keys = set()
    swatches = []
    fingerprint = (0, 0)
    for index in range(12):
        color = (index / 12.0, 0.25, 0.5, 1.0)
        fingerprint = module._record_color(
            color,
            module._color_key(color),
            unique_keys,
            swatches,
            fingerprint,
        )
    assert len(unique_keys) == 12
    assert len(swatches) == 8
    assert fingerprint != (0, 0)

    # A clean Edit cache must not rescan the selected geometry on every Tool
    # Header redraw. Continuous geometry updates are debounced until quiet.
    original_snapshot = module._selected_color_snapshot
    snapshot_calls = []

    def counted_snapshot(*args, **kwargs):
        snapshot_calls.append(1)
        return original_snapshot(*args, **kwargs)

    module._selected_color_snapshot = counted_snapshot
    try:
        module._RUNTIME["edit_dirty"] = False
        for _index in range(8):
            assert module._sync_edit_state(bpy.context) is False
        assert not snapshot_calls
        module._RUNTIME["edit_dirty"] = True
        module._RUNTIME["edit_last_sync"] = 0.0
        module._RUNTIME["edit_last_dirty"] = module.time.perf_counter()
        assert module._sync_edit_state(bpy.context) is False
        assert not snapshot_calls
        module._RUNTIME["edit_last_dirty"] = 0.0
        module._sync_edit_state(bpy.context)
        assert len(snapshot_calls) == 1
    finally:
        module._selected_color_snapshot = original_snapshot

    unselected_before = tuple(
        tuple(point.vertex_color)
        for stroke in drawing.strokes
        for point in stroke.points
        if not point.select
    )
    new_stroke = (0.2, 0.4, 0.6, 0.8)
    new_fill = (0.9, 0.3, 0.1, 0.7)
    state.stroke_color = new_stroke
    state.fill_color = new_fill
    selected_points = tuple(
        point
        for stroke in drawing.strokes
        for point in stroke.points
        if point.select
    )
    assert all(close_color(point.vertex_color, new_stroke) for point in selected_points)
    assert tuple(
        tuple(point.vertex_color)
        for stroke in drawing.strokes
        for point in stroke.points
        if not point.select
    ) == unselected_before
    assert all(close_color(stroke.fill_color, new_fill) for stroke in drawing.strokes)
    assert module._sync_edit_state(bpy.context, force=True)
    assert state.stroke_mixed is False
    assert state.fill_mixed is False

    result = bpy.ops.fbp.swap_gp_vertex_colors()
    assert result == {"FINISHED"}
    assert all(close_color(point.vertex_color, new_fill) for point in selected_points)
    assert all(close_color(stroke.fill_color, new_stroke) for stroke in drawing.strokes)

    bpy.ops.object.mode_set(mode="VERTEX_GREASE_PENCIL")
    assert bpy.context.mode == "VERTEX_GREASE_PENCIL"
    module._RUNTIME["target"] = 0
    assert module._sync_vertex_state(bpy.context)
    paint, brush, owner, gp_settings = module._brush_context(bpy.context)
    assert paint is not None and brush is not None and owner is not None

    # The replacement sampler stays modal and receives recurring TIMER events
    # until the launch key is released, so a held Shift+X never freezes on an
    # accumulated first sample.
    timer_token = object()
    sampler_calls = []
    sampler = SimpleNamespace(
        _timer=timer_token,
        _sample=lambda _context: sampler_calls.append(1) or True,
        _finish=lambda _context: setattr(sampler, "_timer", None),
        _launch_key="X",
        _initial_stroke=None,
    )
    timer_event = SimpleNamespace(type="TIMER", value="NOTHING", timer=timer_token)
    assert module.FBP_OT_SampleGPStrokeColor.modal(sampler, bpy.context, timer_event) == {"RUNNING_MODAL"}
    assert sampler_calls == [1]
    blender_52_timer_event = SimpleNamespace(type="TIMER", value="NOTHING")
    assert module.FBP_OT_SampleGPStrokeColor.modal(
        sampler, bpy.context, blender_52_timer_event
    ) == {"RUNNING_MODAL"}
    assert sampler_calls == [1, 1]
    release_event = SimpleNamespace(type="X", value="RELEASE", timer=None)
    assert module.FBP_OT_SampleGPStrokeColor.modal(sampler, bpy.context, release_event) == {"FINISHED"}
    assert sampler._timer is None

    sample_undo_labels = []
    original_push_undo = module._push_edit_color_undo
    module._push_edit_color_undo = lambda label: sample_undo_labels.append(label) or True
    sampled_sampler = SimpleNamespace(
        _launch_key="X",
        _initial_stroke=(0.99, 0.98, 0.97, 1.0),
        _finish=lambda _context: None,
    )
    try:
        assert module.FBP_OT_SampleGPStrokeColor.modal(
            sampled_sampler,
            bpy.context,
            release_event,
        ) == {"FINISHED"}
    finally:
        module._push_edit_color_undo = original_push_undo
    assert sample_undo_labels == ["Sample Grease Pencil Stroke Color"]

    state.stroke_color = (0.15, 0.25, 0.35, 1.0)
    state.fill_color = (0.75, 0.65, 0.55, 1.0)
    gp_settings.vertex_mode = "STROKE"
    module._sync_vertex_state(bpy.context)
    assert close_color(owner.color, state.stroke_color[:3])
    assert close_color(owner.secondary_color, state.fill_color[:3])

    # Emulate Blender's native X operator and let the semantic synchronizer
    # detect the exact primary/secondary swap.
    before_stroke = tuple(state.stroke_color)
    before_fill = tuple(state.fill_color)
    owner.color, owner.secondary_color = tuple(owner.secondary_color), tuple(owner.color)
    assert module._sync_vertex_state(bpy.context)
    assert close_color(state.stroke_color, before_fill)
    assert close_color(state.fill_color, before_stroke)

    # Emulate Shift+X: only native primary changes, and only semantic Stroke
    # must follow it.
    fill_before_sample = tuple(state.fill_color)
    owner.color = (0.91, 0.12, 0.43)
    assert module._sync_vertex_state(bpy.context)
    assert close_color(state.stroke_color[:3], (0.91, 0.12, 0.43))
    assert close_color(state.fill_color, fill_before_sample)

    # In Fill mode the native primary is the semantic Fill color, while a
    # sampled primary is still captured into Stroke and then Fill is restored.
    gp_settings.vertex_mode = "FILL"
    assert module._sync_vertex_state(bpy.context)
    fill_before_sample = tuple(state.fill_color)
    owner.color = (0.11, 0.82, 0.31)
    assert module._sync_vertex_state(bpy.context)
    assert close_color(state.stroke_color[:3], (0.11, 0.82, 0.31))
    assert close_color(state.fill_color, fill_before_sample)
    assert close_color(owner.color, state.fill_color[:3])
    assert close_color(owner.secondary_color, state.stroke_color[:3])

    bpy.ops.object.mode_set(mode="PAINT_GREASE_PENCIL")
    assert bpy.context.mode == "PAINT_GREASE_PENCIL"
    module._sync_draw_state(bpy.context)
    draw_paint, draw_brush, draw_owner, draw_settings = module._draw_brush_context(bpy.context)
    assert draw_paint is not None and draw_brush is not None and draw_owner is not None

    state.stroke_color = (0.22, 0.32, 0.42, 1.0)
    state.fill_color = (0.72, 0.62, 0.52, 1.0)
    draw_settings.stroke_type = "STROKE"
    module._sync_draw_state(bpy.context)
    assert close_color(draw_owner.color, state.stroke_color[:3])
    assert close_color(draw_owner.secondary_color, state.fill_color[:3])

    before_stroke = tuple(state.stroke_color)
    before_fill = tuple(state.fill_color)
    draw_owner.color, draw_owner.secondary_color = (
        tuple(draw_owner.secondary_color),
        tuple(draw_owner.color),
    )
    assert module.fbp_gp_brush_color_timer() == (1.0 / 30.0)
    assert close_color(state.stroke_color, before_fill)
    assert close_color(state.fill_color, before_stroke)

    fill_before_sample = tuple(state.fill_color)
    draw_owner.color = (0.13, 0.73, 0.93)
    assert module.fbp_gp_brush_color_timer() == (1.0 / 30.0)
    assert close_color(state.stroke_color[:3], (0.13, 0.73, 0.93))
    assert close_color(state.fill_color, fill_before_sample)

    # Blender 5.2 gives Both a single brush color. The add-on preserves the
    # native stroke color and replaces only the fill of newly added curves.
    draw_settings.stroke_type = "BOTH"
    draw_settings.pin_draw_mode = True
    draw_settings.brush_draw_mode = "VERTEXCOLOR"
    bpy.context.scene.tool_settings.use_gpencil_draw_onback = False
    state.stroke_color = (0.18, 0.28, 0.38, 1.0)
    state.fill_color = (0.81, 0.61, 0.21, 0.65)
    state.close_strokes = False
    module._sync_draw_state(bpy.context)
    old_fill = tuple(drawing.strokes[0].fill_color)
    module._reset_draw_both_tracking()
    assert module._sync_draw_both_fill(bpy.context) == 0
    drawing.add_strokes([2])
    newest = drawing.strokes[-1]
    newest.fill_color = tuple(state.stroke_color)
    newest.cyclic = True
    assert module._sync_draw_both_fill(bpy.context) == 1
    assert close_color(newest.fill_color, state.fill_color)
    assert newest.cyclic is False
    assert close_color(drawing.strokes[0].fill_color, old_fill)
    assert tuple(module._new_draw_curve_indices(4, 6, False)) == (4, 5)
    assert tuple(module._new_draw_curve_indices(4, 6, True)) == (0, 1)

    # Closure is independent from Both and works in every Draw target mode.
    draw_settings.stroke_type = "STROKE"
    state.close_strokes = True
    module._reset_draw_both_tracking()
    assert module._sync_draw_both_fill(bpy.context) == 0
    drawing.add_strokes([2])
    closed_stroke = drawing.strokes[-1]
    assert closed_stroke.cyclic is False
    assert module._sync_draw_both_fill(bpy.context) == 1
    assert closed_stroke.cyclic is True

    default_data = bpy.data.grease_pencils.new("FBP Default Bulk Color")
    default_layer = default_data.layers.new("Layer", set_active=True)
    default_drawing = default_layer.frames.new(1).drawing
    default_drawing.add_strokes([2])
    default_stroke = default_drawing.strokes[0]
    default_group = (default_drawing, 2, 2, ((default_stroke, None, 0, 2),))
    assert module._write_point_group_color(default_group, (0.4, 0.5, 0.6, 0.7)) == 2
    assert all(
        close_color(point.vertex_color, (0.4, 0.5, 0.6, 0.7))
        for point in default_stroke.points
    )
    default_fill_group = (default_drawing, 1, 1, ((default_stroke, 0),))
    assert module._write_fill_group_color(default_fill_group, (0.7, 0.6, 0.5, 0.4)) == 1
    assert close_color(default_stroke.fill_color, (0.7, 0.6, 0.5, 0.4))

    assert paint_common.brush_basic__draw_color_selector is module._draw_native_draw_color_selector
    assert (
        paint_common.brush_basic_grease_pencil_paint_settings
        is module._draw_native_gp_paint_settings
    )
    vertex_draw = vars(space_view3d._draw_tool_settings_context_mode)["VERTEX_GREASE_PENCIL"]
    edit_draw = vars(space_view3d._draw_tool_settings_context_mode)["EDIT_GREASE_PENCIL"]
    assert vertex_draw.__func__ is module._draw_native_vertex_tool_settings
    assert edit_draw.__func__ is module._draw_native_edit_tool_settings

    class FakeLayout:
        def __init__(self, root=None):
            self.root = root or self
            if root is None:
                self.calls = []
                self.children = []
            self.enabled = True
            self.ui_units_x = 0.0
            self.scale_x = 1.0
            self.align = None

        def row(self, **kwargs):
            child = FakeLayout(self.root)
            child.align = kwargs.get("align")
            self.root.children.append(child)
            return child

        def separator(self, **_kwargs):
            return None

        def popover(self, **_kwargs):
            return None

        def prop_enum(self, _owner, name, value, **_kwargs):
            self.root.calls.append(("enum", name, value))

        def prop_with_popover(self, _owner, name, **kwargs):
            self.root.calls.append(("color", name, kwargs.get("panel")))

        def prop(self, _owner, name, **kwargs):
            self.root.calls.append(("property", name, kwargs.get("icon")))

        def operator(self, operator_id, **kwargs):
            self.root.calls.append(("operator", operator_id, kwargs.get("icon")))
            return self

    fake_layout = FakeLayout()
    assert module._draw_header_color_pair(fake_layout, bpy.context, owner=draw_owner)
    assert fake_layout.calls == [
        ("color", "stroke_color", "FBP_PT_gp_stroke_color_popover"),
        ("operator", "paint.brush_colors_flip", "ARROW_LEFTRIGHT"),
        ("color", "fill_color", "FBP_PT_gp_fill_color_popover"),
        ("operator", "fbp.toggle_gp_close_gap", "LOOP_BACK"),
    ]
    assert [child.ui_units_x for child in fake_layout.children] == [
        7.75,
        2.5,
        1.25,
        2.5,
        1.5,
    ]

    # Pin Mode belongs immediately after Material / Color Attribute and before
    # the semantic swatches.
    color_layout = FakeLayout()
    module._draw_native_draw_color_selector(
        bpy.context,
        color_layout,
        draw_brush,
        draw_settings,
    )
    pin_index = color_layout.calls.index(("property", "pin_draw_mode", None))
    stroke_index = color_layout.calls.index(
        ("color", "stroke_color", "FBP_PT_gp_stroke_color_popover")
    )
    assert pin_index < stroke_index
    assert not any(
        call[:2] == ("operator", "fbp.toggle_gp_close_gap")
        for call in color_layout.calls
    )

    # Close Gap is injected after Stroke/Fill/Both and before Caps Type. Its
    # own row deliberately uses align=False.
    settings_layout = FakeLayout()
    proxy = module._FBPCloseGapLayoutProxy(settings_layout, bpy.context)
    line_types = proxy.row(align=True)
    line_types.prop_enum(draw_settings, "stroke_type", "STROKE", text="")
    caps = proxy.row(align=True)
    caps.prop(draw_settings, "caps_type", text="")
    assert settings_layout.calls == [
        ("enum", "stroke_type", "STROKE"),
        ("operator", "fbp.toggle_gp_close_gap", "LOOP_BACK"),
        ("property", "caps_type", None),
    ]
    assert [child.align for child in settings_layout.children] == [True, False, True]

    print("FBPTEST gp_dual_vertex_colors: PASS")
except Exception:
    traceback.print_exc()
    raise
finally:
    try:
        if bpy.context.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")
    except Exception:
        pass
    if not INSTALLED_PACKAGE:
        try:
            addon.unregister()
        except Exception:
            traceback.print_exc()
