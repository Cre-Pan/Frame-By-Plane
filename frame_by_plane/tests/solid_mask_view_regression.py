"""Masks in Solid view: the plane is cut where its mask stack is empty.

Solid view never runs the plane material, so ``solid_mask_view`` adds a
viewport-only Geometry Nodes modifier that removes the masked-out parts of the
plane. This checks:

* a Shape Mask adds the cut at the end of the stack (shell placement keeps
  it there), viewport only, and the
  evaluated plane keeps only the inside of the mask with exact UVs;
* Invert cuts a hole instead, Subtract follows the mask stack;
* a Feather edit only rewrites node values (no rebuild);
* Factor below 1 and removing the mask remove the cut;
* adding a mask from the effect stack adds the cut on its own (hook);
* the cut survives save/reopen without a rebuild.

Run with Blender 5.2 or 5.3:
    blender -b --factory-startup --python-exit-code 1 \
        --python frame_by_plane/tests/solid_mask_view_regression.py
"""

import importlib
import math
import os
import sys
import tempfile
import time
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

addon = importlib.import_module(PACKAGE_NAME)
WORKDIR = Path(tempfile.mkdtemp(prefix="fbp_solid_mask_view_"))


def _modules():
    return (
        importlib.import_module(f"{PACKAGE_NAME}.geometry_nodes"),
        importlib.import_module(f"{PACKAGE_NAME}.solid_mask_view"),
        importlib.import_module(f"{PACKAGE_NAME}.object_masks"),
    )


def _rig(name):
    builder = importlib.import_module(f"{PACKAGE_NAME}.builder")
    fixture = WORKDIR / "fixture.png"
    if not fixture.is_file():
        image = bpy.data.images.new("FBP Solid Mask Fixture", 64, 32, alpha=True)
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


def _set_input(modifier, name, value):
    for item in modifier.node_group.interface.items_tree:
        if getattr(item, "in_out", "") == "INPUT" and getattr(item, "name", "") == name:
            getattr(modifier.properties.inputs, item.identifier).value = value
            return
    raise KeyError(name)


def _evaluated(plane):
    depsgraph = bpy.context.evaluated_depsgraph_get()
    depsgraph.update()
    evaluated = plane.evaluated_get(depsgraph)
    mesh = evaluated.to_mesh()
    try:
        positions = [vertex.co.copy() for vertex in mesh.vertices]
        uv_layer = mesh.uv_layers.get("UVMap")
        uvs = [
            (positions[loop.vertex_index], tuple(uv_layer.data[loop.index].uv))
            for loop in mesh.loops
        ]
        centers = [polygon.center.copy() for polygon in mesh.polygons]
        names = {attribute.name for attribute in mesh.attributes}
    finally:
        evaluated.to_mesh_clear()
    return positions, uvs, centers, names


def _helper_center(plane, helper):
    bpy.context.view_layer.update()
    return (plane.matrix_world.inverted() @ helper.matrix_world).translation


def _remove(rig):
    for obj in reversed([rig, *rig.children_recursive]):
        try:
            bpy.data.objects.remove(obj, do_unlink=True)
        except (ReferenceError, RuntimeError):
            pass


def test_circle_cut():
    geo, smv, masks = _modules()
    rig = _rig("FBP Solid Circle")
    try:
        _add(geo, rig, "CIRCLE_MASK")
        plane = geo._fbp_plane(rig)
        helper = masks.find_object_mask_helper(rig, "CIRCLE")
        helper.scale = (0.4, 0.4, 1.0)
        helper.location.x = 0.3
        smv.fbp_solid_mask_sync(rig)
        modifier = smv.solid_mask_modifier(plane)
        assert modifier is not None, "a Shape Mask must add the Solid view cut"
        assert plane.modifiers[-1] == modifier, "the cut must be the last modifier"
        assert modifier.show_render is False and modifier.show_viewport is True
        assert smv.fbp_solid_mask_sync(rig) is False, "an unchanged stack must not rebuild"
        # Shell placement keeps the cut last. When both moved their own
        # modifiers to the end, the two syncs reordered the stack forever and
        # the Modifiers panel flickered in Object Mode.
        shells = importlib.import_module(f"{PACKAGE_NAME}.effect_shells")
        shells.fbp_shell_reposition(rig)
        assert plane.modifiers[-1] == modifier, [m.name for m in plane.modifiers]
        order = [m.name for m in plane.modifiers]
        shells.fbp_shell_reposition(rig)
        assert [m.name for m in plane.modifiers] == order, "shell placement must settle"
        assert smv.fbp_solid_mask_sync(rig) is False

        positions, uvs, centers, names = _evaluated(plane)
        center = _helper_center(plane, helper)
        radius = max(
            math.hypot(position.x - center.x, position.y - center.y) for position in positions
        )
        width = max(p.x for p in positions) - min(p.x for p in positions)
        assert 0.2 < width < 1.0, ("the plane was not cut to the circle", width)
        assert radius < width * 0.5 * 1.05, ("vertex outside the circle", radius, width)
        # Snapped edge vertices keep exact UVs (the plane is 2 x 1 at the origin).
        for position, (u, v) in uvs:
            assert abs((position.x + 1.0) * 0.5 - u) < 1.0e-4, (position, u)
            assert abs((position.y + 0.5) - v) < 1.0e-4, (position, v)
        assert not any(name.startswith("fbp_smv_") for name in names), names

        # Feather slides: node values only, the groups stay.
        shell = plane.modifiers["Circle Mask"]
        group = modifier.node_group
        evaluator = smv._cut_evaluator(group)
        node_count = len(evaluator.nodes)
        _set_input(shell, "Feather", 0.4)
        assert smv.fbp_solid_mask_sync(rig) is True
        assert modifier.node_group == group and smv._cut_evaluator(group) == evaluator
        assert len(evaluator.nodes) == node_count
        assert "0.7" in str(evaluator.get("fbp_solid_mask_view_params", "")), evaluator.get(
            "fbp_solid_mask_view_params"
        )

        # Invert: a hole where the circle is (an inverted Feather would keep
        # its faded ring visible, so turn it off first).
        _set_input(shell, "Feather", 0.0)
        _set_input(shell, "Invert", True)
        smv.fbp_solid_mask_sync(rig)
        positions, _uvs, centers, _names = _evaluated(plane)
        inner = [
            point for point in centers
            if math.hypot(point.x - center.x, point.y - center.y) < width * 0.5 * 0.8
        ]
        assert not inner, f"{len(inner)} faces left inside an inverted circle"
        assert min(p.x for p in positions) < -0.95 and max(p.x for p in positions) > 0.95

        # Factor below 1 never reaches 0: nothing to cut.
        _set_input(shell, "Invert", False)
        _set_input(shell, "Factor", 0.5)
        smv.fbp_solid_mask_sync(rig)
        assert smv.solid_mask_modifier(plane) is None, "Factor < 1 must not cut"
        _set_input(shell, "Factor", 1.0)
        smv.fbp_solid_mask_sync(rig)
        assert smv.solid_mask_modifier(plane) is not None

        # Removing the mask removes the cut and its groups.
        group_names = {group.name for group in bpy.data.node_groups}
        assert geo.fbp_remove_effect(rig, "CIRCLE_MASK")
        smv.fbp_solid_mask_sync(rig)
        assert smv.solid_mask_modifier(plane) is None
        left = {
            group.name for group in bpy.data.node_groups
            if group.name.startswith(smv.GROUP_PREFIX)
        } & group_names
        assert not left, left
    finally:
        _remove(rig)


