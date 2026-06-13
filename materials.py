"""Material, shader-node, opacity, emission, gradient and holdout helpers."""

import bpy
import os
import math

try:
    from .constants import FBP_SUPPORTED_VIDEO_EXT
except ImportError:
    from constants import FBP_SUPPORTED_VIDEO_EXT

# SECTION 00B - Shared runtime helpers #
try:
    from .runtime import fbp_warn, fbp_set_rna_property_silent
except ImportError:
    from runtime import fbp_warn, fbp_set_rna_property_silent

try:
    from . import safe_tasks as _safe_tasks
except ImportError:
    import safe_tasks as _safe_tasks

_PENDING_UNUSED_IMAGE_NAMES = globals().get('_PENDING_UNUSED_IMAGE_NAMES', set())


def ensure_fbp_plane_material_integrity(rig):
    """Keep a native image plane on one valid material slot."""
    plane = getattr(rig, 'fbp_plane_target', None) if rig else None
    mesh = getattr(plane, 'data', None) if plane else None
    if not mesh or not getattr(mesh, 'materials', None) or len(mesh.materials) == 0:
        return False
    try:
        while len(mesh.materials) > 1:
            mesh.materials.pop(index=len(mesh.materials) - 1)
        for poly in mesh.polygons:
            poly.material_index = 0
        mesh.update()
        return True
    except (AttributeError, ReferenceError, RuntimeError) as exc:
        fbp_warn('Could not normalize plane material slots', exc)
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


def fbp_images_from_material(mat):
    """Return image datablocks referenced by a material's image texture nodes."""
    images = []
    if not mat:
        return images
    try:
        nodes = getattr(getattr(mat, "node_tree", None), "nodes", [])
        for node in nodes:
            img = getattr(node, "image", None)
            if img and img not in images:
                images.append(img)
    except ReferenceError:
        pass
    except (AttributeError, TypeError, RuntimeError) as exc:
        fbp_warn("Could not inspect FBP material images", exc)
    return images


def _fbp_run_deferred_unused_image_cleanup():
    """Remove safe, unused image datablocks outside UI/operator callbacks.

    Blender 5.1 can still be decoding a native sequence/movie when a report popup
    closes. Freeing those cached buffers synchronously can enter Blender's movie
    cache teardown and crash the process. Sequence/movie datablocks are therefore
    deliberately left for Blender's orphan purge; simple FILE/GENERATED images are
    removed later from a timer with UI users unlinked.
    """
    processed = 0
    for name in list(_PENDING_UNUSED_IMAGE_NAMES):
        img = bpy.data.images.get(name)
        if img is None:
            _PENDING_UNUSED_IMAGE_NAMES.discard(name)
            continue
        try:
            if img.users != 0 or getattr(img, 'use_fake_user', False):
                _PENDING_UNUSED_IMAGE_NAMES.discard(name)
                continue
            source = str(getattr(img, 'source', 'FILE') or 'FILE').upper()
            if source in {'SEQUENCE', 'MOVIE'}:
                # Avoid Blender 5.1 movie-cache teardown crashes. These remain
                # harmless zero-user datablocks and can be purged explicitly.
                _PENDING_UNUSED_IMAGE_NAMES.discard(name)
                continue
            bpy.data.images.remove(
                img,
                do_unlink=True,
                do_id_user=True,
                do_ui_user=True,
            )
            processed += 1
            _PENDING_UNUSED_IMAGE_NAMES.discard(name)
        except ReferenceError:
            _PENDING_UNUSED_IMAGE_NAMES.discard(name)
        except (AttributeError, TypeError, RuntimeError, ValueError) as exc:
            _PENDING_UNUSED_IMAGE_NAMES.discard(name)
            fbp_warn('Could not remove deferred unused FBP image datablock', exc)
        if processed >= 8:
            break
    return 0.15 if _PENDING_UNUSED_IMAGE_NAMES else None


