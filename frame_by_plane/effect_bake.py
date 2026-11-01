"""Apply Effects: bake a layer's image effects into its pixels.

Image effects are shader nodes in the plane material, so they only show in
Material Preview and Rendered shading. This operator writes the final colour
and alpha of the plane material, one PNG per frame, into
``assets/baked`` beside the .blend. The layer then plays the baked frames and
its image effects are switched off (not removed), so they can be switched back
on. With "Keep Original" a copy of the layer plays the baked frames instead,
and the original is hidden but otherwise left as it was.

Geometry (mesh) effects are not baked: they are switched off while baking and
stay live afterwards.

Two engines are offered:

* **EEVEE** renders the plane alone, in a temporary scene, through an
  orthographic camera fitted to the plane's UV square, so one render pixel is
  one image pixel. It is the fastest on a GPU and matches Material Preview.
* **Cycles** bakes the material in UV space. It is exact for any plane shape
  and works without a GPU, but is slower.

Workbench is not offered: it does not run shader nodes, so it would write the
image without its effects.

Cycles speed: each frame is one Cycles bake. The material is routed to
``Mix(Transparent, Emission)`` and baked as a Combined pass that keeps only
emission, so Cycles writes the colour and the alpha in the same pass (two
Emit bakes used to be needed). Auto tiling is switched off while baking, so
Cycles bakes the whole image as one tile instead of many 2048 px tiles.

The Combined pass is premultiplied and scene linear, so it is baked into a
float image and turned into straight sRGB before the PNG is written. Because
the texture's Alpha stays connected while baking, Cycles also no longer
premultiplies the source colour, which darkened soft edges in older bakes.
"""

from __future__ import annotations

import os
import re

import bpy
from bpy.props import BoolProperty, EnumProperty, IntProperty, StringProperty
from bpy.types import Operator

from .runtime import FBP_DATA_ERRORS, fbp_release_orphan_image, fbp_warn
from .user_storage import fbp_project_assets_dir, fbp_user_data_dir


FBP_BAKE_MAX_SIZE = 8192
_BAKE_NODE_TAG = "fbp_effect_bake_temporary"
_SAFE_NAME = re.compile(r"[^A-Za-z0-9_\-]+")


def _safe_name(value):
    return _SAFE_NAME.sub("_", str(value or "layer")).strip("_") or "layer"


def _plane_materials(plane):
    materials = []
    for slot in getattr(plane, "material_slots", ()) or ():
        material = getattr(slot, "material", None)
        if material is not None and getattr(material, "node_tree", None) and material not in materials:
            materials.append(material)
    return materials


def _source_size(materials):
    """Pixel size of the layer's own image, used for the baked frames."""
    for material in materials:
        nodes = sorted(
            material.node_tree.nodes,
            key=lambda node: not str(getattr(node, "name", "")).startswith("FBP_Native_Media"),
        )
        for node in nodes:
            image = getattr(node, "image", None) if node.type == "TEX_IMAGE" else None
            if image is None:
                continue
            try:
                width, height = int(image.size[0]), int(image.size[1])
                if not (width and height) and image.source in {"SEQUENCE", "MOVIE", "FILE"}:
                    # Sequences have no size until the viewport draws a frame.
                    width, height = _file_image_size(image)
            except FBP_DATA_ERRORS:
                continue
            if width > 0 and height > 0:
                scale = min(1.0, FBP_BAKE_MAX_SIZE / float(max(width, height)))
                return max(1, int(width * scale)), max(1, int(height * scale))
    return 0, 0


def _file_image_size(image):
    path = bpy.path.abspath(getattr(image, "filepath", "") or "")
    if not path or not os.path.isfile(path):
        return 0, 0
    probe = bpy.data.images.load(path, check_existing=False)
    try:
        return int(probe.size[0]), int(probe.size[1])
    finally:
        fbp_release_orphan_image(probe)


def _input_source(node, names):
    """Return (from_socket, default) for the first matching input of node."""
    for name in names:
        socket = node.inputs.get(name) if node is not None else None
        if socket is None:
            continue
        if socket.links:
            return socket.links[0].from_socket, None
        return None, getattr(socket, "default_value", None)
    return None, None


