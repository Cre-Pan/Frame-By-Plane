"""Material, shader-node, opacity, emission, gradient and holdout helpers."""

import bpy
import math


# SECTION 00B - Shared runtime helpers #
from .runtime import (
    FBP_DATA_ERRORS,
    FBP_DATA_IO_ERRORS,
    fbp_warn, fbp_set_rna_property_silent, fbp_obj_runtime_key,
    fbp_find_id_by_runtime_key, fbp_find_action_fcurve,
    fbp_remove_action_fcurves,
)

from . import safe_tasks as _safe_tasks


_PENDING_PROXY_CACHE_ROOTS = globals().get('_PENDING_PROXY_CACHE_ROOTS', set())
if not isinstance(_PENDING_PROXY_CACHE_ROOTS, set):
    _PENDING_PROXY_CACHE_ROOTS = set()
_PENDING_GRADIENT_PREVIEW_SYNC = globals().get('_PENDING_GRADIENT_PREVIEW_SYNC', {})
if not isinstance(_PENDING_GRADIENT_PREVIEW_SYNC, dict):
    _PENDING_GRADIENT_PREVIEW_SYNC = {}


def fbp_primary_plane_material_index(rig):
    """Return the material slot driven by Frame by Plane without altering slots."""
    plane = getattr(rig, "fbp_plane_target", None) if rig else None
    mesh = getattr(plane, "data", None) if plane else None
    materials = getattr(mesh, "materials", None) if mesh else None
    if not materials or len(materials) == 0:
        return -1

    try:
        # Native layers are created with their FBP material in slot zero. Keep
        # that fast path, but recover gracefully if a user reordered the slots.
        first = materials[0]
        if first and fbp_material_is_owned(first):
            return 0
        for index, material in enumerate(materials):
            if material and fbp_material_is_owned(material):
                return index
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, IndexError):
        return -1

    # A current-format FBP plane should always own its material. Falling back to
    # slot zero keeps a manually replaced material renderable without deleting it.
    try:
        return 0 if materials[0] else -1
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, IndexError):
        return -1


def ensure_fbp_plane_material_integrity(rig):
    """Keep native FBP assignments valid while respecting explicit overrides.

    Extra slots and polygons deliberately assigned to a non-FBP material are left
    untouched. Only missing, invalid or stale FBP assignments are repaired. This
    keeps the native sequence reliable without fighting render-specific material
    overrides created by the user.
    """
    plane = getattr(rig, "fbp_plane_target", None) if rig else None
    mesh = getattr(plane, "data", None) if plane else None
    if not mesh or not getattr(mesh, "materials", None) or len(mesh.materials) == 0:
        return False
    material_index = fbp_primary_plane_material_index(rig)
    if material_index < 0:
        return False
    changed = False
    try:
        for poly in mesh.polygons:
            current_index = int(getattr(poly, "material_index", 0) or 0)
            current = (
                mesh.materials[current_index]
                if 0 <= current_index < len(mesh.materials)
                else None
            )
            # Respect an explicit custom override. FBP only repairs its own stale
            # assignment or a missing/invalid slot.
            if current and not fbp_material_is_owned(current):
                continue
            if current_index != material_index:
                poly.material_index = material_index
                changed = True

        active_index = int(getattr(plane, "active_material_index", 0) or 0)
        active = (
            mesh.materials[active_index]
            if 0 <= active_index < len(mesh.materials)
            else None
        )
        if (not active or fbp_material_is_owned(active)) and active_index != material_index:
            plane.active_material_index = material_index
        if changed:
            mesh.update()
        return True
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, IndexError) as exc:
        fbp_warn("Could not restore the Frame by Plane material assignment", exc)
        return False


# SECTION 01 - Utility socket / node tree #
# SECTION 02 - Images, datablocks and material cleanup #

def iter_material_image_nodes():
    for mat in bpy.data.materials:
        if not mat or not getattr(mat, 'use_nodes', False) or not mat.node_tree:
            continue
        for node in mat.node_tree.nodes:
            if node.type == 'TEX_IMAGE' and getattr(node, 'image', None):
                yield mat, node, node.image


def safe_get_socket(node, contains, excludes=()):
    for inp in node.inputs:
        n = inp.name.lower()
        i = inp.identifier.lower()
        if all(c in n or c in i for c in contains) and not any(e in n or e in i for e in excludes):
            return inp
    return None


def _fbp_run_deferred_proxy_cache_cleanup():
    """Clean generated proxy folders after Blender references have disappeared.

    Image datablocks are deliberately left to Blender's explicit orphan purge.
    This task only releases add-on-owned Python state and generated proxy files.
    """
    if _PENDING_PROXY_CACHE_ROOTS:
        from .native_backend import fbp_cleanup_unused_proxy_caches
        try:
            fbp_cleanup_unused_proxy_caches(list(_PENDING_PROXY_CACHE_ROOTS))
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, OSError) as exc:
            fbp_warn('Could not clean unused Frame by Plane proxy cache', exc)
        _PENDING_PROXY_CACHE_ROOTS.clear()
    _PENDING_GRADIENT_PREVIEW_SYNC.clear()
    return None


def fbp_prepare_for_main_replacement():
    """Drop pure-Python cleanup state before Blender replaces Main.

    This function intentionally does not touch ``bpy.data.images``. At load time
    Blender must remain the sole owner of image/movie cache destruction.
    """
    _PENDING_PROXY_CACHE_ROOTS.clear()
    _PENDING_GRADIENT_PREVIEW_SYNC.clear()


def fbp_material_is_owned(mat):
    """Return True only for materials explicitly owned by Frame by Plane."""
    if not mat:
        return False
    try:
        return bool(mat.get("fbp_owned", False))
    except FBP_DATA_ERRORS:
        return False


def fbp_remove_unused_materials_and_images(materials):
    """Remove zero-user FBP materials without freeing Blender Image datablocks.

    The public name is retained for compatibility with existing internal callers.
    Image IDs and their sequence/movie caches remain owned by Blender and can be
    removed explicitly through Orphan Purge.
    """
    unique_materials = []
    seen_materials = set()
    for mat in list(materials or []):
        if not mat:
            continue
        key = fbp_obj_runtime_key(mat)
        if key is None:
            try:
                key = ("NAME", str(getattr(mat, "name_full", mat.name)))
            except FBP_DATA_ERRORS:
                continue
        if key in seen_materials:
            continue
        seen_materials.add(key)
        unique_materials.append(mat)
    materials = unique_materials
    from .native_backend import fbp_proxy_cache_roots_from_materials
    try:
        _PENDING_PROXY_CACHE_ROOTS.update(fbp_proxy_cache_roots_from_materials(materials))
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, OSError) as exc:
        fbp_warn('Could not inspect Frame by Plane proxy cache roots', exc)

    for mat in materials:
        try:
            if mat and fbp_material_is_owned(mat) and mat.users == 0:
                bpy.data.materials.remove(mat)
        except ReferenceError:
            continue
        except (AttributeError, TypeError, RuntimeError) as exc:
            fbp_warn("Could not remove unused FBP material datablock", exc)

    if _PENDING_PROXY_CACHE_ROOTS:
        _safe_tasks.schedule_once(
            'materials.unused_proxy_cache_cleanup',
            _fbp_run_deferred_proxy_cache_cleanup,
            first_interval=1.25,
        )
    return 0


def _fbp_copy_material_animation_unique(source_material, copied_material):
    """Detach node-tree Actions after a material copy.

    Native image timing lives on the material node tree. Blender data copies can
    preserve a shared Action, which would couple frame-offset edits between the
    source plane and its duplicate.
    """
    try:
        source_tree = getattr(source_material, "node_tree", None)
        copied_tree = getattr(copied_material, "node_tree", None)
        source_anim = getattr(source_tree, "animation_data", None) if source_tree else None
        copied_anim = getattr(copied_tree, "animation_data", None) if copied_tree else None
        source_action = getattr(source_anim, "action", None) if source_anim else None
        copied_action = getattr(copied_anim, "action", None) if copied_anim else None
        if copied_anim is not None and copied_action is not None and copied_action == source_action:
            copied_anim.action = copied_action.copy()
    except FBP_DATA_ERRORS:
        pass


def fbp_copy_material_slots_unique(src_plane, dst_plane):
    """Copy material slots without ever sharing an owned animated backend.

    User materials may safely remain linked when Blender refuses to copy them,
    but Frame By Plane native/Cutout/procedural materials own mutable nodes and
    animation data. Sharing one of those after duplication would couple timing,
    opacity and effects between the source and duplicate.
    """
    if not src_plane or not dst_plane or not getattr(dst_plane, 'data', None):
        return False
    dst_plane.data.materials.clear()
    created_materials = []
    try:
        src_mats = list(src_plane.data.materials) if getattr(src_plane, 'data', None) else []
    except ReferenceError:
        return False

    for mat in src_mats:
        if not mat:
            continue
        try:
            new_mat = mat.copy()
            new_mat.name = mat.name + "_Copy"
            _fbp_copy_material_animation_unique(mat, new_mat)
            dst_plane.data.materials.append(new_mat)
            created_materials.append(new_mat)
        except Exception as exc:
            if fbp_material_is_owned(mat):
                # Roll back all private copies. A shared FBP material is more
                # dangerous than cancelling one duplicate operation.
                try:
                    dst_plane.data.materials.clear()
                except FBP_DATA_ERRORS:
                    pass
                try:
                    fbp_remove_unused_materials_and_images(created_materials)
                except FBP_DATA_ERRORS:
                    pass
                fbp_warn("Could not create an independent animated material copy", exc)
                return False
            try:
                dst_plane.data.materials.append(mat)
            except FBP_DATA_ERRORS:
                return False
    return True


