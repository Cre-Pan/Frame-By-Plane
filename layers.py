"""Layer, collection, preview and project-file helpers.

Extracted from core.py so UI and scene synchronization can depend on a focused
layer API instead of the monolithic core module.
"""

import colorsys
import os

import bpy
import bpy.utils.previews
import mathutils

try:
    from .constants import (
        STRIP_COLORS_DICT, preview_collections, fbp_icon, fbp_strip_icon,
        fbp_collection_color_icon,
    )
    from .path_utils import (
        natural_sort_key, is_supported_video_file, is_supported_media_file,
        is_technical_map_file,
    )
    from .materials import (
        iter_material_image_nodes, find_fbp_gradient_ramp_node,
        fbp_apply_holdout_materials_to_rig, restore_original_materials_from_holdout,
        rig_holdout_is_active,
    )
    from .runtime import (
        fbp_runtime_set, fbp_warn, fbp_set_rna_property_silent,
    )
except ImportError:
    from constants import (
        STRIP_COLORS_DICT, preview_collections, fbp_icon, fbp_strip_icon,
        fbp_collection_color_icon,
    )
    from path_utils import (
        natural_sort_key, is_supported_video_file, is_supported_media_file,
        is_technical_map_file,
    )
    from materials import (
        iter_material_image_nodes, find_fbp_gradient_ramp_node,
        fbp_apply_holdout_materials_to_rig, restore_original_materials_from_holdout,
        rig_holdout_is_active,
    )
    from runtime import fbp_runtime_set, fbp_warn, fbp_set_rna_property_silent


_FBP_SYNCING_PROCEDURAL_PREVIEW_ITEMS = set()
_COLLECTION_COLOR_TAGS = {f"COLOR_{index:02d}" for index in range(1, 9)}



def sync_layer_collection(context):
    """Lazy scene-sync bridge without a module-import cycle."""
    try:
        from .scene_sync import sync_layer_collection as _sync
    except ImportError:
        from scene_sync import sync_layer_collection as _sync
    return _sync(context)


def is_fbp_image_rig(obj):
    return bool(obj and getattr(obj, 'is_fbp_control', False))


def is_fbp_layer_object(obj):
    return is_fbp_image_rig(obj)


def safe_collection_color_tag(collection, fallback='COLOR_09'):
    try:
        tag = getattr(collection, 'color_tag', 'NONE')
        return tag if tag in _COLLECTION_COLOR_TAGS else fallback
    except Exception:
        return fallback


def set_collection_color_tag(collection, color_tag):
    """Assign a valid Blender Collection color tag.

    Collection tags support NONE and COLOR_01..COLOR_08. Frame by Plane's
    COLOR_09 is the neutral layer grey, so it maps to NONE for collections.
    """
    if not collection:
        return
    tag = str(color_tag or 'NONE')
    if tag == 'COLOR_09':
        tag = 'NONE'
    if tag != 'NONE' and tag not in _COLLECTION_COLOR_TAGS:
        return
    try:
        collection.color_tag = tag
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
        pass


def make_color_variant(color_tag, index=0):
    """Return a clearly readable depth variant while preserving the tag hue."""
    base = STRIP_COLORS_DICT.get(color_tag, STRIP_COLORS_DICT['COLOR_09'])
    r, g, b, a = base
    h, s, v = colorsys.rgb_to_hsv(r, g, b)
    depth = max(0, int(index or 0))

    # Make the difference visible on wire rigs: the nearest layer starts
    # brighter, then each deeper sibling becomes progressively darker.
    value_factor = max(0.42, 1.28 - (0.13 * min(depth, 7)))
    saturation_factor = min(1.12, 0.96 + (0.02 * min(depth, 7)))
    rr, gg, bb = colorsys.hsv_to_rgb(
        h,
        max(0.0, min(1.0, s * saturation_factor)),
        max(0.0, min(1.0, v * value_factor)),
    )
    return (rr, gg, bb, 1.0)


def get_or_create_child_collection(parent_collection, name, color_tag=None):
    parent_collection = parent_collection or bpy.context.scene.collection
    for child in parent_collection.children:
        if child.name == name:
            coll = child
            break
    else:
        coll = bpy.data.collections.new(name)
        parent_collection.children.link(coll)
    try:
        coll.is_fbp_collection = True
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
        pass
    if color_tag:
        set_collection_color_tag(coll, color_tag)
    return coll


def move_object_to_collection(obj, collection):
    if not obj or not collection:
        return
    try:
        if obj.name not in collection.objects:
            collection.objects.link(obj)
    except Exception:
        try:
            collection.objects.link(obj)
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
            pass
    for coll in list(obj.users_collection):
        if coll != collection:
            try:
                coll.objects.unlink(obj)
            except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
                pass


def get_primary_fbp_collection(obj):
    if not obj:
        return None
    try:
        if getattr(obj, 'fbp_collection_name', ''):
            coll = bpy.data.collections.get(obj.fbp_collection_name)
            if coll:
                return coll
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
        pass
    try:
        for coll in obj.users_collection:
            if getattr(coll, 'is_fbp_collection', False):
                return coll
        return obj.users_collection[0] if obj.users_collection else None
    except Exception:
        return None


def is_layer_item_visible_in_collections(context, item):
    try:
        rig = item.obj
    except ReferenceError:
        return False
    if not rig or not is_fbp_layer_object(rig):
        return False
    try:
        # visible_get respects Collection hide/exclude state in the View Layer.
        return bool(rig.visible_get(view_layer=context.view_layer))
    except TypeError:
        try:
            return bool(rig.visible_get())
        except Exception:
            return object_in_scene(rig, context.scene)
    except Exception:
        return object_in_scene(rig, context.scene)


def visible_layer_indices(context, same_collection_as=None):
    indices = []
    target_collection = get_primary_fbp_collection(same_collection_as) if same_collection_as else None
    for i, item in enumerate(context.scene.fbp_layers):
        try:
            rig = item.obj
            if not rig or not is_fbp_layer_object(rig):
                continue
            if target_collection and get_primary_fbp_collection(rig) != target_collection:
                continue
            if is_layer_item_visible_in_collections(context, item):
                indices.append(i)
        except ReferenceError:
            pass
    return indices