class _MaterialRouting:
    """Temporarily route a material to ``Mix(Transparent, Emission)``.

    The Emission takes the final colour and the Mix factor the final alpha, so
    one Combined bake (emission only) gives both straight colour and alpha.
    """

    def __init__(self, material, target_image):
        from .materials import fbp_active_surface_chain

        self.tree = material.node_tree
        out, shader, mix, _transparent = fbp_active_surface_chain(material)
        if out is None:
            raise RuntimeError(f"Material '{material.name}' has no Material Output")
        self.surface = out.inputs.get("Surface") or out.inputs[0]
        self.original = self.surface.links[0].from_socket if self.surface.links else None
        self.color = _input_source(shader, ("Color", "Base Color"))
        if mix is not None:
            self.alpha = _input_source(mix, ("Fac", "Factor"))
            if self.alpha == (None, None):
                self.alpha = (mix.inputs[0].links[0].from_socket, None) if mix.inputs[0].links else (None, mix.inputs[0].default_value)
        else:
            self.alpha = _input_source(shader, ("Alpha",))
            if self.alpha == (None, None):
                self.alpha = (None, 1.0)
        nodes = self.tree.nodes
        self.emission = nodes.new("ShaderNodeEmission")
        self.emission.inputs["Strength"].default_value = 1.0
        self.transparent = nodes.new("ShaderNodeBsdfTransparent")
        self.transparent.inputs["Color"].default_value = (1.0, 1.0, 1.0, 1.0)
        self.mix = nodes.new("ShaderNodeMixShader")
        self.target = nodes.new("ShaderNodeTexImage")
        self.target.image = target_image
        self._nodes = (self.emission, self.transparent, self.mix, self.target)
        for node in self._nodes:
            node[_BAKE_NODE_TAG] = True
        self.previous_active = nodes.active
        nodes.active = self.target

    def route(self):
        links = self.tree.links
        source, default = self.color
        color_input = self.emission.inputs["Color"]
        if source is not None:
            links.new(source, color_input)
        elif default is not None:
            try:
                values = tuple(default)
            except TypeError:
                values = (float(default),) * 3
            color_input.default_value = (*values[:3], 1.0) if len(values) >= 3 else (values[0],) * 3 + (1.0,)
        source, default = self.alpha
        factor = self.mix.inputs[0]
        if source is not None:
            links.new(source, factor)
        else:
            try:
                factor.default_value = float(default if default is not None else 1.0)
            except (TypeError, ValueError):
                factor.default_value = 1.0
        links.new(self.transparent.outputs[0], self.mix.inputs[1])
        links.new(self.emission.outputs["Emission"], self.mix.inputs[2])
        links.new(self.mix.outputs[0], self.surface)

    def restore(self):
        links = self.tree.links
        try:
            while self.surface.links:
                links.remove(self.surface.links[0])
            if self.original is not None:
                links.new(self.original, self.surface)
        except FBP_DATA_ERRORS as exc:
            fbp_warn("Could not restore the material after Apply Effects", exc)
        for node in self._nodes:
            try:
                self.tree.nodes.remove(node)
            except FBP_DATA_ERRORS:
                pass
        try:
            if self.previous_active is not None:
                self.tree.nodes.active = self.previous_active
        except FBP_DATA_ERRORS:
            pass


def _bake_output_directory(rig):
    """Return a new folder for one bake and the file prefix.

    Every bake gets its own numbered folder: the layer may already play the
    frames of an earlier bake, so those files are never overwritten.
    """
    name = _safe_name(getattr(rig, "name", "layer"))
    parent = fbp_project_assets_dir("baked", name) or fbp_user_data_dir("baked", name)
    if not parent:
        raise OSError("No writable folder for the baked frames")
    index = 1
    while os.path.exists(os.path.join(parent, f"bake_{index:03d}")):
        index += 1
    root = os.path.join(parent, f"bake_{index:03d}")
    os.makedirs(root)
    return root, f"{name}_"


ENGINE_ITEMS = (
    ("EEVEE", "EEVEE", "Render the plane with EEVEE. Fastest on a GPU and matches Material Preview"),
    ("CYCLES", "Cycles", "Bake the material with Cycles. Exact for any plane shape, slower"),
)

# Rough seconds for an estimate before the first run: (setup, per frame,
# per megapixel and sample). Each run measures how far off they were on this
# computer and scales later estimates for that engine.
_DEFAULT_TIMING = {
    "EEVEE": (1.0, 0.15, 0.05),
    "CYCLES": (2.0, 0.3, 0.6),
}
_timing_scale = {}