# SECTION 03 - Image materials, emission and opacity #

def rebuild_fbp_image_material(mat, use_emission=None, opacity=None):
    """Rebuild only current-contract native image materials.

    Generic or outdated image-node materials are deliberately unsupported;
    they must be recreated through the native backend instead of being silently
    converted into a second material implementation.
    """
    if not mat:
        return None
    if bool(mat.get("fbp_drawing_material", False)):
        try:
            from .drawing_plane import fbp_rebuild_drawing_material
            return fbp_rebuild_drawing_material(
                mat, use_emission=use_emission, opacity=opacity
            )
        except (
            AttributeError, ReferenceError, RuntimeError, TypeError, ValueError,
            ImportError, FileNotFoundError,
        ) as exc:
            fbp_warn("Could not rebuild Cutout Plane material", exc)
            return None
    if not bool(mat.get("fbp_native_sequence", False)):
        return None
    try:
        from .native_backend import rebuild_native_sequence_material
        return rebuild_native_sequence_material(
            mat, use_emission=use_emission, opacity=opacity
        )
    except (
        AttributeError, ReferenceError, RuntimeError, TypeError, ValueError,
        ImportError, FileNotFoundError,
    ) as exc:
        fbp_warn("Could not rebuild current native image material", exc)
        return None


def _fbp_reapply_registered_effects(rig, custom_states=None):
    """Restore tagged shader effects and refresh alpha-aware geometry."""
    if not rig:
        return
    try:
        from .geometry_nodes import fbp_reapply_all_effects
        fbp_reapply_all_effects(rig, custom_states=custom_states)
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, ImportError) as exc:
        fbp_warn("Could not reapply Frame by Plane effects", exc)


def do_update_emission(rig):
    plane = rig.fbp_plane_target
    if not plane:
        return
    use_emission = bool(getattr(rig, 'fbp_color_plane_emission', getattr(rig, 'fbp_use_emission', True))) if getattr(rig, 'fbp_is_color_plane', False) else bool(getattr(rig, 'fbp_use_emission', True))
    fbp_set_rna_property_silent(rig, 'fbp_use_emission', use_emission)
    if getattr(rig, 'fbp_is_color_plane', False):
        fbp_set_rna_property_silent(rig, 'fbp_color_plane_emission', use_emission)
    plane.visible_shadow = not use_emission
    opacity = max(0.0, min(1.0, float(getattr(rig, 'fbp_opacity', 1.0))))
    custom_states = {}
    try:
        from .geometry_nodes import fbp_capture_custom_shader_effect_states
        custom_states = fbp_capture_custom_shader_effect_states(rig)
    except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError) as exc:
        fbp_warn("Could not capture custom shader values before material rebuild", exc)
    for i, mat in enumerate(list(plane.data.materials)):
        if (
            not mat
            or not fbp_material_is_owned(mat)
            or not getattr(mat, 'use_nodes', False)
        ):
            continue
        if getattr(rig, 'fbp_is_color_plane', False):
            new_mat = fbp_rebuild_procedural_material_for_emission(mat, rig, use_emission)
        else:
            new_mat = rebuild_fbp_image_material(mat, use_emission=use_emission, opacity=opacity)
        if new_mat:
            plane.data.materials[i] = new_mat
            if new_mat != mat:
                fbp_remove_unused_materials_and_images([mat])
    _fbp_reapply_registered_effects(rig, custom_states=custom_states)


def set_fbp_material_transparency(mat, opacity=1.0):
    configure_fbp_material_surface(mat, opacity, has_alpha=True)


def do_update_opacity(rig):
    """Update layer opacity in place without rebuilding image materials.

    Image planes use one lightweight alpha Multiply node only below 100%.
    It is updated in place and removed at 100%, without rebuilding materials,
    images or native-sequence proxy caches while the slider is dragged.
    """
    plane = getattr(rig, "fbp_plane_target", None)
    if not plane:
        return
    opacity = max(0.0, min(1.0, float(getattr(rig, "fbp_opacity", 1.0))))
    try:
        plane.show_transparent = opacity < 1.0
    except FBP_DATA_IO_ERRORS:
        pass

    is_procedural = bool(getattr(rig, "fbp_is_color_plane", False))
    for mat in list(getattr(plane.data, "materials", ()) or ()):
        if not mat or not fbp_material_is_owned(mat):
            continue
        if is_procedural and getattr(mat, "use_nodes", False):
            # The procedural updater already writes metadata and render settings.
            # Avoid configuring the same material twice for every slider event.
            update_fbp_procedural_material_opacity(mat, opacity)
            continue
        try:
            if abs(float(mat.get("fbp_opacity", 1.0)) - opacity) > 1e-6:
                mat["fbp_opacity"] = opacity
        except FBP_DATA_ERRORS:
            pass
        configure_fbp_material_surface(mat, opacity, has_alpha=True)

    if not is_procedural:
        try:
            from .geometry_nodes import (
                fbp_schedule_clipping_mask_sync,
                fbp_sync_layer_opacity_effect,
            )
            fbp_sync_layer_opacity_effect(rig, opacity)
            # Clipping Mask samples the visible alpha of its source layer.
            # Coalesce slider drags into one safe relation refresh.
            fbp_schedule_clipping_mask_sync(
                getattr(bpy.context, "scene", None)
            )
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, ImportError) as exc:
            fbp_warn("Could not update layer opacity in place", exc)


# SECTION 04 - Safe / empty frame materials #

# SECTION 05 - Image / color / gradient shader construction #

def fbp_alpha_render_method(scene=None):
    # Return the requested FBP alpha surface method for the active Scene.
    if scene is None:
        try:
            scene = getattr(bpy.context, "scene", None)
        except FBP_DATA_IO_ERRORS:
            scene = None
    method = str(getattr(scene, "fbp_alpha_render_method", "AUTO") or "AUTO").upper()
    return method if method in {'AUTO', 'DITHERED', 'BLENDED', 'OPAQUE'} else 'AUTO'


def fbp_resolve_material_render_method(opacity=1.0, has_alpha=True, scene=None):
    # Resolve the effective Blender surface method without wasting alpha on opaque materials.
    alpha = max(0.0, min(1.0, float(opacity)))
    needs_alpha = bool(has_alpha) or alpha < 0.999
    requested = fbp_alpha_render_method(scene)
    if requested == 'OPAQUE' or not needs_alpha:
        return 'OPAQUE'
    if requested == 'BLENDED':
        return 'BLENDED'
    # AUTO preserves smooth alpha edges. Depth Blur is handled as an
    # explicit image effect instead of forcing Eevee depth writes.
    return 'BLENDED'


def configure_fbp_material_surface(mat, opacity=1.0, has_alpha=True, scene=None):
    if not mat:
        return
    changed = False
    alpha = max(0.0, min(1.0, float(opacity)))
    try:
        current = tuple(mat.diffuse_color)
        target = (current[0], current[1], current[2], alpha)
        if any(abs(float(a) - float(b)) > 1e-6 for a, b in zip(current, target, strict=True)):
            mat.diffuse_color = target
            changed = True
    except FBP_DATA_IO_ERRORS:
        pass

    try:
        if bool(mat.get("fbp_surface_has_alpha", not bool(has_alpha))) != bool(has_alpha):
            mat["fbp_surface_has_alpha"] = bool(has_alpha)
            changed = True
        if abs(float(mat.get("fbp_surface_opacity", -1.0)) - alpha) > 1e-6:
            mat["fbp_surface_opacity"] = alpha
            changed = True
    except FBP_DATA_ERRORS:
        pass

    render_method = fbp_resolve_material_render_method(alpha, has_alpha, scene)
    legacy_method = {
        'DITHERED': 'HASHED',
        'BLENDED': 'BLEND',
        'OPAQUE': 'OPAQUE',
    }.get(render_method, 'OPAQUE')
    for attr, value in (
        ('surface_render_method', render_method),
        ('blend_method', legacy_method),
        ('show_transparent_back', True),
        ('use_screen_refraction', False),
    ):
        if hasattr(mat, attr):
            try:
                if getattr(mat, attr) != value:
                    setattr(mat, attr, value)
                    changed = True
            except FBP_DATA_IO_ERRORS:
                pass
    if changed:
        try:
            mat.update_tag()
        except FBP_DATA_IO_ERRORS:
            pass


