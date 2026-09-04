"""Camera output controls backed by native RenderSettings, never UI draw writes.

Old combined presets remain readable in 7.1.x files. Explicit edits through the
new controls retire that preset so a later import cannot silently reapply it.
"""

from fractions import Fraction
import re

import bpy
from bpy.props import BoolProperty, EnumProperty, FloatProperty, IntProperty, StringProperty
from bpy.types import Menu, Operator, Panel, PropertyGroup

from .registration import register_classes, unregister_classes
from .runtime import FBP_DATA_ERRORS, fbp_set_rna_property_silent, fbp_warn
from .ui_style import logical_region_width


RESOLUTION_PRESETS = (('CUSTOM', 0), ('SD', 720), ('HD', 1920), ('2K', 2048),
                      ('4K', 3840), ('8K', 7680))
CAMERA_RESOLUTION_ITEMS = [
    (key, key if key != 'CUSTOM' else 'Custom',
     f"{pixels} pixels on the longest side; preserves aspect ratio" if pixels
     else "Edit width and height in pixels; link dimensions to preserve the aspect ratio", index)
    for index, (key, pixels) in enumerate(RESOLUTION_PRESETS)
]
# Ratios describe the shape independently from its orientation. In particular,
# the requested 4:5 shape is applied as landscape 5:4; Swap makes it portrait.
ASPECT_PRESETS = (
    ('SQUARE', '1:1'), ('FOUR_FIVE', '4:5'), ('FOUR_THREE', '4:3'),
    ('THREE_TWO', '3:2'), ('SIXTEEN_TEN', '16:10'), ('SIXTEEN_NINE', '16:9'),
    ('TWO_ONE', '2:1'), ('TWENTYONE_NINE', '21:9'), ('CINEMA', '2.39:1'),
    ('THIRTYTWO_NINE', '32:9'),
)
CAMERA_ASPECT_ITEMS = [
    (key, label, f"{label} shape, landscape by default. Use Swap for portrait", index)
    for index, (key, label) in enumerate(ASPECT_PRESETS)
]
# Immutable numeric shapes avoid parsing all ten labels on every UI redraw.
_ASPECT_SHAPE_LABELS = {}
for _preset_key, _preset_label in ASPECT_PRESETS:
    _width, _height = (Fraction(value) for value in _preset_label.split(':'))
    _shape = _width / _height
    _ASPECT_SHAPE_LABELS[max(_shape, 1 / _shape)] = _preset_label
del _preset_key, _preset_label, _width, _height, _shape
_ASPECT_KEY = 'fbp_camera_aspect_label'
_PRESET_KEY = 'fbp_camera_resolution_choice'
_ERROR_KEY = 'fbp_camera_output_error'
_CUSTOM_ASPECT_KEY = 'fbp_camera_custom_aspect'
_RATIO_RE = re.compile(r'^\s*(\d+(?:[.,]\d+)?)\s*[:/]\s*(\d+(?:[.,]\d+)?)\s*$')


def parse_aspect_ratio(text):
    if len(str(text)) > 64:
        raise ValueError("Aspect ratio is too long")
    match = _RATIO_RE.fullmatch(str(text))
    if not match:
        raise ValueError("Use a positive W:H ratio, for example 16:9 or 2.39:1")
    width, height = (Fraction(value.replace(',', '.')) for value in match.groups())
    if width <= 0 or height <= 0:
        raise ValueError("Both aspect-ratio values must be greater than zero")
    return width / height


def _display_ratio(render):
    return (Fraction(render.resolution_x) * Fraction(str(render.pixel_aspect_x)) /
            (Fraction(render.resolution_y) * Fraction(str(render.pixel_aspect_y))))


def resolution_for_aspect(ratio, longest, pixel_x=1.0, pixel_y=1.0):
    """Round once, accounting for non-square pixels, before any RNA writes."""
    raster_ratio = float(ratio) * float(pixel_y) / float(pixel_x)
    if raster_ratio >= 1.0:
        size = int(longest), round(longest / raster_ratio)
    else:
        size = round(longest * raster_ratio), int(longest)
    # Blender RenderSettings has a 4..65536 pixel hard range.
    if min(size) < 4 or max(size) > 65536:
        raise ValueError("This ratio needs dimensions outside Blender's 4–65536 pixel range")
    return size


def camera_aspect_get(scene):
    try:
        render = scene.render
        label = str(scene.get(_ASPECT_KEY, '') or '')
        if label:
            try:
                target = resolution_for_aspect(parse_aspect_ratio(label),
                    max(render.resolution_x, render.resolution_y),
                    render.pixel_aspect_x, render.pixel_aspect_y)
                if target == (render.resolution_x, render.resolution_y):
                    return label
            except ValueError:
                pass
        ratio = _display_ratio(render).limit_denominator(10000)
        return f"{ratio.numerator}:{ratio.denominator}"
    except FBP_DATA_ERRORS:
        return '1:1'