def fbp_remove_unused_images(images):
    """Queue unused Blender image datablocks for safe deferred cleanup.

    Never deletes image files from disk. Native SEQUENCE/MOVIE datablocks are not
    auto-freed because Blender may still own active decode/cache state.
    """
    queued = 0
    for img in list(images or []):
        try:
            if img and img.users == 0 and not getattr(img, 'use_fake_user', False):
                name = str(getattr(img, 'name', '') or '')
                if name and name not in _PENDING_UNUSED_IMAGE_NAMES:
                    _PENDING_UNUSED_IMAGE_NAMES.add(name)
                    queued += 1
        except ReferenceError:
            continue
        except (AttributeError, TypeError, RuntimeError) as exc:
            fbp_warn('Could not queue unused FBP image datablock', exc)
    if _PENDING_UNUSED_IMAGE_NAMES:
        _safe_tasks.schedule_once(
            'materials.unused_image_cleanup',
            _fbp_run_deferred_unused_image_cleanup,
            first_interval=1.25,
        )
    return queued


def fbp_remove_unused_materials_and_images(materials):
    """Remove private unused FBP materials and their now-unused image datablocks."""
    images = []
    for mat in list(materials or []):
        try:
            if not mat:
                continue
            for img in fbp_images_from_material(mat):
                if img not in images:
                    images.append(img)
            if mat.users == 0:
                bpy.data.materials.remove(mat)
        except ReferenceError:
            continue
        except (AttributeError, TypeError, RuntimeError) as exc:
            fbp_warn("Could not remove unused FBP material datablock", exc)
    return fbp_remove_unused_images(images)


def fbp_copy_material_slots_unique(src_plane, dst_plane):
    """Copy a plane's material slots so duplicated layers can be edited independently."""
    if not src_plane or not dst_plane or not getattr(dst_plane, 'data', None):
        return
    dst_plane.data.materials.clear()
    src_mats = []
    try:
        src_mats = list(src_plane.data.materials) if getattr(src_plane, 'data', None) else []
    except ReferenceError:
        src_mats = []
    for mat in src_mats:
        if not mat:
            continue
        try:
            new_mat = mat.copy()
            new_mat.name = mat.name + "_Copy"
            dst_plane.data.materials.append(new_mat)
        except Exception:
            dst_plane.data.materials.append(mat)


# SECTION 03 - Image materials, emission and opacity #

def rebuild_fbp_image_material(mat, use_emission=None, opacity=None):
    if not mat or is_fbp_empty_material(mat):
        return mat
    try:
        if bool(mat.get("fbp_native_sequence", False)):
            from .native_backend import rebuild_native_sequence_material
            return rebuild_native_sequence_material(mat, use_emission=use_emission, opacity=opacity)
    except Exception as exc:
        fbp_warn("Could not rebuild native sequence material", exc)
    try:
        image_path = mat.get("fbp_image_path", "")
    except Exception:
        image_path = ""
    if not image_path:
        # Legacy material: try to recover the image path from the existing node tree.
        if getattr(mat, 'use_nodes', False) and mat.node_tree:
            for node in mat.node_tree.nodes:
                if node.type == 'TEX_IMAGE' and getattr(node, 'image', None):
                    image_path = getattr(node.image, 'filepath', '')
                    break
    if not image_path:
        return mat
    interp = mat.get("fbp_interpolation", "Closest") if hasattr(mat, 'get') else "Closest"
    if use_emission is None:
        use_emission = bool(mat.get("fbp_use_emission", True)) if hasattr(mat, 'get') else True
    if opacity is None:
        opacity = float(mat.get("fbp_opacity", 1.0)) if hasattr(mat, 'get') else 1.0
    return create_fbp_material(mat.name, image_path, interp=interp, opacity=opacity, use_emission=use_emission)


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
    for i, mat in enumerate(list(plane.data.materials)):
        if not mat or not getattr(mat, 'use_nodes', False) or is_fbp_empty_material(mat):
            continue
        if getattr(rig, 'fbp_is_color_plane', False):
            new_mat = fbp_rebuild_procedural_material_for_emission(mat, rig, use_emission)
        else:
            new_mat = rebuild_fbp_image_material(mat, use_emission=use_emission, opacity=opacity)
        if new_mat:
            plane.data.materials[i] = new_mat
            if new_mat != mat:
                fbp_remove_unused_materials_and_images([mat])


def set_fbp_material_transparency(mat, opacity=1.0):
    configure_fbp_material_surface(mat, opacity, has_alpha=True)