def fbp_refresh_material_render_methods(scene=None):
    # Apply the selected alpha method to existing owned materials in place.
    changed = 0
    for mat in tuple(getattr(bpy.data, 'materials', ()) or ()):
        if not mat or not fbp_material_is_owned(mat):
            continue
        try:
            opacity = float(mat.get('fbp_surface_opacity', mat.get('fbp_opacity', mat.diffuse_color[3])))
        except FBP_DATA_ERRORS:
            opacity = 1.0
        try:
            has_alpha = bool(mat.get('fbp_surface_has_alpha', True))
        except FBP_DATA_ERRORS:
            has_alpha = True
        before = getattr(mat, 'surface_render_method', None) if hasattr(mat, 'surface_render_method') else getattr(mat, 'blend_method', None)
        configure_fbp_material_surface(mat, opacity, has_alpha, scene=scene)
        after = getattr(mat, 'surface_render_method', None) if hasattr(mat, 'surface_render_method') else getattr(mat, 'blend_method', None)
        if before != after:
            changed += 1
    return changed


def create_fbp_color_material(name, color=(1.0, 1.0, 1.0, 1.0), use_emission=True, holdout=False):
    mat = bpy.data.materials.get(name) or bpy.data.materials.new(name=name)
    mat["fbp_owned"] = True
    mat.use_nodes = True
    configure_fbp_material_surface(mat, color[3], has_alpha=color[3] < 0.999)
    try:
        mat.diffuse_color = color
        mat["fbp_color_material"] = True
        mat["fbp_color_value"] = tuple(color)
    except (TypeError, ValueError) as exc:
        fbp_warn("Could not assign material viewport color", exc)
    nodes = mat.node_tree.nodes
    links = mat.node_tree.links
    nodes.clear()
    out = nodes.new(type='ShaderNodeOutputMaterial')
    out.location = (320, 0)
    if holdout:
        hold = nodes.new(type='ShaderNodeHoldout')
        hold.location = (0, 0)
        links.new(hold.outputs[0], out.inputs[0])
        mat["fbp_holdout_material"] = True
        return mat
    if use_emission:
        shader = nodes.new(type='ShaderNodeEmission')
        shader.location = (0, 0)
        color_sock = safe_get_socket(shader, ['color']) or shader.inputs[0]
        color_sock.default_value = color
        try:
            shader.inputs['Strength'].default_value = 1.0
        except FBP_DATA_IO_ERRORS:
            pass
    else:
        shader = nodes.new(type='ShaderNodeBsdfPrincipled')
        shader.location = (0, 0)
        base = safe_get_socket(shader, ['base', 'color']) or shader.inputs[0]
        base.default_value = color
        alpha = safe_get_socket(shader, ['alpha'])
        if alpha:
            alpha.default_value = color[3]
        spec = safe_get_socket(shader, ['specular'])
        if spec:
            spec.default_value = 0.0
    if use_emission and color[3] < 0.999:
        transparent = nodes.new(type='ShaderNodeBsdfTransparent')
        transparent.name = 'FBP_Transparent'
        transparent.location = (0, -140)
        mix = nodes.new(type='ShaderNodeMixShader')
        mix.name = 'FBP_Alpha_Mix'
        mix.location = (180, 0)
        mix.inputs[0].default_value = color[3]
        links.new(transparent.outputs[0], mix.inputs[1])
        links.new(shader.outputs[0], mix.inputs[2])
        links.new(mix.outputs[0], out.inputs[0])
    else:
        links.new(shader.outputs[0], out.inputs[0])
    return mat


def create_fbp_gradient_material(name, mode='LINEAR', kind='COLOR', color_a=(1.0, 0.3686274509803922, 0.596078431372549, 1.0), color_b=(0.058823529411764705, 0.12941176470588237, 0.24313725490196078, 1.0), reverse=False, use_emission=True):
    """Create a lightweight editable gradient material for FBP color planes.

    The material uses UV coordinates so it is visible in material preview/render.
    Radial gradients are centered around a real pivot before Mapping, so scale and
    rotation behave around the visual center instead of drifting from the corner.
    A real ColorRamp node stays exposed for advanced editing.
    """
    mat = bpy.data.materials.get(name) or bpy.data.materials.new(name=name)
    mat["fbp_owned"] = True
    mat.use_nodes = True
    configure_fbp_material_surface(mat, 1.0, has_alpha=True)
    try:
        mat.diffuse_color = color_b
    except (TypeError, ValueError) as exc:
        fbp_warn("Could not assign gradient material viewport color", exc)
    nodes = mat.node_tree.nodes
    links = mat.node_tree.links
    nodes.clear()

    out = nodes.new(type='ShaderNodeOutputMaterial')
    out.location = (980, 0)
    texcoord = nodes.new(type='ShaderNodeTexCoord')
    texcoord.location = (-980, 0)

    # Pivot-aware vector chain.
    # UV -> subtract editable center -> rotate/scale around that center.
    center = nodes.new(type='ShaderNodeVectorMath')
    center.location = (-760, 0)
    center.name = 'FBP_GradientCenter'
    center.label = 'Frame by Plane Gradient Center'
    center.operation = 'SUBTRACT'
    center['fbp_gradient_center'] = True
    center.inputs[1].default_value[0] = 0.5
    center.inputs[1].default_value[1] = 0.5
    center.inputs[1].default_value[2] = 0.0

    mapping = nodes.new(type='ShaderNodeMapping')
    mapping.location = (-540, 0)
    mapping.name = 'FBP_GradientMapping'
    mapping.label = 'Frame by Plane Gradient Mapping'
    mapping['fbp_gradient_mapping'] = True

    links.new(texcoord.outputs['UV'], center.inputs[0])
    links.new(center.outputs['Vector'], mapping.inputs['Vector'])

    if mode == 'CENTER':
        gradient_vector_output = mapping.outputs['Vector']
        grad_location = (-300, 0)
    else:
        # Linear gradients need the vector moved back to UV space after pivoted transforms,
        # otherwise half the ramp is clamped because coordinates become negative.
        recenter = nodes.new(type='ShaderNodeVectorMath')
        recenter.location = (-320, 0)
        recenter.name = 'FBP_GradientRecenter'
        recenter.label = 'Frame by Plane Gradient Recenter'
        recenter.operation = 'ADD'
        recenter.inputs[1].default_value[0] = 0.5
        recenter.inputs[1].default_value[1] = 0.5
        recenter.inputs[1].default_value[2] = 0.0
        links.new(mapping.outputs['Vector'], recenter.inputs[0])
        gradient_vector_output = recenter.outputs['Vector']
        grad_location = (-100, 0)

    grad = nodes.new(type='ShaderNodeTexGradient')
    grad.location = grad_location
    grad.name = 'FBP_GradientTexture'
    grad.label = 'Frame by Plane Gradient Texture'
    grad.gradient_type = 'SPHERICAL' if mode == 'CENTER' else 'LINEAR'
    links.new(gradient_vector_output, grad.inputs['Vector'])

    ramp = nodes.new(type='ShaderNodeValToRGB')
    ramp.location = (120, 0)
    ramp.name = 'FBP_ColorRamp'
    ramp.label = 'Frame by Plane Color Ramp'
    c0 = tuple(color_a)
    c1 = tuple(color_b)
    if kind == 'ALPHA':
        c0 = (c0[0], c0[1], c0[2], 0.0)
        c1 = (c1[0], c1[1], c1[2], max(0.0, min(1.0, c1[3])))
    if reverse:
        c0, c1 = c1, c0
    ramp['fbp_gradient_ramp'] = True
    ramp.color_ramp.elements[0].position = 0.0
    ramp.color_ramp.elements[0].color = c0
    ramp.color_ramp.elements[1].position = 1.0
    ramp.color_ramp.elements[1].color = c1
    links.new(grad.outputs['Fac'], ramp.inputs['Fac'])

    shader = nodes.new(type='ShaderNodeEmission' if use_emission else 'ShaderNodeBsdfPrincipled')
    shader.location = (440, 110)
    color_sock = safe_get_socket(shader, ['color']) or shader.inputs[0]
    links.new(ramp.outputs['Color'], color_sock)
    if use_emission:
        strength = safe_get_socket(shader, ['strength'])
        if strength:
            strength.default_value = 1.0
        transparent = nodes.new(type='ShaderNodeBsdfTransparent')
        transparent.name = 'FBP_Transparent'
        transparent.location = (440, -140)
        mix = nodes.new(type='ShaderNodeMixShader')
        mix.name = 'FBP_Alpha_Mix'
        mix.location = (760, 0)
        links.new(ramp.outputs['Alpha'], mix.inputs[0])
        links.new(transparent.outputs[0], mix.inputs[1])
        links.new(shader.outputs[0], mix.inputs[2])
        links.new(mix.outputs[0], out.inputs[0])
    else:
        alpha_sock = safe_get_socket(shader, ['alpha'])
        if alpha_sock:
            links.new(ramp.outputs['Alpha'], alpha_sock)
        links.new(shader.outputs[0], out.inputs[0])

    mat['fbp_gradient_material'] = True
    mat['fbp_gradient_mode'] = mode
    mat['fbp_gradient_kind'] = kind
    mat['fbp_gradient_reverse'] = bool(reverse)
    mat['fbp_use_emission'] = bool(use_emission)
    return mat


