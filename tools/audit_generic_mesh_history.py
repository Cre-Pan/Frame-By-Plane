"""Blender 5.2 native Generic Mesh matrix, persistence and Undo regression.

Run in an isolated interactive Blender profile with --factory-startup --python.
FBP_MESH_HISTORY_REPORT selects the report; optional FBP_AUDIT_PACKAGE audits
an enabled installed extension instead of registering the source tree.
"""
import importlib
import json
import os
from pathlib import Path
import sys
import traceback

import bpy

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
REPORT = Path(os.environ['FBP_MESH_HISTORY_REPORT'])
RESULTS = []


def result(name, detail):
    RESULTS.append(dict(name=name, status='PASS', detail=detail))


def override():
    window = bpy.context.window_manager.windows[0]
    area = next(a for a in window.screen.areas if a.type == 'VIEW_3D')
    region = next(r for r in area.regions if r.type == 'WINDOW')
    return bpy.context.temp_override(window=window, area=area, region=region)


def stages():
    package = os.environ.get('FBP_AUDIT_PACKAGE', 'frame_by_plane')
    addon = importlib.import_module(package)
    if package == 'frame_by_plane':
        addon.register()
    else:
        assert package in bpy.context.preferences.addons
    geo = importlib.import_module(package + '.geometry_nodes')
    scope = importlib.import_module(package + '.feature_scope')
    bpy.context.preferences.edit.use_global_undo = True
    bpy.context.scene.fbp_preview_generic_mesh_effects = True
    yield 1.0
    names = []
    for item in geo.fbp_generic_mesh_effect_matrix():
        if not item['supported']:
            continue
        with override():
            bpy.ops.mesh.primitive_grid_add(x_subdivisions=4, y_subdivisions=4)
        obj = bpy.context.object
        obj.name = 'Mesh Audit ' + item['effect_id']
        assert geo.fbp_apply_geometry_effect_to_mesh_object(obj, item['effect_id'], scene=bpy.context.scene), item
        owned = geo._fbp_generic_mesh_owned_effect_modifiers(obj, item['effect_id'])
        assert len(owned) == 1
        assert not geo.fbp_geometry_modifier_52_issues(owned[0][1], item['effect_id'])
        names.append((obj.name, item['effect_id']))
    result('all_supported_generic_effects', names)
    name, effect_id = names[0]
    obj = bpy.data.objects[name]
    modifier = geo._fbp_generic_mesh_owned_effect_modifiers(obj, effect_id)[0][1]
    modifier.name = 'Renamed by Artist'
    uid = modifier.persistent_uid
    artist = obj.modifiers.new(name='Artist shared group', type='NODES')
    artist.node_group = modifier.node_group
    assert not geo.mesh_modifier_metadata(artist)
    duplicate = obj.copy()
    bpy.context.collection.objects.link(duplicate)
    assert len(geo._fbp_generic_mesh_owned_effect_modifiers(duplicate, effect_id)) == 1
    bpy.data.objects.remove(duplicate, do_unlink=True)
    usage = next(r for r in scope.fbp_preview_feature_usage(bpy.context.scene) if r['id'] == 'generic_mesh_effects')
    assert usage['used'], usage
    result('ownership', 'Rename, object duplication, shared artist group and Preview scope detection')
    blend = REPORT.with_suffix('.blend')
    bpy.ops.wm.save_as_mainfile(filepath=str(blend))
    bpy.ops.wm.open_mainfile(filepath=str(blend))
    yield 2.0
    for saved_name, saved_effect in names:
        assert len(geo._fbp_generic_mesh_owned_effect_modifiers(bpy.data.objects[saved_name], saved_effect)) == 1
    obj = bpy.data.objects[name]
    assert geo._fbp_generic_mesh_owned_effect_modifiers(obj, effect_id)[0][1].persistent_uid == uid
    assert not geo.mesh_modifier_metadata(obj.modifiers['Artist shared group'])
    result('save_reopen', 'Every effect retains ownership; artist modifier remains unowned')
    with override():
        bpy.ops.object.select_all(action='DESELECT')
        obj.select_set(True)
        bpy.context.view_layer.objects.active = obj
        bpy.ops.ed.undo_push(message='Generic Mesh baseline')
        assert bpy.ops.fbp.remove_generic_mesh_effects() == {'FINISHED'}
        bpy.ops.ed.undo_push(message='Generic Mesh removed')
    assert not geo._fbp_generic_mesh_owned_effect_modifiers(bpy.data.objects[name], effect_id)
    assert len(bpy.data.objects[name].modifiers) == 1
    with override():
        bpy.ops.ed.undo()
    yield 1.2
    assert len(geo._fbp_generic_mesh_owned_effect_modifiers(bpy.data.objects[name], effect_id)) == 1
    assert len(bpy.data.objects[name].modifiers) == 2
    with override():
        bpy.ops.ed.redo()
    yield 1.2
    assert not geo._fbp_generic_mesh_owned_effect_modifiers(bpy.data.objects[name], effect_id)
    assert len(bpy.data.objects[name].modifiers) == 1
    result('remove_undo_redo', 'Native history restores ownership and leaves the artist modifier intact')


ITERATOR = stages()


def tick():
    try:
        return next(ITERATOR)
    except StopIteration:
        pass
    except Exception:
        RESULTS.append(dict(name='regression', status='FAIL', detail=traceback.format_exc()))
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(dict(passed=all(r['status'] == 'PASS' for r in RESULTS),
                                     results=RESULTS), indent=2), encoding='utf-8')
    bpy.ops.wm.quit_blender()


bpy.app.timers.register(tick, first_interval=.5, persistent=True)