def apply_collection_color_to_layer(obj, color_tag=None, variant_index=None, push_collection=False):
    if not obj or not is_fbp_layer_object(obj):
        return
    coll = get_primary_fbp_collection(obj)
    if color_tag is None and coll:
        color_tag = safe_collection_color_tag(coll, getattr(obj, 'fbp_color_tag', 'COLOR_09'))
    if color_tag not in STRIP_COLORS_DICT:
        color_tag = getattr(obj, 'fbp_color_tag', 'COLOR_09')
        if color_tag not in STRIP_COLORS_DICT:
            color_tag = 'COLOR_09'
    if getattr(obj, 'fbp_color_tag', None) != color_tag:
        try:
            fbp_set_rna_property_silent(obj, 'fbp_color_tag', color_tag)
        except Exception:
            obj.fbp_color_tag = color_tag
    if variant_index is None:
        variant_index = getattr(obj, 'fbp_color_variant_index', 0)
    try:
        fbp_set_rna_property_silent(obj, 'fbp_color_variant_index', int(variant_index))
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
        pass
    obj.color = make_color_variant(color_tag, variant_index)
    plane = getattr(obj, 'fbp_plane_target', None)
    if plane:
        try:
            plane.color = obj.color
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
            pass
    if push_collection and coll:
        set_collection_color_tag(coll, color_tag)


def apply_collection_color_to_rig(rig, color_tag=None, variant_index=None, push_collection=False):
    apply_collection_color_to_layer(rig, color_tag, variant_index, push_collection)


def sync_collection_colors_to_rigs(context):
    if not context:
        return
    groups = {}
    for item in context.scene.fbp_layers:
        try:
            rig = item.obj
            if not rig or not is_fbp_layer_object(rig):
                continue
            if not getattr(rig, 'fbp_follow_collection_color', True):
                continue
            coll = get_primary_fbp_collection(rig)
            if not coll:
                continue
            tag = safe_collection_color_tag(coll, None)
            if tag not in STRIP_COLORS_DICT:
                continue
            groups.setdefault(coll.name, (coll, tag, []))[2].append(rig)
        except ReferenceError:
            pass

    for _name, (_coll, tag, rigs) in groups.items():
        rigs.sort(key=lambda rig: (
            int(getattr(rig, 'fbp_depth_order', 0)),
            getattr(rig, 'name', ''),
        ))
        use_variants = bool(getattr(context.scene, 'fbp_auto_collection_color_variants', True))
        for idx, rig in enumerate(rigs):
            try:
                variant_index = idx if use_variants else 0
                rig.fbp_color_variant_index = variant_index
                apply_collection_color_to_layer(rig, tag, variant_index, push_collection=False)
            except ReferenceError:
                pass


# ── COLLECTION TREE / PROJECT HELPERS ───────────────────────────────────────

def find_layer_collection(layer_collection, collection):
    """Return the ViewLayer LayerCollection wrapper for a bpy.data Collection."""
    if not layer_collection or not collection:
        return None
    try:
        if layer_collection.collection == collection:
            return layer_collection
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
        pass
    for child in getattr(layer_collection, 'children', []):
        found = find_layer_collection(child, collection)
        if found:
            return found
    return None


def collection_is_hidden_in_view_layer(context, collection):
    if not collection:
        return False
    try:
        if getattr(collection, 'hide_viewport', False):
            return True
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
        pass
    try:
        layer_coll = find_layer_collection(context.view_layer.layer_collection, collection)
        if layer_coll and (getattr(layer_coll, 'hide_viewport', False) or getattr(layer_coll, 'exclude', False)):
            return True
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
        pass
    return False


def fbp_rebuild_layer_view_cache(context):
    """Pre-compute which collections contain Frame by Plane rigs.

    Layer UI draw functions read these cached booleans instead of recursively
    scanning collection trees every redraw.
    """
    if not context or not getattr(context, "scene", None):
        return
    sc = context.scene
    parent_map = {}
    try:
        for coll in bpy.data.collections:
            coll["fbp_has_fbp_content"] = False
            coll["fbp_has_fbp_content_recursive"] = False
            for child in coll.children:
                parent_map.setdefault(child.name, []).append(coll)
    except Exception as exc:
        fbp_warn("Could not reset layer view cache", exc)
        return

    def mark_collection(coll):
        stack = [coll]
        seen = set()
        while stack:
            current = stack.pop()
            if not current or current.name in seen:
                continue
            seen.add(current.name)
            try:
                current["fbp_has_fbp_content_recursive"] = True
            except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
                pass
            for parent in parent_map.get(current.name, []):
                stack.append(parent)

    for item in getattr(sc, "fbp_layers", []):
        try:
            rig = item.obj
            if not rig or not is_fbp_layer_object(rig) or not object_in_scene(rig, sc):
                continue
            for coll in getattr(rig, "users_collection", []):
                coll["fbp_has_fbp_content"] = True
                mark_collection(coll)
        except ReferenceError:
            continue
        except Exception as exc:
            fbp_warn("Could not cache layer collection", exc)

    fbp_runtime_set("fbp_layer_cache_dirty", False, context)


def fbp_mark_layer_cache_dirty(context=None):
    fbp_runtime_set("fbp_layer_cache_dirty", True, context)


def collection_has_fbp_content(collection, recursive=True):
    if not collection:
        return False
    key = "fbp_has_fbp_content_recursive" if recursive else "fbp_has_fbp_content"
    try:
        if key in collection:
            return bool(collection.get(key, False))
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
        pass

    # Fallback for very early draw calls before the cache exists.
    try:
        for obj in collection.objects:
            if is_fbp_layer_object(obj):
                return True
        if recursive:
            for child in collection.children:
                if collection_has_fbp_content(child, True):
                    return True
    except Exception as exc:
        fbp_warn("Could not evaluate collection FBP content", exc)
    return False


def get_direct_fbp_rigs_in_collection(context, collection):
    rigs = []
    if not collection:
        return rigs
    order = []
    for item in context.scene.fbp_layers:
        try:
            if item.obj and is_fbp_layer_object(item.obj):
                order.append(item.obj)
        except ReferenceError:
            pass
    try:
        for rig in order:
            if any(coll == collection for coll in rig.users_collection):
                rigs.append(rig)
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
        pass
    return sort_rigs_by_depth_for_layer_view(context, rigs)


def iter_fbp_rigs_in_collection(collection, recursive=True):
    if not collection:
        return
    seen = set()
    try:
        for obj in collection.objects:
            if is_fbp_layer_object(obj) and obj.name not in seen:
                seen.add(obj.name)
                yield obj
        if recursive:
            for child in collection.children:
                for rig in iter_fbp_rigs_in_collection(child, True):
                    if rig.name not in seen:
                        seen.add(rig.name)
                        yield rig
    except Exception:
        return