def fbp_rebuild_color_plane_material(rig):
    """Rebuild the active material of an editable FBP color/gradient/holdout plane.

    When a color/gradient plane has frame rows, each frame must keep an independent
    material. Reuse the active material name instead of a shared rig-wide name, so
    editing one frame never overwrites the others.
    """
    if not rig or not getattr(rig, 'fbp_is_color_plane', False):
        return False
    plane = getattr(rig, 'fbp_plane_target', None)
    if not plane or not getattr(plane, 'data', None):
        return False
    custom_states = {}
    try:
        from .geometry_nodes import fbp_capture_custom_shader_effect_states
        custom_states = fbp_capture_custom_shader_effect_states(rig)
    except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError) as exc:
        fbp_warn("Could not capture custom shader values before procedural rebuild", exc)
    mode = getattr(rig, 'fbp_color_plane_mode', 'SOLID')
    use_emission = bool(getattr(rig, 'fbp_color_plane_emission', getattr(rig, 'fbp_use_emission', True)))

    target_index = None
    target_name = None
    current_mat = None
    if len(getattr(rig, 'fbp_images', [])) > 0 and len(plane.data.materials) > 0:
        target_index = max(0, min(getattr(rig, 'fbp_images_index', 0), len(plane.data.materials) - 1))
        current_mat = plane.data.materials[target_index]
        if current_mat:
            target_name = current_mat.name
    elif len(plane.data.materials) > 0 and plane.data.materials[0]:
        current_mat = plane.data.materials[0]
        target_name = current_mat.name

    old_ramp_data = fbp_capture_color_ramp_data(find_fbp_gradient_ramp_node(current_mat)) if mode == 'GRADIENT' and current_mat else None

    if mode == 'GRADIENT':
        gradient_kind = getattr(rig, 'fbp_gradient_kind', 'COLOR')
        mat = create_fbp_gradient_material(
            target_name or ("FBP_Gradient_" + rig.name),
            getattr(rig, 'fbp_gradient_mode', 'LINEAR'),
            gradient_kind,
            tuple(getattr(rig, 'fbp_gradient_color_a', (1.0, 0.3686274509803922, 0.596078431372549, 1.0))),
            tuple(getattr(rig, 'fbp_gradient_color_b', (0.058823529411764705, 0.12941176470588237, 0.24313725490196078, 1.0))),
            bool(getattr(rig, 'fbp_gradient_reverse', False)),
            use_emission,
        )
        if old_ramp_data:
            fbp_restore_color_ramp_data(old_ramp_data, find_fbp_gradient_ramp_node(mat))
        fbp_apply_gradient_kind_to_ramp_node(find_fbp_gradient_ramp_node(mat), gradient_kind)
    elif mode == 'HOLDOUT':
        mat = create_fbp_color_material(target_name or ("FBP_Mat_" + rig.name), (0.0, 0.0, 0.0, 1.0), use_emission, True)
    else:
        color = tuple(getattr(rig, 'fbp_color_plane_color', (1.0, 1.0, 1.0, 1.0)))
        mat = create_fbp_color_material(target_name or ("FBP_Mat_" + rig.name), color, use_emission, False)
    if target_index is not None and len(plane.data.materials) > 0:
        plane.data.materials[target_index] = mat
    else:
        plane.data.materials.clear()
        plane.data.materials.append(mat)
    fbp_set_rna_property_silent(rig, 'fbp_use_emission', use_emission)
    try:
        procedural_kind = 'GRADIENT' if mode == 'GRADIENT' else ('HOLDOUT' if mode == 'HOLDOUT' else 'SOLID')
        mat['fbp_procedural_kind'] = procedural_kind
        if len(getattr(rig, 'fbp_images', [])) > 0 and target_index is not None and 0 <= target_index < len(rig.fbp_images):
            item = rig.fbp_images[target_index]
            try:
                item.procedural_kind = procedural_kind
            except FBP_DATA_IO_ERRORS:
                pass
            try:
                # Import locally to keep materials.py below layers.py in the module graph.
                # The helper guards the RNA update callbacks while refreshing cached colors.
                from .layers import fbp_cache_procedural_preview_on_item
                fbp_cache_procedural_preview_on_item(item, mat, procedural_kind)
            except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError) as exc:
                fbp_warn('Could not cache procedural frame preview', exc)
    except FBP_DATA_IO_ERRORS:
        pass
    if mode == 'GRADIENT':
        try:
            apply_fbp_gradient_mapping_to_material(rig, mat)
        except Exception as exc:
            fbp_warn("Could not apply gradient transform after rebuilding material", exc)
    if mode != 'HOLDOUT':
        try:
            from .geometry_nodes import fbp_restore_enabled_shader_effects
            fbp_restore_enabled_shader_effects(
                rig, custom_states=custom_states
            )
        except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError) as exc:
            fbp_warn("Could not restore effects after rebuilding procedural material", exc)
    return True


# SECTION 06 - Holdout and original material restore #

def fbp_holdout_material():
    return create_fbp_color_material("FBP_HOLDOUT_MAT", (0.0, 0.0, 0.0, 1.0), True, True)


def _copy_image_user_settings(src_node, dst_node):
    try:
        src = getattr(src_node, 'image_user', None)
        dst = getattr(dst_node, 'image_user', None)
        if not src or not dst:
            return False
        for attr in ('frame_start', 'frame_duration', 'frame_offset', 'use_auto_refresh', 'use_cyclic'):
            try:
                setattr(dst, attr, getattr(src, attr))
            except FBP_DATA_IO_ERRORS:
                pass
        return True
    except Exception:
        return False


def _copy_image_user_animation(src_mat, src_node, dst_mat, dst_node):
    """Mirror ImageUser.frame_offset animation for alpha-aware holdout.

    Blender 5.1 stores Action curves in slot Channelbags instead of exposing
    ``Action.fcurves``. Keyframes are recreated through RNA so this works with
    both action layouts; source drivers are mirrored with one direct property
    driver rather than copying an incomplete expression without variables.
    """
    if not src_mat or not src_node or not dst_mat or not dst_node:
        return False
    src_user = getattr(src_node, 'image_user', None)
    dst_user = getattr(dst_node, 'image_user', None)
    if not src_user or not dst_user:
        return False
    try:
        src_path = src_user.path_from_id('frame_offset')
        dst_path = dst_user.path_from_id('frame_offset')
    except FBP_DATA_ERRORS:
        return False

    src_tree = src_mat.node_tree
    dst_tree = dst_mat.node_tree
    copied = False
    try:
        dst_user.driver_remove('frame_offset')
    except FBP_DATA_ERRORS:
        pass
    fbp_remove_action_fcurves(dst_tree, dst_path)

    src_curve = fbp_find_action_fcurve(src_tree, src_path)
    if src_curve is not None:
        try:
            for key in src_curve.keyframe_points:
                dst_user.frame_offset = int(round(float(key.co.y)))
                dst_tree.keyframe_insert(data_path=dst_path, frame=float(key.co.x))
            dst_curve = fbp_find_action_fcurve(dst_tree, dst_path)
            if dst_curve is not None:
                source_keys = list(src_curve.keyframe_points)
                destination_keys = list(dst_curve.keyframe_points)
                for source_key, destination_key in zip(source_keys, destination_keys, strict=True):
                    destination_key.interpolation = source_key.interpolation
                try:
                    dst_curve.update()
                except FBP_DATA_ERRORS:
                    pass
            copied = True
        except FBP_DATA_ERRORS as exc:
            fbp_warn('Could not copy native ImageUser keyframes to holdout', exc)

    try:
        src_ad = getattr(src_tree, 'animation_data', None)
        src_driver = next(
            (curve for curve in list(getattr(src_ad, 'drivers', []) or []) if curve.data_path == src_path),
            None,
        )
        if src_driver is not None:
            # A single property driver mirrors the fully evaluated source offset,
            # including any source variables and expressions.
            fbp_remove_action_fcurves(dst_tree, dst_path)
            dst_curve = dst_user.driver_add('frame_offset')
            driver = dst_curve.driver
            driver.type = 'SCRIPTED'
            while driver.variables:
                driver.variables.remove(driver.variables[0])
            variable = driver.variables.new()
            variable.name = 'source_offset'
            variable.type = 'SINGLE_PROP'
            target = variable.targets[0]
            target.id = src_tree
            target.data_path = src_path
            driver.expression = 'source_offset'
            copied = True
    except FBP_DATA_ERRORS as exc:
        fbp_warn('Could not mirror native ImageUser driver to holdout', exc)

    try:
        dst_user.frame_offset = int(getattr(src_user, 'frame_offset', 0) or 0)
    except FBP_DATA_ERRORS:
        pass
    return copied