def _default_estimate(engine, frame_count, width, height, samples):
    setup, per_frame, per_megapixel = _DEFAULT_TIMING[engine]
    megapixels = width * height / 1_000_000.0
    return setup + frame_count * (per_frame + per_megapixel * megapixels * max(1, samples))


def fbp_apply_effects_estimate(engine, frame_count, width, height, samples):
    """Return (seconds, measured) for one Apply Effects run."""
    seconds = _default_estimate(engine, frame_count, width, height, samples)
    scale = _timing_scale.get(engine)
    return seconds * (scale or 1.0), scale is not None


def _remember_timing(engine, seconds, frame_count, width, height, samples):
    expected = _default_estimate(engine, frame_count, width, height, samples)
    if expected <= 0 or seconds <= 0:
        return
    scale = seconds / expected
    previous = _timing_scale.get(engine)
    _timing_scale[engine] = scale if previous is None else (previous + scale) * 0.5


def _format_seconds(seconds):
    seconds = max(1, int(round(seconds)))
    if seconds < 60:
        return f"{seconds} s"
    minutes, rest = divmod(seconds, 60)
    if minutes < 60:
        return f"{minutes} min {rest:02d} s"
    hours, minutes = divmod(minutes, 60)
    return f"{hours} h {minutes:02d} min"