def get_child_fbp_collections(collection):
    if not collection:
        return []
    try:
        return sort_collections_for_layer_view(bpy.context, [child for child in collection.children if collection_has_fbp_content(child, True)])
    except Exception:
        return []


def get_top_fbp_collections(context):
    scene_coll = context.scene.collection
    roots = []
    try:
        for coll in scene_coll.children:
            if collection_has_fbp_content(coll, True):
                roots.append(coll)
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
        pass
    return sort_collections_for_layer_view(context, roots)


def get_layer_item_for_rig(context, rig):
    if not rig:
        return None
    for item in context.scene.fbp_layers:
        try:
            if item.obj == rig:
                return item
        except ReferenceError:
            pass
    return None


def fbp_procedural_layer_type(rig):
    """Return the stable procedural layer type used by the Layers UI.

    Color/Gradient planes can have animated procedural frames. Holdout planes
    stay static masks. Selecting a frame updates the editable controls (`fbp_color_plane_mode`) to that
    material, but the layer row icon should not turn into an image/sequence icon
    just because the active frame changed. This custom property stores the
    original procedural family of the layer.
    """
    if not rig or not getattr(rig, 'fbp_is_color_plane', False):
        return ''
    try:
        stable = str(rig.get('fbp_procedural_layer_type', '') or '')
        if stable in {'SOLID', 'GRADIENT', 'HOLDOUT'}:
            return stable
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
        pass
    mode = str(getattr(rig, 'fbp_color_plane_mode', 'SOLID') or 'SOLID')
    if mode not in {'SOLID', 'GRADIENT', 'HOLDOUT'}:
        mode = 'SOLID'
    try:
        rig['fbp_procedural_layer_type'] = mode
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
        pass
    return mode


def fbp_color_plane_type_icon(rig):
    """Icon used for rigged color/gradient/holdout planes in layer rows."""
    if not rig or not getattr(rig, 'fbp_is_color_plane', False):
        return None

    mode = fbp_procedural_layer_type(rig)

    if mode == 'GRADIENT':
        return fbp_icon("COLOR")
    if mode == 'HOLDOUT':
        return fbp_icon("GHOST_DISABLED")

    # Use a material/color icon for solid color planes. Do not use IMAGE here:
    # it looks like an imported image sequence and confused the layer list.
    return fbp_icon("MATERIAL")


def fbp_procedural_kind_from_material(mat, fallback='SOLID'):
    """Return SOLID / GRADIENT / HOLDOUT for a procedural frame material."""
    if not mat:
        return fallback if fallback in {'SOLID', 'GRADIENT', 'HOLDOUT'} else 'SOLID'
    try:
        explicit = str(mat.get('fbp_procedural_kind', '') or '')
        if explicit in {'SOLID', 'GRADIENT', 'HOLDOUT'}:
            return explicit
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
        pass
    try:
        if bool(mat.get('fbp_gradient_material', False)):
            return 'GRADIENT'
        if bool(mat.get('fbp_holdout_material', False)):
            return 'HOLDOUT'
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
        pass
    return fallback if fallback in {'SOLID', 'GRADIENT', 'HOLDOUT'} else 'SOLID'


def fbp_procedural_kind_for_item(rig, index, fallback='SOLID'):
    """Return the stored per-row procedural type, falling back to its material."""
    try:
        if 0 <= int(index) < len(rig.fbp_images):
            item_kind = str(getattr(rig.fbp_images[int(index)], 'procedural_kind', 'AUTO') or 'AUTO')
            if item_kind in {'SOLID', 'GRADIENT', 'HOLDOUT'}:
                return item_kind
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
        pass
    try:
        plane = getattr(rig, 'fbp_plane_target', None)
        if plane and getattr(plane, 'data', None) and 0 <= int(index) < len(plane.data.materials):
            return fbp_procedural_kind_from_material(plane.data.materials[int(index)], fallback)
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
        pass
    return fallback if fallback in {'SOLID', 'GRADIENT', 'HOLDOUT'} else 'SOLID'


def fbp_set_procedural_metadata(mat, kind):
    """Store the procedural kind on a material when possible."""
    if not mat:
        return
    try:
        if kind in {'SOLID', 'GRADIENT', 'HOLDOUT'}:
            mat['fbp_procedural_kind'] = kind
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
        pass


def fbp_procedural_preview_from_material(mat, fallback_kind='SOLID'):
    """Return (kind, color_a, color_b) for UIList drawing without later node scans.

    This is intentionally called while changing sequence data, not from UIList
    draw_item(). The UI can then read cached colors from each FBP_ImageItem.
    """
    kind = fbp_procedural_kind_from_material(mat, fallback_kind)
    color_a = (1.0, 1.0, 1.0, 1.0)
    color_b = (1.0, 1.0, 1.0, 1.0)
    if not mat:
        return kind, color_a, color_b
    try:
        if kind == 'GRADIENT':
            ramp = find_fbp_gradient_ramp_node(mat)
            elems = list(getattr(getattr(ramp, 'color_ramp', None), 'elements', [])) if ramp else []
            if elems:
                color_a = tuple(elems[0].color)
                color_b = tuple(elems[-1].color)
                return kind, color_a, color_b
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
        pass
    try:
        color_a = tuple(getattr(mat, 'diffuse_color', color_a))
        color_b = color_a
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
        pass
    return kind, color_a, color_b


def fbp_cache_procedural_preview_on_item(item, mat, fallback_kind='SOLID'):
    if not item:
        return
    try:
        ptr = item.as_pointer()
    except Exception:
        ptr = None
    try:
        if ptr is not None:
            _FBP_SYNCING_PROCEDURAL_PREVIEW_ITEMS.add(ptr)
        kind, color_a, color_b = fbp_procedural_preview_from_material(mat, fallback_kind)
        if kind in {'SOLID', 'GRADIENT', 'HOLDOUT'}:
            item.procedural_kind = kind
        item.preview_color_a = color_a
        item.preview_color_b = color_b
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
        pass
    finally:
        try:
            if ptr is not None:
                _FBP_SYNCING_PROCEDURAL_PREVIEW_ITEMS.discard(ptr)
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
            pass