def camera_resolution_get(scene):
    try:
        choice = str(scene.get(_PRESET_KEY, 'CUSTOM'))
        longest = max(scene.render.resolution_x, scene.render.resolution_y)
        for index, (key, pixels) in enumerate(RESOLUTION_PRESETS):
            if choice == key and longest == pixels:
                return index
    except FBP_DATA_ERRORS:
        pass
    return 0


def _set_output(scene, *, ratio, longest, label, choice):
    render = scene.render
    size = resolution_for_aspect(ratio, longest, render.pixel_aspect_x, render.pixel_aspect_y)
    # A single property edit/Undo step owns these synchronous changes. Do not
    # defer them to a timer: a pending timer could overwrite the undone values.
    render.resolution_x, render.resolution_y = size
    scene[_ASPECT_KEY] = label
    scene[_PRESET_KEY] = choice
    scene[_ERROR_KEY] = ''
    fbp_set_rna_property_silent(scene, 'fbp_cam_ratio', 'CUSTOM')


def _set_landscape_aspect(scene, value):
    ratio = parse_aspect_ratio(value)
    label = str(value).strip().replace(',', '.').replace('/', ':').replace(' ', '')
    if ratio < 1:
        ratio = 1 / ratio
        first, second = label.split(':')
        label = f'{second}:{first}'
    choice = RESOLUTION_PRESETS[camera_resolution_get(scene)][0]
    _set_output(scene, ratio=ratio,
                longest=max(scene.render.resolution_x, scene.render.resolution_y),
                label=label, choice=choice)
    scene[_CUSTOM_ASPECT_KEY] = False


def camera_aspect_set(scene, value):
    """Retained string API; explicitly choosing a shape now defaults landscape."""
    try:
        _set_landscape_aspect(scene, value)
    except FBP_DATA_ERRORS as exc:
        scene[_ERROR_KEY] = str(exc)
        fbp_warn('Camera aspect was not changed', exc)


def camera_resolution_set(scene, value):
    try:
        if not 0 <= int(value) < len(RESOLUTION_PRESETS):
            return
        key, longest = RESOLUTION_PRESETS[int(value)]
        label = camera_aspect_get(scene)
        _set_output(scene, ratio=parse_aspect_ratio(label),
                    longest=longest or max(scene.render.resolution_x, scene.render.resolution_y),
                    label=label, choice=key)
    except FBP_DATA_ERRORS as exc:
        scene[_ERROR_KEY] = str(exc)
        fbp_warn('Camera resolution was not changed', exc)


def camera_width_get(scene):
    return scene.render.resolution_x


def camera_height_get(scene):
    return scene.render.resolution_y


def _set_custom_pixels(scene, attr, value):
    try:
        render = scene.render
        width, height = render.resolution_x, render.resolution_y
        label = camera_aspect_get(scene)
        linked = scene.fbp_camera_dimensions_linked
        ratio = (parse_aspect_ratio(label) * Fraction(str(render.pixel_aspect_y)) /
                 Fraction(str(render.pixel_aspect_x)))
        if attr == 'resolution_x':
            width = int(value)
            if linked:
                height = round(Fraction(width) / ratio)
        else:
            height = int(value)
            if linked:
                width = round(Fraction(height) * ratio)
        # Validate the whole pair first: Blender silently clamps RNA writes,
        # which would break the requested ratio if one linked side overflows.
        if min(width, height) < 4 or max(width, height) > 65536:
            raise ValueError("Linked dimensions must both stay within 4–65536 px")
        render.resolution_x, render.resolution_y = width, height
        scene[_PRESET_KEY] = 'CUSTOM'
        scene[_ASPECT_KEY] = label if linked else ''
        if not linked:
            scene[_CUSTOM_ASPECT_KEY] = True
        scene[_ERROR_KEY] = ''
        fbp_set_rna_property_silent(scene, 'fbp_cam_ratio', 'CUSTOM')
    except FBP_DATA_ERRORS as exc:
        scene[_ERROR_KEY] = str(exc)
        fbp_warn('Camera pixels were not changed', exc)


def camera_width_set(scene, value):
    _set_custom_pixels(scene, 'resolution_x', value)


def camera_height_set(scene, value):
    _set_custom_pixels(scene, 'resolution_y', value)


def camera_aspect_menu_label(scene):
    """Read current dimensions without coercing older/custom saved formats."""
    if scene.get(_CUSTOM_ASPECT_KEY, False):
        return 'Custom'
    actual = parse_aspect_ratio(camera_aspect_get(scene))
    shape = max(actual, 1 / actual)
    return _ASPECT_SHAPE_LABELS.get(shape, 'Custom')