class FBP_OT_ApplyImageEffects(Operator):
    bl_idname = "fbp.apply_image_effects"
    bl_label = "Apply Effects"
    bl_description = (
        "Bake the image effects of the active layer into new images that the layer "
        "then plays, so the result shows in Solid view too. The image effects are "
        "switched off, not removed. Mesh effects stay live"
    )
    bl_options = {"REGISTER", "UNDO"}

    engine: EnumProperty(
        name="Engine",
        description="How the effects are written into the images",
        items=ENGINE_ITEMS,
        default="EEVEE",
    )
    frames: EnumProperty(
        name="Frames",
        description="Which frames to bake",
        items=(
            ("CURRENT", "Current Frame", "Bake only the current frame into a still image"),
            ("SCENE", "Scene Range", "Bake every frame from Scene Start to Scene End"),
            ("CUSTOM", "Custom Range", "Bake the frames between Start and End"),
        ),
        default="SCENE",
    )
    frame_start: IntProperty(name="Start", description="First frame to bake", default=1)
    frame_end: IntProperty(name="End", description="Last frame to bake", default=250)
    frame_step: IntProperty(
        name="Step",
        description="Bake one frame every Step frames; each baked image is held for Step frames",
        default=1, min=1, soft_max=12,
    )
    resolution: IntProperty(
        name="Resolution",
        description="Size of the baked images, as a percentage of the layer's image",
        default=100, min=5, max=100, subtype="PERCENTAGE",
    )
    samples: IntProperty(
        name="Samples",
        description="Samples per pixel. One is exact for most effects; more smooths noisy or blurred effects",
        default=1, min=1, soft_max=64,
    )
    keep_original: BoolProperty(
        name="Keep Original",
        description="Put the baked images on a copy of the layer and hide the original instead",
        default=False,
    )
    rig_name: StringProperty(default="", options={"HIDDEN", "SKIP_SAVE"})

    @classmethod
    def poll(cls, context):
        return _active_rig(context) is not None

    def invoke(self, context, event):
        from .layers import fbp_layer_backend_type

        rig = _active_rig(context)
        if (
            rig is not None
            and not self.properties.is_property_set("frames")
            and fbp_layer_backend_type(rig) == "NATIVE_IMAGE"
        ):
            self.frames = "CURRENT"
        scene = context.scene
        if self.frame_end < self.frame_start or not self.properties.is_property_set("frame_start"):
            self.frame_start = int(scene.frame_start)
            self.frame_end = int(scene.frame_end)
        return context.window_manager.invoke_props_dialog(self, width=360)

    def _frame_list(self, scene):
        if self.frames == "CURRENT":
            return [int(scene.frame_current)]
        if self.frames == "CUSTOM":
            first, last = sorted((int(self.frame_start), int(self.frame_end)))
        else:
            first, last = int(scene.frame_start), int(scene.frame_end)
        return list(range(first, last + 1, max(1, int(self.frame_step))))

    def _size(self, width, height):
        scale = max(5, min(100, int(self.resolution))) / 100.0
        return max(1, int(round(width * scale))), max(1, int(round(height * scale)))

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False
        layout.prop(self, "engine", expand=True)
        layout.prop(self, "frames")
        if self.frames == "CUSTOM":
            column = layout.column(align=True)
            column.prop(self, "frame_start")
            column.prop(self, "frame_end")
        if self.frames != "CURRENT":
            layout.prop(self, "frame_step")
        layout.prop(self, "resolution", slider=True)
        layout.prop(self, "samples")
        layout.prop(self, "keep_original")

        rig = bpy.data.objects.get(self.rig_name) if self.rig_name else _active_rig(context)
        plane = getattr(rig, "fbp_plane_target", None) if rig else None
        width, height = _source_size(_plane_materials(plane)) if plane else (0, 0)
        count = len(self._frame_list(context.scene))
        box = layout.box()
        column = box.column(align=True)
        if width:
            width, height = self._size(width, height)
            seconds, measured = fbp_apply_effects_estimate(self.engine, count, width, height, self.samples)
            column.label(text=f"{count} frame(s) at {width} x {height} px", icon="RENDER_ANIMATION")
            column.label(
                text=f"{'About' if measured else 'Roughly'} {_format_seconds(seconds)}",
                icon="TIME",
            )
            if not measured:
                column.label(text="The estimate improves after the first run")
        else:
            column.label(text=f"{count} frame(s)", icon="RENDER_ANIMATION")

    def execute(self, context):
        import time

        from .layers import fbp_layer_backend_type

        rig = bpy.data.objects.get(self.rig_name) if self.rig_name else _active_rig(context)
        if rig is None:
            self.report({"WARNING"}, "Select a Frame By Plane image layer")
            return {"CANCELLED"}
        if fbp_layer_backend_type(rig) not in {"NATIVE_IMAGE", "NATIVE_SEQUENCE", "NATIVE_MOVIE"}:
            self.report({"WARNING"}, "Apply Effects works on image, sequence and video layers")
            return {"CANCELLED"}
        plane = getattr(rig, "fbp_plane_target", None)
        materials = _plane_materials(plane) if plane else []
        width, height = _source_size(materials)
        if not materials or not width:
            self.report({"WARNING"}, "This layer has no image to bake")
            return {"CANCELLED"}
        if context.mode != "OBJECT":
            self.report({"WARNING"}, "Switch to Object Mode first")
            return {"CANCELLED"}
        if plane.hide_render or not plane.visible_get():
            self.report({"WARNING"}, "Show the layer before applying its effects")
            return {"CANCELLED"}

        width, height = self._size(width, height)
        frame_list = self._frame_list(context.scene)
        if not frame_list:
            self.report({"WARNING"}, "No frames to bake")
            return {"CANCELLED"}
        step = 1 if self.frames == "CURRENT" else max(1, int(self.frame_step))
        try:
            directory, prefix = _bake_output_directory(rig)
        except OSError as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}

        started = time.perf_counter()
        try:
            if self.engine == "EEVEE":
                files = _render_frames(
                    context, rig, plane, materials, width, height, frame_list, directory, prefix,
                    samples=self.samples,
                )
            else:
                files = _bake_frames(
                    context, rig, plane, materials, width, height, frame_list, directory, prefix,
                    samples=self.samples,
                )
        except Exception as exc:
            fbp_warn("Apply Effects bake failed", exc)
            self.report({"ERROR"}, f"Could not bake the effects: {exc}")
            return {"CANCELLED"}
        elapsed = time.perf_counter() - started
        _remember_timing(self.engine, elapsed, len(frame_list), width, height, self.samples)

        if self.keep_original:
            target = _create_baked_layer(context, rig, directory, files, frame_list[0], step)
        else:
            target = rig if _apply_baked_frames(rig, directory, files, frame_list[0], step) else None
        if target is None:
            self.report(
                {"WARNING"},
                f"Baked {len(files)} frame(s) to {directory}, but could not load them on the layer",
            )
            return {"FINISHED"}
        engine = "EEVEE" if self.engine == "EEVEE" else "Cycles"
        self.report(
            {"INFO"},
            f"Baked {len(files)} frame(s) into '{target.name}' with {engine} in {_format_seconds(elapsed)}",
        )
        return {"FINISHED"}


def _active_rig(context):
    try:
        from .layers import fbp_resolve_rig_from_any_object
        return fbp_resolve_rig_from_any_object(getattr(context, "object", None), context)
    except FBP_DATA_ERRORS:
        return None


