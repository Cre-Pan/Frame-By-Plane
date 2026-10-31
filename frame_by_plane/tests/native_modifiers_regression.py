"""Effects in Blender's Modifiers panel: menu, native edits and modifier shells.

Covers the Add Modifier > Mesh entry, the native reorder / visibility / delete
/ duplicate round trip into the Frame By Plane stack, the per-effect Mask
panel and the preview image-effect shells (material links, Cycles parity,
animated inputs, removal and save/reopen).
"""

import importlib
import math
import os
import sys
import tempfile
import traceback
from pathlib import Path

import bpy


INSTALLED_PACKAGE = os.environ.get("FBP_TEST_INSTALLED") == "1"
PACKAGE_NAME = os.environ.get(
    "FBP_TEST_PACKAGE",
    "bl_ext.fbp_audit.frame_by_plane" if INSTALLED_PACKAGE else "frame_by_plane",
)
if not INSTALLED_PACKAGE:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from ui_layout_stub import StubLayout  # noqa: E402

addon = importlib.import_module(PACKAGE_NAME)
WORKDIR = Path(tempfile.mkdtemp(prefix="fbp_native_modifiers_"))
SHELL_EFFECTS = ("HUE_SATURATION", "VIGNETTE", "POSTERIZE", "GRADIENT_MASK", "CIRCLE_MASK", "SQUARE_MASK")


def _modules():
    return (
        importlib.import_module(f"{PACKAGE_NAME}.geometry_nodes"),
        importlib.import_module(f"{PACKAGE_NAME}.native_modifiers"),
        importlib.import_module(f"{PACKAGE_NAME}.effect_shells"),
    )


def _rig(name):
    builder = importlib.import_module(f"{PACKAGE_NAME}.builder")
    fixture = WORKDIR / "fixture.png"
    if not fixture.is_file():
        image = bpy.data.images.new("FBP Native Modifiers Fixture", 16, 16, alpha=True)
        image.generated_color = (0.2, 0.4, 0.8, 1.0)
        image.filepath_raw = str(fixture)
        image.file_format = "PNG"
        image.save()
        bpy.data.images.remove(image)
    return builder.build_fbp_rig(
        bpy.context, name, str(WORKDIR), [fixture.name], (0.0, 0.0, 0.0),
        target_collection=bpy.context.scene.collection,
    )


def _add(geo, rig, *effect_ids):
    for effect_id in effect_ids:
        assert geo.fbp_add_effect(
            rig, effect_id, select_object_mask_helper=False, inherit_active_group=False,
        ), effect_id


def _ids(geo, tokens):
    return [geo._fbp_effect_ref_effect_id(token) for token in tokens]


def _token(geo, rig, effect_id):
    return next(
        token for token in geo._fbp_mixed_effect_tokens(rig)
        if geo._fbp_effect_ref_effect_id(token) == effect_id
    )


def _remove(rig):
    for obj in reversed([rig, *rig.children_recursive]):
        try:
            bpy.data.objects.remove(obj, do_unlink=True)
        except (ReferenceError, RuntimeError):
            pass


