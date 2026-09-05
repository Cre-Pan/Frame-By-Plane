from __future__ import annotations

import importlib
import importlib.util
import json
import math
import os
import sys
import time
import tracemalloc
import traceback
import tomllib
from pathlib import Path

import bpy

# Blender's embedded Python can ignore PYTHONDONTWRITEBYTECODE during add-on
# loading. Keep release-gate runs from dirtying the audited source tree.
sys.dont_write_bytecode = True

SOURCE = Path(os.environ["FBP_TEST_SOURCE"]).resolve()
REPORT = Path(os.environ["FBP_TEST_REPORT"]).resolve()
WORKDIR = Path(os.environ.get("FBP_TEST_WORKDIR", REPORT.parent)).resolve()
SUITE = os.environ.get("FBP_TEST_SUITE", "background")
RUN_ID = str(os.environ.get("FBP_TEST_RUN_ID", "") or "")
PACKAGE = "frame_by_plane"
RESULTS = []


def _source_release_version():
    try:
        payload = tomllib.loads((SOURCE / "blender_manifest.toml").read_text(encoding="utf-8"))
        value = str(payload.get("version", "") or "").strip()
        parts = tuple(int(part) for part in value.split("."))
        if len(parts) == 3:
            return value, parts
    except (OSError, TypeError, ValueError, tomllib.TOMLDecodeError):
        pass
    return "0.0.0", (0, 0, 0)


RELEASE_VERSION, RELEASE_PARTS = _source_release_version()
RELEASE_TOKEN = RELEASE_VERSION.replace(".", "_")
if RELEASE_PARTS[2] > 0:
    _previous_parts = (RELEASE_PARTS[0], RELEASE_PARTS[1], RELEASE_PARTS[2] - 1)
elif RELEASE_PARTS[1] > 0:
    _previous_parts = (RELEASE_PARTS[0], RELEASE_PARTS[1] - 1, 999)
else:
    _previous_parts = (max(0, RELEASE_PARTS[0] - 1), 999, 999)
PREVIOUS_RELEASE = ".".join(str(part) for part in _previous_parts)


class SkipTest(RuntimeError):
    pass


def record(name, callback):
    started = time.perf_counter()
    try:
        detail = callback()
        RESULTS.append({
            "name": name,
            "status": "PASS",
            "seconds": time.perf_counter() - started,
            "detail": detail or "",
        })
    except SkipTest as exc:
        RESULTS.append({
            "name": name,
            "status": "SKIP",
            "seconds": time.perf_counter() - started,
            "detail": str(exc),
        })
    except Exception as exc:
        RESULTS.append({
            "name": name,
            "status": "FAIL",
            "seconds": time.perf_counter() - started,
            "error": str(exc),
            "traceback": traceback.format_exc(),
        })
    finally:
        _write_checkpoint()