def is_fbp_empty_material(mat):
    try:
        return bool(mat and mat.get("fbp_empty_frame", False))
    except Exception:
        return False


def do_update_opacity(rig):
    plane = rig.fbp_plane_target
    if not plane:
        return
    opacity = max(0.0, min(1.0, float(getattr(rig, 'fbp_opacity', 1.0))))
    try:
        plane.show_transparent = opacity < 1.0
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
        pass
    for i, mat in enumerate(list(plane.data.materials)):
        if is_fbp_empty_material(mat):
            set_fbp_material_transparency(mat, 0.0)
            continue
        if mat and mat.use_nodes:
            if getattr(rig, 'fbp_is_color_plane', False):
                if not update_fbp_procedural_material_opacity(mat, opacity):
                    new_mat = fbp_rebuild_procedural_material_for_emission(mat, rig, bool(getattr(rig, 'fbp_color_plane_emission', getattr(rig, 'fbp_use_emission', True))))
                    if new_mat:
                        plane.data.materials[i] = new_mat
                        if new_mat != mat:
                            fbp_remove_unused_materials_and_images([mat])
            else:
                new_mat = rebuild_fbp_image_material(mat, use_emission=getattr(rig, 'fbp_use_emission', True), opacity=opacity)
                if new_mat:
                    plane.data.materials[i] = new_mat
                    if new_mat != mat:
                        fbp_remove_unused_materials_and_images([mat])
        else:
            set_fbp_material_transparency(mat, opacity)


# SECTION 04 - Safe / empty frame materials #

# SECTION 05 - Image / color / gradient shader construction #

def configure_fbp_material_surface(mat, opacity=1.0, has_alpha=True):
    if not mat:
        return
    alpha = max(0.0, min(1.0, float(opacity)))
    try:
        mat.diffuse_color = (mat.diffuse_color[0], mat.diffuse_color[1], mat.diffuse_color[2], alpha)
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
        pass
    # Keep alpha support for image planes, but avoid extra opacity nodes when opacity is 100%.
    render_method = 'BLENDED' if has_alpha or alpha < 0.999 else 'OPAQUE'
    for attr, value in (
        ('surface_render_method', render_method),
        ('blend_method', 'BLEND' if render_method == 'BLENDED' else 'OPAQUE'),
        ('show_transparent_back', True),
        ('use_screen_refraction', False),
    ):
        if hasattr(mat, attr):
            try:
                setattr(mat, attr, value)
            except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
                pass