def _geometry_effect_modifiers(rig):
    try:
        from .effects_registry import FBP_EFFECT_REGISTRY
        from .geometry_nodes import fbp_effect_ids_for_rig, fbp_find_effect_modifier
    except ImportError:
        return []
    modifiers = []
    for effect_id in fbp_effect_ids_for_rig(rig):
        if FBP_EFFECT_REGISTRY.get(effect_id, {}).get("kind") != "GEOMETRY":
            continue
        modifier = fbp_find_effect_modifier(rig, effect_id)
        if modifier is not None and modifier not in modifiers:
            modifiers.append(modifier)
    return modifiers


def _new_image(name, width, height, colorspace):
    image = bpy.data.images.new(name, width, height, alpha=True, float_buffer=False)
    try:
        image.colorspace_settings.name = colorspace
    except FBP_DATA_ERRORS:
        pass
    return image


def _straight_srgb(pixels):
    """Premultiplied scene-linear RGBA (flat float32) to straight sRGB, in place."""
    import numpy

    rgba = pixels.reshape(-1, 4)
    alpha = rgba[:, 3]
    rgb = rgba[:, :3]
    covered = alpha > 1e-6
    rgb[covered] /= alpha[covered, None]
    rgb[~covered] = 0.0
    numpy.clip(rgb, 0.0, 1.0, out=rgb)
    low = rgb <= 0.0031308
    encoded = numpy.power(rgb, 1.0 / 2.4, dtype=numpy.float32)
    encoded *= 1.055
    encoded -= 0.055
    encoded[low] = rgb[low] * 12.92
    rgb[...] = encoded
    numpy.clip(alpha, 0.0, 1.0, out=alpha)
    return pixels


def _bake_frames(context, rig, plane, materials, width, height, frame_list, directory, prefix, samples=1):
    import numpy

    scene = context.scene
    render = scene.render
    bake = render.bake
    saved = {
        "engine": render.engine,
        "frame": int(scene.frame_current),
        "margin": bake.margin,
        "use_clear": bake.use_clear,
        "use_selected_to_active": bake.use_selected_to_active,
        "target": bake.target,
    }
    frame_changed = False
    cycles = getattr(scene, "cycles", None)
    saved_cycles = {}
    modifiers = [(modifier, bool(modifier.show_render)) for modifier in _geometry_effect_modifiers(rig)]
    bake_image = bpy.data.images.new("FBP Bake Linear", width, height, alpha=True, float_buffer=True)
    output_image = _new_image("FBP Bake Output", width, height, "sRGB")
    pixels = numpy.empty(width * height * 4, dtype=numpy.float32)
    routings = []
    files = []
    window_manager = context.window_manager
    try:
        render.engine = "CYCLES"
        cycles = getattr(scene, "cycles", None)
        if cycles is not None:
            # One whole-image tile: Cycles' default 2048 px auto tiles make a
            # large bake about 1.5x slower and a bake needs no tiling memory.
            for key, value in (("samples", max(1, int(samples))), ("use_denoising", False), ("use_auto_tile", False)):
                if hasattr(cycles, key):
                    saved_cycles[key] = getattr(cycles, key)
                    setattr(cycles, key, value)
        bake.margin = 0
        bake.use_clear = False
        bake.use_selected_to_active = False
        bake.target = "IMAGE_TEXTURES"
        for modifier, _shown in modifiers:
            modifier.show_render = False
        routings = [_MaterialRouting(material, bake_image) for material in materials]
        for routing in routings:
            routing.route()
        # Pixels outside the UVs keep this, so it is cleared once, not per frame.
        pixels.fill(0.0)
        bake_image.pixels.foreach_set(pixels)
        override = {
            "object": plane,
            "active_object": plane,
            "selected_objects": [plane],
            "selected_editable_objects": [plane],
        }
        window_manager.progress_begin(0, len(frame_list))
        for index, frame in enumerate(frame_list, start=1):
            if frame != int(scene.frame_current):
                scene.frame_set(frame)
                frame_changed = True
                _refresh_gp_masks(rig, scene)
            # Combined with only emission: straight colour plus alpha (from
            # the Transparent mix) in one pass.
            with context.temp_override(**override):
                result = bpy.ops.object.bake(
                    type="COMBINED", pass_filter={"EMIT"}, margin=0, use_clear=False, target="IMAGE_TEXTURES",
                )
            if "FINISHED" not in result:
                raise RuntimeError("Cycles did not bake the frame")
            bake_image.pixels.foreach_get(pixels)
            output_image.pixels.foreach_set(_straight_srgb(pixels))
            filename = f"{prefix}{index:04d}.png"
            output_image.filepath_raw = os.path.join(directory, filename)
            output_image.file_format = "PNG"
            output_image.save()
            files.append(filename)
            window_manager.progress_update(index)
    finally:
        try:
            window_manager.progress_end()
        except FBP_DATA_ERRORS:
            pass
        for routing in routings:
            routing.restore()
        for modifier, shown in modifiers:
            try:
                modifier.show_render = shown
            except FBP_DATA_ERRORS:
                pass
        for image in (bake_image, output_image):
            # The bake routes these images through the layer material, so a
            # Material Preview viewport may have compiled a shader that still
            # lists them. Free their pixels but keep the IDs (Blender drops
            # zero-user orphans on save), as deleting them can crash Eevee.
            fbp_release_orphan_image(image)
        try:
            for key, value in saved_cycles.items():
                setattr(cycles, key, value)
            bake.margin = saved["margin"]
            bake.use_clear = saved["use_clear"]
            bake.use_selected_to_active = saved["use_selected_to_active"]
            bake.target = saved["target"]
            render.engine = saved["engine"]
            if frame_changed:
                scene.frame_set(saved["frame"])
                _refresh_gp_masks(rig, scene)
        except FBP_DATA_ERRORS as exc:
            fbp_warn("Could not restore render settings after Apply Effects", exc)
    return files