def test_native_round_trip():
    geo, native, _shells = _modules()
    rig = _rig("FBP Native Round Trip")
    try:
        _add(geo, rig, "HUE_SATURATION", "MESH_WIGGLE", "VIGNETTE", "PAPER_SHARDS")
        plane = geo._fbp_plane(rig)
        assert native.fbp_native_ui_order(rig) == geo._fbp_mixed_effect_tokens(rig)
        native.fbp_native_remember(rig)
        assert not any(native.fbp_sync_native_modifiers(rig).values())

        # Dragging Paper Shards to the bottom of Modifiers = top of the stack.
        names = [modifier.name for modifier in plane.modifiers]
        plane.modifiers.move(names.index("FBP • Paper Shards"), len(names) - 1)
        assert native.fbp_sync_native_modifiers(rig)["reordered"]
        assert _ids(geo, geo._fbp_mixed_effect_tokens(rig))[0] == "PAPER_SHARDS"
        assert native.fbp_native_ui_order(rig) == geo._fbp_mixed_effect_tokens(rig)

        # Eye icons: a mesh effect modifier and an image-effect stage.
        plane.modifiers["FBP • Mesh Wiggle"].show_viewport = False
        native.fbp_sync_native_modifiers(rig)
        assert geo._fbp_stored_effect_visibility(rig, "MESH_WIGGLE", True) is False
        vignette = _token(geo, rig, "VIGNETTE")
        effect_id, instance_id = geo._fbp_effect_ref_parts(vignette)
        plane.modifiers["FBP • Vignette"].show_render = False
        native.fbp_sync_native_modifiers(rig)
        assert geo.fbp_effect_render_visible_state(rig, effect_id, instance_id) is False
        # A change made in the Frame By Plane panel shows on the native row.
        geo.fbp_set_effect_render_visible(rig, effect_id, True, instance_id)
        native.fbp_sync_native_modifiers(rig)
        assert plane.modifiers["FBP • Vignette"].show_render is True

        # Native delete removes the effect; a native copy is dropped.
        plane.modifiers.remove(plane.modifiers["FBP • Mesh Wiggle"])
        assert native.fbp_sync_native_modifiers(rig)["removed"]
        assert not geo.fbp_effect_is_active(rig, "MESH_WIGGLE")
        source = plane.modifiers["FBP • Paper Shards"]
        copy = plane.modifiers.new("Copy", "NODES")
        copy.node_group = source.node_group
        assert native.fbp_sync_native_modifiers(rig)["duplicates"] == 1
        assert "Copy" not in plane.modifiers

        # Frame By Plane removing the last mesh effect drops every stage;
        # the image effects must survive.
        geo.fbp_remove_effect(rig, "PAPER_SHARDS")
        native.fbp_sync_native_modifiers(rig)
        assert _ids(geo, geo._fbp_mixed_effect_tokens(rig)) == ["HUE_SATURATION", "VIGNETTE"]
    finally:
        _remove(rig)


def test_modifier_add_menu():
    geo, native, _shells = _modules()
    rig = _rig("FBP Native Menu")
    try:
        class Owner:
            layout = StubLayout()
        context = bpy.context.copy()
        bpy.context.view_layer.objects.active = rig
        native.draw_modifier_add_mesh(Owner, bpy.context)
        entry = [call for call in Owner.layout.calls if call[0] == "menu"]
        assert entry and entry[0][2]["icon"] == "MESH_MONKEY" and entry[0][2]["text"] == "Mesh"
        assert [(call[2]["text"], call[2]["icon"]) for call in entry] == [
            ("Mesh", "MESH_MONKEY"), ("Image", "IMAGE_DATA"), ("Mask", "MOD_MASK"),
        ], entry
        Owner.layout = StubLayout()
        native.FBP_MT_ModifierAddMask.draw(Owner, bpy.context)
        labels = [call[2].get("text") for call in Owner.layout.calls if call[0] == "operator"]
        assert "Gradient Mask" in labels and "Circle Mask" in labels, labels
        # Native style: one flat column of builtin icons, no section headers.
        assert not [call for call in Owner.layout.calls if call[0] in {"label", "column", "split", "grid_flow"}]
        assert all("icon" in call[2] for call in Owner.layout.calls if call[0] == "operator")
        Owner.layout = StubLayout()
        native.FBP_MT_ModifierAddImage.draw(Owner, bpy.context)
        submenus = [call[2].get("text") for call in Owner.layout.calls if call[0] == "menu"]
        assert submenus[:2] == ["Color", "Light"], submenus
        assert any(call[0] == "prop" for call in Owner.layout.calls)
        Owner.layout = StubLayout()
        native._IMAGE_SECTION_MENUS[0].draw(Owner, bpy.context)
        ops = [call for call in Owner.layout.calls if call[0] == "operator"]
        assert any(call[2].get("text") == "Vignette" and call[1][0] == "fbp.add_effect_modifier" for call in ops), ops
        Owner.layout = StubLayout()
        native.FBP_MT_ModifierAddMesh.draw(Owner, bpy.context)
        labels = [call[2].get("text") for call in Owner.layout.calls if call[0] == "operator"]
        assert "Mesh Wiggle" in labels and "Paper Shards" in labels, labels
        Owner.layout = StubLayout()
        geo.FBP_MT_AddEffect.draw(Owner, bpy.context)
        menus = [call[2].get("text") for call in Owner.layout.calls if call[0] == "menu"]
        assert "Mesh Effects" not in menus, menus
        del context
    finally:
        _remove(rig)