def fbp_mask_icon(is_on):
    """Use the requested UV clip icons for the holdout/mask state."""
    return fbp_icon("CLIPUV_DEHLT") if is_on else 'CLIPUV_HLT'


def fbp_select_rig_icon(is_locked, is_selected=False):
    """Checkbox icon for rig selection. Locked layers use Blender's used-layer icon."""
    if is_locked:
        return fbp_icon("LAYER_USED")
    return fbp_icon("CHECKBOX_HLT") if is_selected else 'CHECKBOX_DEHLT'


def fbp_select_plane_icon(rig, context):
    """Icon for the linked image/color plane viewport selectability toggle."""
    plane = getattr(rig, 'fbp_plane_target', None) if rig else None
    if not plane:
        return fbp_icon("RESTRICT_SELECT_ON")
    try:
        return fbp_icon("RESTRICT_SELECT_ON") if plane.hide_select else 'RESTRICT_SELECT_OFF'
    except ReferenceError:
        return fbp_icon("RESTRICT_SELECT_ON")


def fbp_collection_select_icon(collection, context):
    """Checkbox icon for collection rig selection."""
    if bool(getattr(collection, 'fbp_collection_locked', False)):
        return fbp_icon("LAYER_USED")
    rigs = [rig for rig in iter_fbp_rigs_in_collection(collection, True) if object_in_view_layer(rig, context)]
    if rigs and all(rig.select_get() for rig in rigs):
        return fbp_icon("CHECKBOX_HLT")
    return fbp_icon("CHECKBOX_DEHLT")


def fbp_collection_plane_icon(collection, context):
    """Icon for linked image/color plane selectability inside a collection."""
    planes = []
    for rig in iter_fbp_rigs_in_collection(collection, True):
        plane = getattr(rig, 'fbp_plane_target', None)
        if plane and object_in_view_layer(plane, context):
            planes.append(plane)
    if planes and all(getattr(p, 'hide_select', True) for p in planes):
        return fbp_icon("RESTRICT_SELECT_ON")
    return fbp_icon("RESTRICT_SELECT_OFF")


def fbp_collection_icon(collection):
    """Return the collection icon, preserving Blender collection color tags when available."""
    return fbp_collection_color_icon(getattr(collection, "color_tag", ""))


def fbp_layer_row_type_icon(rig, context):
    """Return a thumbnail when enabled, otherwise the rig Color Tag icon."""
    if bool(getattr(context.scene, 'fbp_show_previews', False)) and not bool(getattr(rig, 'fbp_is_color_plane', False)):
        preview = get_layer_thumbnail(rig)
        if preview:
            return None, preview.icon_id
    try:
        return fbp_strip_icon(getattr(rig, 'fbp_color_tag', 'COLOR_09')), None
    except Exception:
        return fbp_icon("STRIP_COLOR_09"), None


def fbp_add_tree_indent(row, depth):
    """Add one fixed BLANK1 icon for each nested collection level."""
    for _ in range(max(0, depth)):
        cell = row.row(align=True)
        fbp_set_ui_units_x(cell, 1.05)
        cell.label(text="", icon=fbp_icon("BLANK1"))


def fbp_set_ui_units_x(ui_layout, units):
    """Best-effort fixed UI width helper for compact icon blocks.

    Blender supports ui_units_x on recent versions. When unavailable, this
    quietly falls back to the normal dynamic layout instead of breaking UI draw.
    """
    try:
        ui_layout.ui_units_x = units
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
        pass


def indent_row(row, depth):
    """Backward-compatible compact indentation helper for older UI sections."""
    fbp_add_tree_indent(row, depth)


def fbp_collection_rows_are_disabled(collection, context):
    """Return whether collection text/icon should look inactive while controls stay usable."""
    if collection_is_hidden_in_view_layer(context, collection):
        return True
    if bool(getattr(collection, 'fbp_collection_locked', False)):
        return True
    rigs = [rig for rig in iter_fbp_rigs_in_collection(collection, True) if object_in_view_layer(rig, context)]
    if rigs and all(not getattr(rig, 'fbp_is_visible', True) for rig in rigs):
        return True
    return False


def draw_fbp_layer_row(layout, context, rig, depth=0):
    item = get_layer_item_for_rig(context, rig)
    if not item:
        return

    is_disabled = (not getattr(rig, 'fbp_is_visible', True)) or bool(item.rig_locked)

    row = layout.row(align=False)
    split = row.split(factor=0.68, align=False)

    # LEFT: Eye - depth BLANK1(s) - arrow placeholder - icon+name operator.
    # Icon and name are drawn by the same operator to avoid the extra gap created
    # by separate icon_row/name_row blocks.
    left = split.row(align=True)
    left.alignment = 'LEFT'

    vis_icon = fbp_icon("HIDE_OFF") if rig.fbp_is_visible else fbp_icon("HIDE_ON")
    left.prop(rig, "fbp_is_visible", text="", icon=vis_icon, icon_only=True, emboss=False)

    for _ in range(max(0, depth)):
        left.label(text="", icon=fbp_icon("BLANK1"))

    # Keep layer names aligned with collection names, which have a disclosure arrow.
    left.label(text="", icon=fbp_icon("BLANK1"))

    name_row = left.row(align=True)
    name_row.alignment = 'LEFT'
    name_row.active = not is_disabled
    type_icon, preview_icon = fbp_layer_row_type_icon(rig, context)
    if preview_icon:
        op_name = name_row.operator("fbp.select_layer_exclusive", text=rig.name, icon_value=preview_icon, emboss=False)
    else:
        op_name = name_row.operator("fbp.select_layer_exclusive", text=rig.name, icon=type_icon or fbp_icon("STRIP_COLOR_09"), emboss=False)
    op_name.rig_name = rig.name

    # RIGHT: fixed action strip.
    right = split.row(align=True)
    right.alignment = 'RIGHT'
    fbp_set_ui_units_x(right, 5.75)

    solo_icon = fbp_icon("OUTLINER_OB_LIGHT") if item.solo_view else fbp_icon("LIGHT")
    right.prop(item, "solo_view", text="", icon=solo_icon, icon_only=True, emboss=False)

    op_hold = right.operator("fbp.toggle_layer_holdout", text="", icon=fbp_mask_icon(item.holdout), emboss=False)
    op_hold.rig_name = rig.name

    op_plane = right.operator("fbp.select_linked_plane", text="", icon=fbp_select_plane_icon(rig, context), emboss=False)
    op_plane.rig_name = rig.name

    lock_icon = fbp_icon("LOCKED") if item.rig_locked else fbp_icon("UNLOCKED")
    right.prop(item, "rig_locked", text="", icon=lock_icon, icon_only=True, emboss=False)

    sel_row = right.row(align=True)
    sel_row.enabled = not item.rig_locked
    sel_row.prop(item, "selected", text="", icon=fbp_select_rig_icon(item.rig_locked, rig.select_get()), icon_only=True, emboss=False)