def _refresh_gp_masks(rig, scene):
    """Re-raster the layer's Grease Pencil masks for the current frame.

    In the viewport they follow the frame from a timer, which cannot run while
    the bake holds Blender, so an animated mask would stay on its first frame.
    """
    try:
        from .effects_registry import GP_MASK_EFFECT_IDS
        from .grease_pencil_bridge import gp_mask_slot_contract, is_gp_canvas, refresh_gp_mask
    except ImportError:
        return
    for effect_id in GP_MASK_EFFECT_IDS:
        contract = gp_mask_slot_contract(effect_id)
        canvas = getattr(rig, contract["canvas"], None)
        if not is_gp_canvas(canvas):
            continue
        if str(getattr(rig, contract["source_type"], "") or "") != "GREASE_PENCIL":
            continue
        try:
            refresh_gp_mask(canvas, force=True, scene=scene)
        except FBP_DATA_ERRORS as exc:
            fbp_warn("Apply Effects could not refresh a Grease Pencil mask", exc)


def _uv_frame(plane, depsgraph):
    """World origin and edges of the plane's UV square: (origin, u_edge, v_edge).

    Fitted over every loop, so it holds for any flat mesh whose UVs map
    linearly onto it, including cropped planes.
    """
    import numpy
    from mathutils import Vector

    evaluated = plane.evaluated_get(depsgraph)
    mesh = evaluated.to_mesh()
    try:
        uv_layer = mesh.uv_layers.active
        if uv_layer is None or not len(mesh.loops):
            raise RuntimeError("The layer plane has no UV map")
        count = len(mesh.loops)
        uvs = numpy.empty(count * 2, dtype=numpy.float64)
        uv_layer.data.foreach_get("uv", uvs)
        indices = numpy.empty(count, dtype=numpy.int64)
        mesh.loops.foreach_get("vertex_index", indices)
        positions = numpy.empty(len(mesh.vertices) * 3, dtype=numpy.float64)
        mesh.vertices.foreach_get("co", positions)
    finally:
        evaluated.to_mesh_clear()
    uvs = uvs.reshape(-1, 2)
    points = positions.reshape(-1, 3)[indices]
    system = numpy.column_stack((numpy.ones(count), uvs))
    solution, _residual, rank, _values = numpy.linalg.lstsq(system, points, rcond=None)
    if rank < 3:
        raise RuntimeError("The layer plane's UV map is degenerate")
    origin, u_edge, v_edge = (Vector(row) for row in solution)
    matrix = plane.matrix_world
    world_origin = matrix @ origin
    return world_origin, (matrix @ (origin + u_edge)) - world_origin, (matrix @ (origin + v_edge)) - world_origin


