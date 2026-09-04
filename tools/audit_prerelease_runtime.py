"""Blender-native pre-release probes and reproducible hot-path benchmarks.

Use isolated BLENDER_USER_* directories and --background --factory-startup.
FBP_PRERELEASE_REPORT selects the JSON output; baseline failures are recorded,
not hidden behind Blender's process exit status. No user's Main is modified.
"""
import importlib
import json
import os
from pathlib import Path
import statistics
import sys
import time
import traceback

sys.dont_write_bytecode = True
import bpy

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
REPORT = Path(os.environ['FBP_PRERELEASE_REPORT'])


def timed(callback, repeats=30):
    values = []
    for _ in range(repeats):
        start = time.perf_counter()
        callback()
        values.append((time.perf_counter() - start) * 1000)
    return {'median_ms': statistics.median(values), 'max_ms': max(values), 'samples': repeats}


def probe_index_recovery(index):
    scene = bpy.data.scenes.new('PreRelease Partial Mirror')
    objects = []
    try:
        for name in ('A', 'B'):
            rig = bpy.data.objects.new('PreRelease Rig ' + name, None)
            plane = bpy.data.objects.new('PreRelease Plane ' + name, bpy.data.meshes.new('Plane ' + name))
            scene.collection.objects.link(rig)
            scene.collection.objects.link(plane)
            rig.is_fbp_control = True
            plane.is_fbp_plane = True
            rig.fbp_plane_target = plane
            objects.extend((rig, plane))
        scene.fbp_layers.add().obj = objects[0]
        index.invalidate_scene_index(scene)
        assert len(tuple(index.iter_scene_fbp_rigs(scene))) == 1
        rigs = tuple(index.iter_scene_fbp_rigs(scene, fallback=True))
        index.invalidate_scene_index(scene)
        assert len(tuple(index.iter_scene_fbp_planes(scene))) == 1
        planes = tuple(index.iter_scene_fbp_planes(scene, fallback=True))
        index.invalidate_scene_index(scene)
        scene.fbp_layers.clear()
        assert not tuple(index.iter_scene_fbp_planes(scene))
        from_empty = tuple(index.iter_scene_fbp_planes(scene, fallback=True))
        return {'passed': len(rigs) == len(planes) == len(from_empty) == 2,
                'recovered_rigs': len(rigs), 'recovered_planes': len(planes),
                'recovered_after_empty_mirror_cache': len(from_empty)}
    finally:
        for obj in objects:
            data = obj.data
            bpy.data.objects.remove(obj, do_unlink=True)
            if data is not None:
                bpy.data.meshes.remove(data)
        bpy.data.scenes.remove(scene)


def benchmark_empty_scene_index(index):
    scene = bpy.data.scenes.new('PreRelease Unrelated Objects')
    objects = []
    rows = []
    try:
        for count in (1000, 10000):
            while len(objects) < count:
                obj = bpy.data.objects.new(f'Unrelated_{len(objects):05d}', None)
                scene.collection.objects.link(obj)
                objects.append(obj)
            index.invalidate_scene_index(scene)
            lookup = lambda: tuple(index.iter_scene_fbp_rigs(scene, fallback=True))
            assert not lookup()
            record = {'unrelated_objects': count, 'empty_rig_lookup': timed(lookup)}
            original = index.is_fbp_rig
            visits = [0]
            def counted(obj):
                visits[0] += 1
                return original(obj)
            index.is_fbp_rig = counted
            try:
                for _ in range(10):
                    lookup()
            finally:
                index.is_fbp_rig = original
            record['object_visits_in_10_warm_lookups'] = visits[0]
            rows.append(record)
        return rows
    finally:
        for obj in objects:
            bpy.data.objects.remove(obj, do_unlink=True)
        bpy.data.scenes.remove(scene)


def benchmark_camera(output):
    scene = bpy.data.scenes.new('PreRelease Camera Math')
    try:
        scene.fbp_camera_aspect = '32:9'
        scene.fbp_camera_resolution = 'HD'
        return {'aspect_label_100_reads': timed(lambda: [output.camera_aspect_menu_label(scene) for _ in range(100)])}
    finally:
        bpy.data.scenes.remove(scene)


def probe_scheduler_reentrancy(scheduler):
    """An earlier callback may invalidate guards/deadlines/epoch of its batch."""
    scheduler.clear_tasks()
    saved_guard = scheduler._task_guard_delay
    rows = {}
    try:
        for mode in ('guard', 'deadline', 'epoch'):
            state = {'blocked': False}
            events = []
            scheduler._task_guard_delay = lambda _record: .25 if state['blocked'] else 0.0
            def second():
                events.append('second')
            def first():
                events.append('first')
                if mode == 'guard':
                    state['blocked'] = True
                elif mode == 'deadline':
                    scheduler.schedule_task('audit.second', second, delay=60, restart=True)
                else:
                    scheduler.invalidate_scheduler_epoch()
            assert scheduler.schedule_task('audit.first', first, delay=0)
            assert scheduler.schedule_task('audit.second', second, delay=0)
            scheduler._dispatch()
            rows[mode] = {'passed': events == ['first'], 'events': list(events),
                          'second_pending': scheduler.task_is_scheduled('audit.second')}
            rows[mode]['passed'] &= rows[mode]['second_pending'] == (mode != 'epoch')
            state['blocked'] = False
            if mode == 'deadline' and scheduler.task_is_scheduled('audit.second'):
                scheduler._TASKS['audit.second']['due_at'] = scheduler._now() - 1
            scheduler._dispatch()
            rows[mode]['resumed_events'] = list(events)
            rows[mode]['passed'] &= events == (['first'] if mode == 'epoch' else ['first', 'second'])
            scheduler.clear_tasks()
    finally:
        scheduler._task_guard_delay = saved_guard
    return rows


def main():
    start = time.perf_counter()
    addon = importlib.import_module('frame_by_plane')
    imported = time.perf_counter()
    addon.register()
    registered = time.perf_counter()
    index = importlib.import_module('frame_by_plane.fbp_index')
    output = importlib.import_module('frame_by_plane.camera_output')
    payload = {'blender': bpy.app.version_string, 'build_hash': bpy.app.build_hash.decode(),
               'import_ms': (imported - start) * 1000, 'register_ms': (registered - imported) * 1000}
    try:
        scheduler = importlib.import_module('frame_by_plane.runtime_scheduler')
        payload['scheduler_reentrancy'] = probe_scheduler_reentrancy(scheduler)
        payload['index_recovery'] = probe_index_recovery(index)
        if os.environ.get('FBP_PRERELEASE_BENCHMARK', '1') != '0':
            payload['empty_scene_index'] = benchmark_empty_scene_index(index)
            payload['camera'] = benchmark_camera(output)
        payload['passed'] = (payload['index_recovery']['passed']
                             and all(row['passed'] for row in payload['scheduler_reentrancy'].values()))
    except Exception:
        payload['passed'] = False
        payload['error'] = traceback.format_exc()
    finally:
        addon.unregister()
        REPORT.parent.mkdir(parents=True, exist_ok=True)
        REPORT.write_text(json.dumps(payload, indent=2), encoding='utf-8')
    print(json.dumps(payload, indent=2))
    if os.environ.get('FBP_PRERELEASE_STRICT') == '1' and not payload['passed']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