def create_fbp_material(mat_name, image_path, interp='Closest', opacity=1.0, use_emission=True):
    """Create the lightest node tree needed for this image plane.

    - Shadeless uses Image Texture -> Emission -> Output.
    - Lit uses Image Texture -> Principled BSDF -> Output.
    - Opacity Multiply is created only when opacity is below 100%.
    """
    mat = bpy.data.materials.get(mat_name)
    if not mat:
        mat = bpy.data.materials.new(name=mat_name)

    opacity = max(0.0, min(1.0, float(opacity)))
    mat.use_nodes = True
    configure_fbp_material_surface(mat, opacity, has_alpha=True)
    mat["fbp_image_path"] = image_path or ""
    mat["fbp_interpolation"] = interp
    mat["fbp_use_emission"] = bool(use_emission)
    mat["fbp_opacity"] = opacity

    nodes = mat.node_tree.nodes
    links = mat.node_tree.links
    nodes.clear()

    out = nodes.new(type='ShaderNodeOutputMaterial')
    out.location = (520, 0)

    tex = nodes.new(type='ShaderNodeTexImage')
    tex.location = (-420, 70)
    tex.interpolation = interp
    try:
        img = bpy.data.images.load(image_path, check_existing=True)
        tex.image = img
        try:
            if os.path.splitext(str(image_path))[1].lower() in FBP_SUPPORTED_VIDEO_EXT:
                img.source = 'MOVIE'
                tex.image_user.use_auto_refresh = True
                tex.image_user.frame_start = 1
                tex.image_user.frame_duration = max(1, int(getattr(img, 'frame_duration', 250) or 250))
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
            pass
    except Exception as e:
        print(f"[FBP] Image/video load error: {e}")

    if use_emission:
        shader = nodes.new(type='ShaderNodeEmission')
        shader.location = (120, 80)
        color_sock = safe_get_socket(shader, ['color']) or shader.inputs[0]
        links.new(tex.outputs['Color'], color_sock)
        try:
            shader.inputs['Strength'].default_value = 1.0
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
            pass
    else:
        shader = nodes.new(type='ShaderNodeBsdfPrincipled')
        shader.location = (120, 80)
        base_color = safe_get_socket(shader, ['base', 'color']) or shader.inputs[0]
        links.new(tex.outputs['Color'], base_color)
        # Make lit image planes inexpensive by default.
        for socket_names, value in ((['specular'], 0.0), (['specular', 'ior', 'level'], 0.0), (['roughness'], 1.0)):
            sock = safe_get_socket(shader, socket_names)
            if sock:
                try:
                    sock.default_value = value
                except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
                    pass

    if opacity < 0.999:
        math_node = nodes.new(type='ShaderNodeMath')
        math_node.operation = 'MULTIPLY'
        math_node.name = "FBP_Opacity"
        math_node.location = (-120, -170)
        math_node.inputs[1].default_value = opacity
        links.new(tex.outputs['Alpha'], math_node.inputs[0])
        alpha_source = math_node.outputs['Value']
    else:
        alpha_source = tex.outputs['Alpha']

    if use_emission:
        transparent = nodes.new(type='ShaderNodeBsdfTransparent')
        transparent.location = (110, -160)
        mix = nodes.new(type='ShaderNodeMixShader')
        mix.location = (330, 0)
        # factor 0 = shader1, 1 = shader2. Use alpha for visible emission over transparent.
        links.new(alpha_source, mix.inputs[0])
        links.new(transparent.outputs[0], mix.inputs[1])
        links.new(shader.outputs[0], mix.inputs[2])
        links.new(mix.outputs[0], out.inputs[0])
    else:
        alpha_sock = safe_get_socket(shader, ['alpha'])
        if alpha_sock:
            links.new(alpha_source, alpha_sock)
        links.new(shader.outputs[0], out.inputs[0])

    return mat