def fbp_alpha_holdout_material_from_source(source_mat):
    """Create a holdout material that respects the source alpha and native timing."""
    if not source_mat or not getattr(source_mat, "use_nodes", False) or not source_mat.node_tree:
        return fbp_holdout_material()
    img = None
    interpolation = 'Closest'
    src_node = None
    for node in source_mat.node_tree.nodes:
        if node.type == 'TEX_IMAGE' and getattr(node, "image", None):
            img = node.image
            src_node = node
            interpolation = getattr(node, "interpolation", interpolation)
            break
    if not img:
        return fbp_holdout_material()
    mat_name = "FBP_AlphaHoldout_" + source_mat.name
    # Always create a fresh holdout material. Reusing a material with the same
    # name can keep stale ImageUser timing/drivers after the native source
    # sequence has been rebuilt.
    mat = bpy.data.materials.new(mat_name)
    mat["fbp_owned"] = True
    mat.use_nodes = True
    set_fbp_material_transparency(mat, 1.0)
    nodes = mat.node_tree.nodes
    links = mat.node_tree.links
    nodes.clear()
    out = nodes.new(type='ShaderNodeOutputMaterial')
    out.location = (500, 0)
    tex = nodes.new(type='ShaderNodeTexImage')
    tex.name = 'FBP_AlphaHoldout_Texture'
    tex['fbp_holdout_image_node'] = True
    tex.location = (-450, 120)
    tex.image = img
    tex.interpolation = interpolation
    try:
        tex.extension = getattr(src_node, 'extension', tex.extension)
    except FBP_DATA_IO_ERRORS:
        pass
    _copy_image_user_settings(src_node, tex)
    _copy_image_user_animation(source_mat, src_node, mat, tex)
    transparent = nodes.new(type='ShaderNodeBsdfTransparent')
    transparent.location = (-100, -80)
    hold = nodes.new(type='ShaderNodeHoldout')
    hold.location = (-100, 120)
    mix = nodes.new(type='ShaderNodeMixShader')
    mix.location = (220, 40)
    links.new(tex.outputs['Alpha'], mix.inputs[0])
    links.new(transparent.outputs[0], mix.inputs[1])
    links.new(hold.outputs[0], mix.inputs[2])
    links.new(mix.outputs[0], out.inputs[0])
    mat["fbp_holdout_material"] = True
    mat["fbp_procedural_kind"] = "HOLDOUT"
    return mat

def fbp_material_is_holdout(mat):
    try:
        return bool(mat and mat.get('fbp_holdout_material', False))
    except Exception:
        return False


def fbp_plane_uses_holdout_materials(plane):
    try:
        mats = [mat for mat in plane.data.materials if mat]
        return bool(mats and all(fbp_material_is_holdout(mat) for mat in mats))
    except Exception:
        return False


def fbp_is_native_holdout_plane(rig):
    try:
        return bool(getattr(rig, "fbp_is_color_plane", False) and getattr(rig, "fbp_color_plane_mode", 'SOLID') == 'HOLDOUT')
    except Exception:
        return False


def fbp_rebuild_original_materials_for_holdout_restore(rig):
    """Restore non-holdout materials after alpha holdout.

    Image layers are always rebuilt through the native Blender Image Sequence
    backend. Procedural Color/Gradient planes rebuild their single editable
    procedural material. Holdout planes themselves are static masks.
    """
    plane = getattr(rig, "fbp_plane_target", None)
    if not plane or not getattr(plane, "data", None):
        return False

    if getattr(rig, "fbp_is_color_plane", False):
        if fbp_is_native_holdout_plane(rig):
            return True
        plane.data.materials.clear()
        fbp_rebuild_color_plane_material(rig)
        return True

    if len(getattr(rig, "fbp_images", [])) <= 0:
        return False

    try:
        from .native_backend import rebuild_native_sequence_from_rig
    except ImportError as exc:
        fbp_warn("Could not import native sequence restore helper", exc)
        return False

    restored = rebuild_native_sequence_from_rig(rig)
    if restored:
        try:
            ensure_fbp_plane_material_integrity(rig)
        except FBP_DATA_IO_ERRORS:
            pass
    return bool(restored)


def fbp_apply_holdout_materials_to_rig(rig):
    plane = getattr(rig, "fbp_plane_target", None)
    if not plane or not getattr(plane, "data", None) or fbp_is_native_holdout_plane(rig):
        return False

    # Idempotent: never apply holdout twice, otherwise the saved originals can become holdout materials.
    if rig_holdout_is_active(rig):
        return True

    store_original_materials_for_holdout(rig)
    source_materials = [mat for mat in plane.data.materials]
    plane.data.materials.clear()
    if not source_materials:
        plane.data.materials.append(fbp_holdout_material())
    else:
        for mat in source_materials:
            plane.data.materials.append(fbp_alpha_holdout_material_from_source(mat))
    return True


def store_original_materials_for_holdout(rig):
    plane = getattr(rig, "fbp_plane_target", None)
    if not plane or not getattr(plane, "data", None):
        return

    # Preserve the first valid backup. Repeated UI events must not overwrite it.
    if rig.get("fbp_holdout_original_materials", ""):
        return

    original_names = [mat.name if mat else "" for mat in plane.data.materials]
    rig["fbp_holdout_original_materials"] = "|".join(original_names)


def restore_original_materials_from_holdout(rig):
    plane = getattr(rig, "fbp_plane_target", None)
    names = rig.get("fbp_holdout_original_materials", "") if rig else ""
    if not plane:
        return False

    restored = False
    restored_mats = []
    if names:
        for name in names.split("|"):
            mat = bpy.data.materials.get(name) if name else None
            if mat:
                restored_mats.append(mat)

        # Reject a backup that resolves only to holdout materials.
        if restored_mats and not all(fbp_material_is_holdout(mat) for mat in restored_mats):
            plane.data.materials.clear()
            for mat in restored_mats:
                plane.data.materials.append(mat)
            restored = True

    if not restored:
        restored = fbp_rebuild_original_materials_for_holdout_restore(rig)

    if "fbp_holdout_original_materials" in rig:
        del rig["fbp_holdout_original_materials"]
    return bool(restored)


# SECTION 07 - Existing procedural node editing #


def fbp_relink_node_input(links, socket, output_socket):
    try:
        if len(socket.links) == 1 and socket.links[0].from_socket == output_socket:
            return False
        while socket.links:
            links.remove(socket.links[0])
        links.new(output_socket, socket)
        return True
    except FBP_DATA_IO_ERRORS:
        return False


def fbp_active_surface_chain(mat):
    """Return the nodes that currently feed the active Material Output."""
    node_tree = getattr(mat, 'node_tree', None) if mat else None
    if not node_tree:
        return None, None, None, None
    nodes = node_tree.nodes
    outputs = [node for node in nodes if getattr(node, 'type', '') == 'OUTPUT_MATERIAL']
    out = next((node for node in outputs if bool(getattr(node, 'is_active_output', False))), None)
    out = out or (outputs[0] if outputs else None)
    if out is None:
        return None, None, None, None
    surface = safe_get_socket(out, ['surface']) or (out.inputs[0] if out.inputs else None)
    link = surface.links[0] if surface and surface.links else None
    active = getattr(link, 'from_node', None)
    if active is None:
        return out, None, None, None
    if getattr(active, 'type', '') != 'MIX_SHADER':
        return out, active, None, None

    mix = active
    shader_link = mix.inputs[2].links[0] if len(mix.inputs) > 2 and mix.inputs[2].links else None
    transparent_link = mix.inputs[1].links[0] if len(mix.inputs) > 1 and mix.inputs[1].links else None
    shader = getattr(shader_link, 'from_node', None)
    transparent = getattr(transparent_link, 'from_node', None)
    if getattr(transparent, 'type', '') != 'BSDF_TRANSPARENT':
        transparent = None
    return out, shader, mix, transparent