def test_mask_panel():
    geo, _native, _shells = _modules()
    rig = _rig("FBP Native Mask Panel")
    try:
        _add(geo, rig, "HUE_SATURATION", "VIGNETTE")
        effect_id, instance_id = geo._fbp_effect_ref_parts(_token(geo, rig, "HUE_SATURATION"))
        layout = StubLayout()
        geo.fbp_draw_effect_mask_panel(layout, bpy.context, [rig], rig, effect_id, instance_id)
        assert any(call[0] == "operator_menu_enum" for call in layout.calls)
        assert geo.fbp_set_effect_mask_type([rig], "GRADIENT_MASK", effect_id, instance_id)
        assert geo.fbp_masks_targeting_effect(rig, effect_id, instance_id) == ("GRADIENT_MASK",)
        assert geo.fbp_set_effect_mask_type([rig], "CIRCLE_MASK", effect_id, instance_id)
        assert geo.fbp_masks_targeting_effect(rig, effect_id, instance_id) == ("CIRCLE_MASK",)
        assert not geo.fbp_effect_is_active(rig, "GRADIENT_MASK")
        layout = StubLayout()
        geo.fbp_draw_effect_mask_panel(layout, bpy.context, [rig], rig, effect_id, instance_id)
        assert any(call[0] == "panel" for call in layout.calls)
        report = geo.fbp_local_effect_mask_contract_report(rig)
        assert not report["issues"], report
    finally:
        _remove(rig)


def test_toggle_foldouts():
    geo, _native, _shells = _modules()
    rig = _rig("FBP Native Toggle Foldouts")
    try:
        _add(geo, rig, "ASCII", "MESH_WIGGLE")
        layout = StubLayout()
        geo.fbp_draw_effect_settings(layout, rig, "ASCII", selected_count=1)
        panels = [call[1][0] for call in layout.calls if call[0] == "panel"]
        assert "fbp_effect_ascii_edges" in panels, panels
        toggles = {call[1][1] for call in layout.calls if call[0] == "prop" and call[2].get("text") == ""}
        assert "fbp_terminal_ascii_use_edges" in toggles, toggles
        layout = StubLayout()
        geo.fbp_draw_effect_settings(layout, rig, "MESH_WIGGLE", selected_count=1)
        panels = [call[1][0] for call in layout.calls if call[0] == "panel"]
        assert "fbp_effect_animation" in panels, panels
    finally:
        _remove(rig)


def _render_setup(name):
    scene = bpy.context.scene
    for obj in scene.objects:
        if obj.type in {"LIGHT", "CAMERA"} or obj.name == "Cube":
            obj.hide_render = True
    camera = bpy.data.objects.new(name, bpy.data.cameras.new(name))
    scene.collection.objects.link(camera)
    camera.location = (0.0, -6.0, 0.0)
    camera.rotation_euler = (math.pi / 2.0, 0.0, 0.0)
    scene.camera = camera
    scene.render.engine = os.environ.get("FBP_TEST_SHELL_ENGINE", "CYCLES")
    if scene.render.engine == "CYCLES":
        scene.cycles.device = "CPU"
        scene.cycles.samples = 4
    scene.render.resolution_x = scene.render.resolution_y = 24
    scene.render.resolution_percentage = 100
    output = WORKDIR / "shell_render.png"
    scene.render.filepath = str(output)

    def render():
        bpy.ops.render.render(write_still=True)
        image = bpy.data.images.load(str(output), check_existing=False)
        try:
            return list(image.pixels)
        finally:
            bpy.data.images.remove(image)
    return camera, render