def create_fbp_color_material(name, color=(1.0, 1.0, 1.0, 1.0), use_emission=True, holdout=False):
    mat = bpy.data.materials.get(name) or bpy.data.materials.new(name=name)
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
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
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
        transparent.location = (0, -140)
        mix = nodes.new(type='ShaderNodeMixShader')
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
    mat.use_nodes = True
    configure_fbp_material_surface(mat, 1.0, has_alpha=True)
    try:
        mat.diffuse_color = color_b
    except (TypeError, ValueError) as exc:
        fbp_warn("Could not assign gradient material viewport color", exc)
    nodes = mat.node_tree.nodes
    links = mat.node_tree.links
    nodes.clear()

    out = nodes.new(type='ShaderNodeOutputMaterial'); out.location = (980, 0)
    texcoord = nodes.new(type='ShaderNodeTexCoord'); texcoord.location = (-980, 0)

    # Pivot-aware vector chain.
    # UV -> subtract editable center -> rotate/scale around that center.
    center = nodes.new(type='ShaderNodeVectorMath'); center.location = (-760, 0)
    center.name = 'FBP_GradientCenter'; center.label = 'Frame by Plane Gradient Center'
    center.operation = 'SUBTRACT'
    center['fbp_gradient_center'] = True
    center.inputs[1].default_value[0] = 0.5
    center.inputs[1].default_value[1] = 0.5
    center.inputs[1].default_value[2] = 0.0

    mapping = nodes.new(type='ShaderNodeMapping'); mapping.location = (-540, 0)
    mapping.name = 'FBP_GradientMapping'; mapping.label = 'Frame by Plane Gradient Mapping'
    mapping['fbp_gradient_mapping'] = True

    links.new(texcoord.outputs['UV'], center.inputs[0])
    links.new(center.outputs['Vector'], mapping.inputs['Vector'])

    if mode == 'CENTER':
        gradient_vector_output = mapping.outputs['Vector']
        grad_location = (-300, 0)
    else:
        # Linear gradients need the vector moved back to UV space after pivoted transforms,
        # otherwise half the ramp is clamped because coordinates become negative.
        recenter = nodes.new(type='ShaderNodeVectorMath'); recenter.location = (-320, 0)
        recenter.name = 'FBP_GradientRecenter'; recenter.label = 'Frame by Plane Gradient Recenter'
        recenter.operation = 'ADD'
        recenter['fbp_gradient_recenter'] = True
        recenter.inputs[1].default_value[0] = 0.5
        recenter.inputs[1].default_value[1] = 0.5
        recenter.inputs[1].default_value[2] = 0.0
        links.new(mapping.outputs['Vector'], recenter.inputs[0])
        gradient_vector_output = recenter.outputs['Vector']
        grad_location = (-100, 0)

    grad = nodes.new(type='ShaderNodeTexGradient'); grad.location = grad_location
    grad.name = 'FBP_GradientTexture'; grad.label = 'Frame by Plane Gradient Texture'
    grad.gradient_type = 'SPHERICAL' if mode == 'CENTER' else 'LINEAR'
    links.new(gradient_vector_output, grad.inputs['Vector'])

    ramp = nodes.new(type='ShaderNodeValToRGB'); ramp.location = (120, 0)
    ramp.name = 'FBP_ColorRamp'; ramp.label = 'Frame by Plane Color Ramp'
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

    transparent = nodes.new(type='ShaderNodeBsdfTransparent'); transparent.location = (440, -140)
    shader = nodes.new(type='ShaderNodeEmission' if use_emission else 'ShaderNodeBsdfPrincipled'); shader.location = (440, 110)
    color_sock = safe_get_socket(shader, ['color']) or shader.inputs[0]
    links.new(ramp.outputs['Color'], color_sock)
    if use_emission:
        strength = safe_get_socket(shader, ['strength'])
        if strength:
            strength.default_value = 1.0
    else:
        alpha_sock = safe_get_socket(shader, ['alpha'])
        if alpha_sock:
            links.new(ramp.outputs['Alpha'], alpha_sock)

    mix = nodes.new(type='ShaderNodeMixShader'); mix.location = (760, 0)
    links.new(ramp.outputs['Alpha'], mix.inputs[0])
    links.new(transparent.outputs[0], mix.inputs[1])
    links.new(shader.outputs[0], mix.inputs[2])
    links.new(mix.outputs[0], out.inputs[0])

    mat['fbp_gradient_material'] = True
    mat['fbp_gradient_mode'] = mode
    mat['fbp_gradient_kind'] = kind
    mat['fbp_gradient_reverse'] = bool(reverse)
    mat['fbp_use_emission'] = bool(use_emission)
    mat['fbp_solid_view_note'] = 'Procedural ColorRamp gradients are evaluated in Material Preview/Rendered view. Solid view can only show a flat viewport color unless Blender is set to a texture/attribute display mode.'
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
            except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
                pass
            try:
                # Import locally to keep materials.py below layers.py in the module graph.
                # The helper guards the RNA update callbacks while refreshing cached colors.
                try:
                    from .layers import fbp_cache_procedural_preview_on_item
                except ImportError:
                    from layers import fbp_cache_procedural_preview_on_item
                fbp_cache_procedural_preview_on_item(item, mat, procedural_kind)
            except (ImportError, AttributeError, ReferenceError, RuntimeError, TypeError) as exc:
                fbp_warn('Could not cache procedural frame preview', exc)
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
        pass
    if mode == 'GRADIENT':
        try:
            apply_fbp_gradient_mapping_to_material(rig, mat)
        except Exception as exc:
            fbp_warn("Could not apply gradient transform after rebuilding material", exc)
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
            except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
                pass
        return True
    except Exception:
        return False