def update_fbp_procedural_material_opacity(mat, opacity=1.0):
    """Apply the layer opacity slider to solid/gradient procedural materials."""
    if not mat or not getattr(mat, 'use_nodes', False):
        return False
    opacity = max(0.0, min(1.0, float(opacity)))
    nodes = mat.node_tree.nodes
    links = mat.node_tree.links
    configure_fbp_material_surface(mat, opacity, has_alpha=True)
    try:
        rgba = list(getattr(mat, 'diffuse_color', (1.0, 1.0, 1.0, 1.0)))
        rgba[3] = opacity
        mat.diffuse_color = tuple(rgba)
    except FBP_DATA_IO_ERRORS:
        pass
    try:
        if abs(float(mat.get('fbp_opacity', 1.0)) - opacity) > 1e-6:
            mat['fbp_opacity'] = opacity
    except FBP_DATA_ERRORS:
        pass

    if bool(mat.get('fbp_holdout_material', False)):
        return True

    if bool(mat.get('fbp_gradient_material', False)):
        ramp = find_fbp_gradient_ramp_node(mat)
        out, shader, mix, transparent = fbp_active_surface_chain(mat)
        if not ramp or not shader or not out:
            return False
        alpha_source = ramp.outputs['Alpha']
        opacity_node = next(
            (
                node for node in nodes
                if getattr(node, 'type', '') == 'MATH'
                and bool(node.get('fbp_internal_opacity_node', False))
            ),
            None,
        )
        if opacity < 0.999:
            if not opacity_node or opacity_node.type != 'MATH':
                if opacity_node:
                    try:
                        nodes.remove(opacity_node)
                    except FBP_DATA_ERRORS:
                        pass
                opacity_node = nodes.new(type='ShaderNodeMath')
                opacity_node.name = 'FBP_Opacity'
                opacity_node.label = 'Layer Opacity'
                opacity_node['fbp_internal_opacity_node'] = True
                opacity_node.location = (570, -60)
                opacity_node.operation = 'MULTIPLY'
            opacity_node.inputs[1].default_value = opacity
            fbp_relink_node_input(links, opacity_node.inputs[0], alpha_source)
            alpha_source = opacity_node.outputs['Value']
        elif opacity_node:
            try:
                nodes.remove(opacity_node)
            except FBP_DATA_ERRORS:
                pass
        alpha_sock = safe_get_socket(shader, ['alpha'])
        if getattr(shader, 'type', '') == 'EMISSION':
            if transparent is None:
                transparent = nodes.new(type='ShaderNodeBsdfTransparent')
                transparent.name = 'FBP_Transparent'
                transparent.location = (440, -140)
            if mix is None:
                mix = nodes.new(type='ShaderNodeMixShader')
                mix.name = 'FBP_Alpha_Mix'
                mix.location = (760, 0)
            fbp_relink_node_input(links, mix.inputs[0], alpha_source)
            fbp_relink_node_input(links, mix.inputs[1], transparent.outputs[0])
            fbp_relink_node_input(links, mix.inputs[2], shader.outputs[0])
            fbp_relink_node_input(links, out.inputs[0], mix.outputs[0])
        else:
            # Principled Alpha already controls transparency. A second
            # Transparent/Mix branch would square the gradient alpha.
            if alpha_sock:
                fbp_relink_node_input(links, alpha_sock, alpha_source)
            fbp_relink_node_input(links, out.inputs[0], shader.outputs[0])
            for redundant in (mix, transparent):
                if redundant is not None:
                    try:
                        nodes.remove(redundant)
                    except FBP_DATA_ERRORS:
                        pass
        return True

    if bool(mat.get('fbp_color_material', False)):
        color = list(fbp_material_color_value(mat, (1.0, 1.0, 1.0, 1.0)))
        color[3] = opacity
        mat['fbp_color_value'] = tuple(color)
        out, shader, mix, transparent = fbp_active_surface_chain(mat)
        if shader:
            color_sock = safe_get_socket(shader, ['color']) or shader.inputs[0]
            try:
                color_sock.default_value = tuple(color)
            except FBP_DATA_IO_ERRORS:
                pass
            alpha_sock = safe_get_socket(shader, ['alpha'])
            if alpha_sock:
                try:
                    alpha_sock.default_value = opacity
                except FBP_DATA_IO_ERRORS:
                    pass
        if getattr(shader, 'type', '') == 'EMISSION' and out:
            if opacity < 0.999:
                if transparent is None:
                    transparent = nodes.new(type='ShaderNodeBsdfTransparent')
                    transparent.name = 'FBP_Transparent'
                    transparent.location = (0, -140)
                if mix is None:
                    mix = nodes.new(type='ShaderNodeMixShader')
                    mix.name = 'FBP_Alpha_Mix'
                    mix.location = (180, 0)
                mix.inputs[0].default_value = opacity
                fbp_relink_node_input(links, mix.inputs[1], transparent.outputs[0])
                fbp_relink_node_input(links, mix.inputs[2], shader.outputs[0])
                fbp_relink_node_input(links, out.inputs[0], mix.outputs[0])
            else:
                # Opaque emission needs only Emission -> Material Output. Remove
                # the transparent branch instead of leaving dormant shader nodes.
                fbp_relink_node_input(links, out.inputs[0], shader.outputs[0])
                for redundant in (mix, transparent):
                    if redundant is not None:
                        try:
                            nodes.remove(redundant)
                        except FBP_DATA_ERRORS:
                            pass
        return True

    return False


def fbp_rebuild_procedural_material_for_emission(mat, rig, use_emission):
    if not mat:
        return None
    opacity = max(0.0, min(1.0, float(getattr(rig, 'fbp_opacity', 1.0))))
    if bool(mat.get('fbp_holdout_material', False)):
        return create_fbp_color_material(mat.name, (0.0, 0.0, 0.0, 1.0), use_emission, True)
    if bool(mat.get('fbp_gradient_material', False)):
        new_mat = create_fbp_gradient_material(
            mat.name,
            str(mat.get('fbp_gradient_mode', getattr(rig, 'fbp_gradient_mode', 'LINEAR'))),
            str(mat.get('fbp_gradient_kind', getattr(rig, 'fbp_gradient_kind', 'COLOR'))),
            tuple(getattr(rig, 'fbp_gradient_color_a', (0,0,0,0))),
            tuple(getattr(rig, 'fbp_gradient_color_b', (0,0,0,1))),
            bool(mat.get('fbp_gradient_reverse', getattr(rig, 'fbp_gradient_reverse', True))),
            bool(use_emission),
        )
        copy_color_ramp(find_fbp_gradient_ramp_node(mat), find_fbp_gradient_ramp_node(new_mat))
        apply_fbp_gradient_mapping_to_material(rig, new_mat)
        update_fbp_procedural_material_opacity(new_mat, opacity)
        return new_mat
    if bool(mat.get('fbp_color_material', False)):
        color = list(fbp_material_color_value(mat, (1.0,1.0,1.0,1.0)))
        color[3] = opacity
        return create_fbp_color_material(mat.name, tuple(color), bool(use_emission), False)
    return mat


# SECTION 08 - Holdout state and gradient controls backend #

def rig_holdout_is_active(rig):
    """Return True when a rig currently uses temporary Frame by Plane holdout materials."""
    try:
        if not rig or fbp_is_native_holdout_plane(rig):
            return False
        if rig.get("fbp_holdout_original_materials", ""):
            return True
        return fbp_plane_uses_holdout_materials(getattr(rig, "fbp_plane_target", None))
    except Exception:
        return False


# SECTION 09 - Gradient material helpers #

def get_fbp_gradient_material_from_rig(rig):
    """Return the editable gradient material assigned to the selected FBP rig, if any."""
    if not rig or not getattr(rig, 'fbp_is_color_plane', False):
        return None
    plane = getattr(rig, 'fbp_plane_target', None)
    if not plane or not getattr(plane, 'data', None) or not getattr(plane.data, 'materials', None):
        return None
    mat = fbp_get_active_frame_material(rig)
    if mat and getattr(mat, 'use_nodes', False) and mat.get('fbp_gradient_material'):
        return mat
    return None


def find_fbp_gradient_ramp_node(mat):
    """Find the real ColorRamp node used by a Frame by Plane gradient material."""
    if not mat or not getattr(mat, 'node_tree', None):
        return None
    nodes = mat.node_tree.nodes
    node = nodes.get('FBP_ColorRamp')
    if node and node.type == 'VALTORGB':
        return node
    for candidate in nodes:
        if candidate.type == 'VALTORGB' and candidate.get('fbp_gradient_ramp'):
            return candidate
    for candidate in nodes:
        if candidate.type == 'VALTORGB' and candidate.label == 'Frame by Plane Color Ramp':
            return candidate
    for candidate in nodes:
        if candidate.type == 'VALTORGB':
            return candidate
    return None


def get_fbp_gradient_mapping_node(mat):
    """Find the Mapping node used to transform Frame by Plane gradient planes."""
    if not mat or not getattr(mat, 'node_tree', None):
        return None
    node = mat.node_tree.nodes.get('FBP_GradientMapping')
    if node and node.type == 'MAPPING':
        return node
    for candidate in mat.node_tree.nodes:
        if candidate.type == 'MAPPING' and candidate.get('fbp_gradient_mapping'):
            return candidate
    return None


def get_fbp_gradient_center_node(mat):
    """Find the Vector Math node that stores the editable gradient pivot."""
    if not mat or not getattr(mat, 'use_nodes', False):
        return None
    node = mat.node_tree.nodes.get('FBP_GradientCenter')
    if node:
        return node
    for candidate in mat.node_tree.nodes:
        if candidate.type == 'VECT_MATH' and candidate.get('fbp_gradient_center'):
            return candidate
    return None


def update_fbp_gradient_viewport_color(rig, mat=None):
    """Keep Solid View readable by updating the flat viewport color from the ramp.

    Blender Solid View does not evaluate procedural ColorRamp shader nodes. This
    keeps the material/object viewport color close to the visible end color so the
    plane remains recognizable in Solid mode, while the real gradient stays visible
    in Material Preview and Rendered modes.
    """
    mat = mat or get_fbp_gradient_material_from_rig(rig)
    ramp = find_fbp_gradient_ramp_node(mat) if mat else None
    if not mat or not ramp:
        return
    try:
        elems = ramp.color_ramp.elements
        color = tuple(elems[-1].color) if elems else tuple(getattr(rig, 'fbp_gradient_color_b', (0.058823529411764705, 0.12941176470588237, 0.24313725490196078, 1.0)))
        mat.diffuse_color = color
        plane = getattr(rig, 'fbp_plane_target', None)
        if plane:
            plane.color = color
        if rig:
            rig.color = color
    except Exception as exc:
        fbp_warn("Could not update gradient Solid View fallback color", exc)