def swap_camera_dimensions(scene):
    render = scene.render
    width, height = render.resolution_x, render.resolution_y
    pixel_x, pixel_y = render.pixel_aspect_x, render.pixel_aspect_y
    if width == height and pixel_x == pixel_y:
        return False
    first, second = camera_aspect_get(scene).split(':')
    # Swap pixel aspect too: otherwise anamorphic formats would not be a true
    # reciprocal. Two swaps restore the original raster and display dimensions.
    render.resolution_x, render.resolution_y = height, width
    render.pixel_aspect_x, render.pixel_aspect_y = pixel_y, pixel_x
    scene[_ASPECT_KEY] = f'{second}:{first}'
    scene[_ERROR_KEY] = ''
    fbp_set_rna_property_silent(scene, 'fbp_cam_ratio', 'CUSTOM')
    return True


class _CameraFormatOperator:
    @classmethod
    def poll(cls, context):
        scene = getattr(context, 'scene', None)
        return bool(scene is not None and scene.is_editable
                    and getattr(context, 'edit_object', None) is None)


class FBP_OT_SetCameraAspect(_CameraFormatOperator, Operator):
    bl_idname = 'fbp.set_camera_aspect'
    bl_label = 'Set Camera Aspect Ratio'
    bl_description = 'Choose a landscape format; use Swap Dimensions for portrait'
    bl_options = {'REGISTER', 'UNDO'}

    preset: EnumProperty(name='Aspect Ratio', items=CAMERA_ASPECT_ITEMS)

    def execute(self, context):
        try:
            _set_landscape_aspect(context.scene, dict(ASPECT_PRESETS)[self.preset])
        except FBP_DATA_ERRORS as exc:
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}
        return {'FINISHED'}


class FBP_OT_SwapCameraDimensions(_CameraFormatOperator, Operator):
    bl_idname = 'fbp.swap_camera_dimensions'
    bl_label = 'Swap Camera Dimensions'
    bl_description = 'Swap horizontal and vertical format without changing resolution scale'
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        try:
            changed = swap_camera_dimensions(context.scene)
        except FBP_DATA_ERRORS as exc:
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}
        return {'FINISHED'} if changed else {'CANCELLED'}


class FBP_MT_CameraAspect(Menu):
    bl_idname = 'FBP_MT_camera_aspect'
    bl_label = 'Aspect Ratio'

    def draw(self, context):
        current = camera_aspect_menu_label(context.scene)
        for key, label in ASPECT_PRESETS:
            self.layout.operator('fbp.set_camera_aspect', text=label,
                                 icon='CHECKMARK' if label == current else 'NONE').preset = key


class FBP_CameraFormatPreset(PropertyGroup):
    name: StringProperty(name='Name', default='Camera Format', maxlen=64)
    width: IntProperty(min=4, max=65536, default=1920)
    height: IntProperty(min=4, max=65536, default=1080)
    pixel_x: FloatProperty(min=1.0, max=200.0, default=1.0)
    pixel_y: FloatProperty(min=1.0, max=200.0, default=1.0)
    aspect: StringProperty(default='16:9')
    resolution: StringProperty(default='CUSTOM')
    linked: BoolProperty(default=True)
    custom_aspect: BoolProperty(default=False)


class FBP_OT_SaveCameraFormatPreset(_CameraFormatOperator, Operator):
    bl_idname = 'fbp.save_camera_format_preset'
    bl_label = 'Save Camera Format Preset'
    bl_description = 'Save this format and dimension link in the current blend file'
    bl_options = {'REGISTER', 'UNDO'}

    name: StringProperty(name='Name', default='Camera Format', maxlen=54)

    def invoke(self, context, _event):
        render = context.scene.render
        self.name = f'{render.resolution_x} × {render.resolution_y}'
        return context.window_manager.invoke_props_dialog(self)

    def draw(self, _context):
        self.layout.prop(self, 'name')

    def execute(self, context):
        scene = context.scene
        base = self.name.strip() or 'Camera Format'
        names = {item.name.casefold() for item in scene.fbp_camera_format_presets}
        name, number = base, 2
        while name.casefold() in names:
            name, number = f'{base} {number}', number + 1
        preset = scene.fbp_camera_format_presets.add()
        preset.name = name
        preset.width, preset.height = scene.render.resolution_x, scene.render.resolution_y
        preset.pixel_x, preset.pixel_y = scene.render.pixel_aspect_x, scene.render.pixel_aspect_y
        preset.aspect = camera_aspect_get(scene)
        preset.resolution = RESOLUTION_PRESETS[camera_resolution_get(scene)][0]
        preset.linked = scene.fbp_camera_dimensions_linked
        preset.custom_aspect = camera_aspect_menu_label(scene) == 'Custom'
        return {'FINISHED'}