def _write_json_atomic(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    temp.replace(path)


def _write_checkpoint():
    """Keep completed results available even if Blender itself crashes later."""
    payload = {
        "suite": SUITE,
        "run_id": RUN_ID,
        "blender": bpy.app.version_string,
        "addon_release": RELEASE_VERSION,
        "results": RESULTS,
        "passed": False,
        "in_progress": True,
        "failed": sum(item["status"] == "FAIL" for item in RESULTS),
        "skipped": sum(item["status"] == "SKIP" for item in RESULTS),
        "workdir": str(WORKDIR),
    }
    try:
        _write_json_atomic(REPORT, payload)
    except OSError:
        # A diagnostic checkpoint must never change the test result.
        pass


def reset_file():
    bpy.ops.wm.read_factory_settings(use_empty=True)


def _drop_package_modules():
    for name in sorted(
        (name for name in sys.modules if name == PACKAGE or name.startswith(PACKAGE + ".")),
        key=lambda value: value.count("."),
        reverse=True,
    ):
        sys.modules.pop(name, None)


def load_addon_module(*, fresh=False):
    if fresh:
        _drop_package_modules()
    existing = sys.modules.get(PACKAGE)
    if existing is not None:
        return existing
    spec = importlib.util.spec_from_file_location(
        PACKAGE,
        SOURCE / "__init__.py",
        submodule_search_locations=[str(SOURCE)],
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not create the Frame By Plane package spec")
    module = importlib.util.module_from_spec(spec)
    sys.modules[PACKAGE] = module
    spec.loader.exec_module(module)
    return module


def reload_addon_module_in_place(module):
    """Re-execute the package while preserving its module identity.

    ``importlib.reload`` asks the import system to rediscover the package by
    name.  That makes the regression suite depend on the extracted source
    directory being named exactly ``frame_by_plane``, even though the suite's
    direct loader intentionally supports arbitrary checkout and artifact paths.
    Blender's extension updater already has the package object and executes the
    package entry point in place, so rebuild the explicit source spec here too.
    """
    spec = importlib.util.spec_from_file_location(
        PACKAGE,
        SOURCE / "__init__.py",
        submodule_search_locations=[str(SOURCE)],
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not recreate the Frame By Plane package spec")
    module.__spec__ = spec
    module.__loader__ = spec.loader
    module.__file__ = str(SOURCE / "__init__.py")
    module.__package__ = PACKAGE
    module.__path__ = [str(SOURCE)]
    spec.loader.exec_module(module)
    return module


def import_addon(*, fresh=False):
    module = load_addon_module(fresh=fresh)
    module.register()
    return module


def unregister_addon(module):
    module.unregister()


def test_version():
    assert bpy.app.version[:2] == (5, 2), bpy.app.version_string
    return bpy.app.version_string


def test_release_sync(_module):
    constants = importlib.import_module(f"{PACKAGE}.constants")
    policy = importlib.import_module(f"{PACKAGE}.support_policy")
    assert constants.FBP_VERSION_STRING == RELEASE_VERSION, (constants.FBP_VERSION_STRING, RELEASE_VERSION)
    assert policy.FBP_LTS_TARGET_VERSION == RELEASE_VERSION, (policy.FBP_LTS_TARGET_VERSION, RELEASE_VERSION)
    assert constants.FBP_FEEDBACK_RELEASE == RELEASE_VERSION
    return RELEASE_VERSION


def test_control_panel_and_camera_contract(module):
    """Exercise panel placement switches and live camera proxy callbacks."""
    del module
    ui = importlib.import_module(f"{PACKAGE}.ui")

    assert ui.FBP_PT_ImagePlaneData.bl_context == "data"
    assert not getattr(ui.FBP_PT_ImagePlaneData, "bl_parent_id", "")
    assert ui.FBP_PT_ImagePlaneData in ui.ui_classes
    assert ui.FBP_PT_ToolSequence in ui.ui_classes
    assert ui.FBP_PT_FrameByPlaneSidebarAnchor in ui.ui_classes
    assert ui.FBP_PT_ToolSidebarAnchor in ui.ui_classes
    assert ui.FBP_PT_LayerStack.bl_parent_id == ui.FBP_PT_FrameByPlaneSidebarAnchor.bl_idname
    assert ui.FBP_PT_ToolLayerStack.bl_parent_id == ui.FBP_PT_ToolSidebarAnchor.bl_idname
    assert ui.FBP_PT_LayerStack in ui.FBP_PT_ToolLayerStack.__mro__[1:]
    assert ui.FBP_PT_Sequence in ui.FBP_PT_ToolSequence.__mro__[1:]

    class FakePreferences:
        show_control_panel_properties = True
        show_control_panel_n_panel = True
        show_panel_layers = True
        show_panel_grease_pencil = True
        show_panel_layer_settings = True

    original_preferences = ui._fbp_ui_preferences
    original_context_available = ui._fbp_tool_ui_context_available
    original_active_plane = ui._fbp_active_plane_context
    original_scene_gp = ui._fbp_scene_has_drawing_gp
    try:
        ui._fbp_ui_preferences = lambda _context: FakePreferences()
        ui._fbp_tool_ui_context_available = lambda _context: True
        ui._fbp_active_plane_context = lambda _context: bpy.context.object
        ui._fbp_scene_has_drawing_gp = lambda _context: True

        mesh = bpy.data.meshes.new("FBP Panel Contract Mesh")
        obj = bpy.data.objects.new("FBP Panel Contract Rig", mesh)
        bpy.context.scene.collection.objects.link(obj)
        bpy.context.view_layer.objects.active = obj
        obj.select_set(True)
        assert ui.FBP_PT_LayerStack.poll(bpy.context)
        assert ui.FBP_PT_GreasePencilStack.poll(bpy.context)
        assert ui.FBP_PT_Sequence.poll(bpy.context)
        assert ui.FBP_PT_ToolLayerStack.poll(bpy.context)
        assert ui.FBP_PT_ToolGreasePencilStack.poll(bpy.context)
        assert ui.FBP_PT_ToolSequence.poll(bpy.context)
        assert ui.FBP_PT_ImagePlaneData.poll(bpy.context)
    finally:
        ui._fbp_ui_preferences = original_preferences
        ui._fbp_tool_ui_context_available = original_context_available
        ui._fbp_active_plane_context = original_active_plane
        ui._fbp_scene_has_drawing_gp = original_scene_gp

    bpy.ops.object.select_all(action='DESELECT')
    bpy.ops.object.camera_add()
    camera_object = bpy.context.object
    camera_data = camera_object.data
    scene = bpy.context.scene
    scene.camera = camera_object

    scene.fbp_camera_projection = 'ORTHO'
    assert camera_data.type == 'ORTHO'
    scene.fbp_camera_ortho_scale = 7.25
    assert math.isclose(camera_data.ortho_scale, 7.25)
    scene.fbp_camera_projection = 'PERSP'
    assert camera_data.type == 'PERSP'
    scene.fbp_camera_lens = 63.0
    assert math.isclose(camera_data.lens, 63.0)
    scene.fbp_camera_clip_start = 0.25
    scene.fbp_camera_clip_end = 725.0
    assert math.isclose(camera_data.clip_start, 0.25)
    assert math.isclose(camera_data.clip_end, 725.0)
    scene.fbp_cam_ratio = 'HD_16_9'
    assert (scene.render.resolution_x, scene.render.resolution_y) == (1920, 1080)

    return {
        "data_panel": ui.FBP_PT_ImagePlaneData.bl_idname,
        "tool_panels": [
            ui.FBP_PT_ToolLayerStack.bl_idname,
            ui.FBP_PT_ToolGreasePencilStack.bl_idname,
            ui.FBP_PT_ToolSequence.bl_idname,
        ],
        "n_panel_root_panels": 1,
        "camera_projection": camera_data.type,
        "camera_lens": camera_data.lens,
        "camera_ratio": [scene.render.resolution_x, scene.render.resolution_y],
    }


def test_camera_output_format(_module):
    output = importlib.import_module(f"{PACKAGE}.camera_output")
    core = importlib.import_module(f"{PACKAGE}.core")
    scene = bpy.data.scenes.new("FBP Camera Output Regression")
    try:
        scene.fbp_camera_aspect = '16:9'
        checked = {}
        for key, longest in output.RESOLUTION_PRESETS[1:]:
            scene.fbp_camera_resolution = key
            expected = output.resolution_for_aspect(output.parse_aspect_ratio('16:9'), longest)
            assert (scene.render.resolution_x, scene.render.resolution_y) == expected
            assert scene.fbp_camera_resolution == key
            checked[key] = expected
        scene.fbp_camera_aspect = '9:16'
        assert (scene.render.resolution_x, scene.render.resolution_y) == (7680, 4320)
        output.swap_camera_dimensions(scene)
        assert (scene.render.resolution_x, scene.render.resolution_y) == (4320, 7680)
        scene.fbp_camera_aspect = '1:1'
        assert scene.render.resolution_x == scene.render.resolution_y == 7680
        assert output.swap_camera_dimensions(scene) is False
        scene.fbp_camera_resolution = 'CUSTOM'
        scene.fbp_camera_fit_source_aspect = True
        scene.fbp_camera_dimensions_linked = False
        scene.fbp_camera_width = 1234
        scene.fbp_camera_height = 987
        core.apply_camera_ratio_settings(scene)
        assert (scene.render.resolution_x, scene.render.resolution_y) == (1234, 987)
        assert scene.fbp_camera_aspect == '1234:987'
        assert scene.fbp_cam_ratio == 'CUSTOM'

        assert len(output.ASPECT_PRESETS) == 10
        previous_ratio = 0
        scene.render.resolution_percentage = 37
        for key, label in output.ASPECT_PRESETS:
            with bpy.context.temp_override(scene=scene):
                assert 'FINISHED' in bpy.ops.fbp.set_camera_aspect(preset=key)
            ratio = output.parse_aspect_ratio(scene.fbp_camera_aspect)
            assert ratio >= 1 and ratio > previous_ratio
            assert output.camera_aspect_menu_label(scene) == label
            assert scene.render.resolution_percentage == 37
            original = scene.render.resolution_x, scene.render.resolution_y
            output.swap_camera_dimensions(scene)
            assert (scene.render.resolution_x, scene.render.resolution_y) == original[::-1]
            assert output.camera_aspect_menu_label(scene) == label
            output.swap_camera_dimensions(scene)
            assert (scene.render.resolution_x, scene.render.resolution_y) == original
            previous_ratio = ratio
        scene.fbp_camera_resolution = 'HD'
        scene.fbp_camera_aspect = '4:5'
        assert (scene.render.resolution_x, scene.render.resolution_y) == (1920, 1536)
        assert output.camera_aspect_menu_label(scene) == '4:5'

        class Layout:
            def __init__(self, captured, parent=None, align=False):
                self.captured, self.parent, self.align = captured, parent, align
            def row(self, **kwargs):
                return Layout(self.captured, self, kwargs.get('align', False))
            column = row
            def prop(self, owner, key, **kwargs):
                self.captured[key] = (self, kwargs)
            def label(self, **kwargs):
                self.captured['label_icon'] = kwargs.get('icon')
            def menu(self, identifier, **kwargs):
                self.captured['menu'] = (identifier, kwargs.get('text'))
            def operator(self, identifier, **kwargs):
                assert self.align is False
                self.captured['operator'] = (identifier, kwargs.get('icon'), kwargs.get('text'))
            def popover(self, **kwargs):
                self.captured['presets'] = kwargs
        for resolution in ('HD', 'CUSTOM'):
            scene.fbp_camera_resolution = resolution
            for width in (320, 800):
                for linked in (False, True):
                    scene.fbp_camera_dimensions_linked = linked
                    captured = {}
                    output.draw_camera_output(Layout(captured), scene, available_width=width)
                    assert captured['menu'] == ('FBP_MT_camera_aspect', '4:5')
                    assert captured['label_icon'] == 'IMAGE_BACKGROUND'
                    assert captured['operator'] == ('fbp.swap_camera_dimensions', 'RENDER_SWAP_DIMENSIONS', '')
                    assert captured['presets']['panel'] == 'FBP_PT_camera_format_presets'
                    pixel_row = captured['fbp_camera_width'][0]
                    assert pixel_row is captured['fbp_camera_height'][0]
                    assert pixel_row is captured['fbp_camera_dimensions_linked'][0]
                    assert pixel_row.align is False
                    resolution_row = captured['fbp_camera_resolution'][0]
                    assert (pixel_row.parent is resolution_row) == (width >= 540)
                    assert captured['fbp_camera_width'][1]['text'] == 'Width (px)'
                    assert captured['fbp_camera_height'][1]['text'] == 'Height (px)'
                    assert captured['fbp_camera_dimensions_linked'][1]['icon'] == ('LINKED' if linked else 'UNLINKED')
                    assert set(captured) == {'menu', 'label_icon', 'operator', 'presets',
                        'fbp_camera_resolution', 'fbp_camera_width', 'fbp_camera_height',
                        'fbp_camera_dimensions_linked'}
        icons = bpy.types.UILayout.bl_rna.functions['operator'].parameters['icon'].enum_items
        assert {'IMAGE_BACKGROUND', 'RENDER_SWAP_DIMENSIONS', 'LINKED', 'UNLINKED', 'PRESET'} <= set(icons.keys())
        scene.render.resolution_x = 1200
        scene.render.resolution_y = 800
        assert scene.fbp_camera_aspect == '3:2'
        assert scene.fbp_camera_resolution == 'CUSTOM'
        scene.render.pixel_aspect_x = 2.0
        scene.render.pixel_aspect_y = 1.0
        scene.fbp_camera_aspect = '16:9'
        original = (scene.render.resolution_x, scene.render.resolution_y,
                    scene.render.pixel_aspect_x, scene.render.pixel_aspect_y)
        output.swap_camera_dimensions(scene)
        assert scene.fbp_camera_aspect == '9:16'
        assert scene.render.pixel_aspect_x == 1.0 and scene.render.pixel_aspect_y == 2.0
        output.swap_camera_dimensions(scene)
        assert (scene.render.resolution_x, scene.render.resolution_y,
                scene.render.pixel_aspect_x, scene.render.pixel_aspect_y) == original
        return {'presets': checked, 'aspect_presets': len(output.ASPECT_PRESETS),
                'landscape_default_and_swap': True, 'responsive_pixel_fields': True,
                'native_icons_valid': True, 'non_square_pixel_swap': True,
                'native_output_edits_reflected': True, 'draw_read_only': True}
    finally:
        bpy.data.scenes.remove(scene)


def test_camera_pixels_and_presets(_module):
    output = importlib.import_module(f"{PACKAGE}.camera_output")
    scene = bpy.data.scenes.new('FBP Linked Camera Regression')
    loaded = None
    try:
        def size():
            return scene.render.resolution_x, scene.render.resolution_y
        assert scene.fbp_camera_dimensions_linked is True
        scene.fbp_camera_aspect = '1:1'
        scene.fbp_camera_height = 1000
        assert size() == (1000, 1000)
        scene.fbp_camera_width = 1200
        assert size() == (1200, 1200)
        assert scene.fbp_camera_resolution == 'CUSTOM'
        assert output.camera_aspect_menu_label(scene) == '1:1'
        scene.fbp_camera_aspect = '16:9'
        scene.fbp_camera_width = 1920
        assert size() == (1920, 1080)
        scene.fbp_camera_height = 720
        assert size() == (1280, 720)
        output.swap_camera_dimensions(scene)
        scene.fbp_camera_height = 1920
        assert size() == (1080, 1920)
        scene.fbp_camera_dimensions_linked = False
        scene.fbp_camera_width = 1000
        assert size() == (1000, 1920)
        assert output.camera_aspect_menu_label(scene) == 'Custom'
        scene.fbp_camera_dimensions_linked = True
        assert size() == (1000, 1920)  # Re-link never resizes the image.
        scene.fbp_camera_height = 960
        assert size() == (500, 960)
        assert output.camera_aspect_menu_label(scene) == 'Custom'
        scene.fbp_camera_aspect = '1:1'
        assert output.camera_aspect_menu_label(scene) == '1:1'

        scene.render.pixel_aspect_x = 2.0
        scene.fbp_camera_aspect = '16:9'
        scene.fbp_camera_height = 1080
        assert size() == (960, 1080)
        scene.fbp_camera_width = 1920
        assert size() == (1920, 2160)
        # Reject a linked overflow/underflow atomically, with a visible error.
        scene.render.pixel_aspect_x = 1.0
        scene.fbp_camera_aspect = '32:9'
        original = size()
        scene.fbp_camera_height = 65536
        assert size() == original and scene.get(output._ERROR_KEY)
        scene.fbp_camera_width = 4
        assert size() == original and scene.get(output._ERROR_KEY)
        scene.fbp_camera_width = 1920
        assert size() == (1920, 540) and not scene.get(output._ERROR_KEY)

        scene.render.resolution_percentage = 37
        scene.fbp_camera_dimensions_linked = False
        scene.fbp_camera_width = 1234
        scene.fbp_camera_height = 987
        with bpy.context.temp_override(scene=scene):
            assert bpy.ops.fbp.save_camera_format_preset(name='My Format') == {'FINISHED'}
            assert bpy.ops.fbp.save_camera_format_preset(name='My Format') == {'FINISHED'}
            assert [p.name for p in scene.fbp_camera_format_presets] == ['My Format', 'My Format 2']
            scene.fbp_camera_aspect = '16:9'
            scene.fbp_camera_resolution = 'HD'
            scene.fbp_camera_dimensions_linked = True
            assert bpy.ops.fbp.apply_camera_format_preset(index=0) == {'FINISHED'}
            assert size() == (1234, 987)
            assert not scene.fbp_camera_dimensions_linked
            assert output.camera_aspect_menu_label(scene) == 'Custom'
            assert scene.render.resolution_percentage == 37
            assert bpy.ops.fbp.apply_camera_format_preset(index=99) == {'CANCELLED'}
            assert bpy.ops.fbp.remove_camera_format_preset(index=1) == {'FINISHED'}
            assert bpy.ops.fbp.remove_camera_format_preset(index=99) == {'CANCELLED'}
        # Presets persist with scene data rather than a process-local cache.
        preset_file = WORKDIR / 'camera-format-presets.blend'
        bpy.data.libraries.write(str(preset_file), {scene})
        with bpy.data.libraries.load(str(preset_file), link=False) as (source, target):
            target.scenes = [scene.name]
        loaded = target.scenes[0]
        assert loaded.fbp_camera_format_presets[0].name == 'My Format'
        assert loaded.fbp_camera_format_presets[0].width == 1234
        assert loaded.fbp_camera_format_presets[0].linked is False
        return {'linked_default': True, 'both_axes_and_orientations': True,
                'unlinked_custom_aspect': True, 'non_square_pixels': True,
                'bounds_atomic': True, 'preset_save_apply_remove_persistence': True}
    finally:
        if loaded is not None:
            bpy.data.scenes.remove(loaded)
        bpy.data.scenes.remove(scene)


def _owned_handler_count(handler_list, callback_name, module_suffix):
    return sum(
        1
        for callback in tuple(handler_list)
        if str(getattr(callback, "__name__", "")) == callback_name
        and str(getattr(callback, "__module__", "")).endswith(
            f".{module_suffix}"
        )
    )


def test_effect_evolution_handler_lifecycle(module):
    lifecycle = importlib.import_module(f"{PACKAGE}.lifecycle")
    geometry = importlib.import_module(f"{PACKAGE}.geometry_nodes")
    callback = geometry.fbp_effect_evolve_frame_change
    callback_name = callback.__name__

    def counts():
        return {
            "pre": _owned_handler_count(
                bpy.app.handlers.frame_change_pre,
                callback_name,
                "geometry_nodes",
            ),
            "post": _owned_handler_count(
                bpy.app.handlers.frame_change_post,
                callback_name,
                "geometry_nodes",
            ),
        }

    assert counts() == {"pre": 0, "post": 1}, counts()
    initial_audit = lifecycle.lifecycle_audit(bpy.context.scene, repair=False)
    assert not [
        issue
        for issue in initial_audit["issues"]
        if callback_name in issue
    ], initial_audit

    # Simulate an interrupted older Repair that left callbacks in both phases.
    bpy.app.handlers.frame_change_pre.extend((callback, callback))
    stale_counts = counts()
    assert stale_counts == {"pre": 2, "post": 1}, stale_counts
    stale_audit = lifecycle.lifecycle_audit(bpy.context.scene, repair=False)
    assert any(callback_name in issue for issue in stale_audit["issues"]), stale_audit

    repaired = lifecycle.lifecycle_audit(bpy.context.scene, repair=True)
    assert counts() == {"pre": 0, "post": 1}, (counts(), repaired)
    assert not [
        issue
        for issue in lifecycle.lifecycle_audit(bpy.context.scene, repair=False)["issues"]
        if callback_name in issue
    ]

    module.unregister()
    assert counts() == {"pre": 0, "post": 0}, counts()
    module.register()
    assert counts() == {"pre": 0, "post": 1}, counts()
    return {
        "phase": "frame_change_post",
        "before_repair": stale_counts,
        "after_repair": counts(),
    }


def _addon_handler_total():
    total = 0
    for list_name in dir(bpy.app.handlers):
        if list_name.startswith("_"):
            continue
        handler_list = getattr(bpy.app.handlers, list_name, None)
        if not isinstance(handler_list, list):
            continue
        total += sum(
            1
            for callback in tuple(handler_list)
            if str(getattr(callback, "__module__", "")).startswith(f"{PACKAGE}.")
        )
    return total


def test_registration_failure_transaction(module):
    runtime = importlib.import_module(f"{PACKAGE}.runtime")
    scheduler = importlib.import_module(f"{PACKAGE}.runtime_scheduler")
    lifecycle = importlib.import_module(f"{PACKAGE}.lifecycle")
    properties_module = importlib.import_module(f"{PACKAGE}.properties")

    module.unregister()
    assert runtime.fbp_registration_state() == "INACTIVE"
    assert not runtime.fbp_registration_busy()

    ordered_modules = []
    original_unregister = {}
    target_index = tuple(module.modules).index(properties_module)
    previous_modules = [
        item
        for item in tuple(module.modules)[:target_index]
        if callable(getattr(item, "register", None))
        and callable(getattr(item, "unregister", None))
    ]
    tracked_modules = previous_modules + [properties_module]
    for tracked in tracked_modules:
        callback = tracked.unregister
        original_unregister[tracked] = callback

        def observed_unregister(callback=callback, name=tracked.__name__):
            ordered_modules.append(name)
            return callback()

        tracked.unregister = observed_unregister

    original_properties_register = properties_module.register

    def forced_register_failure():
        raise RuntimeError("forced registration transaction failure")

    properties_module.register = forced_register_failure
    try:
        try:
            module.register()
        except RuntimeError as exc:
            assert "forced registration transaction failure" in str(exc)
        else:
            raise AssertionError("Injected register failure did not propagate")
    finally:
        properties_module.register = original_properties_register
        for tracked, callback in original_unregister.items():
            tracked.unregister = callback

    expected_order = [properties_module.__name__] + [
        item.__name__ for item in reversed(previous_modules)
    ]
    assert ordered_modules == expected_order, (ordered_modules, expected_order)
    assert runtime.fbp_registration_state() == "FAILED"
    assert not runtime.fbp_registration_busy()
    assert _addon_handler_total() == 0, _addon_handler_total()
    rollback_metrics = scheduler.scheduler_metrics()
    assert rollback_metrics["pending"] == 0, rollback_metrics
    assert not rollback_metrics["dispatcher_registered"], rollback_metrics

    module.register()
    assert runtime.fbp_registration_state() == "ACTIVE"
    assert not runtime.fbp_registration_busy()
    assert not lifecycle.lifecycle_audit(bpy.context.scene, repair=False)["issues"]

    original_scheduler_unregister = scheduler.unregister

    def forced_unregister_failure():
        raise RuntimeError("forced teardown transaction failure")

    scheduler.unregister = forced_unregister_failure
    try:
        module.unregister()
    finally:
        scheduler.unregister = original_scheduler_unregister
    assert runtime.fbp_registration_state() == "FAILED_UNSAFE"
    assert runtime.fbp_registration_busy()
    teardown_metrics = scheduler.scheduler_metrics()
    assert teardown_metrics["pending"] == 0, teardown_metrics
    assert not teardown_metrics["dispatcher_registered"], teardown_metrics

    # The failed scheduler unregister retained no work; restore its normal
    # cleanup before enabling the add-on again in this same Blender session.
    original_scheduler_unregister()
    module.register()
    assert runtime.fbp_registration_state() == "ACTIVE"
    assert not runtime.fbp_registration_busy()
    assert not lifecycle.lifecycle_audit(bpy.context.scene, repair=False)["issues"]
    return {
        "register_failure_state": "FAILED",
        "rollback_modules": len(ordered_modules),
        "handlers_after_rollback": 0,
        "teardown_failure_state": "FAILED_UNSAFE",
        "reenabled": True,
    }


def test_generation_timer_deadline(_module):
    operator_common = importlib.import_module(f"{PACKAGE}.operator_common")

    class Probe:
        pass

    operator = Probe()
    operator._fbp_generation_cancelled = False
    operator._fbp_generation_started = False
    operator._fbp_generation_deadline = 100.20

    event = Probe()
    event.type = "TIMER"
    owned_timer = object()
    event.timer = owned_timer
    operator._fbp_generation_timer = owned_timer

    foreign_event = Probe()
    foreign_event.type = "TIMER"
    foreign_event.timer = object()
    assert not operator_common._fbp_claim_generation_start(
        operator, foreign_event, now=100.20
    )

    assert not operator_common._fbp_claim_generation_start(
        operator, event, now=100.01
    )
    assert not operator._fbp_generation_started
    assert operator_common._fbp_claim_generation_start(
        operator, event, now=100.20
    )
    assert operator._fbp_generation_started
    assert not operator_common._fbp_claim_generation_start(
        operator, event, now=100.21
    )

    cancelled = Probe()
    cancelled._fbp_generation_cancelled = True
    cancelled._fbp_generation_started = False
    cancelled._fbp_generation_deadline = 0.0
    assert not operator_common._fbp_claim_generation_start(
        cancelled, event, now=101.0
    )

    non_timer = Probe()
    non_timer.type = "MOUSEMOVE"
    waiting = Probe()
    waiting._fbp_generation_cancelled = False
    waiting._fbp_generation_started = False
    waiting._fbp_generation_deadline = 0.0
    assert not operator_common._fbp_claim_generation_start(
        waiting, non_timer, now=101.0
    )

    chunk = Probe()
    chunk._fbp_generation_timer = owned_timer
    chunk._fbp_generation_next_due = 200.0
    chunk._fbp_generation_advancing = False
    assert not operator_common._fbp_generation_chunk_is_due(
        chunk, foreign_event, now=200.5
    )
    assert not operator_common._fbp_generation_chunk_is_due(
        chunk, event, now=199.999
    )
    assert operator_common._fbp_generation_chunk_is_due(
        chunk, event, now=200.0
    )
    chunk._fbp_generation_advancing = True
    assert not operator_common._fbp_generation_chunk_is_due(
        chunk, event, now=201.0
    )
    return {
        "deadline_seconds": 0.20,
        "foreign_timer_before_deadline": "ignored",
        "single_claim": True,
        "cancelled_claim": False,
        "foreign_1ms_timer_ignored": True,
        "one_step_per_deadline": True,
        "reentrancy_guard": True,
    }


def test_generation_progress_and_rollback(_module):
    operator_import = importlib.import_module(f"{PACKAGE}.operator_import")

    class Probe:
        pass

    operator = Probe()

    def steps():
        yield {"completed": 0, "total": 2, "step": "Prepare", "cancellable": True}
        yield {"completed": 1, "total": 2, "step": "Build", "cancellable": False}
        return {'FINISHED'}

    try:
        result = operator_import._fbp_drain_generation_iterator(
            bpy.context,
            operator,
            steps(),
        )
    finally:
        bpy.context.window_manager.progress_end()
    assert result == {'FINISHED'}, result
    assert operator._fbp_generation_progress_completed == 1
    assert operator._fbp_generation_progress_total == 2

    names = {
        "object": "FBP Rollback Test Object",
        "mesh": "FBP Rollback Test Mesh",
        "material": "FBP Rollback Test Material",
        "image": "FBP Rollback Test Image",
        "nodes": "FBP Rollback Test Nodes",
    }
    before = {
        "objects": len(bpy.data.objects),
        "meshes": len(bpy.data.meshes),
        "materials": len(bpy.data.materials),
        "images": len(bpy.data.images),
        "node_groups": len(bpy.data.node_groups),
    }
    snapshot = operator_import._fbp_multiplane_runtime_snapshot(bpy.context)
    try:
        mesh = bpy.data.meshes.new(names["mesh"])
        obj = bpy.data.objects.new(names["object"], mesh)
        bpy.context.scene.collection.objects.link(obj)
        obj.is_fbp_control = True
        material = bpy.data.materials.new(names["material"])
        mesh.materials.append(material)
        bpy.data.images.new(names["image"], width=8, height=8)
        bpy.data.node_groups.new(names["nodes"], "GeometryNodeTree")
        assert operator_import._fbp_rollback_unexpected_multiplane_build(
            bpy.context,
            snapshot,
        )
        after = {
            "objects": len(bpy.data.objects),
            "meshes": len(bpy.data.meshes),
            "materials": len(bpy.data.materials),
            "images": len(bpy.data.images),
            "node_groups": len(bpy.data.node_groups),
        }
        assert after == before, (before, after)
    finally:
        obj = bpy.data.objects.get(names["object"])
        if obj is not None:
            bpy.data.objects.remove(obj, do_unlink=True)
        for collection_name, key in (
            ("meshes", "mesh"),
            ("materials", "material"),
            ("images", "image"),
            ("node_groups", "nodes"),
        ):
            collection = getattr(bpy.data, collection_name)
            datablock = collection.get(names[key])
            if datablock is not None and int(getattr(datablock, "users", 0) or 0) == 0:
                collection.remove(datablock)
    return {
        "progress_steps": 2,
        "rollback_restored": True,
        "datablock_types": sorted(before),
    }


def test_incremental_generation_owner_contract(_module):
    coordinator = importlib.import_module(f"{PACKAGE}.generation_transaction")

    coordinator.retire_active_generation(
        bpy.context,
        reason="regression preflight",
        rollback=True,
    )
    owner, refusal = coordinator.acquire_generation(
        bpy.context,
        operator_id="fbp.test_generation_a",
        mode="Regression A",
    )
    assert owner is not None, refusal
    assert owner.token
    assert owner.operator_id == "fbp.test_generation_a"
    assert owner.scene_pointer == bpy.context.scene.as_pointer()

    blocked, blocked_reason = coordinator.acquire_generation(
        bpy.context,
        operator_id="fbp.test_generation_b",
        mode="Regression B",
    )
    assert blocked is None
    assert "Regression A" in blocked_reason, blocked_reason
    assert coordinator.active_generation_snapshot()["token"] == owner.token

    owned_mesh = bpy.data.meshes.new("FBP Owned Journal Mesh")
    owned_object = bpy.data.objects.new("FBP Owned Journal Object", owned_mesh)
    bpy.context.scene.collection.objects.link(owned_object)
    owner.record_datablock(owned_mesh, kind="MESH")
    owner.record_datablock(owned_object, kind="OBJECT")

    foreign_mesh = bpy.data.meshes.new("FBP Foreign Journal Mesh")
    foreign_object = bpy.data.objects.new("FBP Foreign Journal Object", foreign_mesh)
    bpy.context.scene.collection.objects.link(foreign_object)
    rollback = coordinator.retire_active_generation(
        bpy.context,
        reason="regression cancellation",
        rollback=True,
    )
    assert rollback["verified"], rollback
    assert not rollback["failed"], rollback
    assert not rollback["remaining"], rollback
    assert bpy.data.objects.get("FBP Owned Journal Object") is None
    assert bpy.data.meshes.get("FBP Owned Journal Mesh") is None
    assert bpy.data.objects.get("FBP Foreign Journal Object") is foreign_object
    assert bpy.data.meshes.get("FBP Foreign Journal Mesh") is foreign_mesh
    assert coordinator.active_generation_snapshot() == {}

    bpy.data.objects.remove(foreign_object, do_unlink=True)
    if foreign_mesh.users == 0:
        bpy.data.meshes.remove(foreign_mesh)
    return {
        "exclusive_owner": True,
        "owner_token": "uuid",
        "foreign_datablock_preserved": True,
        "rollback_verified": True,
    }


def test_incremental_progress_owner_contract(_module):
    coordinator = importlib.import_module(f"{PACKAGE}.generation_transaction")

    class ProgressProbe:
        def __init__(self):
            self.calls = []

        def progress_begin(self, minimum, maximum):
            self.calls.append(("begin", minimum, maximum))

        def progress_update(self, value):
            self.calls.append(("update", value))

        def progress_end(self):
            self.calls.append(("end",))

    probe = ProgressProbe()
    progress = coordinator.GenerationProgressOwner(probe, token="progress-token")
    assert progress.begin()
    assert not progress.begin()
    assert progress.update(0.0, phase="prepare")
    assert progress.update(0.50, phase="build")
    assert progress.update(0.25, phase="late-stale-update")
    assert progress.update(1.0, phase="commit")
    assert progress.end()
    assert not progress.end()
    assert not progress.update(1.0, phase="after-end")

    begins = [call for call in probe.calls if call[0] == "begin"]
    updates = [call[1] for call in probe.calls if call[0] == "update"]
    ends = [call for call in probe.calls if call[0] == "end"]
    assert len(begins) == 1, probe.calls
    assert len(ends) == 1, probe.calls
    assert updates == sorted(updates), updates
    assert updates[-1] == 100.0, updates
    return {
        "begin_calls": len(begins),
        "end_calls": len(ends),
        "monotonic_updates": updates,
        "updates_after_end": 0,
    }


def test_fast_import_preserves_global_undo(_module):
    importer = importlib.import_module(f"{PACKAGE}.importer")
    preferences = bpy.context.preferences.edit
    original = bool(preferences.use_global_undo)
    observations = []
    try:
        for initial in (True, False):
            preferences.use_global_undo = initial
            importer.fbp_begin_fast_import(bpy.context)
            try:
                observations.append(bool(preferences.use_global_undo))
                assert bool(preferences.use_global_undo) is initial
            finally:
                importer.fbp_abort_fast_import(bpy.context)
            assert bool(preferences.use_global_undo) is initial
    finally:
        preferences.use_global_undo = original
        importer.fbp_abort_fast_import(bpy.context)
    return {
        "initial_true_preserved": observations[0],
        "initial_false_preserved": not observations[1],
        "depth": importer.fbp_fast_import_depth(),
    }


def test_incremental_user_state_rollback(_module):
    coordinator = importlib.import_module(f"{PACKAGE}.generation_transaction")
    scene = bpy.context.scene
    mesh = bpy.data.meshes.new("FBP User State Mesh")
    original = bpy.data.objects.new("FBP User State Active", mesh)
    scene.collection.objects.link(original)
    bpy.ops.object.select_all(action='DESELECT')
    original.select_set(True)
    bpy.context.view_layer.objects.active = original
    scene.cursor.location = (1.0, 2.0, 3.0)
    scene.tool_settings.transform_pivot_point = 'CURSOR'
    scene.render.resolution_x = 1234
    scene.render.resolution_y = 567
    scene.render.pixel_aspect_x = 2.0
    scene.render.pixel_aspect_y = 3.0
    before_directory = str(WORKDIR / "before-transaction")
    mutated_directory = str(WORKDIR / "mutated-transaction")
    scene.fbp_last_directory = before_directory

    owner, refusal = coordinator.acquire_generation(
        bpy.context,
        operator_id="fbp.test_user_state",
        mode="User State Regression",
    )
    assert owner is not None, refusal
    bpy.ops.object.select_all(action='DESELECT')
    scene.cursor.location = (9.0, 9.0, 9.0)
    scene.tool_settings.transform_pivot_point = 'MEDIAN_POINT'
    scene.render.resolution_x = 16
    scene.render.resolution_y = 16
    scene.render.pixel_aspect_x = 1.0
    scene.render.pixel_aspect_y = 1.0
    scene.fbp_last_directory = mutated_directory

    rollback = coordinator.retire_active_generation(
        bpy.context,
        reason="state regression",
        rollback=True,
    )
    assert rollback["verified"], rollback
    assert tuple(scene.cursor.location) == (1.0, 2.0, 3.0)
    assert scene.tool_settings.transform_pivot_point == 'CURSOR'
    assert scene.render.resolution_x == 1234
    assert scene.render.resolution_y == 567
    assert scene.render.pixel_aspect_x == 2.0
    assert scene.render.pixel_aspect_y == 3.0
    assert scene.fbp_last_directory == before_directory
    assert bpy.context.view_layer.objects.active is original
    assert original.select_get()

    bpy.data.objects.remove(original, do_unlink=True)
    if mesh.users == 0:
        bpy.data.meshes.remove(mesh)
    return {
        "selection": "restored",
        "active_object": "restored",
        "camera_cursor_pivot": "restored",
        "resolution_aspect": "restored",
        "last_directory": "restored",
    }


def test_incremental_lifecycle_and_deep_rollback(_module):
    coordinator = importlib.import_module(f"{PACKAGE}.generation_transaction")
    handlers = importlib.import_module(f"{PACKAGE}.handlers")
    runtime = importlib.import_module(f"{PACKAGE}.runtime")
    scene = bpy.context.scene

    owner, refusal = coordinator.acquire_generation(
        bpy.context,
        operator_id="fbp.test_deep_rollback",
        mode="Deep Rollback",
    )
    assert owner is not None, refusal
    root = bpy.data.collections.new("FBP Journal Depth 00")
    scene.collection.children.link(root)
    owner.record_collection(root)
    parent = root
    for depth in range(1, 20):
        child = bpy.data.collections.new(f"FBP Journal Depth {depth:02d}")
        parent.children.link(child)
        owner.record_collection(child)
        parent = child

    owned_material = bpy.data.materials.new("FBP Owned Journal Material")
    owned_image = bpy.data.images.new("FBP Owned Journal Image", width=4, height=4)
    owner.record_datablock(owned_material, kind="MATERIAL")
    owner.record_datablock(owned_image, kind="IMAGE")
    foreign_material = bpy.data.materials.new("FBP Foreign Journal Material")
    foreign_image = bpy.data.images.new("FBP Foreign Journal Image", width=4, height=4)
    second_scene = bpy.data.scenes.new("FBP Concurrent Scene")
    fake_context = type("SceneContext", (), {"scene": second_scene})()
    blocked, blocked_reason = coordinator.acquire_generation(
        fake_context,
        operator_id="fbp.test_other_scene",
        mode="Other Scene",
    )
    assert blocked is None and "Deep Rollback" in blocked_reason
    rollback = coordinator.retire_active_generation(
        bpy.context,
        reason="deep rollback regression",
        rollback=True,
    )
    assert rollback["verified"], rollback
    assert sum(item.startswith("COLLECTION:") for item in rollback["removed"]) == 20, rollback
    assert bpy.data.materials.get(foreign_material.name) is foreign_material
    assert bpy.data.images.get(foreign_image.name) is foreign_image
    assert bpy.data.materials.get("FBP Owned Journal Material") is None
    assert bpy.data.images.get("FBP Owned Journal Image") is None
    bpy.data.materials.remove(foreign_material)
    bpy.data.images.remove(foreign_image)
    bpy.data.scenes.remove(second_scene)

    # Deterministic failure immediately after a yielded phase must use the same
    # verified rollback path.
    owner, refusal = coordinator.acquire_generation(
        bpy.context,
        operator_id="fbp.test_failpoint",
        mode="Failure Injection",
    )
    assert owner is not None, refusal
    fail_mesh = bpy.data.meshes.new("FBP Failpoint Mesh")
    fail_object = bpy.data.objects.new("FBP Failpoint Object", fail_mesh)
    scene.collection.objects.link(fail_object)
    owner.record_datablock(fail_mesh, kind="MESH")
    owner.record_datablock(fail_object, kind="OBJECT")
    coordinator.arm_generation_failpoint("AFTER_YIELD")
    try:
        owner.checkpoint("AFTER_YIELD", completed_steps=1, total_steps=2)
        raise AssertionError("Incremental failpoint did not trigger")
    except RuntimeError as exc:
        assert "AFTER_YIELD" in str(exc)
    failpoint_rollback = coordinator.retire_active_generation(
        bpy.context,
        reason="injected after yield",
        rollback=True,
    )
    assert failpoint_rollback["verified"], failpoint_rollback

    # load_pre must retire before Blender replaces Main.
    owner, refusal = coordinator.acquire_generation(
        bpy.context,
        operator_id="fbp.test_load_pre",
        mode="Load Lifecycle",
    )
    assert owner is not None, refusal
    load_mesh = bpy.data.meshes.new("FBP Load Pre Mesh")
    load_object = bpy.data.objects.new("FBP Load Pre Object", load_mesh)
    scene.collection.objects.link(load_object)
    owner.record_datablock(load_mesh, kind="MESH")
    owner.record_datablock(load_object, kind="OBJECT")
    handlers.fbp_load_pre_handler(None)
    assert coordinator.active_generation_snapshot() == {}
    assert bpy.data.objects.get("FBP Load Pre Object") is None
    handlers.fbp_set_undo_guard(False)
    runtime.fbp_runtime_set("fbp_pause_managed_timers", False)

    # importlib.reload executes the early retirement hook before accepting a
    # new owner from the reloaded module generation.
    owner, refusal = coordinator.acquire_generation(
        bpy.context,
        operator_id="fbp.test_reload",
        mode="Reload Lifecycle",
    )
    assert owner is not None, refusal
    reload_mesh = bpy.data.meshes.new("FBP Reload Mesh")
    reload_object = bpy.data.objects.new("FBP Reload Object", reload_mesh)
    scene.collection.objects.link(reload_object)
    owner.record_datablock(reload_mesh, kind="MESH")
    owner.record_datablock(reload_object, kind="OBJECT")
    coordinator = importlib.reload(coordinator)
    assert coordinator.active_generation_snapshot() == {}
    assert bpy.data.objects.get("FBP Reload Object") is None

    owner, refusal = coordinator.acquire_generation(
        bpy.context,
        operator_id="fbp.test_unregister",
        mode="Unregister Lifecycle",
    )
    assert owner is not None, refusal
    unregister_mesh = bpy.data.meshes.new("FBP Unregister Mesh")
    unregister_object = bpy.data.objects.new("FBP Unregister Object", unregister_mesh)
    scene.collection.objects.link(unregister_object)
    owner.record_datablock(unregister_mesh, kind="MESH")
    owner.record_datablock(unregister_object, kind="OBJECT")
    coordinator.unregister()
    assert coordinator.active_generation_snapshot() == {}
    assert bpy.data.objects.get("FBP Unregister Object") is None
    coordinator.register()
    return {
        "different_scene_refused": True,
        "nested_collection_depth": 20,
        "foreign_material_preserved": True,
        "foreign_image_preserved": True,
        "failure_after_yield": "verified rollback",
        "load_pre": "retired",
        "reload_scripts": "retired",
        "unregister": "retired",
    }


def test_synchronous_media_generation(_module):
    operator_import = importlib.import_module(f"{PACKAGE}.operator_import")
    scene = bpy.context.scene
    assert hasattr(bpy.types.Scene, "fbp_project_path")
    assert hasattr(bpy.types.Scene, "fbp_last_directory")
    assert hasattr(scene, "fbp_project_path")
    assert hasattr(scene, "fbp_last_directory")

    reports = []

    class MissingImportProperties:
        pass

    class ReportingOperator:
        def report(self, level, message):
            reports.append((set(level), str(message)))

    incomplete_result = operator_import.FBP_OT_ImportSingleImage.invoke(
        ReportingOperator(),
        type("ImportContext", (), {"scene": MissingImportProperties()})(),
        None,
    )
    assert incomplete_result == {'CANCELLED'}, incomplete_result
    assert reports and reports[-1][0] == {'ERROR'}, reports
    assert "not fully registered" in reports[-1][1], reports

    class StaleImportScene:
        def __getattribute__(self, name):
            if str(name).startswith("fbp_"):
                raise ReferenceError("StructRNA of type Scene has been removed")
            return super().__getattribute__(name)

    stale_result = operator_import.FBP_OT_ImportSingleImage.invoke(
        ReportingOperator(),
        type("StaleImportContext", (), {"scene": StaleImportScene()})(),
        None,
    )
    assert stale_result == {'CANCELLED'}, stale_result
    assert reports[-1][0] == {'ERROR'}, reports
    assert "not fully registered" in reports[-1][1], reports

    directory_probe = type(
        "ImportDirectoryProbe",
        (),
        {"fbp_project_path": "", "fbp_last_directory": str(WORKDIR)},
    )()
    assert operator_import._fbp_scene_import_directory(directory_probe) == str(WORKDIR)

    fixture_path = WORKDIR / "fbp_generation_fixture.png"
    fixture_image = bpy.data.images.new(
        "FBP Generation Fixture Source",
        width=16,
        height=16,
        alpha=True,
    )
    try:
        fixture_image.generated_color = (0.2, 0.4, 0.8, 1.0)
        fixture_image.filepath_raw = str(fixture_path)
        fixture_image.file_format = 'PNG'
        fixture_image.save()
    finally:
        bpy.data.images.remove(fixture_image)
    assert fixture_path.is_file(), fixture_path

    snapshot = operator_import._fbp_multiplane_runtime_snapshot(bpy.context)
    before_rigs = {
        obj.as_pointer()
        for obj in bpy.context.scene.objects
        if bool(getattr(obj, "is_fbp_control", False))
    }
    operator_class = operator_import.FBP_OT_ImportSequence
    temporary_registration = getattr(bpy.types, operator_class.__name__, None) is None
    if temporary_registration:
        bpy.utils.register_class(operator_class)
    try:
        result = bpy.ops.fbp.import_sequence(
            'EXEC_DEFAULT',
            synchronous=True,
            filepath=str(fixture_path),
            directory=str(fixture_path.parent),
            media_filter='IMAGES',
        )
        assert result == {'FINISHED'}, result
        generated = [
            obj
            for obj in bpy.context.scene.objects
            if bool(getattr(obj, "is_fbp_control", False))
            and obj.as_pointer() not in before_rigs
        ]
        assert len(generated) == 1, [obj.name for obj in generated]
        # Clean success reports are intentionally cleared after UI finalization;
        # warning/cancel reports remain available for diagnostics.
        assert operator_import._fbp_generation_report(bpy.context) == {}
    finally:
        assert operator_import._fbp_rollback_unexpected_multiplane_build(
            bpy.context,
            snapshot,
        )
        if temporary_registration:
            bpy.utils.unregister_class(operator_class)
    return {
        "fixture": str(fixture_path),
        "generated_rigs": 1,
        "background_mode": bool(bpy.app.background),
        "rollback_restored": True,
        "partial_registration_guard": True,
        "stale_scene_guard": True,
    }


def test_register_cycles():
    module = import_addon(fresh=True)
    for cycle in range(3):
        scheduler = importlib.import_module(f"{PACKAGE}.runtime_scheduler")
        assert scheduler.scheduler_accepting_tasks(), f"cycle {cycle}: scheduler not accepting"
        marker = []

        def deferred_probe():
            marker.append(True)
            return None

        assert scheduler.schedule_task(
            f"tests.reload_probe.{cycle}",
            deferred_probe,
            delay=60.0,
            category="tests",
        )
        assert scheduler.task_count(category="tests") == 1
        unregister_addon(module)
        assert not scheduler.scheduler_accepting_tasks()
        assert scheduler.task_count() == 0, scheduler.scheduler_snapshot()
        module = import_addon(fresh=True)

    # Blender's extension updater normally reloads the existing package object
    # rather than deleting every module first. Exercise that separate lifecycle
    # so previous-generation timer globals and class references are retired.
    scheduler = importlib.import_module(f"{PACKAGE}.runtime_scheduler")
    unregister_addon(module)
    assert not scheduler.scheduler_accepting_tasks()
    module = reload_addon_module_in_place(module)
    module.register()
    scheduler = importlib.import_module(f"{PACKAGE}.runtime_scheduler")
    assert scheduler.scheduler_accepting_tasks()
    assert scheduler.task_count(category="tests") == 0
    return module, "3 clean reloads plus 1 in-place extension reload; scheduler quiescent"


def test_scheduler_rna_capture(_module):
    scheduler = importlib.import_module(f"{PACKAGE}.runtime_scheduler")
    scene = bpy.context.scene

    deep_payload = {"a": [{"b": [{"c": [{"d": scene}]}]}]}
    def unsafe_default(payload=deep_payload):
        return None
    assert not scheduler.schedule_task(
        "tests.unsafe_nested_rna", unsafe_default, delay=60.0, category="tests"
    )

    class SlottedCallback:
        __slots__ = ("payload",)
        def __init__(self, payload):
            self.payload = payload
        def __call__(self):
            return None

    assert not scheduler.schedule_task(
        "tests.unsafe_slotted_rna", SlottedCallback({"scene": scene}),
        delay=60.0, category="tests",
    )
    safe_payload = {"a": [{"b": [1, 2, 3, "safe"]}]}
    assert scheduler.schedule_task(
        "tests.safe_nested_primitives", lambda payload=safe_payload: None,
        delay=60.0, category="tests",
    )
    assert scheduler.cancel_task("tests.safe_nested_primitives")

    # The safety scan must fail closed rather than accepting an opaque payload
    # merely because its nesting exceeds the bounded traversal contract.
    too_deep = value = {}
    for index in range(12):
        child = {}
        value[f"level_{index}"] = child
        value = child
    value["leaf"] = "primitive"
    assert not scheduler.schedule_task(
        "tests.inconclusive_deep_payload", lambda payload=too_deep: None,
        delay=60.0, category="tests",
    )
    oversized_payload = {f"item_{index}": index for index in range(96)}
    assert not scheduler.schedule_task(
        "tests.inconclusive_oversized_payload", lambda payload=oversized_payload: None,
        delay=60.0, category="tests",
    )

    # Facade registries must also revalidate their real payload at dispatch.
    # The scheduler itself only owns the wrapper runner, so mutable callbacks
    # could otherwise acquire RNA after registration and bypass the guard.
    safe_tasks = importlib.import_module(f"{PACKAGE}.safe_tasks")
    facade_payload = {"target": "safe"}
    facade_calls = []
    def facade_callback(payload=facade_payload):
        facade_calls.append(payload["target"])
        return None
    assert safe_tasks.schedule_once(
        "tests.mutable_safe_facade", facade_callback, first_interval=60.0
    )
    facade_payload["target"] = scene
    facade_runner = scheduler.task_callback("tests.mutable_safe_facade")
    assert callable(facade_runner)
    assert facade_runner() is None
    assert not facade_calls
    scheduler.cancel_task("tests.mutable_safe_facade")

    managed = importlib.import_module(f"{PACKAGE}.managed_timers")
    managed_payload = {"target": "safe"}
    managed_calls = []
    def managed_callback(payload=managed_payload):
        managed_calls.append(payload["target"])
        return None
    assert managed.fbp_register_timer_once(managed_callback, 60.0)
    managed_payload["target"] = scene
    managed_key = managed._scheduler_key(managed_callback)
    managed_runner = scheduler.task_callback(managed_key)
    assert callable(managed_runner)
    assert managed_runner() is None
    assert not managed_calls
    managed.fbp_unregister_managed_timer(managed_callback)

    metrics = scheduler.scheduler_metrics()
    assert int(metrics.get("rna_callbacks_rejected", 0)) >= 6, metrics
    assert int(metrics.get("rna_scans_inconclusive", 0)) >= 2, metrics
    return (
        "RNA captures, inconclusive payloads and post-registration facade mutations rejected; "
        "bounded primitive payload accepted"
    )


def test_collections(_module):
    layers = importlib.import_module(f"{PACKAGE}.layers")
    ui_layout = importlib.import_module(f"{PACKAGE}.ui_layout")
    scene = bpy.context.scene
    root = layers.get_or_create_child_collection(scene.collection, "FBP Test Root")
    child = layers.get_or_create_child_collection(root, "FBP Test Child")
    nested = layers.get_or_create_child_collection(child, "FBP Test Nested")
    mesh = bpy.data.meshes.new("FBP Test Mesh")
    obj = bpy.data.objects.new("FBP Test Object", mesh)
    nested.objects.link(obj)

    for index in range(80):
        obj.hide_viewport = not obj.hide_viewport
        obj.hide_render = not obj.hide_render
        root.fbp_collapsed = bool(index & 1)
        root.fbp_collapsed = False
        if index % 8 == 0:
            ui_layout.fbp_refresh_layer_tree_rows(bpy.context)
            ui_layout.fbp_refresh_layer_tree_group_snapshots(bpy.context)

    child.children.unlink(nested)
    root.children.link(nested)
    ui_layout.fbp_refresh_layer_tree_rows(bpy.context)
    bpy.data.collections.remove(child)
    ui_layout.fbp_invalidate_layer_tree_snapshot(scene)
    ui_layout.fbp_refresh_layer_tree_rows(bpy.context)
    tree = layers.fbp_build_canonical_collection_tree(scene)
    assert obj.name in bpy.data.objects and nested.name in bpy.data.collections
    assert tree["root"] is scene.collection
    return "managed create/reparent/toggle/delete plus scalar Layer Tree snapshots"


def test_undo_redo(_module):
    override = None
    for window in tuple(bpy.context.window_manager.windows):
        for area in tuple(window.screen.areas):
            if area.type != "VIEW_3D":
                continue
            region = next(
                (candidate for candidate in area.regions if candidate.type == "WINDOW"),
                None,
            )
            if region is not None:
                override = {"window": window, "screen": window.screen, "area": area, "region": region}
                break
        if override is not None:
            break
    if override is None:
        raise SkipTest("Undo operators need an interactive View3D context")
    with bpy.context.temp_override(**override):
        if not bpy.ops.ed.undo_push.poll():
            raise SkipTest("Undo push is unavailable in the interactive View3D context")
        bpy.ops.mesh.primitive_plane_add()
        obj = bpy.context.object
        obj.name = "FBP Undo Target"
        for index in range(20):
            obj.location.x = index
            bpy.ops.ed.undo_push(message=f"FBP test {index}")
        if not bpy.ops.ed.undo.poll():
            raise SkipTest("Undo history was not exposed after 20 pushes")
        undo_count = 0
        for _ in range(20):
            if not bpy.ops.ed.undo.poll():
                break
            bpy.ops.ed.undo()
            undo_count += 1
        redo_count = 0
        for _ in range(undo_count):
            if not bpy.ops.ed.redo.poll():
                break
            bpy.ops.ed.redo()
            redo_count += 1
    if bpy.app.background:
        assert undo_count >= 1 and redo_count == undo_count, (undo_count, redo_count)
    else:
        assert undo_count == 20 and redo_count == 20, (undo_count, redo_count)
    assert bpy.data.objects.get("FBP Undo Target") is not None
    return {
        "pushes": 20,
        "undo": undo_count,
        "redo": redo_count,
        "interactive_20_cycle_requirement": not bpy.app.background,
    }


def test_scrub_bar_regressions(_module):
    scrub = importlib.import_module(f"{PACKAGE}.grease_pencil_scrub")
    bridge = importlib.import_module(f"{PACKAGE}.grease_pencil_bridge")
    icons = importlib.import_module(f"{PACKAGE}.ui_icons")

    vertical = scrub.scrub_overlay_layout(
        900,
        600,
        position="LEFT",
        ui_scale=1.0,
        length_ratio=0.5,
        edge_offset=180.0,
    )
    base_x = float(vertical["x"])
    assert scrub.magnetic_scrub_axis_offset(
        base_x + 150.0,
        300.0,
        vertical,
        capture_px=96.0,
    ) == 0.0
    assert math.isclose(
        scrub.magnetic_scrub_axis_offset(
            base_x + 24.0,
            300.0,
            vertical,
            capture_px=96.0,
        ),
        24.0,
        abs_tol=1.0e-6,
    )
    outer = scrub.magnetic_scrub_axis_offset(
        base_x + 72.0,
        300.0,
        vertical,
        capture_px=96.0,
    )
    assert 0.0 < outer < 72.0
    assert scrub.magnetic_scrub_axis_offset(
        base_x + 24.0,
        800.0,
        vertical,
        capture_px=96.0,
    ) == 0.0

    assert not scrub.scrub_magnet_should_release(
        "TIMER",
        event_in_window=False,
        cursor_in_owned_window=True,
    )
    assert scrub.scrub_magnet_should_release(
        "TIMER",
        event_in_window=True,
        cursor_in_owned_window=False,
    )
    assert scrub.scrub_magnet_should_release(
        "MOUSEMOVE",
        event_in_window=False,
        cursor_in_owned_window=True,
    )

    horizontal = scrub.scrub_overlay_layout(
        900,
        600,
        position="BOTTOM",
        ui_scale=1.0,
        length_ratio=0.5,
        edge_offset=120.0,
    )
    direct = scrub.direct_scrub_mapping_factor(
        (horizontal["x0"] + horizontal["x1"]) * 0.5,
        horizontal["y"],
        horizontal,
        capture_px=96.0,
        inner_px=12.0,
        strength=1.0,
    )
    transition = scrub.direct_scrub_mapping_factor(
        (horizontal["x0"] + horizontal["x1"]) * 0.5,
        horizontal["y"] + 48.0,
        horizontal,
        capture_px=96.0,
        inner_px=12.0,
        strength=1.0,
    )
    relative = scrub.direct_scrub_mapping_factor(
        (horizontal["x0"] + horizontal["x1"]) * 0.5,
        horizontal["y"] + 120.0,
        horizontal,
        capture_px=96.0,
        inner_px=12.0,
        strength=1.0,
    )
    assert direct == 1.0
    assert 0.0 < transition < 1.0
    assert relative == 0.0

    class RangeScene:
        frame_start = 1
        frame_end = 250
        use_preview_range = False

    for center, count, expected in (
        (50, 50, (25, 74)),
        (1, 50, (1, 50)),
        (250, 50, (201, 250)),
    ):
        display = scrub.scrub_display_range(RangeScene(), center, count)
        assert display == expected, (center, count, display)
        assert display[1] - display[0] + 1 == count

    # Relative scrubbing must use the actual visible distance available on
    # each side. At scene frame 1, a 1-50 window must reach frame 50.
    target, _delta = scrub.relative_scrub_target(
        1,
        100.0,
        24.5,
        100.0,
        sensitivity=1.0,
        negative_radius=0.0,
        positive_radius=49.0,
    )
    assert math.isclose(target, 50.0), target

    # Leaving the exact direct zone must be distinguishable from the outer
    # transition so the modal operator can re-anchor at the exit position.
    assert scrub.direct_scrub_mapping_factor(
        (horizontal["x0"] + horizontal["x1"]) * 0.5,
        horizontal["y"],
        horizontal,
        capture_px=96.0,
        inner_px=12.0,
        strength=1.0,
    ) == 1.0
    assert scrub._bookmark_native_name("Shot A") == "✦ - Shot A"
    assert scrub._bookmark_label_from_name("✦ - Shot A") == "Shot A"
    assert len(scrub._BOOKMARK_COLOR_ITEMS) == 9
    assert {
        identifier: icon
        for identifier, _label, _description, icon, _index in scrub._BOOKMARK_COLOR_ITEMS
    } == {
        "NONE": "SNAP_FACE",
        "GREY": "STRIP_COLOR_09",
        "RED": "STRIP_COLOR_01",
        "ORANGE": "STRIP_COLOR_02",
        "YELLOW": "STRIP_COLOR_03",
        "GREEN": "STRIP_COLOR_04",
        "CYAN": "STRIP_COLOR_05",
        "PURPLE": "STRIP_COLOR_06",
        "MAGENTA": "STRIP_COLOR_07",
    }
    assert scrub._bookmark_color_tag("WHITE") == "NONE"
    assert scrub._bookmark_color_tag("BLUE") == "CYAN"
    assert scrub._bookmark_color_tag("CYAN") == "CYAN"
    assert scrub._bookmark_color_tag("unknown") == "NONE"
    assert scrub._bookmark_color("BLUE") == scrub._BOOKMARK_COLORS["CYAN"]
    assert scrub._bookmark_color("CYAN") == scrub._BOOKMARK_COLORS["CYAN"]
    adaptive_none = scrub._bookmark_color(
        "NONE",
        none_color=(0.12, 0.34, 0.56, 1.0),
    )
    assert adaptive_none == (0.12, 0.34, 0.56, 0.88), adaptive_none
    class FakeScrubInk:
        pass

    original_background_color = scrub.viewport_background_color
    try:
        scrub.viewport_background_color = lambda _context: (0.90, 0.80, 0.70)
        fake_scrub_ink = FakeScrubInk()
        scrub._apply_inverted_scrub_ink(fake_scrub_ink, bpy.context)
        assert fake_scrub_ink._bookmark_none_color[:3] == (0.035, 0.035, 0.035)
        scrub.viewport_background_color = lambda _context: (0.10, 0.12, 0.15)
        scrub._apply_inverted_scrub_ink(fake_scrub_ink, bpy.context)
        assert fake_scrub_ink._bookmark_none_color[:3] == (0.97, 0.97, 0.97)
    finally:
        scrub.viewport_background_color = original_background_color

    class FakeKeyframe:
        def __init__(self, keyframe_type):
            self.keyframe_type = keyframe_type

    assert scrub.selected_keyframe_type_icon(()) == "KEYFRAME"
    assert scrub.selected_keyframe_type_icon(((None, FakeKeyframe("EXTREME")),)) == "KEYTYPE_EXTREME_VEC"
    assert scrub.selected_keyframe_type_icon((
        (None, FakeKeyframe("EXTREME")),
        (None, FakeKeyframe("BREAKDOWN")),
    )) == "KEYFRAME"

    native_header_draw = bpy.types.VIEW3D_HT_header.draw
    assert not bool(getattr(native_header_draw, "_fbp_scrub_header_patch", False))
    from bl_ui import space_view3d as native_view3d

    native_gp_layer_draw = getattr(
        native_view3d.draw_topbar_grease_pencil_layer_panel,
        "_fbp_original_draw",
        native_view3d.draw_topbar_grease_pencil_layer_panel,
    )
    scrub._unregister_header()
    assert bpy.types.VIEW3D_HT_header.draw is native_header_draw
    assert native_view3d.draw_topbar_grease_pencil_layer_panel is native_gp_layer_draw
    scrub._register_header()
    assert bpy.types.VIEW3D_HT_header.draw is native_header_draw
    assert bool(getattr(
        native_view3d.draw_topbar_grease_pencil_layer_panel,
        "_fbp_scrub_gp_layer_patch",
        False,
    ))

    keys = (10, 20, 30, 40, 60, 70)
    assert scrub._onion_endpoint_frame(50, 2, "BEFORE", "RELATIVE", keys) == 30
    assert scrub._onion_endpoint_frame(50, 2, "AFTER", "RELATIVE", keys) == 70
    assert scrub._onion_amount_from_frame(50, 25, "BEFORE", "RELATIVE", keys) == 2
    assert scrub._onion_amount_from_frame(50, 65, "AFTER", "RELATIVE", keys) == 1

    value = 0.0
    for _index in range(40):
        value = scrub.smooth_scrub_magnet_offset(
            value,
            24.0,
            0.22,
            0.04,
        )
    assert math.isclose(value, 24.0, abs_tol=0.05), value

    class SceneZero:
        frame_current = 0

    assert bridge._scene_current_frame_number(SceneZero(), 1) == 0
    assert icons._FBP_CUSTOM_ICON_UI_KEYS.get("settings.scrub_slider") == "floating_timeline"
    icon_path = SOURCE / "assets" / "icons" / "icon_FLOATINGTIMELINE_paste.png"
    assert icon_path.is_file(), icon_path
    return {
        "magnet_outer_offset": outer,
        "direct_scrub_factor": direct,
        "range_50": scrub.scrub_display_range(RangeScene(), 50, 50),
        "frame_zero": bridge._scene_current_frame_number(SceneZero(), 1),
        "preferences_icon": icon_path.name,
    }


def test_gp_support(_module):
    bridge = importlib.import_module(f"{PACKAGE}.grease_pencil_bridge")
    blender_icons = {
        item.identifier
        for item in bpy.types.UILayout.bl_rna.functions["operator"]
        .parameters["icon"].enum_items
    }
    presentation_icons = {
        icon
        for _label, icon in bridge._GP_EFFECT_COMPATIBILITY_TIER_PRESENTATION.values()
    }
    assert presentation_icons <= blender_icons, sorted(presentation_icons - blender_icons)
    summary = bridge.fbp_gp_effect_support_summary()
    assert len(bridge.GP_NATIVE_EFFECTS) >= 27, len(bridge.GP_NATIVE_EFFECTS)
    assert summary["total"] == sum(
        summary[key] for key in ("NATIVE", "GEOMETRY_CANDIDATE", "RASTER_ONLY")
    ), summary
    assert any(
        item["effect_id"] == "SURFACE_CONFORM" and item["tier"] == "NATIVE"
        for item in bridge.fbp_gp_effect_backend_matrix()
    )
    records = bridge._gp_effect_compatibility_records()
    assert len(records) == summary["total"], (len(records), summary)
    assert all(str(item.get("reason", "")).strip() for item in records), records
    assert any("not available yet" in item["reason"].casefold() for item in records)
    assert any("no native conversion is planned yet" in item["reason"].casefold() for item in records)
    report = bridge._fbp_gp_effect_compatibility_report_text()
    assert "Grease Pencil Effect Compatibility" in report, report
    assert "This report stays local" in report, report
    assert hasattr(bpy.types.Object, "fbp_gp_effect_compatibility_filter")
    return summary


def test_gp_runtime_cache_cleanup(_module):
    bridge = importlib.import_module(f"{PACKAGE}.grease_pencil_bridge")
    raster = importlib.import_module(f"{PACKAGE}.gp_mask_raster")
    raster._RGBA_CACHE["release-gate"] = (object(), 64)
    raster._GRID_CACHE["release-gate"] = (object(), object(), 96)
    raster._RGBA_CACHE_BYTES = 64
    raster._GRID_CACHE_BYTES = 96
    bridge.clear_grease_pencil_runtime_caches()
    assert not raster._RGBA_CACHE and raster._RGBA_CACHE_BYTES == 0
    assert not raster._GRID_CACHE and raster._GRID_CACHE_BYTES == 0
    return {"rgba_bytes": 0, "grid_bytes": 0, "reload_cleanup": True}


def test_felt_fuzz_canonical_contract(_module):
    geo = importlib.import_module(f"{PACKAGE}.geometry_nodes")
    builtin = importlib.import_module(f"{PACKAGE}.builtin_effects")
    registry = importlib.import_module(f"{PACKAGE}.effects_registry")
    effect_id = registry.FBP_EFFECT_FELT_FUZZ
    definition = registry.fbp_effect_definition(effect_id)
    group = geo._fbp_load_effect_group(effect_id)
    assert group is not None
    assert builtin._builtin_group_is_complete(group, definition)
    assert int(group.get("fbp_alpha_mask_patch_version", 0) or 0) >= geo.FBP_ALPHA_MASK_PATCH_VERSION
    node_count = len(group.nodes)
    cached = geo._fbp_load_effect_group(effect_id)
    assert cached is group
    assert len(cached.nodes) == node_count
    inputs = geo._fbp_interface_inputs(group)
    assert "Seed" in inputs
    assert "Alpha Threshold" in inputs and "Alpha Resolution" in inputs
    return {"nodes": node_count, "canonical_upgrade_once": True}


def test_audited_operator_tooltips(_module):
    tooltips = importlib.import_module(f"{PACKAGE}.tooltips")
    audited = (
        "fbp.reset_uilist_filter", "fbp.uilist_column_visibility",
        "fbp.uilist_column_drag", "fbp.uilist_columns_reset",
        "fbp.uilist_label_alignment", "fbp.move_layer_filter_preset",
        "fbp.safe_gp_mask_shrink_fatten",
        "fbp.copy_grease_pencil_scrub_keyframes",
        "fbp.paste_grease_pencil_scrub_keyframes",
        "fbp.duplicate_grease_pencil_scrub_keyframes",
        "fbp.delete_grease_pencil_scrub_keyframes",
        "fbp.select_all_grease_pencil_scrub_keyframes",
        "fbp.mirror_grease_pencil_scrub_keyframes",
        "fbp.set_grease_pencil_scrub_keyframe_type",
        "fbp.set_grease_pencil_scrub_position", "fbp.set_quick_mask_slot",
        "fbp.reset_quick_mask_slots", "fbp.quick_mask_library_popup",
        "fbp.quick_effect_library_popup", "fbp.gradient_controller",
        "fbp.apply_layer_set", "fbp.motion_select_row",
        "fbp.select_generation_rename_row", "fbp.drop_media",
        "fbp.stack_row_action", "fbp.add_compositor_asset",
        "fbp.layer_set_row_action", "fbp.layer_set_batch",
        "fbp.remap_layer_set_source", "fbp.layer_set_preview",
        "fbp.output_pass_action", "fbp.validate_composite",
        "fbp.compositor_package_action", "fbp.compositor_auto_layers",
        "fbp.compositor_select_row", "fbp.compositor_layer_action",
        "fbp.compositor_effect_select_row", "fbp.compositor_sync",
        "fbp.move_effect_stack_preset", "fbp.gradient_light_controller",
    )
    assert len(audited) == 40 and len(set(audited)) == 40, audited
    missing = [item for item in audited if not tooltips.EXACT_TOOLTIPS.get(item)]
    assert not missing, missing
    generic = [
        item for item in audited
        if len(tooltips.EXACT_TOOLTIPS[item]) < 120
        or "current Frame By Plane context" in tooltips.EXACT_TOOLTIPS[item]
    ]
    assert not generic, generic
    compositor = [item for item in audited if "compositor" in item or item in {
        "fbp.stack_row_action", "fbp.layer_set_row_action", "fbp.layer_set_batch",
        "fbp.remap_layer_set_source", "fbp.layer_set_preview",
        "fbp.output_pass_action", "fbp.validate_composite",
    }]
    assert all("Preview" in tooltips.EXACT_TOOLTIPS[item] for item in compositor)
    return {"audited": len(audited), "preview_descriptions": len(compositor)}


def test_preview_scope_policy(_module):
    feature_scope = importlib.import_module(f"{PACKAGE}.feature_scope")

    class PreviewModifier:
        type = "NODES"
        id_data = {"fbp_generic_mesh_modifiers_v1": '{"test":{"fbp_generic_mesh_effect":true}}'}

        class node_group:
            class interface:
                items_tree = (type('Socket', (), dict(item_type='SOCKET', in_out='INPUT',
                               name='FBP Generic Mesh Owner', identifier='owner'))(),)

        class properties:
            class inputs:
                owner = type('Value', (), dict(value='test'))()

    class PreviewObject:
        modifiers = (PreviewModifier(),)

    class PreviewScene:
        fbp_experimental_compositor = True
        fbp_preview_procreate_import = False
        fbp_preview_generic_mesh_effects = False
        fbp_compositor_layers = (object(), object())
        fbp_compositor_enabled = True
        fbp_layered_report_format = "PROCREATE"
        objects = (PreviewObject(),)

    usage = feature_scope.fbp_preview_feature_usage(PreviewScene())
    assert len(usage) == 3, usage
    assert all(item["used"] for item in usage), usage
    assert next(item for item in usage if item["id"] == "compositor_layers")["enabled"]
    diagnostics = feature_scope.fbp_preview_diagnostics_text(PreviewScene())
    assert "outside the Frame By Plane 7.1 LTS stability promise" in diagnostics
    assert "no file paths, project media or telemetry" in diagnostics

    project_health = importlib.import_module(f"{PACKAGE}.project_health")
    scene = bpy.context.scene
    previous = bool(getattr(scene, "fbp_preview_procreate_import", False))
    try:
        scene.fbp_preview_procreate_import = True
        health = project_health.scan_project_health(scene, repair=False)
    finally:
        scene.fbp_preview_procreate_import = previous
    preview_issues = [
        item for item in health.get("issues", ())
        if item.get("code") == "PREVIEW_FEATURE"
    ]
    assert preview_issues, health
    assert all("not an LTS error" in item.get("message", "") for item in preview_issues)
    return {
        "features": len(usage),
        "used_features": sum(item["used"] for item in usage),
        "doctor_preview_issues": len(preview_issues),
    }


def test_irreversible_action_contracts(_module):
    geometry_nodes = importlib.import_module(f"{PACKAGE}.geometry_nodes")
    operator_import = importlib.import_module(f"{PACKAGE}.operator_import")
    operator_layers = importlib.import_module(f"{PACKAGE}.operator_layers")
    operator_render = importlib.import_module(f"{PACKAGE}.operator_render")

    preset_dir = WORKDIR / "irreversible-contracts"
    preset_dir.mkdir(parents=True, exist_ok=True)
    preset_path = preset_dir / "effect_presets.json"
    preset_payload = '{"PIXELATE": {"Audit": {"size": 4}}}\n'
    preset_path.write_text(preset_payload, encoding="utf-8")
    original_preset_path = geometry_nodes._fbp_user_preset_path
    geometry_nodes._fbp_user_preset_path = lambda: preset_path
    try:
        backup_ok, backup_path = geometry_nodes._fbp_backup_user_preset_library()
        assert backup_ok and backup_path is not None, (backup_ok, backup_path)
        assert backup_path.read_text(encoding="utf-8") == preset_payload

        assert geometry_nodes._fbp_save_user_presets(
            {"PIXELATE": {"Atomic": {"size": 8}}}
        )
        assert json.loads(preset_path.read_text(encoding="utf-8"))["PIXELATE"]["Atomic"]

        backup_path.write_text(
            json.dumps({"PIXELATE": {"Recovered": {"size": 6}}}),
            encoding="utf-8",
        )
        preset_path.write_text("{corrupted json", encoding="utf-8")
        geometry_nodes._FBP_USER_PRESET_CACHE["stamp"] = None
        recovered = geometry_nodes._fbp_load_user_presets()
        assert recovered["PIXELATE"]["Recovered"]["size"] == 6, recovered
        assert geometry_nodes._FBP_USER_PRESET_CACHE["status"] == "RECOVERED_BACKUP"
        prepared, recovered_backup, corrupt_copy, prepare_error = (
            geometry_nodes._fbp_prepare_user_preset_mutation()
        )
        assert prepared and not prepare_error, prepare_error
        assert recovered_backup is not None and corrupt_copy is not None
        assert corrupt_copy.read_text(encoding="utf-8") == "{corrupted json"
        assert json.loads(preset_path.read_text(encoding="utf-8"))["PIXELATE"]["Recovered"]

        # A read-only file can still be atomically replaced when its parent is
        # writable on Unix. Use a regular file as the parent instead, which is
        # a deterministic write failure on every supported operating system.
        invalid_parent = preset_dir / "not-a-directory"
        invalid_parent.write_text("FBP audit blocker", encoding="utf-8")
        geometry_nodes._fbp_user_preset_path = lambda: invalid_parent / "effect_presets.json"
        try:
            assert not geometry_nodes._fbp_save_user_presets(
                {"PIXELATE": {"Must Not Replace": {"size": 99}}}
            )
        finally:
            geometry_nodes._fbp_user_preset_path = lambda: preset_path

        preset_path.write_text("{still corrupted", encoding="utf-8")
        backup_path.write_text("{backup corrupted", encoding="utf-8")
        geometry_nodes._FBP_USER_PRESET_CACHE["stamp"] = None
        prepared, _backup, _recovery, prepare_error = (
            geometry_nodes._fbp_prepare_user_preset_mutation()
        )
        assert not prepared and "corrupt" in prepare_error.lower(), prepare_error
    finally:
        geometry_nodes._fbp_user_preset_path = original_preset_path

    assert "Blender Undo cannot restore" in geometry_nodes.FBP_OT_SaveEffectPreset.bl_description
    assert "Blender Undo cannot restore" in geometry_nodes.FBP_OT_DeleteEffectPreset.bl_description

    sources = (preset_dir / "old one.png", preset_dir / "old two.png")
    targets = (preset_dir / "shot_0001.png", preset_dir / "shot_0002.png")
    for source in sources:
        source.write_bytes(b"FBP audit fixture")
    manifest, error = operator_import.FBP_OT_RenameSequenceForBlender._write_rename_manifest(
        None,
        str(preset_dir),
        tuple(str(path) for path in sources),
        tuple(str(path) for path in targets),
    )
    assert manifest and not error, (manifest, error)
    payload = json.loads(Path(manifest).read_text(encoding="utf-8"))
    assert payload["schema"] == 2 and len(payload["files"]) == 2, payload
    assert len(payload["operation_id"]) == 32, payload
    assert payload["timezone"] == "UTC" and payload["status"] == "PLANNED", payload
    assert payload["files"][0] == {"source": "old one.png", "target": "shot_0001.png"}
    second_manifest, second_error = operator_import.FBP_OT_RenameSequenceForBlender._write_rename_manifest(
        None,
        str(preset_dir),
        tuple(str(path) for path in sources),
        tuple(str(path) for path in targets),
    )
    assert second_manifest and not second_error and second_manifest != manifest
    assert operator_import.FBP_OT_RenameSequenceForBlender._finalize_rename_manifest(
        manifest,
        "COMPLETED",
        detail="regression fixture",
    )
    finalized = json.loads(Path(manifest).read_text(encoding="utf-8"))
    assert finalized["status"] == "COMPLETED" and finalized["finalized_at"], finalized

    assert "INTERNAL" in operator_layers.FBP_OT_RepairLayerRelation.bl_options
    assert "UNDO" not in operator_layers.FBP_OT_RepairLayerRelation.bl_options
    assert "UNDO" not in operator_layers.FBP_OT_RepairAllLayerRelations.bl_options
    assert "UNDO" not in operator_import.FBP_OT_RemoveCorruptedGeneratedPlanes.bl_options
    assert "UNDO" not in operator_render.FBP_OT_SyncRenderOutput.bl_options
    sync_help = operator_render.FBP_OT_SyncRenderOutput.description(
        bpy.context,
        type("SyncProperties", (), {"from_native": True})(),
    )
    assert "no folders or files are created" in sync_help
    return {
        "preset_backup": backup_path.name,
        "preset_atomic_write": True,
        "preset_corrupt_recovery": True,
        "preset_corrupt_fail_closed": True,
        "preset_read_only_preserved": True,
        "preset_save_delete_undo_warning": True,
        "rename_manifest": Path(manifest).name,
        "rename_manifest_uuid": True,
        "rename_manifest_finalized": True,
        "filesystem_undo_advertised": False,
        "targeted_repair_internal": True,
    }


def test_gp_native_apply(_module):
    bridge = importlib.import_module(f"{PACKAGE}.grease_pencil_bridge")
    result = bpy.ops.fbp.add_grease_pencil_canvas(
        "EXEC_DEFAULT",
        canvas_name="FBP GP Native Backend",
        owner_name="__FREE__",
        enter_draw_mode=False,
    )
    assert "FINISHED" in result, result
    canvas = bpy.context.object
    supported = []
    added = []
    for definition in bridge.GP_NATIVE_EFFECTS:
        effect_id = definition[0]
        if not bridge._gp_native_effect_supported(canvas, definition):
            continue
        supported.append(effect_id)
        item = bridge._gp_add_native_effect(canvas, effect_id)
        if item is not None:
            added.append(effect_id)
    if added:
        instances = bridge._gp_native_effect_instances(canvas)
        bridge._gp_sync_native_effect_items(canvas)
        list_ids = [str(row.effect_id) for row in canvas.fbp_gp_effect_items]
        ordered_ids = [
            effect_id
            for effect_id, _item, _backend, _index
            in bridge._gp_native_effect_stack_state(canvas)[1]
        ]
        assert list_ids == ordered_ids, (list_ids, ordered_ids)
        assert hasattr(bpy.types, "FBP_UL_GPNativeEffectStack")
        assert hasattr(bpy.types, "FBP_MT_gp_native_effect_actions")
        assert all(
            hasattr(bpy.types, menu_class.bl_idname)
            for menu_class in bridge._GP_NATIVE_EFFECT_GROUP_MENUS
        )
        grouped_ids = {
            effect_id
            for _label, _icon, effect_ids in bridge._GP_NATIVE_EFFECT_LIBRARY_GROUPS
            for effect_id in effect_ids
        }
        assert grouped_ids == {definition[0] for definition in bridge.GP_NATIVE_EFFECTS}

        same_backend_pair = next((
            (first, second)
            for first, second in zip(ordered_ids, ordered_ids[1:])
            if bridge._gp_native_effect_definition(first)[3]
            == bridge._gp_native_effect_definition(second)[3]
        ), None)
        if same_backend_pair:
            first, second = same_backend_pair
            canvas.fbp_gp_effect_items_index = list_ids.index(first)
            assert bridge._gp_active_native_effect_id(canvas) == first
            assert bridge._gp_move_native_effect(canvas, first, 1)
            moved_ids = [str(row.effect_id) for row in canvas.fbp_gp_effect_items]
            assert moved_ids.index(first) == moved_ids.index(second) + 1, moved_ids
            assert bridge._gp_active_native_effect_id(canvas) == first
            assert bridge._gp_move_native_effect(canvas, first, -1)

        expected_controls = {
            "RIM": {"mask_color", "samples"},
            "SHADOW": {
                "samples", "use_wave", "orientation", "amplitude", "period",
                "phase", "use_object", "object", "scale",
            },
            "GAUSSIAN_BLUR": {"use_dof_mode"},
            "GP_GLOW": {
                "opacity", "size", "samples", "mode", "blend_mode",
                "select_color", "rotation", "use_glow_under",
            },
            "CUTOUT_OUTLINE": {"subdivision", "outline_material", "object"},
        }
        for effect_id, logical_names in expected_controls.items():
            item = instances.get(effect_id)
            if item is None:
                continue
            unresolved = {
                name for name in logical_names
                if not bridge._gp_resolve_native_attr(item, name)
            }
            assert not unresolved, {effect_id: sorted(unresolved)}

        glow = instances.get("GP_GLOW")
        if glow is not None:
            opacity_attr = bridge._gp_resolve_native_attr(glow, "opacity")
            size_attr = bridge._gp_resolve_native_attr(glow, "size")
            samples_attr = bridge._gp_resolve_native_attr(glow, "samples")
            assert abs(float(getattr(glow, opacity_attr)) - 0.35) < 1.0e-5
            assert tuple(round(float(value), 5) for value in getattr(glow, size_attr)) == (6.0, 6.0)
            assert int(getattr(glow, samples_attr)) == 8
            setattr(glow, opacity_attr, 0.9)
            assert bridge._gp_reset_native_effect(canvas, "GP_GLOW")
            assert abs(float(getattr(glow, opacity_attr)) - 0.35) < 1.0e-5

        effect_id = added[0]
        definition = bridge._gp_native_effect_definition(effect_id)
        collection = bridge._gp_native_effect_collection(canvas, definition[3])
        native_type = bridge._gp_supported_native_type(canvas, definition)
        duplicate = bridge._gp_new_native_effect_item(
            collection,
            bridge._gp_native_effect_name(effect_id) + " Duplicate",
            native_type,
        )
        assert duplicate is not None
        assert bridge._gp_tag_native_effect_item(duplicate, effect_id)
        assert bridge._gp_native_effect_id_from_item(
            duplicate, bridge._gp_native_effect_definitions()
        ) == effect_id
        _active, _ordered, _lengths, duplicates = bridge._gp_native_effect_stack_state(canvas)
        assert duplicates.get(effect_id, 0) == 2, duplicates
        assert bridge._gp_repair_native_effect_duplicates(canvas) == 1
        _active, _ordered, _lengths, duplicates = bridge._gp_native_effect_stack_state(canvas)
        assert duplicates.get(effect_id, 0) == 1, duplicates
    for effect_id in reversed(added):
        assert bridge._gp_remove_native_effect(canvas, effect_id), effect_id
    if not supported:
        raise SkipTest("This Blender build exposed no supported native GP effect type")
    assert added, {"supported": supported}
    assert len(canvas.fbp_gp_effect_items) == 0
    return {
        "supported_by_blender": len(supported),
        "created_and_removed": len(added),
        "visual_control_contracts": 5,
        "glow_defaults_reset": True,
        "ui_list_and_grouped_menu": True,
    }


def test_timeline_backport(_module):
    timeline = importlib.import_module(f"{PACKAGE}.timeline_backport")
    workspace = bpy.context.workspace
    window = bpy.context.window
    assert window is not None
    assert hasattr(workspace, "show_jump_to_endpoints")
    assert hasattr(workspace, "show_jump_to_keyframes")
    assert hasattr(workspace, "show_jump_by_delta")
    assert hasattr(workspace, "use_scene_time_sync_follow_scene")
    assert hasattr(workspace, "fbp_use_scene_time_sync")
    assert hasattr(bpy.types, "FBP_PT_time_jump")
    assert hasattr(bpy.types, "FBP_PT_dopesheet_time_sync")
    assert hasattr(bpy.types, "FBP_PT_graph_time_sync")
    assert hasattr(bpy.types, "FBP_PT_nla_time_sync")
    assert hasattr(bpy.types, "FBP_PT_sequencer_time_sync")
    assert sum(
        getattr(handler, "__name__", "") == "fbp_timeline_scene_time_sync"
        for handler in bpy.app.handlers.frame_change_post
    ) == 1

    original_scene = window.scene
    original_sequencer_scene = workspace.sequencer_scene
    original_sync = bool(workspace.fbp_use_scene_time_sync)
    original_follow = bool(workspace.use_scene_time_sync_follow_scene)
    original_native_sync = bool(workspace.use_scene_time_sync)
    master = bpy.data.scenes.new("FBP Timeline Backport Master")
    source = bpy.data.scenes.new("FBP Timeline Backport Source")
    source.frame_start = 1
    strip = master.sequence_editor_create().strips.new_scene(
        "FBP Timeline Scene Strip", source, 3, 20
    )
    try:
        workspace.sequencer_scene = master
        workspace.fbp_use_scene_time_sync = True
        workspace.use_scene_time_sync_follow_scene = False
        assert workspace.use_scene_time_sync is False
        window.scene = source

        master.frame_set(25)
        timeline.fbp_timeline_scene_time_sync(master)
        assert source.frame_current == 6, (master.frame_current, source.frame_current)
        assert window.scene == source

        source.frame_set(12)
        timeline.fbp_timeline_scene_time_sync(source)
        assert master.frame_current == 31, (master.frame_current, source.frame_current)
        assert window.scene == source

        strip.use_reverse_frames = True
        mapped = timeline._timeline_to_scene_frame(master, strip, 25.0)
        assert mapped is not None
        assert abs(timeline._scene_to_timeline_frame(master, strip, mapped) - 25.0) < 1.0e-6
    finally:
        window.scene = original_scene
        workspace.sequencer_scene = original_sequencer_scene
        workspace.use_scene_time_sync_follow_scene = original_follow
        workspace.fbp_use_scene_time_sync = original_sync
        workspace.use_scene_time_sync = original_native_sync
        bpy.data.scenes.remove(master)
        bpy.data.scenes.remove(source)

    return {
        "compact_jump_controls": True,
        "all_time_editor_popovers": 4,
        "bidirectional_scene_strip_sync": True,
        "follow_scene_split": True,
    }


def test_generic_mesh_matrix(_module):
    geo = importlib.import_module(f"{PACKAGE}.geometry_nodes")
    matrix = geo.fbp_generic_mesh_effect_matrix()
    assert matrix and all("reason" in item for item in matrix)
    assert any(item["supported"] for item in matrix)
    assert all(not item["supported"] for item in matrix if item["alpha_aware"])
    assert not geo.fbp_generic_mesh_effect_support('CAMERA_SCALE_LOCK')['supported']
    return {"total": len(matrix), "supported": sum(item["supported"] for item in matrix)}



def _fbp_test_mesh_object(name, vertices, edges, faces):
    mesh = bpy.data.meshes.new(name + " Mesh")
    mesh.from_pydata(vertices, edges, faces)
    mesh.update()
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.scene.collection.objects.link(obj)
    return obj


def test_generic_mesh_topology_profiles(_module):
    geo = importlib.import_module(f"{PACKAGE}.geometry_nodes")

    bpy.ops.mesh.primitive_cube_add()
    closed = bpy.context.object
    closed.name = "FBP Topology Closed"

    bpy.ops.mesh.primitive_plane_add()
    open_surface = bpy.context.object
    open_surface.name = "FBP Topology Open"

    wire = _fbp_test_mesh_object(
        "FBP Topology Wire",
        [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (2.0, 0.0, 0.0)],
        [(0, 1), (1, 2)],
        [],
    )
    non_manifold = _fbp_test_mesh_object(
        "FBP Topology Non Manifold",
        [
            (0.0, 0.0, 0.0),
            (1.0, 0.0, 0.0),
            (0.0, 1.0, 0.0),
            (0.0, -1.0, 0.0),
            (0.0, 0.0, 1.0),
        ],
        [],
        [(0, 1, 2), (1, 0, 3), (0, 1, 4)],
    )

    profiles = {
        "closed": geo.fbp_generic_mesh_topology_profile(closed),
        "open": geo.fbp_generic_mesh_topology_profile(open_surface),
        "wire": geo.fbp_generic_mesh_topology_profile(wire),
        "non_manifold": geo.fbp_generic_mesh_topology_profile(non_manifold),
    }
    assert profiles["closed"]["classification"] == "CLOSED_MANIFOLD", profiles
    assert profiles["open"]["classification"] == "OPEN_SURFACE", profiles
    assert profiles["wire"]["classification"] == "WIRE", profiles
    assert profiles["non_manifold"]["classification"] == "NON_MANIFOLD", profiles
    assert all(profile.get("coordinate_scan_complete") for profile in profiles.values()), profiles
    assert all(profile.get("sampled_vertices") == profile.get("vertices") for profile in profiles.values()), profiles

    for obj in (closed, open_surface, wire, non_manifold):
        valid, _reason, profile = geo.fbp_generic_mesh_preflight(obj)
        assert valid, profile

    original = tuple(float(value) for value in wire.data.vertices[0].co)
    wire.data.vertices[0].co.x = float("nan")
    valid, reason, profile = geo.fbp_generic_mesh_preflight(wire)
    assert not valid and profile["classification"] == "NON_FINITE", (reason, profile)
    wire.data.vertices[0].co = original
    return {key: value["classification"] for key, value in profiles.items()}


def test_generic_mesh_supported_group_contracts(_module):
    geo = importlib.import_module(f"{PACKAGE}.geometry_nodes")
    supported = [item["effect_id"] for item in geo.fbp_generic_mesh_effect_matrix() if item["supported"]]
    checked = []
    missing = []
    invalid = []
    for effect_id in supported:
        group = geo.fbp_load_mesh_wiggle_group() if effect_id == geo.FBP_EFFECT_MESH_WIGGLE else geo._fbp_load_effect_group(effect_id)
        if group is None:
            missing.append(effect_id)
            continue
        has_input, has_output = geo._fbp_node_group_geometry_contract(group)
        if not has_input or not has_output:
            invalid.append(effect_id)
        else:
            checked.append(effect_id)
    assert not invalid, {"invalid_geometry_contracts": invalid}
    if not checked:
        raise SkipTest(f"No bundled Generic Mesh group was available; missing: {missing}")
    return {"checked": len(checked), "missing": missing}


def test_generic_mesh_apply(_module):
    scene = bpy.context.scene
    enabled = scene.fbp_preview_generic_mesh_effects
    try:
        scene.fbp_preview_generic_mesh_effects = True
        return _test_generic_mesh_apply_enabled(_module)
    finally:
        scene.fbp_preview_generic_mesh_effects = enabled


def _test_generic_mesh_apply_enabled(_module):
    geo = importlib.import_module(f"{PACKAGE}.geometry_nodes")
    metadata = geo.mesh_modifier_metadata
    supported = [item["effect_id"] for item in geo.fbp_generic_mesh_effect_matrix() if item["supported"]]
    assert supported, "No Generic Mesh backend is marked supported"
    bpy.ops.mesh.primitive_grid_add(x_subdivisions=4, y_subdivisions=4)
    obj = bpy.context.object
    effect_id = supported[0]
    changed = geo.fbp_apply_geometry_effect_to_mesh_object(obj, effect_id, scene=bpy.context.scene)
    assert changed, f"Supported Generic Mesh effect {effect_id} failed application with Preview enabled"
    owned = [m for m in obj.modifiers if metadata(m).get("fbp_generic_mesh_effect", False)]
    assert len(owned) == 1 and metadata(owned[0]).get("fbp_effect_id") == effect_id
    assert metadata(owned[0]).get("fbp_input_topology") in {
        "CLOSED_MANIFOLD", "OPEN_SURFACE", "NON_MANIFOLD", "LOOSE_GEOMETRY", "WIRE", "POINTS", "EMPTY"
    }
    valid, reason = geo.fbp_validate_generic_mesh_object(obj)
    assert valid, reason

    # Updating an existing FBP modifier is transactional. A failed evaluated
    # result must restore its previous name, group and custom inputs.
    current = owned[0]
    current.name = "FBP Mesh Effect — Rollback Sentinel"
    input_id = geo._fbp_interface_socket_for_name(geo._fbp_interface_inputs(current.node_group), 'Mirror X')
    assert input_id
    geo._fbp_modifier_input_set(current, input_id, True)
    original_validator = geo.fbp_validate_generic_mesh_object
    geo.fbp_validate_generic_mesh_object = lambda *_args, **_kwargs: (False, "forced runner rollback")
    try:
        assert not geo.fbp_apply_geometry_effect_to_mesh_object(obj, effect_id, scene=bpy.context.scene)
    finally:
        geo.fbp_validate_generic_mesh_object = original_validator
    assert current.name == "FBP Mesh Effect — Rollback Sentinel"
    assert geo.fbp_modifier_input_get(current, input_id) is True

    node_group = current.node_group
    obj.modifiers.remove(current)
    artist = obj.modifiers.new(name="Artist Nodes — Must Survive", type="NODES")
    artist.node_group = node_group
    assert not metadata(artist)
    assert geo.fbp_apply_geometry_effect_to_mesh_object(obj, effect_id, scene=bpy.context.scene)
    owned = [m for m in obj.modifiers if metadata(m).get("fbp_generic_mesh_effect", False)]
    assert len(owned) == 1
    assert obj.modifiers.get(artist.name) == artist
    assert not metadata(artist)

    owned = [m for m in obj.modifiers if metadata(m).get("fbp_generic_mesh_effect", False)]
    assert len(owned) == 1
    duplicate = obj.modifiers.new(name="FBP Duplicate Owned Modifier", type="NODES")
    duplicate.node_group = owned[0].node_group
    geo.set_mesh_modifier_metadata(duplicate, metadata(owned[0]))
    assert geo.fbp_generic_mesh_duplicate_effects(obj).get(effect_id) == 2
    assert geo.fbp_repair_generic_mesh_duplicates(obj) == 1
    assert not geo.fbp_generic_mesh_duplicate_effects(obj)
    assert obj.modifiers.get(artist.name) == artist

    # Multi-object application is atomic: a failure on the second target must
    # restore the first object's FBP modifier and remove the second object's
    # newly-created modifier, while preserving artist modifiers on both.
    first_owned = next(m for m in obj.modifiers if metadata(m).get("fbp_generic_mesh_effect", False))
    first_owned.name = "FBP Atomic Rollback Sentinel"
    geo._fbp_modifier_input_set(first_owned, input_id, True)
    bpy.ops.mesh.primitive_grid_add(x_subdivisions=3, y_subdivisions=3)
    failing_obj = bpy.context.object
    failing_obj.name = "FBP Atomic Failure Target"
    failing_artist = failing_obj.modifiers.new(name="Artist Modifier — Atomic", type="NODES")
    failing_artist.node_group = node_group

    original_validator = geo.fbp_validate_generic_mesh_object
    def atomic_validator(target, *_args, **_kwargs):
        if target == failing_obj:
            return False, "forced atomic batch failure"
        return original_validator(target, *_args, **_kwargs)
    geo.fbp_validate_generic_mesh_object = atomic_validator
    try:
        changed, failure = geo.fbp_apply_geometry_effect_to_mesh_objects(
            (obj, failing_obj), effect_id, scene=bpy.context.scene
        )
    finally:
        geo.fbp_validate_generic_mesh_object = original_validator
    assert changed == 0 and "rolled back" in failure, (changed, failure)
    restored_owned = [m for m in obj.modifiers if metadata(m).get("fbp_generic_mesh_effect", False)]
    assert len(restored_owned) == 1
    assert restored_owned[0].name == "FBP Atomic Rollback Sentinel"
    assert geo.fbp_modifier_input_get(restored_owned[0], input_id) is True
    assert not [m for m in failing_obj.modifiers if metadata(m).get("fbp_generic_mesh_effect", False)]
    assert failing_obj.modifiers.get(failing_artist.name) == failing_artist

    return {
        "effect": effect_id,
        "artist_modifier_preserved": True,
        "duplicate_repair": True,
        "atomic_batch_rollback": True,
    }


def test_compositor(_module):
    scene = bpy.context.scene
    sets = importlib.import_module(f"{PACKAGE}.compositor_sets")
    tree = sets._root_tree(scene)
    rgb = tree.nodes.new("CompositorNodeRGB")
    rgb_name = "Artist RGB — Must Survive"
    rgb.name = rgb_name
    mix = tree.nodes.new("ShaderNodeMix")
    mix_name = "Artist Mix — Must Survive"
    mix.name = mix_name
    mix.data_type = "RGBA"
    color_b = next(
        socket for socket in mix.inputs
        if socket.name == "B" and socket.type == "RGBA"
    )
    tree.links.new(rgb.outputs[0], color_b)
    rgb.outputs[0].default_value = (0.15, 0.25, 0.35, 1.0)
    mix.blend_type = "MULTIPLY"
    mix.inputs[0].default_value = 0.375
    mix["artist_note"] = "preserve"

    group_tree = bpy.data.node_groups.new("FBP Artist Group Tree", "CompositorNodeTree")
    group_rgb = group_tree.nodes.new("CompositorNodeRGB")
    group_rgb_name = "Artist Group RGB"
    group_rgb.name = group_rgb_name
    group_rgb.outputs[0].default_value = (0.8, 0.1, 0.2, 1.0)
    group_node = tree.nodes.new("CompositorNodeGroup")
    group_node_name = "Artist Group — Must Survive"
    group_node.name = group_node_name
    group_node.node_tree = group_tree

    # Nested group safety limits must propagate to the root completeness flag.
    # A partial deep-group snapshot is not sufficient to authorize Safe Repair.
    deep_trees = [
        bpy.data.node_groups.new(f"FBP Snapshot Depth {index}", "CompositorNodeTree")
        for index in range(5)
    ]
    for index in range(len(deep_trees) - 1):
        nested_node = deep_trees[index].nodes.new("CompositorNodeGroup")
        nested_node.node_tree = deep_trees[index + 1]
    deep_root_node = tree.nodes.new("CompositorNodeGroup")
    deep_root_node.name = "Artist Deep Group — Snapshot Limit Probe"
    deep_root_node.node_tree = deep_trees[0]
    deep_snapshot = sets.fbp_compositor_artist_graph_snapshot(scene)
    assert not deep_snapshot.get("complete", True), deep_snapshot
    assert any("depth-limit" in error for error in deep_snapshot.get("errors", ())), deep_snapshot
    tree.nodes.remove(deep_root_node)
    for deep_tree in reversed(deep_trees):
        if deep_tree.users == 0:
            bpy.data.node_groups.remove(deep_tree)

    graph_before = sets.fbp_compositor_artist_graph_snapshot(scene)
    assert graph_before.get("complete", False), graph_before
    assert graph_before["nodes"] and graph_before["links"]
    bounded = sets.fbp_compositor_artist_graph_snapshot(scene, max_nodes=1)
    assert not bounded.get("complete", True) and bounded.get("errors"), bounded
    original_label = rgb.label
    rgb.label = "Runner State Mutation"
    assert graph_before != sets.fbp_compositor_artist_graph_snapshot(scene)
    rgb.label = original_label
    assert graph_before == sets.fbp_compositor_artist_graph_snapshot(scene)

    original_color = tuple(rgb.outputs[0].default_value)
    rgb.outputs[0].default_value = (0.9, 0.9, 0.9, 1.0)
    assert graph_before != sets.fbp_compositor_artist_graph_snapshot(scene)
    rgb.outputs[0].default_value = original_color

    original_blend = mix.blend_type
    mix.blend_type = "ADD"
    assert graph_before != sets.fbp_compositor_artist_graph_snapshot(scene)
    mix.blend_type = original_blend

    original_group_color = tuple(group_rgb.outputs[0].default_value)
    group_rgb.outputs[0].default_value = (0.1, 0.8, 0.2, 1.0)
    assert graph_before != sets.fbp_compositor_artist_graph_snapshot(scene)
    group_rgb.outputs[0].default_value = original_group_color
    assert graph_before == sets.fbp_compositor_artist_graph_snapshot(scene)

    issues = sets.fbp_validate_composite(scene)
    current_rgb = tree.nodes.get(rgb_name)
    current_mix = tree.nodes.get(mix_name)
    assert current_rgb is not None and current_mix is not None
    assert current_rgb.as_pointer() == rgb.as_pointer()
    assert current_mix.as_pointer() == mix.as_pointer()
    assert graph_before == sets.fbp_compositor_artist_graph_snapshot(scene)

    # Exercise the same rollback primitive used by Safe Repair.
    backup_state = sets._fbp_safe_repair_backup(scene)
    unsafe_rgb = scene.compositing_node_group.nodes.get(rgb_name)
    unsafe_mix = scene.compositing_node_group.nodes.get(mix_name)
    unsafe_rgb.label = "Unsafe Mutation"
    unsafe_rgb.outputs[0].default_value = (1.0, 1.0, 1.0, 1.0)
    unsafe_mix.blend_type = "SCREEN"
    group_rgb.outputs[0].default_value = (0.0, 1.0, 0.0, 1.0)
    assert sets._fbp_safe_repair_restore(scene, backup_state)
    restored_tree = scene.compositing_node_group
    # The failed root can be removed during rollback, invalidating every RNA
    # node wrapper it owned. Resolve the restored nodes with captured strings.
    restored_rgb = restored_tree.nodes.get(rgb_name)
    restored_mix = restored_tree.nodes.get(mix_name)
    assert restored_rgb is not None and restored_mix is not None
    assert restored_rgb.label == original_label
    assert tuple(restored_rgb.outputs[0].default_value) == original_color
    assert restored_mix.blend_type == original_blend
    assert restored_mix.get("artist_note") == "preserve"
    restored_group = restored_tree.nodes.get(group_node_name)
    assert restored_group is not None and restored_group.node_tree is not None
    restored_group_rgb = restored_group.node_tree.nodes.get(group_rgb_name)
    assert restored_group_rgb is not None
    assert tuple(restored_group_rgb.outputs[0].default_value) == original_group_color
    assert not bool(restored_group.node_tree.get("fbp_safe_repair_nested_backup", False))

    # Successful repair paths must discard the deep backup and every orphaned
    # nested copy instead of leaking hidden NodeTree datablocks.
    discard_state = sets._fbp_safe_repair_backup(scene)
    discard_names = [discard_state["backup"].name] + [tree.name for tree in discard_state.get("nested_backups", ())]
    sets._fbp_safe_repair_discard(discard_state)
    assert all(bpy.data.node_groups.get(name) is None for name in discard_names), discard_names

    duplicate = scene.copy()
    duplicate.name = "FBP Duplicate Scene"
    sets.fbp_ensure_scene_copy_independence(duplicate)
    assert duplicate.name in bpy.data.scenes
    return {
        "artist_nodes": len(graph_before["nodes"]),
        "artist_links": len(graph_before["links"]),
        "issues": len(issues or ()),
        "duplicate_scene": duplicate.name,
    }


def test_toon_boom_contract(_module):
    importer = importlib.import_module(f"{PACKAGE}.operator_import")
    caps = importer.fbp_toon_boom_exchange_capabilities()
    assert caps["raster_export_folder"] is True
    assert caps["native_xstage_import"] is False
    assert caps["round_trip_export"] is False
    return caps


def test_projector_contract(_module):
    projector = importlib.import_module(f"{PACKAGE}.projector")
    assert ".mp4" in projector._MEDIA_EXTENSIONS
    assert ".png" in projector._MEDIA_EXTENSIONS
    assert not (projector._VIDEO_EXTENSIONS & projector._IMAGE_EXTENSIONS)
    return sorted(projector._VIDEO_EXTENSIONS)


def test_save_reopen(_module):
    path = WORKDIR / f"fbp_{RELEASE_TOKEN}_regression.blend"
    bpy.ops.wm.save_as_mainfile(filepath=str(path), check_existing=False)
    assert path.exists() and path.stat().st_size > 0
    bpy.ops.wm.open_mainfile(filepath=str(path), load_ui=False)
    assert bpy.context.scene is not None
    return str(path)


def test_tiny_render(_module):
    scene = bpy.context.scene
    previous_group = getattr(scene, "compositing_node_group", None)
    previous_use_compositing = bool(scene.render.use_compositing)
    scene.compositing_node_group = None
    scene.render.use_compositing = False
    previous_engine = str(scene.render.engine)
    previous_resolution = (
        int(scene.render.resolution_x),
        int(scene.render.resolution_y),
        int(scene.render.resolution_percentage),
    )
    scene.render.resolution_x = 16
    scene.render.resolution_y = 16
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    bpy.ops.mesh.primitive_cube_add()
    cube = bpy.context.object
    bpy.ops.object.camera_add(location=(0.0, -6.0, 0.0))
    camera = bpy.context.object
    camera.rotation_euler = (cube.location - camera.location).to_track_quat("-Z", "Y").to_euler()
    scene.camera = camera
    rendered = {}
    engines = (
        (("cycles", "CYCLES"),)
        if os.environ.get("FBP_TEST_HEADLESS_RENDER_SAFE_ONLY", "") == "1"
        else (
            ("workbench", "BLENDER_WORKBENCH"),
            ("eevee", "BLENDER_EEVEE"),
            ("cycles", "CYCLES"),
        )
    )
    try:
        for label, engine in engines:
            scene.render.engine = engine
            if engine == "CYCLES":
                scene.cycles.samples = 1
                scene.cycles.use_denoising = False
            path = WORKDIR / f"fbp_{RELEASE_TOKEN}_render_{label}.png"
            scene.render.filepath = str(path)
            result = bpy.ops.render.render(write_still=True)
            assert "FINISHED" in result, (engine, result)
            assert path.exists() and path.stat().st_size > 0, (engine, path)
            rendered[label] = str(path)
        return rendered
    finally:
        scene.render.engine = previous_engine
        (
            scene.render.resolution_x,
            scene.render.resolution_y,
            scene.render.resolution_percentage,
        ) = previous_resolution
        scene.compositing_node_group = previous_group
        scene.render.use_compositing = previous_use_compositing


def test_performance_profile_contract(module):
    dashboard = importlib.import_module(f"{PACKAGE}.performance_dashboard")
    geometry = importlib.import_module(f"{PACKAGE}.geometry_nodes")
    scheduler = importlib.import_module(f"{PACKAGE}.runtime_scheduler")
    icons = importlib.import_module(f"{PACKAGE}.ui_icons")
    handlers = importlib.import_module(f"{PACKAGE}.handlers")
    runtime = importlib.import_module(f"{PACKAGE}.runtime")
    coordinator = importlib.import_module(f"{PACKAGE}.generation_transaction")
    scene = bpy.context.scene
    original_frame = int(scene.frame_current)
    profile = dashboard.profile_frame_changes(
        scene,
        frame_count=12,
        warmup=2,
        profile_context="PLAYBACK",
    )
    assert scene.frame_current == original_frame, (scene.frame_current, original_frame)
    assert profile["state_restored"] is True, profile
    assert profile["measured_frames"] == 12, profile
    assert profile["frame_evaluation"]["samples"] == 12, profile
    assert profile["effect_handler"]["timed_samples"] >= 12, profile
    assert profile["scheduler"]["average_task_duration_ms"] >= 0.0, profile
    assert profile["memory"]["python_initial_bytes"] >= 0, profile
    assert profile["memory"]["included_in_timing"] is False, profile
    assert profile["instrumentation"]["timing_tracemalloc"] is False, profile
    assert profile["instrumentation"]["calibration_samples"] == 12, profile
    assert "estimated_overhead_percent" in profile["instrumentation"], profile
    report = dashboard.build_performance_report(scene)
    report["frame_profile"] = profile
    json.dumps(report)
    text = dashboard.performance_report_text(report)
    assert "Profile 120 Frames" in text and "Local runtime profile" in text, text
    startup = module.fbp_startup_profile_snapshot()
    assert startup["register_total_ms"] >= 0.0, startup
    assert "preview_loads" in icons.custom_icon_metrics()
    assert geometry.fbp_effect_runtime_profile_metrics()["timed_samples"] >= 12
    assert "average_dispatch_duration_ms" in scheduler.scheduler_metrics()

    # Every concurrency guard is exercised independently so a later ordering
    # change cannot hide a missing condition behind an earlier rejection.
    dashboard._PROFILE_RUN_ACTIVE = True
    try:
        assert "already active" in dashboard._profile_runtime_block_reason(bpy.context)
    finally:
        dashboard._PROFILE_RUN_ACTIVE = False

    owner, refusal = coordinator.acquire_generation(
        bpy.context,
        operator_id="fbp.profile_guard_test",
        mode="Profiler guard test",
    )
    assert owner is not None, refusal
    try:
        assert "generation" in dashboard._profile_runtime_block_reason(bpy.context).lower()
    finally:
        retired = coordinator.retire_active_generation(
            bpy.context,
            reason="profiler guard test",
            rollback=True,
        )
        assert retired["verified"], retired

    handlers.fbp_set_undo_guard(True, timeout=5.0)
    try:
        assert "Undo" in dashboard._profile_runtime_block_reason(bpy.context)
    finally:
        handlers.fbp_set_undo_guard(False)

    original_render_state = runtime.fbp_render_state
    runtime.fbp_render_state = lambda include_guard=True: runtime.FBP_RENDER_BUSY
    try:
        assert "render" in dashboard._profile_runtime_block_reason(bpy.context).lower()
    finally:
        runtime.fbp_render_state = original_render_state

    fake_context = type(
        "ProfilePlaybackContext",
        (),
        {"screen": type("ProfileScreen", (), {"is_animation_playing": True})()},
    )()
    assert "playback" in dashboard._profile_runtime_block_reason(fake_context).lower()
    assert "background" in dashboard._profile_runtime_block_reason(
        bpy.context,
        reject_background=True,
    ).lower()

    tracemalloc.start()
    try:
        try:
            dashboard.profile_frame_changes(scene, frame_count=1, warmup=0)
        except RuntimeError as exc:
            assert "allocation trace" in str(exc), exc
        else:
            raise AssertionError("Existing tracemalloc run was not refused")
    finally:
        tracemalloc.stop()
    return {
        "measured_frames": 12,
        "handler_samples": profile["effect_handler"]["timed_samples"],
        "timing_tracemalloc": profile["instrumentation"]["timing_tracemalloc"],
        "memory_run_separate": not profile["memory"]["included_in_timing"],
        "estimated_overhead_percent": profile["instrumentation"]["estimated_overhead_percent"],
        "concurrency_guards": [
            "playback",
            "render",
            "generation",
            "undo_load",
            "active_profiler",
            "external_tracemalloc",
            "background_operator",
        ],
        "state_restored": True,
        "json_serializable": True,
    }


def test_icon_runtime_contract(_module):
    icons = importlib.import_module(f"{PACKAGE}.ui_icons")
    icons.unregister_custom_icons()
    icons.custom_icon_metrics(reset=True)
    assert icons.register_custom_icons()
    preload = icons.custom_icon_metrics()
    assert preload["preview_loads"] <= 12, preload
    assert preload["logical_cache_entries"] <= 12, preload
    assert icons._registered_icon_key("layer.visible_on") == "HIDE_OFF"

    before_loads = int(preload["preview_loads"])
    values = tuple(
        icons.effect_custom_icon_value(effect_id)
        for effect_id in ("GP_MASK_SLOT_2", "GP_MASK_SLOT_3", "GP_MASK_SLOT_4")
    )
    after = icons.custom_icon_metrics()
    if any(values):
        assert len(set(values)) == 1, values
        assert int(after["preview_loads"]) - before_loads == 1, (preload, after)
        assert int(after["path_alias_hits"]) >= 2, after
    return {
        "preloaded": preload["preview_loads"],
        "duplicate_alias_ids": values,
        "alias_hits": after["path_alias_hits"],
        "filesystem_checks": after["filesystem_checks"],
    }


def _redraw_all(iterations=1):
    for window in tuple(bpy.context.window_manager.windows):
        for area in tuple(window.screen.areas):
            area.tag_redraw()
    if bpy.ops.wm.redraw_timer.poll():
        bpy.ops.wm.redraw_timer(type="DRAW_WIN_SWAP", iterations=max(1, int(iterations)))


def _prepare_view3d_sidebars():
    count = 0
    for window in tuple(bpy.context.window_manager.windows):
        for area in tuple(window.screen.areas):
            if area.type != "VIEW_3D":
                continue
            try:
                area.spaces.active.show_region_ui = True
            except Exception:
                pass
            area.tag_redraw()
            count += 1
    return count


def test_interactive_layer_tree_gp(_module):
    if bpy.app.background:
        raise SkipTest("Interactive UI required")
    layers = importlib.import_module(f"{PACKAGE}.layers")
    ui_layout = importlib.import_module(f"{PACKAGE}.ui_layout")
    scene = bpy.context.scene
    view_count = _prepare_view3d_sidebars()
    if not view_count:
        raise SkipTest("No View3D area available for sidebar redraw stress")

    root = layers.get_or_create_child_collection(scene.collection, "FBP UI Stress Root")
    children = []
    for index in range(20):
        parent = root if index < 10 else children[index - 10]
        child = layers.get_or_create_child_collection(parent, f"FBP UI Child {index:02d}")
        children.append(child)

    result = bpy.ops.fbp.add_grease_pencil_canvas(
        "EXEC_DEFAULT",
        canvas_name="FBP GP Stress",
        owner_name="__FREE__",
        enter_draw_mode=False,
    )
    assert "FINISHED" in result, result
    canvas = bpy.context.object
    ui_layout.fbp_refresh_layer_tree_rows(bpy.context)
    canvas.fbp_gp_ui_show_unavailable_effects = True
    canvas.fbp_gp_effect_compatibility_filter = "GEOMETRY_CANDIDATE"
    _redraw_all(2)
    copy_result = bpy.ops.fbp.copy_gp_effect_compatibility_report("EXEC_DEFAULT")
    assert "FINISHED" in copy_result, copy_result
    assert "Grease Pencil Effect Compatibility" in bpy.context.window_manager.clipboard
    preview_result = bpy.ops.fbp.copy_preview_diagnostics("EXEC_DEFAULT")
    assert "FINISHED" in preview_result, preview_result
    assert "Preview Feature Diagnostics" in bpy.context.window_manager.clipboard
    canvas.fbp_gp_ui_show_unavailable_effects = False
    canvas.fbp_gp_effect_compatibility_filter = "ALL"

    for index in range(300):
        scene.frame_set((index % 48) + 1)
        canvas.hide_viewport = bool(index & 1)
        canvas.hide_viewport = False
        child = children[index % len(children)]
        child.fbp_collapsed = bool(index & 1)
        if index % 5 == 0:
            child.hide_viewport = not child.hide_viewport
        if index % 10 == 0:
            ui_layout.fbp_schedule_layer_tree_rebuild(bpy.context, force=True)
        _redraw_all(1)
    return "300 View3D sidebar redraw cycles with GP and nested managed collections"


def test_interactive_generation_lock_windows(_module):
    if bpy.app.background:
        raise SkipTest("Interactive UI required")
    coordinator = importlib.import_module(f"{PACKAGE}.generation_transaction")
    original_window = bpy.context.window
    if len(bpy.context.window_manager.windows) < 2 and bpy.ops.screen.userpref_show.poll():
        bpy.ops.screen.userpref_show("INVOKE_DEFAULT")
        _redraw_all(2)
    other_window = next(
        (window for window in bpy.context.window_manager.windows if window != original_window),
        None,
    )
    if other_window is None:
        raise SkipTest("Blender did not expose a second interactive window")

    owner, refusal = coordinator.acquire_generation(
        bpy.context,
        operator_id="fbp.generate_multiplane",
        mode="Window A Multiplane",
    )
    assert owner is not None, refusal
    try:
        with bpy.context.temp_override(window=other_window):
            same_blocked, same_reason = coordinator.acquire_generation(
                bpy.context,
                operator_id="fbp.generate_multiplane",
                mode="Window B Multiplane",
            )
            blocked, blocked_reason = coordinator.acquire_generation(
                bpy.context,
                operator_id="fbp.import_sequence",
                mode="Window B Sequence",
            )
        assert same_blocked is None, same_blocked
        assert "Window A Multiplane" in same_reason, same_reason
        assert blocked is None, blocked
        assert "Window A Multiplane" in blocked_reason, blocked_reason
        assert coordinator.active_generation_snapshot()["window_pointer"] == owner.window_pointer
    finally:
        rollback = coordinator.retire_active_generation(
            bpy.context,
            reason="interactive two-window regression",
            rollback=True,
        )
    assert rollback["verified"], rollback
    assert coordinator.active_generation_snapshot() == {}
    return {
        "windows": len(bpy.context.window_manager.windows),
        "same_operator_refused": True,
        "different_operator_refused": True,
        "blocked_job_never_became_owner": True,
        "owner_continued": True,
        "rollback_verified": True,
    }


def test_interactive_scrub_header_contract(_module):
    """Keep the native header draw intact while using its centered lane."""
    if bpy.app.background:
        raise SkipTest("Interactive UI required")
    header = bpy.types.VIEW3D_HT_header
    centered = header.draw_xform_template
    from bl_ui import space_view3d as native_view3d

    gp_centered = native_view3d.draw_topbar_grease_pencil_layer_panel
    assert not bool(getattr(header.draw, "_fbp_scrub_header_patch", False))
    assert bool(getattr(centered, "_fbp_scrub_xform_patch", False))
    assert callable(getattr(centered, "_fbp_original_draw", None))
    assert bool(getattr(gp_centered, "_fbp_scrub_gp_layer_patch", False))
    assert callable(getattr(gp_centered, "_fbp_original_draw", None))
    viewports = []
    for window in tuple(bpy.context.window_manager.windows):
        screen = getattr(window, "screen", None)
        for area in tuple(getattr(screen, "areas", ()) or ()):
            if area.type != "VIEW_3D":
                continue
            headers = [
                (int(region.width), int(region.height))
                for region in area.regions
                if region.type == "HEADER"
            ]
            assert headers, "View3D has no header region"
            assert all(width > 0 and height >= 20 for width, height in headers), headers
            viewports.append(headers)
    assert viewports, "Interactive test has no View3D area"
    return {
        "native_draw_preserved": True,
        "centered_xform_patch": True,
        "centered_gp_layer_patch": True,
        "viewports": len(viewports),
    }


def test_interactive_reload_and_splash(module):
    if bpy.app.background:
        raise SkipTest("Interactive UI required")
    feedback = importlib.import_module(f"{PACKAGE}.feedback")
    prefs = feedback._preferences()
    if prefs is None:
        # Direct-source registration does not create an enabled extension entry
        # in Preferences. A primitive stand-in still exercises window selection,
        # scheduling and the native Preferences dialog path without RNA capture.
        class TestPreferences:
            whats_new_enabled = True
            whats_new_last_seen_version = PREVIOUS_RELEASE

        prefs = TestPreferences()
        feedback._preferences = lambda _context=None: prefs
    else:
        prefs.whats_new_enabled = True
        prefs.whats_new_last_seen_version = PREVIOUS_RELEASE

    before = len(bpy.context.window_manager.windows)
    if bpy.ops.screen.userpref_show.poll():
        bpy.ops.screen.userpref_show("INVOKE_DEFAULT")
        _redraw_all(2)
    module.unregister()
    module.register()
    test_interactive_scrub_header_contract(module)
    feedback = importlib.import_module(f"{PACKAGE}.feedback")
    safe_tasks = importlib.import_module(f"{PACKAGE}.safe_tasks")
    scheduled = feedback.fbp_schedule_whats_new_prompt(delay=0.05)
    if not scheduled and safe_tasks.scheduled_task_pending("fbp_whats_new_prompt"):
        # feedback.register() already claimed and queued the single automatic
        # prompt during module.register(). Accelerate that existing request for
        # the interactive runner instead of treating the intended deduplication
        # result as a scheduling failure.
        scheduled = safe_tasks.schedule_once(
            "fbp_whats_new_prompt",
            feedback._try_show_whats_new_prompt,
            first_interval=0.05,
        )
    assert scheduled, "What's New prompt was not scheduled after update"
    for _ in range(8):
        _redraw_all(1)
        time.sleep(0.03)
    after = len(bpy.context.window_manager.windows)
    return {"scheduled": True, "windows_before": before, "windows_after": after}


def finish(module):
    cleanup_error = ""
    try:
        if module is not None:
            module.unregister()
    except Exception as exc:
        cleanup_error = f"{type(exc).__name__}: {exc}"
    failures = [item for item in RESULTS if item["status"] == "FAIL"]
    payload = {
        "suite": SUITE,
        "run_id": RUN_ID,
        "blender": bpy.app.version_string,
        "addon_release": RELEASE_VERSION,
        "results": RESULTS,
        "passed": not failures and not cleanup_error,
        "failed": len(failures),
        "skipped": sum(item["status"] == "SKIP" for item in RESULTS),
        "cleanup_error": cleanup_error,
        "workdir": str(WORKDIR),
    }
    _write_json_atomic(REPORT, payload)
    if os.environ.get("FBP_TEST_NO_QUIT", "") != "1":
        bpy.ops.wm.quit_blender()


def run_background():
    reset_file()
    record("blender_version", test_version)
    holder = {}

    def reg():
        holder["m"], detail = test_register_cycles()
        return detail

    record("register_unregister_reload", reg)
    module = holder.get("m")
    if module:
        tests = (
            ("release_metadata_sync", test_release_sync),
            ("control_panel_and_camera_contract", test_control_panel_and_camera_contract),
            ("camera_output_format", test_camera_output_format),
            ("camera_pixels_and_presets", test_camera_pixels_and_presets),
            ("effect_evolution_handler_lifecycle", test_effect_evolution_handler_lifecycle),
            ("registration_failure_transaction", test_registration_failure_transaction),
            ("generation_timer_deadline", test_generation_timer_deadline),
            ("generation_progress_and_rollback", test_generation_progress_and_rollback),
            ("incremental_generation_owner_contract", test_incremental_generation_owner_contract),
            ("incremental_progress_owner_contract", test_incremental_progress_owner_contract),
            ("fast_import_preserves_global_undo", test_fast_import_preserves_global_undo),
            ("incremental_user_state_rollback", test_incremental_user_state_rollback),
            ("incremental_lifecycle_and_deep_rollback", test_incremental_lifecycle_and_deep_rollback),
            ("synchronous_media_generation", test_synchronous_media_generation),
            ("scheduler_rna_capture_guard", test_scheduler_rna_capture),
            ("collections_and_layer_tree", test_collections),
            ("undo_redo", test_undo_redo),
            ("scrub_bar_regressions", test_scrub_bar_regressions),
            ("timeline_pr_162412_backport", test_timeline_backport),
            ("gp_effect_support", test_gp_support),
            ("gp_runtime_cache_cleanup", test_gp_runtime_cache_cleanup),
            ("felt_fuzz_canonical_contract", test_felt_fuzz_canonical_contract),
            ("audited_operator_tooltips", test_audited_operator_tooltips),
            ("preview_scope_policy", test_preview_scope_policy),
            ("irreversible_action_contracts", test_irreversible_action_contracts),
            ("gp_native_apply_remove", test_gp_native_apply),
            ("generic_mesh_matrix", test_generic_mesh_matrix),
            ("generic_mesh_topology_profiles", test_generic_mesh_topology_profiles),
            ("generic_mesh_group_contracts", test_generic_mesh_supported_group_contracts),
            ("generic_mesh_artist_modifier_preservation", test_generic_mesh_apply),
            ("compositor_artist_graph", test_compositor),
            ("toon_boom_contract", test_toon_boom_contract),
            ("projector_contract", test_projector_contract),
            ("performance_profile_contract", test_performance_profile_contract),
            ("icon_runtime_contract", test_icon_runtime_contract),
            ("save_reopen", test_save_reopen),
            ("tiny_render", test_tiny_render),
        )
        for name, function in tests:
            record(name, lambda function=function: function(module))
    finish(module)


def run_interactive():
    reset_file()
    record("blender_version", test_version)
    holder = {}

    def reg():
        holder["m"] = import_addon(fresh=True)
        return "registered"

    record("register", reg)

    def delayed():
        module = holder.get("m")
        if module:
            record("undo_redo_20_cycles", lambda: test_undo_redo(module))
            record("icon_runtime_contract", lambda: test_icon_runtime_contract(module))
            record("generation_lock_two_windows", lambda: test_interactive_generation_lock_windows(module))
            record("scrub_header_native_center_contract", lambda: test_interactive_scrub_header_contract(module))
            record("layer_tree_gp_redraw_stress", lambda: test_interactive_layer_tree_gp(module))
            record("preferences_reload_and_splash", lambda: test_interactive_reload_and_splash(module))
        finish(module)
        return None

    bpy.app.timers.register(delayed, first_interval=0.75)


run_interactive() if SUITE == "interactive" else run_background()