def draw_fbp_collection_row(layout, context, collection, depth=0):
    if not collection_has_fbp_content(collection, True):
        return

    hidden = collection_is_hidden_in_view_layer(context, collection)
    collapsed = bool(getattr(collection, 'fbp_collapsed', False))
    is_disabled = fbp_collection_rows_are_disabled(collection, context)

    row = layout.row(align=False)
    split = row.split(factor=0.68, align=False)

    # LEFT: Eye - depth BLANK1(s) - disclosure arrow - collection icon+name operator.
    left = split.row(align=True)
    left.alignment = 'LEFT'

    vis_icon = fbp_icon("HIDE_OFF") if collection.fbp_collection_visible else fbp_icon("HIDE_ON")
    left.prop(collection, "fbp_collection_visible", text="", icon=vis_icon, icon_only=True, emboss=False)

    for _ in range(max(0, depth)):
        left.label(text="", icon=fbp_icon("BLANK1"))

    fold_icon = fbp_icon("RIGHTARROW") if collapsed else fbp_icon("DOWNARROW_HLT")
    op = left.operator("fbp.toggle_collection_collapse", text="", icon=fold_icon, emboss=False)
    op.collection_name = collection.name

    name_row = left.row(align=True)
    name_row.alignment = 'LEFT'
    name_row.active = not is_disabled
    op_sel = name_row.operator("fbp.select_collection_layers", text=collection.name, icon=fbp_collection_icon(collection), emboss=False)
    op_sel.collection_name = collection.name

    # RIGHT: fixed action strip.
    right = split.row(align=True)
    right.alignment = 'RIGHT'
    fbp_set_ui_units_x(right, 5.75)

    solo_icon = fbp_icon("OUTLINER_OB_LIGHT") if collection.fbp_collection_solo else fbp_icon("LIGHT")
    right.prop(collection, "fbp_collection_solo", text="", icon=solo_icon, icon_only=True, emboss=False)

    op_hold = right.operator("fbp.toggle_collection_holdout", text="", icon=fbp_mask_icon(collection.fbp_collection_holdout), emboss=False)
    op_hold.collection_name = collection.name

    op_planes = right.operator("fbp.select_collection_planes", text="", icon=fbp_collection_plane_icon(collection, context), emboss=False)
    op_planes.collection_name = collection.name

    lock_icon = fbp_icon("LOCKED") if collection.fbp_collection_locked else fbp_icon("UNLOCKED")
    right.prop(collection, "fbp_collection_locked", text="", icon=lock_icon, icon_only=True, emboss=False)

    sel_row = right.row(align=True)
    sel_row.enabled = not collection.fbp_collection_locked
    sel_row.prop(collection, "fbp_collection_selected", text="", icon=fbp_collection_select_icon(collection, context), icon_only=True, emboss=False)

    if collapsed or hidden:
        return

    for child in get_child_fbp_collections(collection):
        draw_fbp_collection_row(layout, context, child, depth + 1)

    direct = list(reversed(get_direct_fbp_rigs_in_collection(context, collection)))
    for rig in direct:
        draw_fbp_layer_row(layout, context, rig, depth + 1)


def collect_project_image_paths():
    paths = []
    for _mat, _node, img in iter_material_image_nodes():
        p = getattr(img, 'filepath', '')
        if p:
            paths.append(p)
    return paths


def missing_project_images():
    missing = []
    for p in collect_project_image_paths():
        abs_p = bpy.path.abspath(p)
        if abs_p and not os.path.exists(abs_p):
            missing.append(p)
    return sorted(set(missing), key=natural_sort_key)


def build_project_file_index(root):
    index = {}
    root = bpy.path.abspath(root)
    if not root or not os.path.isdir(root):
        return index
    for dirpath, _dirnames, filenames in os.walk(root):
        for filename in filenames:
            if not is_supported_media_file(filename) or (not is_supported_video_file(filename) and is_technical_map_file(filename)):
                continue
            index.setdefault(filename.lower(), []).append(os.path.join(dirpath, filename))
    return index


def relink_missing_images_from_root(root, make_relative=True):
    file_index = build_project_file_index(root)
    relinked = 0
    ambiguous = []
    still_missing = []
    for _mat, _node, img in iter_material_image_nodes():
        old_path = getattr(img, 'filepath', '')
        if not old_path:
            continue
        abs_old = bpy.path.abspath(old_path)
        if os.path.exists(abs_old):
            if make_relative:
                try:
                    img.filepath = bpy.path.relpath(abs_old)
                except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
                    pass
            continue
        filename = os.path.basename(old_path).lower()
        matches = file_index.get(filename, [])
        if len(matches) == 1:
            new_path = matches[0]
            img.filepath = bpy.path.relpath(new_path) if make_relative else new_path
            relinked += 1
        elif len(matches) > 1:
            ambiguous.append(old_path)
        else:
            still_missing.append(old_path)
    return relinked, ambiguous, still_missing


def project_root_for_package(context):
    sc = context.scene
    root = bpy.path.abspath(getattr(sc, 'fbp_project_path', '') or '')
    if root and os.path.isdir(root):
        return root
    if bpy.data.is_saved:
        return os.path.dirname(bpy.data.filepath)
    return ''


def rig_has_missing_images(rig):
    plane = getattr(rig, 'fbp_plane_target', None)
    if not plane:
        return False
    for mat in plane.data.materials:
        if not mat or not getattr(mat, 'use_nodes', False) or not mat.node_tree:
            continue
        for node in mat.node_tree.nodes:
            if node.type == 'TEX_IMAGE' and getattr(node, 'image', None):
                p = getattr(node.image, 'filepath', '')
                if p and not os.path.exists(bpy.path.abspath(p)):
                    return True
    return False


