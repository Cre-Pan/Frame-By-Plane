"""Transparent rows must show a real blank frame in every viewport.

Regression: a sequence with Alpha rows as first and last frame showed the
first drawing on those rows in Solid view and Material Preview, because only
a shader mask hid them. After adding a PNG with Import Frame the problem was
easy to see. Transparent rows now point at a fully transparent PNG appended to
the runtime proxy sequence, and older files are repaired on load.
"""

import importlib
import json
import os
import struct
import sys
import tempfile
import traceback
import zlib
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


def write_png(path, width, height, rgba):
    def chunk(kind, data):
        body = kind + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)

    row = b"\x00" + bytes(rgba) * width
    Path(path).write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(row * height))
        + chunk(b"IEND", b"")
    )


def png_alpha_is_zero(path):
    data = Path(path).read_bytes()
    width, height = struct.unpack(">II", data[16:24])
    position = 8
    idat = b""
    while position < len(data):
        length = struct.unpack(">I", data[position:position + 4])[0]
        kind = data[position + 4:position + 8]
        if kind == b"IDAT":
            idat += data[position + 8:position + 8 + length]
        position += 12 + length
    raw = zlib.decompress(idat)
    stride = 1 + 4 * width
    return (width, height), all(
        raw[y * stride + 1 + 4 * x + 3] == 0 for y in range(height) for x in range(width)
    )


def rigs():
    return [obj for obj in bpy.context.scene.objects if bool(getattr(obj, "is_fbp_control", False))]


def select_only(rig, index):
    for row_index, item in enumerate(rig.fbp_images):
        item.is_selected = row_index == index
    rig.fbp_images_index = index


def shown_frames(native, rig):
    """Runtime file number and mask value Blender resolves on each frame."""
    mat = native._native_material_from_rig(rig)
    node = native.fbp_native_sequence_nodes(mat)[0]
    visibility = mat.node_tree.nodes.get("FBP_Native_Frame_Visibility")
    total = sum(max(1, item.duration) for item in rig.fbp_images)
    result = []
    for frame in range(rig.fbp_start_frame - 2, rig.fbp_start_frame + total + 3):
        bpy.context.scene.frame_set(frame)
        user = node.image_user
        number = (frame - user.frame_start + 1) + user.frame_offset
        visible = visibility.outputs[0].default_value > 0.5 if visibility else True
        result.append((frame, number, visible))
    return mat, result


def check_layer(native, rig, label):
    mat, frames = shown_frames(native, rig)
    directory, files = native._runtime_sequence_from_material(mat)
    blank_index = int(mat.get("fbp_native_blank_runtime_index", -1))
    assert 0 <= blank_index == len(files) - 1, (label, blank_index, files)
    blank_path = os.path.join(directory, files[blank_index])
    size, empty = png_alpha_is_zero(blank_path)
    assert empty and size == (6, 4), (label, size, empty)
    base = int(mat.get("fbp_native_frame_number_base", 1))
    blank_number = base + blank_index
    rows = list(rig.fbp_images)
    durations = [max(1, item.duration) for item in rows]
    for frame, number, visible in frames:
        row = native._source_index_at_elapsed(
            frame - rig.fbp_start_frame, len(rows), durations, rig.fbp_loop_mode
        )
        if rows[row].is_empty:
            assert number == blank_number and not visible, (label, frame, number, visible)
        else:
            assert number != blank_number and visible, (label, frame, number, visible)
            shown = os.path.realpath(os.path.join(directory, files[number - base]))
            assert os.path.samefile(shown, rows[row].filepath), (label, frame, shown, rows[row].filepath)
    assert native.fbp_native_rig_contract_issues(rig) == [], native.fbp_native_rig_contract_issues(rig)


if not INSTALLED_PACKAGE:
    addon.register()