def _difference(first, second):
    return max(abs(a - b) for a, b in zip(first, second))


def test_add_image_modifier():
    geo, native, shells = _modules()
    scene = bpy.context.scene
    registered = hasattr(bpy.types, "FBP_OT_add_effect_modifier") or "add_effect_modifier" in dir(bpy.ops.fbp)
    if not registered:
        bpy.utils.register_class(native.FBP_OT_AddEffectModifier)
    rig = _rig("FBP Native Add Image")
    try:
        for obj in bpy.context.view_layer.objects:
            obj.select_set(False)
        rig.select_set(True)
        bpy.context.view_layer.objects.active = rig
        scene.fbp_preview_native_effect_shells = True
        assert bpy.ops.fbp.add_effect_modifier(effect_id="VIGNETTE") == {"FINISHED"}
        assert geo.fbp_effect_is_active(rig, "VIGNETTE")
        assert [shells.fbp_shell_token(mod) for mod in shells.fbp_shell_modifiers(rig)], "Vignette must land as a modifier"
        scene.fbp_preview_native_effect_shells = False
        assert bpy.ops.fbp.add_effect_modifier(effect_id="POSTERIZE") == {"FINISHED"}
        assert geo.fbp_effect_is_active(rig, "POSTERIZE")
        assert len(shells.fbp_shell_modifiers(rig)) == 1, "preview off adds to the stack only"
    finally:
        scene.fbp_preview_native_effect_shells = False
        _remove(rig)
        if not registered:
            bpy.utils.unregister_class(native.FBP_OT_AddEffectModifier)