def swap_layer_depth_only(context, rig_a, rig_b):
    if not rig_a or not rig_b:
        return
    # Swap depth only, without recalculating every layer.
    axis = 1 if (getattr(rig_a, 'fbp_is_vertical', False) or getattr(rig_b, 'fbp_is_vertical', False)) else 2
    loc_a = rig_a.location.copy()
    loc_b = rig_b.location.copy()
    loc_a[axis], loc_b[axis] = loc_b[axis], loc_a[axis]
    rig_a.location = loc_a
    rig_b.location = loc_b


def object_in_scene(obj, scene=None):
    if not obj:
        return False
    try:
        if bpy.data.objects.get(obj.name) != obj:
            return False
        scene = scene or (bpy.context.scene if bpy.context else None)
        if not scene:
            return True
        return any(scene_obj == obj for scene_obj in scene.objects)
    except ReferenceError:
        return False


def object_in_view_layer(obj, context=None):
    context = context or bpy.context
    if not obj or not context:
        return False
    try:
        if not object_in_scene(obj, context.scene):
            return False
        return any(view_obj == obj for view_obj in context.view_layer.objects)
    except ReferenceError:
        return False


def ensure_object_in_active_collection(obj, context=None):
    context = context or bpy.context
    if not obj or not context:
        return False
    try:
        if object_in_view_layer(obj, context):
            return True
        coll = context.collection or context.scene.collection
        if not any(existing == obj for existing in coll.objects):
            coll.objects.link(obj)
        context.view_layer.update()
        return object_in_view_layer(obj, context)
    except Exception:
        return False


def get_selected_rigs(context):
    return get_selected_fbp_roots(context)


def fbp_resolve_rig_from_any_object(obj, context=None):
    """Return the FBP rig represented by either a rig or its linked image plane."""
    if not obj:
        return None
    try:
        if getattr(obj, "is_fbp_control", False):
            return obj
    except ReferenceError:
        return None
    try:
        if getattr(obj, "is_fbp_plane", False):
            parent = getattr(obj, "parent", None)
            if parent and getattr(parent, "is_fbp_control", False):
                return parent
            rig_name = obj.get("fbp_parent_rig_name", "")
            rig = bpy.data.objects.get(rig_name) if rig_name else None
            if rig and getattr(rig, "is_fbp_control", False):
                return rig
            # Last fallback for old files: find the rig whose pointer still targets this plane.
            scene = getattr(context, "scene", None) if context else None
            candidates = list(scene.objects) if scene else list(bpy.data.objects)
            for maybe_rig in candidates:
                try:
                    if getattr(maybe_rig, "is_fbp_control", False) and getattr(maybe_rig, "fbp_plane_target", None) == obj:
                        return maybe_rig
                except ReferenceError:
                    continue
    except ReferenceError:
        return None
    return None


def get_selected_fbp_roots(context):
    """Return selected FBP rigs with the active rig first for reliable multi-edit UI."""
    roots = []
    selected = list(getattr(context, "selected_objects", []) or [])
    active = getattr(context, "object", None)
    ordered = ([active] if active else []) + [obj for obj in selected if obj != active]
    for ob in ordered:
        rig = fbp_resolve_rig_from_any_object(ob, context)
        if rig and rig not in roots:
            roots.append(rig)
    return roots


def clear_previews():
    for pcoll in preview_collections.values():
        bpy.utils.previews.remove(pcoll)
    preview_collections.clear()


def update_global_visibility(context=None):
    if not context:
        context = bpy.context
    for item in context.scene.fbp_layers:
        try:
            obj = item.obj
            if not obj:
                continue
            vis = obj.fbp_is_visible and not item.mute
            plane = getattr(obj, 'fbp_plane_target', None)
            if not plane:
                continue
            plane.hide_viewport = not vis
            plane.hide_render = not vis
        except ReferenceError:
            pass


def update_mute_cb(self, context):
    update_global_visibility(context)


def get_preview_collection():
    pcoll = preview_collections.get("fbp_previews")
    if not pcoll:
        pcoll = bpy.utils.previews.new()
        preview_collections["fbp_previews"] = pcoll
    return pcoll


def load_preview(image_path):
    pcoll = get_preview_collection()
    abs_path = bpy.path.abspath(image_path)
    if abs_path in pcoll:
        return pcoll[abs_path]
    if os.path.exists(abs_path):
        try:
            return pcoll.load(abs_path, abs_path, 'IMAGE')
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
            pass
    return None


def get_layer_thumbnail(obj):
    if not obj or not hasattr(obj, "fbp_preview_path") or not obj.fbp_preview_path:
        return None
    return load_preview(obj.fbp_preview_path)


def set_viewport_object_color(context):
    """Prepare viewport display colors without changing texture display.

    Frame by Plane should keep object color mode on TEXTURE, because textured
    planes must remain visible while editing. Only wireframe colors are switched
    to Object when Blender exposes that setting.
    """
    screen = getattr(context, 'screen', None)
    if not screen:
        return
    for area in screen.areas:
        if area.type == 'VIEW_3D':
            for space in area.spaces:
                if space.type == 'VIEW_3D':
                    shading = getattr(space, 'shading', None)
                    if not shading:
                        continue
                    # Keep textured planes visible.
                    if hasattr(shading, 'color_type'):
                        try:
                            shading.color_type = 'TEXTURE'
                        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
                            pass
                    # Use object colors for wire display if available in this Blender version.
                    for attr in ('wireframe_color_type', 'wire_color_type'):
                        if hasattr(shading, attr):
                            try:
                                setattr(shading, attr, 'OBJECT')
                            except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
                                pass


def fbp_make_depth_context_cache(context):
    """Precompute camera vectors once for UI sorting/redraw paths.

    UIList.filter_items can be called very often while the mouse is moving.
    Keeping the active camera matrix calculation outside the per-layer sort key
    prevents repeated matrix work during redraw.
    """
    try:
        scene = getattr(context, "scene", None) if context else None
        cam = scene.camera if scene else None
        if cam:
            return {
                "has_camera": True,
                "camera_location": cam.matrix_world.translation.copy(),
                "camera_forward": cam.matrix_world.to_3x3() @ mathutils.Vector((0.0, 0.0, -1.0)),
            }
    except ReferenceError:
        pass
    except (AttributeError, TypeError, RuntimeError) as exc:
        fbp_warn("Could not build layer depth camera cache", exc)
    return {"has_camera": False}