def apply_fbp_gradient_mapping_to_material(rig, mat=None):
    """Apply selected rig gradient transform controls to the real material nodes."""
    if not rig:
        return
    mat = mat or get_fbp_gradient_material_from_rig(rig)
    mapping = get_fbp_gradient_mapping_node(mat) if mat else None
    if not mapping:
        return
    mode = getattr(rig, 'fbp_gradient_mode', 'LINEAR')
    offset_x = float(getattr(rig, 'fbp_gradient_offset_x', 0.0))
    offset_y = float(getattr(rig, 'fbp_gradient_offset_y', 0.0))
    scale_x = max(0.001, float(getattr(rig, 'fbp_gradient_scale_x', 1.0)))
    scale_y = max(0.001, float(getattr(rig, 'fbp_gradient_scale_y', 1.0)))
    rotation = math.radians(float(getattr(rig, 'fbp_gradient_rotation', 0.0)))

    center = get_fbp_gradient_center_node(mat)
    if not center:
        return
    # Positive offset moves the visual center in the same direction on the plane.
    center.inputs[1].default_value[0] = 0.5 + offset_x
    center.inputs[1].default_value[1] = 0.5 + offset_y
    center.inputs[1].default_value[2] = 0.0
    mapping.inputs['Location'].default_value[0] = 0.0
    mapping.inputs['Location'].default_value[1] = 0.0
    mapping.inputs['Location'].default_value[2] = 0.0

    # Radial gradients use coordinates centered around zero; scaling by 2 maps
    # the distance from center to plane edge to roughly the full ColorRamp range.
    if mode == 'CENTER':
        mapping.inputs['Scale'].default_value[0] = 2.0 / scale_x
        mapping.inputs['Scale'].default_value[1] = 2.0 / scale_y
    else:
        mapping.inputs['Scale'].default_value[0] = 1.0 / scale_x
        mapping.inputs['Scale'].default_value[1] = 1.0 / scale_y
    mapping.inputs['Scale'].default_value[2] = 1.0
    mapping.inputs['Rotation'].default_value[0] = 0.0
    mapping.inputs['Rotation'].default_value[1] = 0.0
    mapping.inputs['Rotation'].default_value[2] = rotation
    update_fbp_gradient_viewport_color(rig, mat)


# SECTION 10 - Gradient preview scene material #

def get_fbp_gradient_preview_material(scene):
    """Return the hidden preview material used by the creation ColorRamp without creating data-blocks.

    Blender may call UI draw methods in a read-only context, so data-block creation must
    happen in an operator/invoke/execute step, not while drawing a panel or popup.
    """
    mat_name = getattr(scene, 'fbp_gradient_preview_material_name', '') if scene else ''
    mat = bpy.data.materials.get(mat_name) if mat_name else None
    if mat and bool(mat.get('fbp_gradient_preview_material')):
        return mat
    return None


def get_or_create_fbp_gradient_preview_material(scene):
    """Create/reuse the hidden material that exposes Blender's native ColorRamp in creation popups."""
    mode = getattr(scene, 'fbp_gradient_mode', 'LINEAR')
    kind = getattr(scene, 'fbp_gradient_kind', 'COLOR')
    color_a = tuple(getattr(scene, 'fbp_gradient_color_a', (1.0, 0.3686274509803922, 0.596078431372549, 1.0)))
    color_b = tuple(getattr(scene, 'fbp_gradient_color_b', (0.058823529411764705, 0.12941176470588237, 0.24313725490196078, 1.0)))
    reverse = bool(getattr(scene, 'fbp_gradient_reverse', False))
    use_emission = bool(getattr(scene, 'fbp_color_plane_emission', True))

    mat = get_fbp_gradient_preview_material(scene)
    needs_rebuild = mat is None
    if mat is not None:
        try:
            needs_rebuild = (
                mat.get('fbp_gradient_mode') != mode or
                mat.get('fbp_gradient_kind') != kind or
                bool(mat.get('fbp_gradient_reverse', False)) != reverse or
                bool(mat.get('fbp_use_emission', use_emission)) != use_emission
            )
        except Exception:
            needs_rebuild = True

    ramp_data = fbp_capture_color_ramp_data(find_fbp_gradient_ramp_node(mat)) if mat else None
    mat_name = mat.name if mat else "FBP_Gradient_Creation_Preview"
    if needs_rebuild:
        mat = create_fbp_gradient_material(mat_name, mode, kind, color_a, color_b, reverse, use_emission)
        mat.use_fake_user = True
        mat['fbp_gradient_preview_material'] = True
        if scene is not None:
            scene.fbp_gradient_preview_material_name = mat.name
        if ramp_data:
            fbp_restore_color_ramp_data(ramp_data, find_fbp_gradient_ramp_node(mat))

    fbp_apply_gradient_kind_to_ramp_node(find_fbp_gradient_ramp_node(mat), kind)
    return mat


def fbp_update_scene_gradient_preview_material(scene):
    mat = get_or_create_fbp_gradient_preview_material(scene)
    fbp_apply_gradient_kind_to_ramp_node(
        find_fbp_gradient_ramp_node(mat),
        getattr(scene, 'fbp_gradient_kind', 'COLOR'),
    )
    return mat


def fbp_schedule_gradient_preview_material_sync(scene, *, first_interval=0.03):
    """Create/update the hidden gradient preview from Blender's idle timer.

    Scene property callbacks and panel ``draw()`` can run while Blender is
    rebuilding RNA/Undo state. They therefore only enqueue a serializable scene
    identity; the timer resolves the current Scene again before touching any
    Material or node datablock. Repeated slider/dropdown updates collapse into
    one task that reads the newest Scene values.
    """
    if scene is None:
        return False
    scene_key = fbp_obj_runtime_key(scene)
    if scene_key is None:
        return False
    try:
        scene_name = str(getattr(scene, "name", "") or "")
    except FBP_DATA_ERRORS:
        return False
    token = str(scene_key)
    _PENDING_GRADIENT_PREVIEW_SYNC[token] = scene_name

    def _sync_latest():
        stored_name = _PENDING_GRADIENT_PREVIEW_SYNC.pop(token, None)
        if stored_name is None:
            return None
        target = fbp_find_id_by_runtime_key(
            bpy.data.scenes, scene_key, stored_name
        )
        if target is None:
            return None
        try:
            fbp_update_scene_gradient_preview_material(target)
        except FBP_DATA_ERRORS as exc:
            fbp_warn("Could not update gradient preview material", exc)
            return None
        try:
            from .core import fbp_tag_view3d_ui_redraw
            fbp_tag_view3d_ui_redraw()
        except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            pass
        return None

    scheduled = _safe_tasks.schedule_once(
        f"materials.gradient_preview_sync:{token}",
        _sync_latest,
        first_interval=max(0.0, float(first_interval)),
    )
    if not scheduled:
        # A task with this key may already be pending. Its callback will consume
        # the freshly replaced payload above, so this is still a successful
        # coalesced request.
        return token in _PENDING_GRADIENT_PREVIEW_SYNC
    return True


def fbp_capture_color_ramp_data(ramp_node):
    """Store ColorRamp values before rebuilding nodes/materials."""
    if not ramp_node:
        return None
    try:
        ramp = ramp_node.color_ramp
        return {
            "interpolation": ramp.interpolation,
            "elements": [(float(el.position), tuple(el.color)) for el in ramp.elements],
        }
    except Exception as exc:
        fbp_warn("Could not capture ColorRamp data", exc)
        return None


def fbp_restore_color_ramp_data(data, target_node):
    """Restore ColorRamp values after rebuilding nodes/materials."""
    if not data or not target_node:
        return False
    try:
        ramp = target_node.color_ramp
        ramp.interpolation = data.get("interpolation", ramp.interpolation)
        elements = list(data.get("elements", []))
        if not elements:
            return False
        while len(ramp.elements) > 2:
            ramp.elements.remove(ramp.elements[-1])
        while len(ramp.elements) < len(elements):
            ramp.elements.new(elements[len(ramp.elements)][0])
        for el, (pos, color) in zip(ramp.elements, elements, strict=True):
            el.position = max(0.0, min(1.0, float(pos)))
            el.color = tuple(color)
        return True
    except Exception as exc:
        fbp_warn("Could not restore ColorRamp data", exc)
        return False


def fbp_apply_gradient_kind_to_ramp_node(ramp_node, kind):
    """Apply Color-to-Color or Transparent-to-Visible without rebuilding the whole material."""
    if not ramp_node:
        return False
    try:
        ramp = ramp_node.color_ramp
        elements = list(ramp.elements)
        if not elements:
            return False
        kind = (kind or 'ALPHA').upper()
        if kind == 'COLOR':
            for el in elements:
                col = list(el.color)
                col[3] = 1.0
                el.color = tuple(col)
        else:
            if len(elements) == 1:
                col = list(elements[0].color)
                col[3] = 1.0
                elements[0].color = tuple(col)
            else:
                first = list(elements[0].color)
                first[3] = 0.0
                elements[0].color = tuple(first)
                last = list(elements[-1].color)
                last[3] = 1.0
                elements[-1].color = tuple(last)
        return True
    except Exception as exc:
        fbp_warn("Could not apply gradient type to ColorRamp", exc)
        return False