def _fitted_camera(scene, plane, depsgraph, width, height):
    from mathutils import Matrix

    origin, u_edge, v_edge = _uv_frame(plane, depsgraph)
    if u_edge.length < 1e-9 or v_edge.length < 1e-9:
        raise RuntimeError("The layer plane has no area")
    x_axis = u_edge.normalized()
    z_axis = u_edge.cross(v_edge).normalized()
    y_axis = z_axis.cross(x_axis)
    distance = max(u_edge.length, v_edge.length) + 1.0
    center = origin + u_edge * 0.5 + v_edge * 0.5
    data = bpy.data.cameras.new("FBP Apply Effects Camera")
    data.type = "ORTHO"
    # Ortho Scale spans the wider side of the render.
    data.ortho_scale = u_edge.length if width >= height else v_edge.length
    data.clip_start = distance * 0.01
    data.clip_end = distance * 2.0
    camera = bpy.data.objects.new("FBP Apply Effects Camera", data)
    camera.matrix_world = Matrix.Translation(center + z_axis * distance) @ Matrix(
        (x_axis, y_axis, z_axis)
    ).transposed().to_4x4()
    scene.collection.objects.link(camera)
    scene.camera = camera
    return camera


def _render_frames(context, rig, plane, materials, width, height, frame_list, directory, prefix, samples=1):
    """Render the plane alone with EEVEE through a camera fitted to its UVs."""
    scene = context.scene
    saved_frame = int(scene.frame_current)
    frame_changed = False
    modifiers = [(modifier, bool(modifier.show_render)) for modifier in _geometry_effect_modifiers(rig)]
    methods = [(material, getattr(material, "surface_render_method", None)) for material in materials]
    temporary = None
    camera = None
    files = []
    window_manager = context.window_manager
    try:
        for modifier, _shown in modifiers:
            modifier.show_render = False
        for material, method in methods:
            # Blended gives exact partial alpha in one sample; Dithered needs many.
            if method is not None:
                material.surface_render_method = "BLENDED"
        temporary = bpy.data.scenes.new("FBP Apply Effects")
        temporary.collection.objects.link(plane)
        render = temporary.render
        render.engine = "BLENDER_EEVEE"
        render.resolution_x = int(width)
        render.resolution_y = int(height)
        render.resolution_percentage = 100
        render.pixel_aspect_x = render.pixel_aspect_y = 1.0
        render.film_transparent = True
        render.filter_size = 0.0
        render.use_compositing = False
        render.use_sequencer = False
        settings = render.image_settings
        settings.file_format = "PNG"
        settings.color_mode = "RGBA"
        settings.color_depth = "8"
        view = temporary.view_settings
        view.view_transform = "Standard"
        view.look = "None"
        view.exposure = 0.0
        view.gamma = 1.0
        try:
            temporary.display_settings.display_device = scene.display_settings.display_device
        except FBP_DATA_ERRORS:
            pass
        eevee = getattr(temporary, "eevee", None)
        if eevee is not None and hasattr(eevee, "taa_render_samples"):
            eevee.taa_render_samples = max(1, int(samples))
        temporary.frame_set(saved_frame)
        camera = _fitted_camera(temporary, plane, temporary.view_layers[0].depsgraph, width, height)
        window_manager.progress_begin(0, len(frame_list))
        for index, frame in enumerate(frame_list, start=1):
            if frame != int(scene.frame_current):
                scene.frame_set(frame)
                frame_changed = True
                _refresh_gp_masks(rig, scene)
            temporary.frame_set(frame)
            filename = f"{prefix}{index:04d}.png"
            render.filepath = os.path.join(directory, filename)
            result = bpy.ops.render.render(write_still=True, scene=temporary.name)
            if "FINISHED" not in result or not os.path.isfile(render.filepath):
                raise RuntimeError("EEVEE did not render the frame")
            files.append(filename)
            window_manager.progress_update(index)
    finally:
        try:
            window_manager.progress_end()
        except FBP_DATA_ERRORS:
            pass
        if camera is not None:
            data = camera.data
            try:
                bpy.data.objects.remove(camera, do_unlink=True)
                bpy.data.cameras.remove(data)
            except FBP_DATA_ERRORS:
                pass
        if temporary is not None:
            try:
                bpy.data.scenes.remove(temporary)
            except FBP_DATA_ERRORS as exc:
                fbp_warn("Could not remove the Apply Effects scene", exc)
        for material, method in methods:
            if method is not None:
                try:
                    material.surface_render_method = method
                except FBP_DATA_ERRORS:
                    pass
        for modifier, shown in modifiers:
            try:
                modifier.show_render = shown
            except FBP_DATA_ERRORS:
                pass
        if frame_changed:
            try:
                scene.frame_set(saved_frame)
                _refresh_gp_masks(rig, scene)
            except FBP_DATA_ERRORS as exc:
                fbp_warn("Could not restore the frame after Apply Effects", exc)
    return files