class FBP_OT_ApplyCameraFormatPreset(_CameraFormatOperator, Operator):
    bl_idname = 'fbp.apply_camera_format_preset'
    bl_label = 'Apply Camera Format Preset'
    bl_description = 'Restore saved dimensions, aspect ratio and link; keep render scale'
    bl_options = {'REGISTER', 'UNDO'}

    index: IntProperty(default=-1, options={'HIDDEN'})

    def execute(self, context):
        scene = context.scene
        if not 0 <= self.index < len(scene.fbp_camera_format_presets):
            self.report({'WARNING'}, 'Camera format preset is no longer available')
            return {'CANCELLED'}
        preset = scene.fbp_camera_format_presets[self.index]
        try:
            parse_aspect_ratio(preset.aspect)
        except ValueError as exc:
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}
        render = scene.render
        render.resolution_x, render.resolution_y = preset.width, preset.height
        render.pixel_aspect_x, render.pixel_aspect_y = preset.pixel_x, preset.pixel_y
        scene.fbp_camera_dimensions_linked = preset.linked
        scene[_ASPECT_KEY] = preset.aspect
        scene[_PRESET_KEY] = preset.resolution
        scene[_CUSTOM_ASPECT_KEY] = preset.custom_aspect
        scene[_ERROR_KEY] = ''
        fbp_set_rna_property_silent(scene, 'fbp_cam_ratio', 'CUSTOM')
        return {'FINISHED'}


class FBP_OT_RemoveCameraFormatPreset(_CameraFormatOperator, Operator):
    bl_idname = 'fbp.remove_camera_format_preset'
    bl_label = 'Remove Camera Format Preset'
    bl_description = 'Remove this saved format from the blend file; can be undone'
    bl_options = {'REGISTER', 'UNDO'}

    index: IntProperty(default=-1, options={'HIDDEN'})

    def execute(self, context):
        presets = context.scene.fbp_camera_format_presets
        if not 0 <= self.index < len(presets):
            return {'CANCELLED'}
        presets.remove(self.index)
        return {'FINISHED'}


class FBP_PT_CameraFormatPresets(Panel):
    bl_idname = 'FBP_PT_camera_format_presets'
    bl_label = 'Camera Format Presets'
    bl_space_type = 'PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_options = {'INSTANCED'}
    bl_ui_units_x = 16

    def draw(self, context):
        layout = self.layout
        layout.operator('fbp.save_camera_format_preset', text='Save Current Format...', icon='ADD')
        layout.separator()
        presets = context.scene.fbp_camera_format_presets
        if not presets:
            layout.label(text='Presets are saved in this blend file', icon='INFO')
        for index, preset in enumerate(presets):
            row = layout.row(align=False)
            row.operator('fbp.apply_camera_format_preset', text=preset.name, icon='PRESET').index = index
            row.operator('fbp.remove_camera_format_preset', text='', icon='TRASH').index = index


def draw_camera_output(layout, scene, context=None, *, available_width=None):
    """Always expose pixels; wrap the resolution row in narrow editors/dialogs."""
    context = context or bpy.context
    width = logical_region_width(context) if available_width is None else available_width
    controls = layout.column(align=False)
    controls.use_property_split = False
    controls.use_property_decorate = False
    controls.enabled = _CameraFormatOperator.poll(context)
    row = controls.row(align=False)
    row.label(text='Aspect Ratio', icon='IMAGE_BACKGROUND')
    row.menu('FBP_MT_camera_aspect', text=camera_aspect_menu_label(scene))
    row.operator('fbp.swap_camera_dimensions', text='', icon='RENDER_SWAP_DIMENSIONS')
    row.popover(panel='FBP_PT_camera_format_presets', text='', icon='PRESET')
    error = str(scene.get(_ERROR_KEY, '') or '')
    if error:
        row = controls.row()
        row.alert = True
        row.label(text=error, icon='ERROR')
    row = controls.row(align=False)
    row.prop(scene, 'fbp_camera_resolution', text='Resolution')
    pixels = controls.row(align=False) if width < 540 else row.row(align=False)
    pixels.prop(scene, 'fbp_camera_width', text='Width (px)')
    pixels.prop(scene, 'fbp_camera_dimensions_linked', text='', toggle=True,
                icon='LINKED' if scene.fbp_camera_dimensions_linked else 'UNLINKED')
    pixels.prop(scene, 'fbp_camera_height', text='Height (px)')


classes = (FBP_CameraFormatPreset, FBP_OT_SetCameraAspect, FBP_OT_SwapCameraDimensions,
           FBP_MT_CameraAspect, FBP_OT_SaveCameraFormatPreset, FBP_OT_ApplyCameraFormatPreset,
           FBP_OT_RemoveCameraFormatPreset, FBP_PT_CameraFormatPresets)


def register():
    register_classes(classes)


def unregister():
    unregister_classes(classes)