def copy_color_ramp(source_node, target_node):
    """Copy ColorRamp elements and interpolation from one Blender ramp node to another."""
    return fbp_restore_color_ramp_data(fbp_capture_color_ramp_data(source_node), target_node)


def copy_scene_preview_ramp_to_rig(scene, rig):
    """After creating a Gradient Plane, copy the popup/N-Panel creation ramp to the real material."""
    preview = get_or_create_fbp_gradient_preview_material(scene)
    src = find_fbp_gradient_ramp_node(preview) if preview else None
    mat = get_fbp_gradient_material_from_rig(rig)
    dst = find_fbp_gradient_ramp_node(mat) if mat else None
    copy_color_ramp(src, dst)
    apply_fbp_gradient_mapping_to_material(rig, mat)


# SECTION 11 - Sequence frame procedural materials #

def fbp_get_active_frame_material(rig):
    """Return the material assigned to the active frame, falling back to slot 0."""
    plane = getattr(rig, 'fbp_plane_target', None)
    if not plane or not getattr(plane, 'data', None) or not getattr(plane.data, 'materials', None):
        return None
    if not plane.data.materials:
        return None
    if len(getattr(rig, 'fbp_images', [])) > 0:
        idx = max(0, min(int(getattr(rig, 'fbp_images_index', 0)), len(plane.data.materials) - 1))
        return plane.data.materials[idx]
    return plane.data.materials[0]


def fbp_material_color_value(mat, fallback=(1.0, 1.0, 1.0, 1.0)):
    """Read the flat color from an FBP material without assuming one shader type."""
    if not mat:
        return fallback
    try:
        value = mat.get('fbp_color_value')
        if value and len(value) >= 4:
            return tuple(float(v) for v in value[:4])
    except FBP_DATA_IO_ERRORS:
        pass
    try:
        if getattr(mat, 'diffuse_color', None):
            return tuple(float(v) for v in mat.diffuse_color)
    except FBP_DATA_IO_ERRORS:
        pass
    return fallback


def fbp_unique_material_name(base):
    """Return a material name that is not already used by bpy.data.materials."""
    base = str(base or "FBP_Material").strip() or "FBP_Material"
    if base not in bpy.data.materials:
        return base
    index = 1
    while True:
        candidate = f"{base}_{index:03d}"
        if candidate not in bpy.data.materials:
            return candidate
        index += 1


def fbp_duplicate_procedural_material_for_frame(source_mat, rig=None, suffix="Copy"):
    """Create a truly independent Color/Gradient/Holdout frame material.

    Gradient frame sequences must never share the same material datablock or node
    tree, otherwise editing one frame updates all frames. This helper recreates
    gradient/color materials from the
    active frame state and restoring the ColorRamp when needed.
    """
    if not source_mat:
        return None
    suffix = str(suffix or "Copy").replace(" ", "_")
    base_name = fbp_unique_material_name(f"{source_mat.name}_{suffix}")
    use_emission = bool(source_mat.get('fbp_use_emission', getattr(rig, 'fbp_use_emission', True) if rig else True))

    try:
        if bool(source_mat.get('fbp_gradient_material', False)):
            ramp_data = fbp_capture_color_ramp_data(find_fbp_gradient_ramp_node(source_mat))
            mat = create_fbp_gradient_material(
                base_name,
                source_mat.get('fbp_gradient_mode', getattr(rig, 'fbp_gradient_mode', 'LINEAR') if rig else 'LINEAR'),
                source_mat.get('fbp_gradient_kind', getattr(rig, 'fbp_gradient_kind', 'COLOR') if rig else 'COLOR'),
                tuple(getattr(rig, 'fbp_gradient_color_a', (1.0, 0.3686274509803922, 0.596078431372549, 1.0))) if rig else (1.0, 0.3686274509803922, 0.596078431372549, 1.0),
                tuple(getattr(rig, 'fbp_gradient_color_b', (0.058823529411764705, 0.12941176470588237, 0.24313725490196078, 1.0))) if rig else (0.058823529411764705, 0.12941176470588237, 0.24313725490196078, 1.0),
                bool(source_mat.get('fbp_gradient_reverse', getattr(rig, 'fbp_gradient_reverse', False) if rig else False)),
                use_emission,
            )
            if ramp_data:
                fbp_restore_color_ramp_data(ramp_data, find_fbp_gradient_ramp_node(mat))
            try:
                mat['fbp_procedural_kind'] = 'GRADIENT'
            except FBP_DATA_IO_ERRORS:
                pass
            if rig:
                try:
                    apply_fbp_gradient_mapping_to_material(rig, mat)
                except Exception as exc:
                    fbp_warn("Could not copy gradient mapping to duplicated frame material", exc)
            return mat

        if bool(source_mat.get('fbp_holdout_material', False)):
            mat = create_fbp_color_material(base_name, (0.0, 0.0, 0.0, 1.0), use_emission, True)
            try:
                mat['fbp_procedural_kind'] = 'HOLDOUT'
            except FBP_DATA_IO_ERRORS:
                pass
            return mat

        color = fbp_material_color_value(source_mat, tuple(getattr(rig, 'fbp_color_plane_color', (1.0, 1.0, 1.0, 1.0))) if rig else (1.0, 1.0, 1.0, 1.0))
        mat = create_fbp_color_material(base_name, color, use_emission, False)
        try:
            mat['fbp_procedural_kind'] = 'SOLID'
        except FBP_DATA_IO_ERRORS:
            pass
        return mat
    except Exception as exc:
        fbp_warn("Could not create independent procedural frame material", exc)

    try:
        mat = source_mat.copy()
        mat.name = base_name
        # Defensive: if Blender ever keeps a shared node tree here, make it local.
        try:
            if getattr(mat, 'node_tree', None):
                mat.node_tree = mat.node_tree.copy()
        except FBP_DATA_IO_ERRORS:
            pass
        return mat
    except Exception as exc:
        fbp_warn("Could not fallback-copy procedural material", exc)
        return None


def fbp_create_procedural_frame_material_for_rig(rig, suffix="Frame"):
    """Create an independent procedural material for a new color/gradient frame.

    The new frame copies the currently active procedural material first. This
    preserves edited solid colors and native ColorRamp edits, then the copy can
    be changed without affecting the source frame.
    """
    if not rig or not getattr(rig, "fbp_is_color_plane", False):
        return None, "Transparent Frame", True
    mode = getattr(rig, 'fbp_color_plane_mode', 'SOLID')
    use_emission = bool(getattr(rig, 'fbp_color_plane_emission', getattr(rig, 'fbp_use_emission', True)))
    safe_suffix = str(suffix).replace(" ", "_")

    active_mat = fbp_get_active_frame_material(rig)
    active_kind = 'GRADIENT' if (active_mat and bool(active_mat.get('fbp_gradient_material', False))) else ('HOLDOUT' if (active_mat and bool(active_mat.get('fbp_holdout_material', False))) else 'SOLID')
    # Only copy the active material when it matches the requested frame type.
    # Otherwise a Color frame inserted after selecting a Gradient frame would
    # inherit the gradient material and turn back into a gradient on selection.
    if active_mat and mode != 'HOLDOUT' and active_kind == mode:
        mat = fbp_duplicate_procedural_material_for_frame(active_mat, rig, safe_suffix)
        if mat:
            try:
                mat['fbp_procedural_kind'] = active_kind
            except FBP_DATA_IO_ERRORS:
                pass
            label = "Gradient Frame" if active_kind == 'GRADIENT' else "Color Frame"
            return mat, label, False

    if mode == 'GRADIENT':
        mat = create_fbp_gradient_material(
            f"FBP_Gradient_{rig.name}_{safe_suffix}",
            getattr(rig, 'fbp_gradient_mode', 'LINEAR'),
            getattr(rig, 'fbp_gradient_kind', 'COLOR'),
            tuple(getattr(rig, 'fbp_gradient_color_a', (1.0, 0.3686274509803922, 0.596078431372549, 1.0))),
            tuple(getattr(rig, 'fbp_gradient_color_b', (0.058823529411764705, 0.12941176470588237, 0.24313725490196078, 1.0))),
            bool(getattr(rig, 'fbp_gradient_reverse', False)),
            use_emission,
        )
        try:
            apply_fbp_gradient_mapping_to_material(rig, mat)
        except Exception as exc:
            fbp_warn("Could not copy gradient transform to new frame material", exc)
        try:
            mat['fbp_procedural_kind'] = 'GRADIENT'
        except FBP_DATA_IO_ERRORS:
            pass
        return mat, "Gradient Frame", False
    color = tuple(getattr(rig, 'fbp_color_plane_color', (1.0, 1.0, 1.0, 1.0)))
    mat = create_fbp_color_material(f"FBP_Color_{rig.name}_{safe_suffix}", color, use_emission, False)
    try:
        mat['fbp_procedural_kind'] = 'SOLID'
    except FBP_DATA_IO_ERRORS:
        pass
    return mat, "Color Frame", False


def unregister():
    _PENDING_PROXY_CACHE_ROOTS.clear()
    _PENDING_GRADIENT_PREVIEW_SYNC.clear()
    return None