def _copy_image_user_animation(src_mat, src_node, dst_mat, dst_node):
    """Copy ImageUser.frame_offset drivers/keyframes for alpha-aware image holdout."""
    if not src_mat or not src_node or not dst_mat or not dst_node:
        return False
    copied = False
    try:
        src_path = src_node.path_from_id('image_user.frame_offset')
        dst_path = dst_node.path_from_id('image_user.frame_offset')
    except Exception:
        return False
    try:
        src_action = getattr(getattr(src_mat.node_tree, 'animation_data', None), 'action', None)
        if src_action:
            for src_fc in src_action.fcurves:
                if src_fc.data_path != src_path:
                    continue
                try:
                    dst_fc = dst_mat.node_tree.animation_data_create().action.fcurves.new(data_path=dst_path, index=src_fc.array_index)
                except Exception:
                    try:
                        action = bpy.data.actions.new(dst_mat.name + '_ImageUser_Action')
                        dst_mat.node_tree.animation_data_create().action = action
                        dst_fc = action.fcurves.new(data_path=dst_path, index=src_fc.array_index)
                    except Exception:
                        dst_fc = None
                if not dst_fc:
                    continue
                for kp in src_fc.keyframe_points:
                    new_kp = dst_fc.keyframe_points.insert(kp.co.x, kp.co.y, options={'FAST'})
                    new_kp.interpolation = kp.interpolation
                try:
                    dst_fc.update()
                except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
                    pass
                copied = True
    except Exception as exc:
        fbp_warn('Could not copy native ImageUser keyframes to holdout', exc)

    try:
        src_ad = getattr(src_mat.node_tree, 'animation_data', None)
        if src_ad and src_ad.drivers:
            for src_fc in src_ad.drivers:
                if src_fc.data_path != src_path:
                    continue
                try:
                    dst_fc = dst_node.image_user.driver_add('frame_offset')
                    dst_drv = dst_fc.driver
                    dst_drv.type = src_fc.driver.type
                    dst_drv.expression = src_fc.driver.expression
                    copied = True
                except Exception as exc:
                    fbp_warn('Could not copy native ImageUser driver to holdout', exc)
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
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
    # Always create a fresh holdout material. Reusing an old material with the
    # same name can keep stale ImageUser timing/drivers after the native source
    # sequence has been rebuilt.
    mat = bpy.data.materials.new(mat_name)
    mat.use_nodes = True
    set_fbp_material_transparency(mat, 1.0)
    nodes = mat.node_tree.nodes
    links = mat.node_tree.links
    nodes.clear()
    out = nodes.new(type='ShaderNodeOutputMaterial')
    out.location = (500, 0)
    tex = nodes.new(type='ShaderNodeTexImage')
    tex.name = 'FBP_AlphaHoldout_Texture'
    tex.location = (-450, 120)
    tex.image = img
    tex.interpolation = interpolation
    try:
        tex.extension = getattr(src_node, 'extension', tex.extension)
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
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
    mat["fbp_alpha_holdout"] = True
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
    except ImportError:
        try:
            from native_backend import rebuild_native_sequence_from_rig
        except ImportError as exc:
            fbp_warn("Could not import native sequence restore helper", exc)
            return False

    restored = rebuild_native_sequence_from_rig(rig)
    if restored:
        try:
            ensure_fbp_plane_material_integrity(rig)
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
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

        # Old bug guard: if the backup is made only of FBP holdout mats, rebuild the real originals.
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

def fbp_find_node_by_type(nodes, node_type):
    for node in nodes:
        if node.type == node_type:
            return node
    return None


