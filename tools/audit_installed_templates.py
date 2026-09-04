"""Scripted interactive template/import QA; not manual visual acceptance.

Run with an installed/enabled ZIP in an isolated Blender profile, without
--background. Set FBP_TEMPLATE_REPORT. This script closes its own Blender.
"""
import json
import os
from pathlib import Path
import sys
import traceback

sys.dont_write_bytecode = True
import bpy
from PIL import Image

REPORT = Path(os.environ['FBP_TEMPLATE_REPORT'])
REPORT.parent.mkdir(parents=True, exist_ok=True)
TEMPLATES = ('2D_Animation', 'Storyboarding', '', '2D_Animation', 'Storyboarding')
RESULTS = []


def finish(error=''):
    payload = {'blender': bpy.app.version_string, 'passed': not bool(error),
               'templates': RESULTS, 'error': error}
    REPORT.write_text(json.dumps(payload, indent=2), encoding='utf-8')
    print('FBP_TEMPLATE_REPORT', json.dumps(payload), flush=True)
    bpy.ops.wm.quit_blender()


def inspect_and_import(index):
    try:
        scene = bpy.context.scene
        assert hasattr(scene, 'fbp_project_path') and hasattr(scene, 'fbp_last_directory')
        headers = [(r.width, r.height) for a in bpy.context.screen.areas if a.type == 'VIEW_3D'
                   for r in a.regions if r.type == 'HEADER']
        assert headers and all(w > 0 and h >= 20 for w, h in headers), headers
        if bpy.context.object is not None and bpy.context.object.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
        row = {'template': TEMPLATES[index] or 'General', 'headers': headers, 'imports': []}
        for extension in ('png', 'jpg', 'gif'):
            path = REPORT.parent / ('template-fixture.' + extension)
            if not path.exists():
                first = Image.new('RGB', (48, 32), (70, 130, 200))
                if extension == 'gif':
                    second = Image.new('RGB', (48, 32), (180, 60, 90))
                    first.save(path, save_all=True, append_images=[second], duration=100, loop=0)
                    second.close()
                else:
                    first.save(path)
                first.close()
            before = {obj.session_uid for obj in scene.objects if getattr(obj, 'is_fbp_control', False)}
            result = bpy.ops.fbp.import_single_image('EXEC_DEFAULT', filepath=str(path), directory=str(path.parent))
            generated = [obj for obj in scene.objects if getattr(obj, 'is_fbp_control', False)
                         and obj.session_uid not in before]
            assert result == {'FINISHED'} and len(generated) == 1, (extension, result, len(generated))
            assert generated[0].fbp_plane_target is not None
            row['imports'].append({'format': extension, 'result': 'PASS'})
        RESULTS.append(row)
        if index + 1 == len(TEMPLATES):
            finish()
        else:
            bpy.app.timers.register(lambda: cycle(index + 1), first_interval=.5, persistent=True)
    except Exception:
        finish(traceback.format_exc())
    return None


def cycle(index=0):
    try:
        bpy.ops.wm.read_homefile(app_template=TEMPLATES[index])
        bpy.context.preferences.view.show_splash = False
        bpy.app.timers.register(lambda: inspect_and_import(index), first_interval=1.0, persistent=True)
    except Exception:
        finish(traceback.format_exc())
    return None


bpy.context.preferences.view.show_splash = False
bpy.app.timers.register(cycle, first_interval=.5, persistent=True)