def fbp_layer_depth_value_from_cache(rig, depth_cache=None):
    """Return a stable depth value using a precomputed context cache when available."""
    if not rig:
        return 0.0
    try:
        if depth_cache and depth_cache.get("has_camera"):
            return float((rig.matrix_world.translation - depth_cache["camera_location"]).dot(depth_cache["camera_forward"]))
        return float(rig.location.y if getattr(rig, "fbp_is_vertical", False) else rig.location.z)
    except ReferenceError:
        return 0.0
    except (AttributeError, TypeError, RuntimeError, ValueError) as exc:
        fbp_warn("Could not compute layer depth", exc)
        return 0.0


def sort_rigs_for_layer_view(context, rigs):
    if not context:
        return list(rigs)
    if getattr(context.scene, 'fbp_sort_layers_alpha', False):
        return sorted(rigs, key=lambda rig: natural_sort_key(rig.name))
    # Farther layers first internally; UI reverses this where needed so closest appears on top.
    depth_ctx = fbp_make_depth_context_cache(context)
    depth_cache = {rig.name: fbp_layer_depth_value_from_cache(rig, depth_ctx) for rig in rigs if rig}
    return sorted(rigs, key=lambda rig: (depth_cache.get(rig.name, 0.0), natural_sort_key(rig.name)), reverse=True)


def sort_rigs_by_depth_for_layer_view(context, rigs):
    return sort_rigs_for_layer_view(context, rigs)


def sort_collections_for_layer_view(context, collections):
    if getattr(context.scene, 'fbp_sort_layers_alpha', False):
        return sorted(collections, key=lambda c: natural_sort_key(c.name))
    depth_ctx = fbp_make_depth_context_cache(context)
    def _collection_depth(coll):
        rigs = list(iter_fbp_rigs_in_collection(coll, True))
        if not rigs:
            return 0.0
        return sum(fbp_layer_depth_value_from_cache(rig, depth_ctx) for rig in rigs) / max(1, len(rigs))
    return sorted(collections, key=lambda c: (_collection_depth(c), natural_sort_key(c.name)), reverse=True)


# ── LAYER UI BOOLEAN HELPERS ─────────────────────────────────────────────────

def _safe_layer_obj(layer_item):
    try:
        obj = layer_item.obj
        if obj and object_in_scene(obj):
            return obj
    except ReferenceError:
        pass
    return None


def get_layer_selected(self):
    obj = _safe_layer_obj(self)
    return bool(obj and obj.select_get())


def set_layer_selected(self, value):
    obj = _safe_layer_obj(self)
    if not obj:
        return
    try:
        context = bpy.context
        if value and not object_in_view_layer(obj, context):
            if not ensure_object_in_active_collection(obj, context):
                sync_layer_collection(context)
                return
        obj.select_set(bool(value))
        if value and context and context.view_layer and object_in_view_layer(obj, context):
            context.view_layer.objects.active = obj
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
        pass


def get_layer_rig_locked(self):
    obj = _safe_layer_obj(self)
    return bool(obj.hide_select) if obj else False


def set_layer_rig_locked(self, value):
    obj = _safe_layer_obj(self)
    if obj:
        obj.hide_select = bool(value)


def get_layer_plane_locked(self):
    obj = _safe_layer_obj(self)
    plane = getattr(obj, "fbp_plane_target", None) if obj else None
    return bool(plane.hide_select) if plane else False


def set_layer_plane_locked(self, value):
    obj = _safe_layer_obj(self)
    plane = getattr(obj, "fbp_plane_target", None) if obj else None
    if plane:
        plane.hide_select = bool(value)


def get_layer_solo_view(self):
    return bool(self.solo)


def set_layer_solo_view(self, value):
    context = bpy.context
    sc = context.scene if context else None
    rig = _safe_layer_obj(self)
    value = bool(value)

    if not sc:
        self.solo = value
        return

    if value:
        # First solo click isolates the layer. Further solo clicks add more layers.
        if not any(item.solo for item in sc.fbp_layers):
            for item in sc.fbp_layers:
                item.solo = False
                obj = _safe_layer_obj(item)
                if obj:
                    obj.fbp_is_visible = False

        self.solo = True
        if rig:
            rig.fbp_is_visible = True
    else:
        self.solo = False
        if rig:
            rig.fbp_is_visible = False

        # If no layer remains soloed, restore all layers.
        if not any(item.solo for item in sc.fbp_layers):
            for item in sc.fbp_layers:
                obj = _safe_layer_obj(item)
                if obj:
                    obj.fbp_is_visible = True

    update_global_visibility(context)


def get_layer_holdout(self):
    obj = _safe_layer_obj(self)
    try:
        return bool(obj and rig_holdout_is_active(obj))
    except Exception:
        return False


def set_layer_holdout(self, value):
    obj = _safe_layer_obj(self)
    if not obj:
        return
    try:
        if value:
            fbp_apply_holdout_materials_to_rig(obj)
        else:
            restore_original_materials_from_holdout(obj)
    except Exception as exc:
        print(f"[FBP] Holdout toggle skipped: {exc}")


def fbp_begin_safe_bulk_viewport_operation(reason="Bulk Operation", restore_after=0.85):
    """Temporarily switch to Wireframe before operations that touch many FBP objects.

    Collection toggles can change selection/visibility/material state for dozens of
    textured planes at once. If the viewport is in Material Preview/Workbench
    texture mode, Blender may try to upload many textures in the same redraw.
    This lightweight guard avoids that without permanently forcing Wireframe.
    """
    try:
        from .handlers import fbp_make_viewports_undo_safe
    except ImportError:
        try:
            from handlers import fbp_make_viewports_undo_safe
        except ImportError:
            fbp_make_viewports_undo_safe = None
    if fbp_make_viewports_undo_safe:
        try:
            fbp_make_viewports_undo_safe(restore_after=restore_after, release=False)
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
            pass

def _collection_rigs_for_ui(collection):
    try:
        return list(iter_fbp_rigs_in_collection(collection, True))
    except Exception:
        return []


def get_collection_selected(self):
    rigs = _collection_rigs_for_ui(self)
    try:
        return bool(rigs and all(get_layer_item_for_rig(bpy.context, rig).selected for rig in rigs if get_layer_item_for_rig(bpy.context, rig)))
    except Exception:
        return False


def set_collection_selected(self, value):
    fbp_begin_safe_bulk_viewport_operation("set_collection_selected")
    for rig in _collection_rigs_for_ui(self):
        item = get_layer_item_for_rig(bpy.context, rig)
        if item:
            item.selected = bool(value)