def fbp_relink_node_input(links, socket, output_socket):
    try:
        while socket.links:
            links.remove(socket.links[0])
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
        pass
    try:
        links.new(output_socket, socket)
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
        pass


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
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
        pass
    mat['fbp_opacity'] = opacity

    if bool(mat.get('fbp_holdout_material', False)):
        return True

    if bool(mat.get('fbp_gradient_material', False)):
        ramp = find_fbp_gradient_ramp_node(mat)
        shader = fbp_find_node_by_type(nodes, 'EMISSION') or fbp_find_node_by_type(nodes, 'BSDF_PRINCIPLED')
        mix = fbp_find_node_by_type(nodes, 'MIX_SHADER')
        if not ramp or not shader or not mix:
            return False
        opacity_node = nodes.get('FBP_Opacity')
        if not opacity_node or opacity_node.type != 'MATH':
            opacity_node = nodes.new(type='ShaderNodeMath')
            opacity_node.name = 'FBP_Opacity'
            opacity_node.location = (570, -60)
            opacity_node.operation = 'MULTIPLY'
        opacity_node.inputs[1].default_value = opacity
        fbp_relink_node_input(links, opacity_node.inputs[0], ramp.outputs['Alpha'])
        fbp_relink_node_input(links, mix.inputs[0], opacity_node.outputs['Value'])
        alpha_sock = safe_get_socket(shader, ['alpha'])
        if alpha_sock:
            fbp_relink_node_input(links, alpha_sock, opacity_node.outputs['Value'])
        return True

    if bool(mat.get('fbp_color_material', False)):
        color = list(fbp_material_color_value(mat, (1.0, 1.0, 1.0, 1.0)))
        color[3] = opacity
        mat['fbp_color_value'] = tuple(color)
        shader = fbp_find_node_by_type(nodes, 'EMISSION') or fbp_find_node_by_type(nodes, 'BSDF_PRINCIPLED')
        mix = fbp_find_node_by_type(nodes, 'MIX_SHADER')
        transparent = fbp_find_node_by_type(nodes, 'BSDF_TRANSPARENT')
        out = fbp_find_node_by_type(nodes, 'OUTPUT_MATERIAL')
        if shader:
            color_sock = safe_get_socket(shader, ['color']) or shader.inputs[0]
            try:
                color_sock.default_value = tuple(color)
            except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
                pass
            alpha_sock = safe_get_socket(shader, ['alpha'])
            if alpha_sock:
                try:
                    alpha_sock.default_value = opacity
                except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
                    pass
        if fbp_find_node_by_type(nodes, 'EMISSION'):
            if mix and transparent and out:
                try:
                    mix.inputs[0].default_value = opacity
                except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
                    pass
            elif opacity < 0.999 and shader and out:
                transparent = nodes.new(type='ShaderNodeBsdfTransparent')
                transparent.location = (0, -140)
                mix = nodes.new(type='ShaderNodeMixShader')
                mix.location = (180, 0)
                mix.inputs[0].default_value = opacity
                try:
                    while out.inputs[0].links:
                        links.remove(out.inputs[0].links[0])
                except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
                    pass
                links.new(transparent.outputs[0], mix.inputs[1])
                links.new(shader.outputs[0], mix.inputs[2])
                links.new(mix.outputs[0], out.inputs[0])
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
    if center:
        # Positive offset moves the visual center in the same direction on the plane.
        center.inputs[1].default_value[0] = 0.5 + offset_x
        center.inputs[1].default_value[1] = 0.5 + offset_y
        center.inputs[1].default_value[2] = 0.0
        mapping.inputs['Location'].default_value[0] = 0.0
        mapping.inputs['Location'].default_value[1] = 0.0
        mapping.inputs['Location'].default_value[2] = 0.0
    else:
        # Fallback for gradients created by older builds.
        mapping.inputs['Location'].default_value[0] = (-0.5 - offset_x) if mode == 'CENTER' else -offset_x
        mapping.inputs['Location'].default_value[1] = (-0.5 - offset_y) if mode == 'CENTER' else -offset_y
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
    fbp_apply_gradient_kind_to_ramp_node(find_fbp_gradient_ramp_node(mat), getattr(scene, 'fbp_gradient_kind', 'COLOR'))
    return mat


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
        for el, (pos, color) in zip(ramp.elements, elements):
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
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
        pass
    try:
        if getattr(mat, 'diffuse_color', None):
            return tuple(float(v) for v in mat.diffuse_color)
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
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
    tree, otherwise editing one frame updates all frames. This helper avoids the
    old linked-copy behavior by recreating gradient/color materials from the
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
            except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
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
            except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
                pass
            return mat

        color = fbp_material_color_value(source_mat, tuple(getattr(rig, 'fbp_color_plane_color', (1.0, 1.0, 1.0, 1.0))) if rig else (1.0, 1.0, 1.0, 1.0))
        mat = create_fbp_color_material(base_name, color, use_emission, False)
        try:
            mat['fbp_procedural_kind'] = 'SOLID'
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
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
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
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
            except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
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
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
            pass
        return mat, "Gradient Frame", False
    color = tuple(getattr(rig, 'fbp_color_plane_color', (1.0, 1.0, 1.0, 1.0)))
    mat = create_fbp_color_material(f"FBP_Color_{rig.name}_{safe_suffix}", color, use_emission, False)
    try:
        mat['fbp_procedural_kind'] = 'SOLID'
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
        pass
    return mat, "Color Frame", False


def register():
    # Materials module has no Blender classes to register.
    return None


def unregister():
    return None