def test_effect_shells():
    geo, native, shells = _modules()
    scene = bpy.context.scene
    scene.fbp_preview_native_effect_shells = True
    rig = _rig("FBP Native Shells")
    camera = None
    try:
        color_effects, masks = SHELL_EFFECTS[:3], SHELL_EFFECTS[3:]
        _add(geo, rig, *color_effects)
        camera, render = _render_setup("FBP Shell Camera")
        before = render()
        for effect_id in color_effects:
            assert shells.fbp_shell_create(rig, effect_id) is not None, effect_id
        plane = geo._fbp_plane(rig)
        # The shells drive the material without changing the image.
        after = render()
        assert _difference(before, after) < 1e-4, _difference(before, after)

        vignette = shells.fbp_shell_modifier(rig, "VIGNETTE", geo._fbp_effect_ref_parts(_token(geo, rig, "VIGNETTE"))[1])
        strength = next(entry for entry in shells._shell_mapping(vignette.node_group) if entry[1] == "Strength")
        geo._fbp_modifier_input_set(vignette, strength[2], 0.0)
        edited = render()
        assert _difference(after, edited) > 0.01, "a modifier input must change the render"

        _add(geo, rig, *masks)
        before = render()
        for effect_id in masks:
            assert shells.fbp_shell_create(rig, effect_id) is not None, effect_id
        assert _difference(before, render()) < 1e-4, "mask shells must not change the image"
        assert len(shells.fbp_shell_modifiers(rig)) == len(SHELL_EFFECTS)
        assert native.fbp_native_ui_order(rig) == geo._fbp_mixed_effect_tokens(rig)

        gradient = shells.fbp_shell_modifier(rig, "GRADIENT_MASK")
        position = next(entry for entry in shells._shell_mapping(gradient.node_group) if entry[1] == "Position")
        handle = geo._fbp_modifier_input_handle(gradient, position[2])
        handle.value = 0.0
        handle.keyframe_insert("value", frame=1)
        handle.value = 1.0
        handle.keyframe_insert("value", frame=10)
        scene.frame_set(1)
        first = render()
        scene.frame_set(10)
        last = render()
        assert _difference(first, last) > 0.01, "a keyframed modifier input must animate"

        # Links survive Frame By Plane rebuilding the material chain.
        tokens = geo._fbp_mixed_effect_tokens(rig)
        geo.fbp_sort_effect_stacks_transactional([rig], list(reversed(_ids(geo, tokens))))
        geo.fbp_sync_effect_items(rig)
        assert shells.fbp_shell_refresh_links(rig) == 0, "shells lost their material links"

        # Native reorder of a shell reorders the image effects.
        native.fbp_native_remember(rig)
        names = [modifier.name for modifier in plane.modifiers]
        plane.modifiers.move(names.index("Posterize"), 0)
        assert native.fbp_sync_native_modifiers(rig)["reordered"]
        assert _ids(geo, geo._fbp_mixed_effect_tokens(rig))[-1] == "POSTERIZE"

        # Native eye toggle mutes the image effect.
        plane.modifiers["Posterize"].show_viewport = False
        native.fbp_sync_native_modifiers(rig)
        posterize = geo._fbp_effect_ref_parts(_token(geo, rig, "POSTERIZE"))
        assert geo.fbp_effect_visible_state(rig, *posterize) is False

        # Native delete removes the effect and its shell.
        plane.modifiers.remove(plane.modifiers["Square Mask"])
        assert native.fbp_sync_native_modifiers(rig)["removed"]
        assert not geo.fbp_effect_is_active(rig, "SQUARE_MASK")

        # A mesh effect turns the stack mixed: shells stay linked.
        _add(geo, rig, "PAPER_SHARDS")
        geo.fbp_sync_effect_items(rig)
        assert shells.fbp_shell_refresh_links(rig) == 0

        # Save / reopen keeps shells and their links.
        path = WORKDIR / "shells.blend"
        bpy.ops.wm.save_as_mainfile(filepath=str(path))
        bpy.ops.wm.open_mainfile(filepath=str(path))
        rig = bpy.data.objects["FBP Native Shells"]
        assert len(shells.fbp_shell_modifiers(rig)) == len(SHELL_EFFECTS) - 1
        assert shells.fbp_shell_refresh_links(rig) == 0

        # Back to the panel: values go home, no shell nodes remain.
        vignette_instance = geo._fbp_effect_ref_parts(_token(geo, rig, "VIGNETTE"))[1]
        assert shells.fbp_shell_remove(rig, "VIGNETTE", vignette_instance)
        channel = geo.fbp_effect_instance_channel(rig, "VIGNETTE", vignette_instance, "fbp_vignette_strength")
        assert channel is not None and abs(geo.fbp_effect_instance_channel_value(channel)) < 1e-6
        node = geo._fbp_find_shader_effect_nodes_for_rig(rig, "VIGNETTE", instance_id=vignette_instance)[0]
        assert not node.inputs["Strength"].is_linked and abs(node.inputs["Strength"].default_value) < 1e-6
        assert shells.fbp_shell_remove(rig, "GRADIENT_MASK")
        for material in geo._fbp_plane_materials(rig):
            for node in material.node_tree.nodes:
                assert node.get("fbp_shell_attribute", "") != "GRADIENT_MASK"
        camera = None
    finally:
        if camera is not None:
            try:
                bpy.data.objects.remove(camera, do_unlink=True)
            except (ReferenceError, RuntimeError):
                pass
        try:
            _remove(rig)
        except (ReferenceError, NameError):
            pass


TESTS = (
    test_modifier_add_menu, test_native_round_trip, test_mask_panel, test_toggle_foldouts,
    test_add_image_modifier, test_effect_shells,
)

failed = []
try:
    if not INSTALLED_PACKAGE:
        addon.register()
    for test in TESTS:
        try:
            test()
            print(f"FBPTEST {test.__name__}: PASS")
        except Exception:
            traceback.print_exc()
            failed.append(test.__name__)
            print(f"FBPTEST {test.__name__}: FAIL")
finally:
    if not INSTALLED_PACKAGE:
        try:
            addon.unregister()
        except Exception:
            traceback.print_exc()
if failed:
    raise SystemExit(f"native modifiers regression failed: {', '.join(failed)}")
print("FBPTEST native_modifiers_regression: PASS")