temporary = []
try:
    native = importlib.import_module(f"{PACKAGE_NAME}.native_backend")
    operator_import = importlib.import_module(f"{PACKAGE_NAME}.operator_import")
    operator_sequence = importlib.import_module(f"{PACKAGE_NAME}.operator_sequence")
    for operator_class in (
        operator_import.FBP_OT_ImportSequence,
        operator_sequence.FBP_OT_InsertTransparentFrame,
        operator_sequence.FBP_OT_InsertLinkedImageAfterSelected,
        operator_sequence.FBP_OT_ListAction,
    ):
        if getattr(bpy.types, operator_class.__name__, None) is None:
            bpy.utils.register_class(operator_class)
            temporary.append(operator_class)

    workdir = Path(tempfile.mkdtemp(prefix="fbp_blank_"))
    other = Path(tempfile.mkdtemp(prefix="fbp_blank_other_"))
    names = []
    for index in range(3):
        name = f"line art_{index:04d}.png"
        write_png(workdir / name, 6, 4, (60 * (index + 1), 20, 20, 255))
        names.append(name)
    write_png(other / "extra.png", 6, 4, (0, 0, 255, 255))

    assert bpy.ops.fbp.import_sequence(
        'EXEC_DEFAULT', synchronous=True, filepath=str(workdir / names[0]),
        directory=str(workdir), files=[{"name": name} for name in names],
        media_filter='IMAGES',
    ) == {'FINISHED'}
    (rig,) = rigs()
    rig.fbp_loop_mode = 'NONE'
    rig.fbp_start_frame = 120
    for obj in bpy.context.selected_objects:
        obj.select_set(False)
    rig.select_set(True)
    bpy.context.view_layer.objects.active = rig

    # Alpha as last frame, then Alpha moved to the top as first frame.
    select_only(rig, len(rig.fbp_images) - 1)
    assert bpy.ops.fbp.insert_transparent_frame() == {'FINISHED'}
    select_only(rig, 0)
    assert bpy.ops.fbp.insert_transparent_frame() == {'FINISHED'}
    select_only(rig, 1)
    assert bpy.ops.fbp.list_action(action='MOVE_TOP') == {'FINISHED'}
    assert [item.is_empty for item in rig.fbp_images] == [True, False, False, False, True]
    check_layer(native, rig, "alpha first and last")

    # Import Frame from another folder keeps both Alpha rows blank.
    select_only(rig, 1)
    assert bpy.ops.fbp.insert_linked_image_after_selected(
        'EXEC_DEFAULT', rig_name=rig.name, directory=str(other),
        files=[{"name": "extra.png"}], filepath=str(other / "extra.png"),
    ) == {'FINISHED'}
    assert len(rig.fbp_images) == 6
    check_layer(native, rig, "after Import Frame")

    rig.fbp_loop_mode = 'REPEAT'
    check_layer(native, rig, "loop")
    rig.fbp_loop_mode = 'NONE'

    # A file saved before the blank frame existed is repaired on load.
    mat = native._native_material_from_rig(rig)
    source_directory, source_files = native._source_sequence_from_material(mat)
    old_directory, old_files = native._ensure_native_sequence_proxy(source_directory, source_files)
    assert old_files and len(old_files) == len(source_files)
    mat["fbp_native_runtime_sequence_json"] = json.dumps({"directory": old_directory, "files": old_files})
    mat["fbp_native_blank_runtime_index"] = -1
    mat["fbp_native_timing_revision"] = 6
    assert native.fbp_native_rig_contract_issues(rig), "old material must be reported"
    assert native.fbp_repair_native_sequence_timing_scene(bpy.context.scene) == 1
    check_layer(native, rig, "repaired")
    print("FBPTEST transparent_frame_runtime: PASS")
except Exception:
    traceback.print_exc()
    raise
finally:
    for operator_class in reversed(temporary):
        try:
            bpy.utils.unregister_class(operator_class)
        except RuntimeError:
            pass
    if not INSTALLED_PACKAGE:
        try:
            addon.unregister()
        except Exception:
            traceback.print_exc()