def get_collection_solo(self):
    rigs = _collection_rigs_for_ui(self)
    try:
        return bool(rigs and all(get_layer_item_for_rig(bpy.context, rig).solo_view for rig in rigs if get_layer_item_for_rig(bpy.context, rig)))
    except Exception:
        return False


def set_collection_solo(self, value):
    fbp_begin_safe_bulk_viewport_operation("set_collection_solo")
    for rig in _collection_rigs_for_ui(self):
        item = get_layer_item_for_rig(bpy.context, rig)
        if item:
            item.solo_view = bool(value)
    try:
        update_global_visibility(bpy.context)
    except Exception as exc:
        fbp_warn("Could not update collection solo visibility", exc)

def get_collection_locked(self):
    rigs = _collection_rigs_for_ui(self)
    return bool(rigs and all(getattr(rig, 'hide_select', False) for rig in rigs))


def set_collection_locked(self, value):
    fbp_begin_safe_bulk_viewport_operation("set_collection_locked")
    for rig in _collection_rigs_for_ui(self):
        rig.hide_select = bool(value)


def get_collection_plane_locked(self):
    planes = []
    for rig in _collection_rigs_for_ui(self):
        plane = getattr(rig, 'fbp_plane_target', None)
        if plane:
            planes.append(plane)
    return bool(planes and all(bool(getattr(plane, 'hide_select', True)) for plane in planes))


def set_collection_plane_locked(self, value):
    fbp_begin_safe_bulk_viewport_operation("set_collection_plane_locked")
    for rig in _collection_rigs_for_ui(self):
        plane = getattr(rig, 'fbp_plane_target', None)
        if not plane:
            continue
        try:
            plane.hide_select = bool(value)
            if plane.hide_select and plane.select_get():
                plane.select_set(False)
        except ReferenceError:
            continue
        except Exception as exc:
            fbp_warn('Could not paint collection linked plane selectability', exc)


def get_collection_visible(self):
    try:
        return not collection_is_hidden_in_view_layer(bpy.context, self)
    except Exception:
        return True


def set_collection_visible(self, value):
    fbp_begin_safe_bulk_viewport_operation("set_collection_visible")
    hidden = not bool(value)
    try:
        self.hide_viewport = hidden
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
        pass
    try:
        layer_coll = find_layer_collection(bpy.context.view_layer.layer_collection, self)
        if layer_coll:
            layer_coll.hide_viewport = hidden
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
        pass
    try:
        update_global_visibility(bpy.context)
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
        pass


def get_collection_holdout(self):
    rigs = _collection_rigs_for_ui(self)
    try:
        # Folder icon is considered active if at least one child layer is currently in temporary holdout.
        return bool(rigs and any(rig_holdout_is_active(rig) for rig in rigs))
    except Exception:
        return False


def set_collection_holdout(self, value):
    fbp_begin_safe_bulk_viewport_operation("set_collection_holdout")
    for rig in _collection_rigs_for_ui(self):
        try:
            if value:
                fbp_apply_holdout_materials_to_rig(rig)
            else:
                restore_original_materials_from_holdout(rig)
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, KeyError, IndexError, OSError):
            pass

__all__ = ['is_fbp_image_rig', 'is_fbp_layer_object', 'safe_collection_color_tag', 'set_collection_color_tag', 'make_color_variant', 'get_or_create_child_collection', 'move_object_to_collection', 'get_primary_fbp_collection', 'is_layer_item_visible_in_collections', 'visible_layer_indices', 'apply_collection_color_to_layer', 'apply_collection_color_to_rig', 'sync_collection_colors_to_rigs', 'find_layer_collection', 'collection_is_hidden_in_view_layer', 'fbp_rebuild_layer_view_cache', 'fbp_mark_layer_cache_dirty', 'collection_has_fbp_content', 'get_direct_fbp_rigs_in_collection', 'iter_fbp_rigs_in_collection', 'get_child_fbp_collections', 'get_top_fbp_collections', 'get_layer_item_for_rig', 'fbp_procedural_layer_type', 'fbp_color_plane_type_icon', 'fbp_procedural_kind_from_material', 'fbp_procedural_kind_for_item', 'fbp_set_procedural_metadata', 'fbp_procedural_preview_from_material', 'fbp_cache_procedural_preview_on_item', 'fbp_mask_icon', 'fbp_select_rig_icon', 'fbp_select_plane_icon', 'fbp_collection_select_icon', 'fbp_collection_plane_icon', 'fbp_collection_icon', 'fbp_layer_row_type_icon', 'fbp_add_tree_indent', 'fbp_set_ui_units_x', 'indent_row', 'fbp_collection_rows_are_disabled', 'draw_fbp_layer_row', 'draw_fbp_collection_row', 'collect_project_image_paths', 'missing_project_images', 'build_project_file_index', 'relink_missing_images_from_root', 'project_root_for_package', 'rig_has_missing_images', 'swap_layer_depth_only', 'object_in_scene', 'object_in_view_layer', 'ensure_object_in_active_collection', 'get_selected_rigs', 'fbp_resolve_rig_from_any_object', 'get_selected_fbp_roots', 'clear_previews', 'update_global_visibility', 'update_mute_cb', 'get_preview_collection', 'load_preview', 'get_layer_thumbnail', 'set_viewport_object_color', 'fbp_make_depth_context_cache', 'fbp_layer_depth_value_from_cache', 'sort_rigs_for_layer_view', 'sort_rigs_by_depth_for_layer_view', 'sort_collections_for_layer_view', '_safe_layer_obj', 'get_layer_selected', 'set_layer_selected', 'get_layer_rig_locked', 'set_layer_rig_locked', 'get_layer_plane_locked', 'set_layer_plane_locked', 'get_layer_solo_view', 'set_layer_solo_view', 'get_layer_holdout', 'set_layer_holdout', 'fbp_begin_safe_bulk_viewport_operation', '_collection_rigs_for_ui', 'get_collection_selected', 'set_collection_selected', 'get_collection_solo', 'set_collection_solo', 'get_collection_locked', 'set_collection_locked', 'get_collection_plane_locked', 'set_collection_plane_locked', 'get_collection_visible', 'set_collection_visible', 'get_collection_holdout', 'set_collection_holdout', '_FBP_SYNCING_PROCEDURAL_PREVIEW_ITEMS']