def fbp_switch_off_image_effects(rig):
    """Hide every image (shader) effect of a layer in viewport and render.

    The effects stay in the stack, so the eye icons switch them back on.
    Returns the number of effects switched off.
    """
    from .geometry_nodes import (
        _fbp_refresh_geometry_source_materials,
        _fbp_store_effect_solo_ids,
        fbp_effect_definition,
        fbp_effect_ids_for_rig,
        fbp_set_effect_render_visible,
        fbp_set_effect_visible,
    )

    effect_ids = [
        effect_id for effect_id in dict.fromkeys(fbp_effect_ids_for_rig(rig))
        if fbp_effect_definition(effect_id).get("kind") == "SHADER"
    ]
    for effect_id in effect_ids:
        # Without an instance id both setters reach every instance of the effect.
        fbp_set_effect_visible(rig, effect_id, False, refresh_mixed=False)
        fbp_set_effect_render_visible(rig, effect_id, False)
    for view in ("2D", "MASK"):
        # A leftover Solo set would switch the effects back on when cleared.
        _fbp_store_effect_solo_ids(rig, view, set())
    if effect_ids:
        _fbp_refresh_geometry_source_materials(rig)
    return len(effect_ids)


def _load_baked_frames(rig, directory, files, start_frame, step=1):
    from .core import fbp_replace_sequence_backend

    rig.fbp_sequence_reversed = False
    step = max(1, int(step))
    if not fbp_replace_sequence_backend(rig, directory, files, item_durations=[step] * len(files)):
        raise RuntimeError("the baked frames could not be loaded")
    rig.fbp_loop_mode = "NONE"
    rig.fbp_start_frame = int(start_frame)
    rig.fbp_opacity = 1.0  # Opacity is already in the baked alpha.


def _apply_baked_frames(rig, directory, files, start_frame, step=1):
    """Make the layer play the baked frames and switch its image effects off."""
    try:
        _load_baked_frames(rig, directory, files, start_frame, step)
        fbp_switch_off_image_effects(rig)
    except (ImportError, *FBP_DATA_ERRORS) as exc:
        fbp_warn("Apply Effects could not load the baked frames", exc)
        return False
    return True


def _create_baked_layer(context, rig, directory, files, start_frame, step=1):
    """Duplicate the layer, swap in the baked frames and drop shader effects."""
    try:
        from .effects_registry import FBP_EFFECT_REGISTRY
        from .geometry_nodes import (
            fbp_effect_ids_for_rig,
            fbp_persist_effect_stacks,
            fbp_remove_effect,
            fbp_sync_effect_items,
        )
    except ImportError as exc:
        fbp_warn("Apply Effects could not load layer tools", exc)
        return None

    before = set(bpy.data.objects)
    try:
        result = bpy.ops.fbp.duplicate_selected_layers(rig_name=rig.name)
    except FBP_DATA_ERRORS as exc:
        fbp_warn("Apply Effects could not duplicate the layer", exc)
        return None
    if "FINISHED" not in result:
        return None
    new_rig = next(
        (
            obj for obj in bpy.data.objects
            if obj not in before and bool(getattr(obj, "is_fbp_control", False))
        ),
        None,
    )
    if new_rig is None:
        return None
    try:
        _load_baked_frames(new_rig, directory, files, start_frame, step)
        for effect_id in tuple(fbp_effect_ids_for_rig(new_rig)):
            if FBP_EFFECT_REGISTRY.get(effect_id, {}).get("kind") == "SHADER":
                fbp_remove_effect(new_rig, effect_id, sync_items=False)
        fbp_persist_effect_stacks([new_rig])
        fbp_sync_effect_items(new_rig, [new_rig], repair_assets=False, normalize_instance_ids=False)
        new_rig.name = f"{rig.name} Applied"
        rig.fbp_is_visible = False
    except FBP_DATA_ERRORS as exc:
        fbp_warn("Apply Effects could not finish the new layer", exc)
    return new_rig


_classes = (FBP_OT_ApplyImageEffects,)


def register():
    for cls in _classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(_classes):
        try:
            bpy.utils.unregister_class(cls)
        except RuntimeError:
            pass


__all__ = ("FBP_OT_ApplyImageEffects", "fbp_apply_effects_estimate", "fbp_switch_off_image_effects")
