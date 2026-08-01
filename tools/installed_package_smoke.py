from __future__ import annotations

import json
import importlib
import os
from pathlib import Path

import bpy


REPORT = Path(os.environ["FBP_PACKAGE_SMOKE_REPORT"]).resolve()
BLEND = Path(os.environ["FBP_PACKAGE_SMOKE_BLEND"]).resolve()
MODULE = "bl_ext.fbp_audit.frame_by_plane"


def main():
    enabled = {str(item.module) for item in bpy.context.preferences.addons}
    if MODULE not in enabled:
        raise RuntimeError(f"Installed extension is not enabled: {MODULE}; enabled={sorted(enabled)}")
    if not hasattr(bpy.ops.fbp, "add_grease_pencil_canvas"):
        raise RuntimeError("Frame By Plane operators are not registered")

    result = bpy.ops.fbp.add_grease_pencil_canvas(
        "EXEC_DEFAULT",
        canvas_name="FBP Installed Package Smoke",
        owner_name="__FREE__",
        enter_draw_mode=False,
    )
    if "FINISHED" not in result:
        raise RuntimeError(f"Grease Pencil canvas creation failed: {result}")
    canvas_name = bpy.context.object.name
    BLEND.parent.mkdir(parents=True, exist_ok=True)
    save_result = bpy.ops.wm.save_as_mainfile(filepath=str(BLEND), check_existing=False)
    if "FINISHED" not in save_result:
        raise RuntimeError(f"Save failed: {save_result}")
    open_result = bpy.ops.wm.open_mainfile(filepath=str(BLEND), load_ui=False)
    if "FINISHED" not in open_result:
        raise RuntimeError(f"Reopen failed: {open_result}")
    canvas = bpy.data.objects.get(canvas_name)
    if canvas is None:
        raise RuntimeError(f"Created canvas was not preserved after reopen: {canvas_name}")
    if not bool(canvas.get("fbp_is_gp_canvas", False)):
        raise RuntimeError("Reopened object lost its Frame By Plane canvas marker")
    if not hasattr(bpy.ops.fbp, "generate_multiplane"):
        raise RuntimeError("Frame By Plane operators disappeared after reopen")

    coordinator = importlib.import_module(f"{MODULE}.generation_transaction")

    def exercise_main_replacement(label, callback):
        owner, refusal = coordinator.acquire_generation(
            bpy.context,
            operator_id=f"fbp.package_smoke_{label}",
            mode=f"Package smoke {label}",
        )
        if owner is None:
            raise RuntimeError(refusal)
        mesh_name = f"FBP Package Smoke {label} Mesh"
        object_name = f"FBP Package Smoke {label} Object"
        mesh = bpy.data.meshes.new(mesh_name)
        obj = bpy.data.objects.new(object_name, mesh)
        bpy.context.scene.collection.objects.link(obj)
        owner.record_datablock(mesh, kind="MESH")
        owner.record_datablock(obj, kind="OBJECT")
        operation_result = callback()
        if "FINISHED" not in operation_result:
            raise RuntimeError(f"{label} failed: {operation_result}")
        if coordinator.active_generation_snapshot():
            raise RuntimeError(f"{label} left an active generation owner")
        if bpy.data.objects.get(object_name) is not None:
            raise RuntimeError(f"{label} preserved transaction-owned partial data")
        return sorted(operation_result)

    open_with_active_owner = exercise_main_replacement(
        "open",
        lambda: bpy.ops.wm.open_mainfile(filepath=str(BLEND), load_ui=False),
    )
    revert_with_active_owner = exercise_main_replacement(
        "revert",
        lambda: bpy.ops.wm.revert_mainfile(),
    )
    new_with_active_owner = exercise_main_replacement(
        "new",
        lambda: bpy.ops.wm.read_homefile(use_empty=True),
    )

    payload = {
        "blender": bpy.app.version_string,
        "module": MODULE,
        "enabled": True,
        "operator_registered": True,
        "created_object": canvas_name,
        "save_result": sorted(save_result),
        "reopen_result": sorted(open_result),
        "object_preserved": True,
        "fbp_marker_preserved": True,
        "active_owner_file_open": open_with_active_owner,
        "active_owner_file_revert": revert_with_active_owner,
        "active_owner_new_file": new_with_active_owner,
        "orphan_owner_after_main_replacement": False,
        "blend_file": str(BLEND),
    }
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"FBP_PACKAGE_SMOKE_REPORT={REPORT}")


if __name__ == "__main__":
    main()
