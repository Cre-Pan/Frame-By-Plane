"""Open isolated wide/narrow camera Properties for desktop visual acceptance."""
import os
from pathlib import Path
import sys

sys.dont_write_bytecode = True
import bpy

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import frame_by_plane

frame_by_plane.register()
bpy.ops.object.camera_add()
scene = bpy.context.scene
scene.camera = bpy.context.object
scene.fbp_camera_aspect = '1:1'
scene.fbp_camera_height = 1000
bpy.ops.fbp.save_camera_format_preset(name='Square 1000')
for area in bpy.context.screen.areas:
    if area.type in {'VIEW_3D', 'PROPERTIES'}:
        area.type = 'PROPERTIES'
        area.spaces.active.context = 'DATA'
        area.tag_redraw()
qa_dir = Path(os.environ['FBP_CAMERA_VISUAL_DIR'])
bpy.ops.wm.save_as_mainfile(filepath=str(qa_dir / 'FBP_Camera_Linked_QA.blend'))


def close_when_requested():
    if (qa_dir / 'close.request').exists():
        bpy.ops.wm.quit_blender()
        return None
    return 1.0


bpy.app.timers.register(close_when_requested, first_interval=1.0)