def test_subtract_stack():
    geo, smv, masks = _modules()
    rig = _rig("FBP Solid Subtract")
    try:
        _add(geo, rig, "SQUARE_MASK", "CIRCLE_MASK")
        plane = geo._fbp_plane(rig)
        circle = masks.find_object_mask_helper(rig, "CIRCLE")
        circle.scale = (0.25, 0.25, 1.0)
        circle.location.x = 0.4
        geo.fbp_set_mask_stack_operation(rig, "CIRCLE_MASK", "SUBTRACT")
        tree = smv._plane_mask_tree(plane)
        assert tree is not None and tree["kind"] in {"SUB", "MUL", "MAX"}, tree
        smv.fbp_solid_mask_sync(rig)
        assert smv.solid_mask_modifier(plane) is not None
        positions, _uvs, centers, _names = _evaluated(plane)
        assert positions, "the stack removed the whole plane"
    finally:
        _remove(rig)


def test_hook_adds_cut():
    geo, smv, _masks = _modules()
    rig = _rig("FBP Solid Hook")
    try:
        _add(geo, rig, "SQUARE_MASK")
        plane = geo._fbp_plane(rig)
        dispatch = importlib.import_module(
            f"{PACKAGE_NAME}.runtime_scheduler"
        ).scheduler_dispatcher_callback()
        end = time.monotonic() + 2.0
        while time.monotonic() < end and smv.solid_mask_modifier(plane) is None:
            dispatch()
            time.sleep(0.02)
        assert smv.solid_mask_modifier(plane) is not None, "adding a mask must add the cut"
    finally:
        _remove(rig)


def test_save_reopen():
    geo, smv, masks = _modules()
    rig = _rig("FBP Solid Reopen")
    _add(geo, rig, "CIRCLE_MASK")
    masks.find_object_mask_helper(rig, "CIRCLE").scale = (0.3, 0.3, 1.0)
    smv.fbp_solid_mask_sync(rig)
    plane_name = geo._fbp_plane(rig).name
    before = len(_evaluated(geo._fbp_plane(rig))[0])
    path = WORKDIR / "solid_mask_view.blend"
    bpy.ops.wm.save_as_mainfile(filepath=str(path), copy=True)
    bpy.ops.wm.open_mainfile(filepath=str(path))
    geo, smv, _masks = _modules()
    plane = bpy.data.objects[plane_name]
    rig = bpy.data.objects["FBP Solid Reopen"]
    assert smv.solid_mask_modifier(plane) is not None, "the cut must survive save/reopen"
    assert smv.fbp_solid_mask_sync(rig) is False, "a reopened file must not rebuild the cut"
    # The SDF image is not saved: the Shape Mask runtime rasterizes it again
    # after load and rebinds the material, and the cut follows that binding.
    helper = _masks.find_object_mask_helper(rig, "CIRCLE")
    _masks.refresh_object_mask_geometry(helper, force=True)
    smv.fbp_solid_mask_sync(rig)
    after = len(_evaluated(plane)[0])
    assert after == before, (before, after)


def main():
    if not INSTALLED_PACKAGE:
        addon.register()
    failures = []
    try:
        for test in (test_circle_cut, test_subtract_stack, test_hook_adds_cut, test_save_reopen):
            try:
                test()
                print(f"[PASS] {test.__name__}")
            except Exception:
                traceback.print_exc()
                failures.append(test.__name__)
                print(f"[FAIL] {test.__name__}")
    finally:
        if not INSTALLED_PACKAGE:
            try:
                addon.unregister()
            except Exception:
                traceback.print_exc()
    if failures:
        raise SystemExit(f"Solid view mask regression failed: {', '.join(failures)}")
    print("Solid view mask regression passed")


main()
