"""Masks in Solid view: cut the layer plane where its mask stack is empty.

Masks run per pixel in the plane material, and Blender's Solid view (the
Workbench engine) never evaluates material nodes: a masked layer showed its
whole rectangle there. This module adds one small Geometry Nodes modifier at
the end of a masked plane's stack that removes the parts of the plane the mask
stack hides, so Solid view (any colour mode) shows the layer as masked.

The cut follows the material, not a second copy of the settings: the mask
stack is read from the material's own nodes (the "Apply Mask Stack" node and
the boolean helpers feeding it) and each supported mask is rebuilt in Geometry
Nodes with the same helper object, SDF image and bounds the shader samples.
For every sub-stack two signed fields are kept:

* ``P > 0`` wherever the matte may be above 0 (the part that can be visible);
* ``Q > 0`` wherever the matte may be below 1 (needed by Subtract / Invert).

Both are supersets, so the cut is conservative: it only removes geometry the
material would draw fully transparent. Shape Masks (Square, Circle, Triangle)
and raster masks sampled over the plane UV (Grease Pencil Mask slots, Imported
Layer Mask) are supported. A mask the cut cannot read (procedural, Color Key,
mattes...) counts as "could be visible everywhere" and simply cuts nothing. Feather stays in the material: it softens inward, so the cut sits
on the outer edge of the mask.

The plane is subdivided into a grid (finer for a single quad, coarser for a
plane that a mesh effect already split), triangulated, and every vertex just
outside the mask is moved onto the mask edge, found by bisection along the
edges that cross it (rasters have no signed distance to interpolate), with its
UV moved the same way. The edge is therefore smooth instead
of a staircase of grid cells.

The modifier is viewport only: renders never see it, and in Material Preview it
only removes pixels that were already transparent.
"""

from __future__ import annotations

import bpy

from .runtime import FBP_DATA_ERRORS, fbp_undo_guard_active, fbp_warn
from .registration import append_handler_once, remove_handlers_by_name


MODIFIER_NAME = "Solid View Masks"
GROUP_PREFIX = "FBP Solid View Masks"
_GROUP_TAG = "fbp_solid_mask_view"
_STRUCTURE_KEY = "fbp_solid_mask_view_structure"
_PARAMS_KEY = "fbp_solid_mask_view_params"
_CUT_KEY = "fbp_solid_mask_view_cut"
_PARAM_NODE_KEY = "fbp_smv_param"
_PARAM_SOCKET_KEY = "fbp_smv_socket"
# Bump when the generated node layout changes: saved files rebuild once.
_FORMAT = 1
_PLANE_KEY = "fbp_solid_mask_view_plane"
_MODULE_SUFFIX = "solid_mask_view"
# Signed-field stand-ins for "everywhere" (+) and "nowhere" (-).
_BIG = 1.0e6
# Grid level for a single quad: 2**6 = 64 cells per side.
_MAX_LEVEL = 6
_UV_NAME = "UVMap"
_BISECTION_STEPS = 6
_ATTR_P = "fbp_smv_p"
_ATTR_UV = "fbp_smv_uv"
_ATTR_IN = "fbp_smv_in"
_ATTR_FLAG = "fbp_smv_cf"
_ATTR_POS = "fbp_smv_cp"
_ATTR_CUV = "fbp_smv_cu"
_ATTR_NUV = "fbp_smv_nuv"
_TEMP_ATTRIBUTES = (_ATTR_P, _ATTR_UV, _ATTR_IN, _ATTR_FLAG, _ATTR_POS, _ATTR_CUV, _ATTR_NUV)

_PENDING = set()
# Planes known to carry the cut: frame changes re-check only these.
_TRACKED = set()


# --------------------------------------------------------------------------
# Reading the material mask stack
# --------------------------------------------------------------------------

def _plane_for_rig(rig):
    try:
        from .geometry_nodes import _fbp_plane
        return _fbp_plane(rig, repair=False)
    except (ImportError, *FBP_DATA_ERRORS):
        return None


def _mask_stack_factor(material):
    """The combined layer matte socket of a material, or ``None``."""
    tree = getattr(material, "node_tree", None)
    if tree is None:
        return None
    try:
        for node in tree.nodes:
            if not bool(node.get("fbp_mask_stack_final", False)):
                continue
            if bool(getattr(node, "mute", False)) or len(node.inputs) < 2:
                return None
            socket = node.inputs[1]
            if not socket.is_linked:
                return None
            return socket.links[0].from_socket
    except FBP_DATA_ERRORS:
        return None
    return None


def _follow(socket):
    """Skip reroutes back to the producing output socket."""
    seen = 0
    while socket is not None and getattr(socket.node, "bl_idname", "") == "NodeReroute":
        seen += 1
        if seen > 64:
            return None
        inputs = socket.node.inputs
        if not inputs or not inputs[0].is_linked:
            return None
        socket = inputs[0].links[0].from_socket
    return socket


def _input_value(plane, node, name):
    """A float input of a mask node: its value, or what a shell attribute reads."""
    socket = None
    for item in node.inputs:
        if item.name == name:
            socket = item
            break
    if socket is None:
        return None
    if not socket.is_linked:
        try:
            return float(socket.default_value)
        except (TypeError, ValueError):
            return None
    source = _follow(socket.links[0].from_socket)
    if source is None:
        return None
    source_node = source.node
    if (
        source_node.bl_idname == "ShaderNodeAttribute"
        and str(getattr(source_node, "attribute_type", "")) == "OBJECT"
    ):
        path = str(getattr(source_node, "attribute_name", "") or "")
        if not path:
            return None
        try:
            return float(plane.path_resolve(path))
        except (*FBP_DATA_ERRORS, KeyError, IndexError):
            return None
    if source_node.bl_idname == "ShaderNodeValue":
        try:
            return float(source_node.outputs[0].default_value)
        except (TypeError, ValueError, IndexError):
            return None
    return None


def _shape_mask_leaf(plane, node):
    """Settings of one editable Shape Mask node, or ``None`` when unreadable."""
    tree = getattr(node, "node_tree", None)
    if tree is None or not tree.get("fbp_object_mask_shape"):
        return None
    helper = None
    image = None
    sampling = ("Linear", "CLIP")
    for inner in tree.nodes:
        try:
            if bool(inner.get("fbp_object_mask_coord_node", False)):
                helper = getattr(inner, "object", None)
            elif bool(inner.get("fbp_object_mask_image_node", False)):
                image = getattr(inner, "image", None)
                sampling = (str(inner.interpolation), str(inner.extension))
        except FBP_DATA_ERRORS:
            continue
    values = {}
    for name in (
        "Use Mask Object", "Factor", "Invert", "Feather",
        "Shape Min X", "Shape Max X", "Shape Min Y", "Shape Max Y",
    ):
        value = _input_value(plane, node, name)
        if value is None:
            return None
        values[name] = value
    use = values["Use Mask Object"] > 0.5 and helper is not None and image is not None
    return {
        "kind": "SHAPE",
        "sampling": sampling,
        "helper": helper if use else None,
        "image": image if use else None,
        "use": bool(use),
        "factor": values["Factor"],
        "invert": values["Invert"],
        "feather": values["Feather"],
        "bounds": (
            values["Shape Min X"], values["Shape Max X"],
            values["Shape Min Y"], values["Shape Max Y"],
        ),
    }


def _plain_uv_source(node, name):
    """True when ``name`` reads the plane UV unchanged (no UV-stage effect)."""
    socket = None
    for item in node.inputs:
        if item.name == name:
            socket = item
            break
    if socket is None or not socket.is_linked:
        return False
    source = _follow(socket.links[0].from_socket)
    if source is None:
        return False
    if source.node.bl_idname == "ShaderNodeTexCoord":
        return source.name == "UV"
    if source.node.bl_idname == "ShaderNodeUVMap":
        return str(getattr(source.node, "uv_map", "") or "") in {"", _UV_NAME}
    return False


def _image_mask_leaf(plane, node):
    """Imported and Grease Pencil masks: a raster sampled over the plane UV."""
    tree = getattr(node, "node_tree", None)
    if tree is None or not tree.get("fbp_imported_mask_contract_version"):
        return None
    image = None
    sampling = ("Linear", "CLIP")
    for inner in tree.nodes:
        try:
            if bool(inner.get("fbp_imported_mask_image_node", False)):
                image = getattr(inner, "image", None)
                sampling = (str(inner.interpolation), str(inner.extension))
                break
        except FBP_DATA_ERRORS:
            continue
    if not _plain_uv_source(node, "UV Vector"):
        return None
    values = {}
    for name in ("Use Mask Sample", "Factor", "Invert"):
        value = _input_value(plane, node, name)
        if value is None:
            return None
        values[name] = value
    use = values["Use Mask Sample"] > 0.5 and image is not None
    return {
        "kind": "IMAGE",
        "image": image if use else None,
        "sampling": sampling,
        "use": bool(use),
        "factor": values["Factor"],
        "invert": values["Invert"],
    }


def _read_tree(plane, socket, depth=0):
    """Describe the matte feeding ``socket`` as a small expression tree."""
    socket = _follow(socket)
    if socket is None or depth > 48:
        return {"kind": "UNKNOWN"}
    node = socket.node
    if bool(getattr(node, "mute", False)):
        return {"kind": "UNKNOWN"}
    idname = node.bl_idname
    if idname == "ShaderNodeGroup":
        if socket.name != "Mask Out":
            return {"kind": "UNKNOWN"}
        return (
            _shape_mask_leaf(plane, node)
            or _image_mask_leaf(plane, node)
            or {"kind": "UNKNOWN"}
        )
    if idname != "ShaderNodeMath":
        return {"kind": "UNKNOWN"}
    operation = str(node.operation)

    def operand(index):
        item = node.inputs[index]
        if item.is_linked:
            return _read_tree(plane, item.links[0].from_socket, depth + 1)
        try:
            return {"kind": "CONST", "value": float(item.default_value)}
        except (TypeError, ValueError):
            return {"kind": "UNKNOWN"}

    if operation == "MAXIMUM":
        return {"kind": "MAX", "a": operand(0), "b": operand(1)}
    if operation == "MULTIPLY":
        return {"kind": "MUL", "a": operand(0), "b": operand(1)}
    if operation == "SUBTRACT" and bool(node.use_clamp):
        return {"kind": "SUB", "a": operand(0), "b": operand(1)}
    if operation == "ABSOLUTE":
        inner = node.inputs[0]
        if inner.is_linked:
            source = _follow(inner.links[0].from_socket)
            if (
                source is not None
                and source.node.bl_idname == "ShaderNodeMath"
                and str(source.node.operation) == "SUBTRACT"
            ):
                subtract = source.node

                def sub_operand(index):
                    item = subtract.inputs[index]
                    if item.is_linked:
                        return _read_tree(plane, item.links[0].from_socket, depth + 2)
                    try:
                        return {"kind": "CONST", "value": float(item.default_value)}
                    except (TypeError, ValueError):
                        return {"kind": "UNKNOWN"}

                return {"kind": "DIFF", "a": sub_operand(0), "b": sub_operand(1)}
    return {"kind": "UNKNOWN"}


def _plane_mask_tree(plane):
    """The mask expression of the plane's first masked material."""
    try:
        materials = [slot.material for slot in plane.material_slots if slot.material]
    except FBP_DATA_ERRORS:
        return None
    for material in materials:
        factor = _mask_stack_factor(material)
        if factor is not None:
            return _read_tree(plane, factor)
    return None


def _has_cut(tree):
    """True when the stack can be fully transparent somewhere.

    Mirrors ``_Builder.tree`` with symbols instead of nodes: +1 is "everywhere",
    -1 "nowhere" and 0 a real field. Only a real (or -1) visible field cuts.
    """
    if tree is None:
        return False

    def high(a, b):
        return 1 if 1 in (a, b) else (b if a == -1 else (a if b == -1 else 0))

    def low(a, b):
        return -1 if -1 in (a, b) else (b if a == 1 else (a if b == 1 else 0))

    def walk(item):
        kind = item["kind"]
        if kind in {"SHAPE", "IMAGE"}:
            state, invert, factor = _leaf_class(item)
            if state == "OFF":
                return 1, -1
            p, q = (1, 0) if invert == "PART" else (0, 0)
            return (1 if factor == "SOFT" else p), q
        if kind == "CONST":
            value = float(item["value"])
            return (1 if value > 0.0 else -1), (1 if value < 1.0 else -1)
        if kind in {"MAX", "MUL", "SUB", "DIFF"}:
            pa, qa = walk(item["a"])
            pb, qb = walk(item["b"])
            if kind == "MAX":
                return high(pa, pb), low(qa, qb)
            if kind == "MUL":
                return low(pa, pb), high(qa, qb)
            if kind == "SUB":
                return low(pa, qb), high(qa, pb)
            return high(pa, pb), 1
        return 1, 1

    return walk(tree)[0] != 1


def _leaf_class(item):
    """Formula branch of a leaf: which of its fields can cut geometry."""
    factor = float(item["factor"])
    invert = float(item["invert"])
    return (
        "OFF" if not item["use"] or factor <= 0.0 else "ON",
        "INV" if invert >= 0.5 else ("PART" if invert > 0.0 else "NORM"),
        "SOFT" if factor < 1.0 else "FULL",
    )


def _describe(tree):
    """``(structure, params)``: what needs a rebuild vs. plain value updates.

    Numbers that slide continuously (Shape Mask bounds and Feather) only change
    node values; everything else (masks, operations, helpers, images, Invert
    and Factor branches) rebuilds the stack evaluator.
    """
    params = {}
    counter = [0]

    def walk(item):
        kind = item["kind"]
        if kind in {"SHAPE", "IMAGE"}:
            index = counter[0]
            counter[0] += 1
            item["index"] = index
            image = item.get("image")
            entry = [
                kind, _leaf_class(item), item["sampling"],
                image.name if image is not None else "",
            ]
            if kind == "SHAPE":
                helper = item.get("helper")
                entry.append(helper.name if helper is not None else "")
                names = ("min_x", "max_x", "min_y", "max_y")
                for name, value in zip(names, item["bounds"], strict=True):
                    params[f"L{index}.{name}"] = float(value)
                params[f"L{index}.inner"] = 0.5 + max(float(item["feather"]) * 0.5, 0.0005)
            return tuple(entry)
        if kind == "CONST":
            value = float(item["value"])
            return (kind, value > 0.0, value < 1.0)
        if kind in {"MAX", "MUL", "SUB", "DIFF"}:
            return (kind, walk(item["a"]), walk(item["b"]))
        return (kind,)

    structure = repr((_FORMAT, walk(tree)))
    return structure, params


# --------------------------------------------------------------------------
# Building the Geometry Nodes cut
# --------------------------------------------------------------------------

class _Builder:
    def __init__(self, group):
        self.group = group
        self.nodes = group.nodes
        self.links = group.links
        self.count = 0
        self._position = None
        # Where the mask stack is evaluated: a position and a plane UV field.
        self.at_position = None
        self.at_uv = None
        self.params = {}

    def node(self, idname, **props):
        node = self.nodes.new(idname)
        self.count += 1
        node.location = ((self.count % 12) * 180.0, -(self.count // 12) * 220.0)
        for key, value in props.items():
            setattr(node, key, value)
        return node

    def link(self, socket, target):
        self.links.new(socket, target)

    def position(self):
        if self._position is None:
            self._position = self.node("GeometryNodeInputPosition").outputs[0]
        return self._position

    def param(self, node, socket, key):
        """Tag a node input that later value updates write in place."""
        node[_PARAM_NODE_KEY] = key
        node[_PARAM_SOCKET_KEY] = socket
        value = self.params.get(key)
        if value is not None:
            node.inputs[socket].default_value = float(value)

    def math(self, operation, a, b=None, *, clamp=False):
        node = self.node("ShaderNodeMath", operation=operation, use_clamp=clamp)
        for index, value in enumerate((a, b)):
            if value is None:
                continue
            if isinstance(value, (int, float)):
                node.inputs[index].default_value = float(value)
            else:
                self.link(value, node.inputs[index])
        return node.outputs[0]

    def value(self, number):
        node = self.node("ShaderNodeValue")
        node.outputs[0].default_value = float(number)
        return node.outputs[0]

    def named(self, name, data_type):
        node = self.node("GeometryNodeInputNamedAttribute", data_type=data_type)
        node.inputs["Name"].default_value = name
        return node.outputs["Attribute"]

    def store(self, geometry, name, value, *, data_type, domain):
        node = self.node(
            "GeometryNodeStoreNamedAttribute", data_type=data_type, domain=domain,
        )
        self.link(geometry, node.inputs["Geometry"])
        node.inputs["Name"].default_value = name
        value_input = next(
            socket for socket in node.inputs
            if socket.name == "Value" and socket.enabled
        )
        self.link(value, value_input)
        return node.outputs["Geometry"]

    def compare(self, a, b, operation):
        node = self.node("FunctionNodeCompare", data_type="FLOAT", operation=operation)
        inputs = [socket for socket in node.inputs if socket.enabled]
        for target, value in zip(inputs[:2], (a, b)):
            if isinstance(value, (int, float)):
                target.default_value = float(value)
            else:
                self.link(value, target)
        return node.outputs["Result"]

    def boolean(self, operation, a, b):
        node = self.node("FunctionNodeBooleanMath", operation=operation)
        self.link(a, node.inputs[0])
        self.link(b, node.inputs[1])
        return node.outputs[0]

    def switch(self, input_type, condition, false, true):
        node = self.node("GeometryNodeSwitch", input_type=input_type)
        self.link(condition, node.inputs["Switch"])
        for name, value in (("False", false), ("True", true)):
            if isinstance(value, (int, float)):
                node.inputs[name].default_value = float(value)
            else:
                self.link(value, node.inputs[name])
        return node.outputs[0]

    def vector_mix(self, a, b, factor):
        node = self.node("ShaderNodeMix", data_type="VECTOR", clamp_factor=False)
        sockets = [socket for socket in node.inputs if socket.enabled]
        # Enabled inputs: Factor (float), A, B (vectors).
        self.link(factor, sockets[0])
        self.link(a, sockets[1])
        self.link(b, sockets[2])
        return next(socket for socket in node.outputs if socket.enabled)

    def vector_math(self, operation, a, b=None, *, scale=None):
        node = self.node("ShaderNodeVectorMath", operation=operation)
        self.link(a, node.inputs[0])
        if b is not None:
            self.link(b, node.inputs[1])
        if scale is not None:
            self.link(scale, node.inputs["Scale"])
        return node.outputs["Vector"]

    def at_index(self, value, index, data_type):
        node = self.node("GeometryNodeFieldAtIndex", data_type=data_type, domain="POINT")
        self.link(value, node.inputs["Value"])
        self.link(index, node.inputs["Index"])
        return node.outputs["Value"]

    def evaluate(self, evaluator, position, uv):
        """One instance of the stack evaluator group: the signed field P."""
        node = self.node("GeometryNodeGroup")
        node.node_tree = evaluator
        self.link(position, node.inputs["Position"])
        self.link(uv, node.inputs["UV"])
        return node.outputs["Visible"]

    # Signed fields: python floats are constants (+/-_BIG), sockets are fields.
    def fmax(self, a, b):
        if isinstance(a, float) and isinstance(b, float):
            return max(a, b)
        for x, y in ((a, b), (b, a)):
            if isinstance(x, float):
                if x >= _BIG:
                    return _BIG
                if x <= -_BIG:
                    return y
        return self.math("MAXIMUM", a, b)

    def fmin(self, a, b):
        if isinstance(a, float) and isinstance(b, float):
            return min(a, b)
        for x, y in ((a, b), (b, a)):
            if isinstance(x, float):
                if x <= -_BIG:
                    return -_BIG
                if x >= _BIG:
                    return y
        return self.math("MINIMUM", a, b)

    def image_node(self, item):
        """Image Texture sampled like the material's own node."""
        interpolation, extension = item["sampling"]
        image = self.node("GeometryNodeImageTexture")
        for prop, value, fallback in (
            ("interpolation", interpolation, "Linear"),
            ("extension", extension, "CLIP"),
        ):
            try:
                setattr(image, prop, value)
            except (TypeError, ValueError):
                setattr(image, prop, fallback)
        image.inputs["Image"].default_value = item["image"]
        return image

    def finish_leaf(self, item, outer, inner):
        """Apply Invert and Factor to a leaf's (visible, not-full) fields."""
        _state, invert, factor = _leaf_class(item)
        if invert == "INV":
            selected_p, selected_q = inner, outer
        elif invert == "PART":
            # A partial invert keeps every pixel partly visible.
            selected_p, selected_q = _BIG, self.fmax(outer, inner)
        else:
            selected_p, selected_q = outer, inner
        if factor == "SOFT":
            # (1 - F) + F * mask never reaches 0.
            return _BIG, selected_q
        return selected_p, selected_q

    def shape_leaf(self, item):
        """(P, Q) of one Shape Mask, matching ``_create_object_shape_mask``."""
        if _leaf_class(item)[0] == "OFF":
            # Pass through: the matte is 1 everywhere.
            return _BIG, -_BIG
        index = item["index"]
        info = self.node("GeometryNodeObjectInfo", transform_space="RELATIVE")
        info.inputs["Object"].default_value = item["helper"]
        invert = self.node("FunctionNodeInvertMatrix")
        self.link(info.outputs["Transform"], invert.inputs["Matrix"])
        local = self.node("FunctionNodeTransformPoint")
        self.link(self.at_position, local.inputs["Vector"])
        self.link(invert.outputs["Matrix"], local.inputs["Transform"])
        separate = self.node("ShaderNodeSeparateXYZ")
        self.link(local.outputs["Vector"], separate.inputs[0])
        combine = self.node("ShaderNodeCombineXYZ")
        for axis, low, high in (("X", "min_x", "max_x"), ("Y", "min_y", "max_y")):
            mapper = self.node(
                "ShaderNodeMapRange", data_type="FLOAT", interpolation_type="LINEAR", clamp=False,
            )
            self.link(separate.outputs[axis], mapper.inputs["Value"])
            # One tag per node: the two ends get one Math node each.
            low_value = self.math("ADD", 0.0, 0.0)
            self.param(low_value.node, 0, f"L{index}.{low}")
            high_value = self.math("ADD", 0.0, 0.0)
            self.param(high_value.node, 0, f"L{index}.{high}")
            self.link(low_value, mapper.inputs["From Min"])
            self.link(high_value, mapper.inputs["From Max"])
            mapper.inputs["To Min"].default_value = 0.0
            mapper.inputs["To Max"].default_value = 1.0
            self.link(mapper.outputs["Result"], combine.inputs[axis])
        image = self.image_node(item)
        self.link(combine.outputs[0], image.inputs["Vector"])
        sdf = image.outputs["Alpha"]
        # The SDF edge is at 0.5 and Feather softens inward up to 0.5 + width.
        outer = self.math("SUBTRACT", sdf, 0.5)          # > 0 inside the shape
        inner = self.math("SUBTRACT", 0.5, sdf)          # > 0 below full strength
        self.param(inner.node, 0, f"L{index}.inner")
        return self.finish_leaf(item, outer, inner)

    def image_leaf(self, item):
        """(P, Q) of an Imported / Grease Pencil mask (``_create_imported_mask``)."""
        if _leaf_class(item)[0] == "OFF":
            return _BIG, -_BIG
        image = self.image_node(item)
        self.link(self.at_uv, image.inputs["Vector"])
        # RGB to BW (Rec. 709 luminance, Blender's default scene-linear space).
        luminance = self.node("ShaderNodeVectorMath", operation="DOT_PRODUCT")
        self.link(image.outputs["Color"], luminance.inputs[0])
        luminance.inputs[1].default_value = (0.2126, 0.7152, 0.0722)
        value = luminance.outputs["Value"]
        # A raster has no signed distance: pixels below 1/512 count as empty.
        threshold = 1.0 / 512.0
        outer = self.math("SUBTRACT", value, threshold)
        inner = self.math("SUBTRACT", 1.0 - threshold, value)
        return self.finish_leaf(item, outer, inner)

    def tree(self, item):
        kind = item["kind"]
        if kind == "SHAPE":
            return self.shape_leaf(item)
        if kind == "IMAGE":
            return self.image_leaf(item)
        if kind == "CONST":
            value = float(item["value"])
            return (_BIG if value > 0.0 else -_BIG), (_BIG if value < 1.0 else -_BIG)
        if kind in {"MAX", "MUL", "SUB", "DIFF"}:
            pa, qa = self.tree(item["a"])
            pb, qb = self.tree(item["b"])
            if kind == "MAX":
                return self.fmax(pa, pb), self.fmin(qa, qb)
            if kind == "MUL":
                return self.fmin(pa, pb), self.fmax(qa, qb)
            if kind == "SUB":
                return self.fmin(pa, qb), self.fmax(qa, pb)
            return self.fmax(pa, pb), _BIG
        return _BIG, _BIG


def _new_group(name, kind):
    group = bpy.data.node_groups.new(name, "GeometryNodeTree")
    interface = group.interface
    if kind == "CUT":
        interface.new_socket("Geometry", in_out="INPUT", socket_type="NodeSocketGeometry")
        interface.new_socket("Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")
    else:
        interface.new_socket("Position", in_out="INPUT", socket_type="NodeSocketVector")
        interface.new_socket("UV", in_out="INPUT", socket_type="NodeSocketVector")
        interface.new_socket("Visible", in_out="OUTPUT", socket_type="NodeSocketFloat")
    group[_GROUP_TAG] = kind
    return group


def _build_evaluator(group, tree, params):
    """The mask stack as a field: ``Visible`` > 0 where the matte may be > 0."""
    group.nodes.clear()
    build = _Builder(group)
    build.params = dict(params)
    group_in = build.node("NodeGroupInput")
    group_out = build.node("NodeGroupOutput")
    build.at_position = group_in.outputs["Position"]
    build.at_uv = group_in.outputs["UV"]
    visible, _q = build.tree(tree)
    if isinstance(visible, float):
        visible = build.value(visible)
    build.link(visible, group_out.inputs["Visible"])
    group[_PARAMS_KEY] = repr(sorted(params.items()))


def _update_evaluator_params(group, params):
    """Write changed bounds / Feather values in place. Returns True on change."""
    stored = repr(sorted(params.items()))
    if str(group.get(_PARAMS_KEY, "")) == stored:
        return False
    for node in group.nodes:
        key = node.get(_PARAM_NODE_KEY)
        if key is None or key not in params:
            continue
        try:
            socket = node.inputs[int(node.get(_PARAM_SOCKET_KEY, 0))]
            if abs(float(socket.default_value) - params[key]) > 1.0e-9:
                socket.default_value = params[key]
        except (*FBP_DATA_ERRORS, IndexError):
            continue
    group[_PARAMS_KEY] = stored
    return True


def _build_cut(group, evaluator, detail):
    """The cut pipeline around one evaluator: grid, snap to the mask edge, delete."""
    group.nodes.clear()
    build = _Builder(group)
    group_in = build.node("NodeGroupInput")
    group_out = build.node("NodeGroupOutput")
    geometry = group_in.outputs[0]

    # Grid detail: 64 cells per side on a single quad, fewer when a mesh
    # effect already split the plane, so the total stays near 4096 quads.
    size = build.node("GeometryNodeAttributeDomainSize", component="MESH")
    build.link(geometry, size.inputs["Geometry"])
    faces = build.math("MAXIMUM", size.outputs["Face Count"], 1.0)
    level = build.math("SUBTRACT", float(detail), build.math("LOGARITHM", faces, 4.0))
    level = build.math("MINIMUM", build.math("MAXIMUM", build.math("ROUND", level), 0.0), float(detail))
    subdivide = build.node("GeometryNodeSubdivideMesh")
    build.link(geometry, subdivide.inputs["Mesh"])
    build.link(level, subdivide.inputs["Level"])
    triangulate = build.node("GeometryNodeTriangulate")
    build.link(subdivide.outputs["Mesh"], triangulate.inputs["Mesh"])
    geometry = triangulate.outputs["Mesh"]

    signed = build.evaluate(evaluator, build.position(), build.named(_UV_NAME, "FLOAT_VECTOR"))
    geometry = build.store(geometry, _ATTR_P, signed, data_type="FLOAT", domain="POINT")
    geometry = build.store(
        geometry, _ATTR_UV, build.named(_UV_NAME, "FLOAT_VECTOR"),
        data_type="FLOAT_VECTOR", domain="POINT",
    )
    inside = build.compare(build.named(_ATTR_P, "FLOAT"), 0.0, "GREATER_THAN")
    geometry = build.store(geometry, _ATTR_IN, inside, data_type="FLOAT", domain="POINT")

    # Edges crossing the mask edge, and where along them it lies. A raster
    # mask has no signed distance to interpolate, so bisect: the evaluator
    # runs again in the middle of the remaining interval, and six steps put
    # the edge within 1/64 of a grid cell.
    edge = build.node("GeometryNodeInputMeshEdgeVertices")
    position1 = edge.outputs["Position 1"]
    position2 = edge.outputs["Position 2"]
    s1 = build.at_index(build.named(_ATTR_P, "FLOAT"), edge.outputs["Vertex Index 1"], "FLOAT")
    s2 = build.at_index(build.named(_ATTR_P, "FLOAT"), edge.outputs["Vertex Index 2"], "FLOAT")
    uv1 = build.at_index(build.named(_ATTR_UV, "FLOAT_VECTOR"), edge.outputs["Vertex Index 1"], "FLOAT_VECTOR")
    uv2 = build.at_index(build.named(_ATTR_UV, "FLOAT_VECTOR"), edge.outputs["Vertex Index 2"], "FLOAT_VECTOR")
    in1 = build.compare(s1, 0.0, "GREATER_THAN")
    in2 = build.compare(s2, 0.0, "GREATER_THAN")
    crosses = build.boolean("XOR", in1, in2)
    flag = build.switch("FLOAT", crosses, 0.0, 1.0)
    low, high = build.value(0.0), build.value(1.0)
    for _step in range(_BISECTION_STEPS):
        middle = build.math("MULTIPLY", build.math("ADD", low, high), 0.5)
        value = build.evaluate(
            evaluator,
            build.vector_mix(position1, position2, middle),
            build.vector_mix(uv1, uv2, middle),
        )
        same = build.boolean("XNOR", build.compare(value, 0.0, "GREATER_THAN"), in1)
        low, high = build.switch("FLOAT", same, low, middle), build.switch("FLOAT", same, middle, high)
    t = build.math("MULTIPLY", build.math("ADD", low, high), 0.5)
    crossing = build.vector_mix(position1, position2, t)
    crossing_uv = build.vector_mix(uv1, uv2, t)
    geometry = build.store(geometry, _ATTR_FLAG, flag, data_type="FLOAT", domain="EDGE")
    geometry = build.store(
        geometry, _ATTR_POS, build.vector_math("SCALE", crossing, scale=flag),
        data_type="FLOAT_VECTOR", domain="EDGE",
    )
    geometry = build.store(
        geometry, _ATTR_CUV, build.vector_math("SCALE", crossing_uv, scale=flag),
        data_type="FLOAT_VECTOR", domain="EDGE",
    )

    # Read on points, edge attributes average over the connected edges: the
    # ratio is the mean crossing point of a vertex just outside the mask.
    count = build.named(_ATTR_FLAG, "FLOAT")
    inverse = build.math("DIVIDE", 1.0, build.math("MAXIMUM", count, 1.0e-9))
    snapped_position = build.vector_math("SCALE", build.named(_ATTR_POS, "FLOAT_VECTOR"), scale=inverse)
    snapped_uv = build.vector_math("SCALE", build.named(_ATTR_CUV, "FLOAT_VECTOR"), scale=inverse)
    snap = build.boolean(
        "AND",
        build.compare(build.named(_ATTR_P, "FLOAT"), 0.0, "LESS_EQUAL"),
        build.compare(count, 0.0, "GREATER_THAN"),
    )
    new_uv = build.switch("VECTOR", snap, build.named(_ATTR_UV, "FLOAT_VECTOR"), snapped_uv)
    geometry = build.store(geometry, _ATTR_NUV, new_uv, data_type="FLOAT_VECTOR", domain="POINT")

    set_position = build.node("GeometryNodeSetPosition")
    build.link(geometry, set_position.inputs["Geometry"])
    build.link(snap, set_position.inputs["Selection"])
    build.link(snapped_position, set_position.inputs["Position"])
    geometry = set_position.outputs["Geometry"]

    # UVMap stays a face-corner attribute: write back only where it exists.
    has_uv = build.node("GeometryNodeInputNamedAttribute", data_type="FLOAT_VECTOR")
    has_uv.inputs["Name"].default_value = _UV_NAME
    store_uv = build.node("GeometryNodeStoreNamedAttribute", data_type="FLOAT2", domain="CORNER")
    build.link(geometry, store_uv.inputs["Geometry"])
    build.link(has_uv.outputs["Exists"], store_uv.inputs["Selection"])
    store_uv.inputs["Name"].default_value = _UV_NAME
    build.link(
        build.named(_ATTR_NUV, "FLOAT_VECTOR"),
        next(socket for socket in store_uv.inputs if socket.name == "Value" and socket.enabled),
    )
    geometry = store_uv.outputs["Geometry"]

    # Faces with no corner inside the mask are fully transparent: drop them.
    delete = build.node("GeometryNodeDeleteGeometry", domain="FACE", mode="ALL")
    build.link(geometry, delete.inputs["Geometry"])
    build.link(
        build.compare(build.named(_ATTR_IN, "FLOAT"), 1.0e-6, "LESS_THAN"),
        delete.inputs["Selection"],
    )
    geometry = delete.outputs["Geometry"]
    for name in _TEMP_ATTRIBUTES:
        remove = build.node("GeometryNodeRemoveAttribute")
        build.link(geometry, remove.inputs["Geometry"])
        remove.inputs["Name"].default_value = name
        geometry = remove.outputs["Geometry"]
    build.link(geometry, group_out.inputs[0])
    group[_CUT_KEY] = repr((_FORMAT, detail))


def _cut_evaluator(group):
    """The evaluator group the cut instances, if it is still intact."""
    try:
        for node in group.nodes:
            if node.bl_idname == "GeometryNodeGroup" and node.node_tree is not None:
                return node.node_tree
    except FBP_DATA_ERRORS:
        return None
    return None


# --------------------------------------------------------------------------
# Modifier lifecycle
# --------------------------------------------------------------------------

def solid_mask_modifier(plane):
    try:
        for modifier in plane.modifiers:
            group = getattr(modifier, "node_group", None)
            if (
                modifier.type == "NODES"
                and group is not None
                and str(group.get(_GROUP_TAG, "")) == "CUT"
            ):
                return modifier
    except FBP_DATA_ERRORS:
        return None
    return None


def _remove_group_if_unused(group):
    try:
        if group is not None and int(group.users) == 0:
            bpy.data.node_groups.remove(group)
    except FBP_DATA_ERRORS:
        pass


def _remove_modifier(plane):
    modifier = solid_mask_modifier(plane)
    if modifier is None:
        _TRACKED.discard(getattr(plane, "name", ""))
        return False
    group = modifier.node_group
    evaluator = _cut_evaluator(group) if group is not None else None
    try:
        plane.modifiers.remove(modifier)
    except FBP_DATA_ERRORS:
        return False
    _remove_group_if_unused(group)
    _remove_group_if_unused(evaluator)
    _TRACKED.discard(plane.name)
    return True


def _frame_stack_active(rig):
    try:
        from .geometry_nodes import fbp_effect_is_active
        return bool(fbp_effect_is_active(rig, "FRAME_STACK"))
    except (ImportError, *FBP_DATA_ERRORS):
        return False


def _owned_groups(plane, modifier, detail):
    """The plane's own cut and evaluator groups, created when missing/shared."""
    group = modifier.node_group
    evaluator = _cut_evaluator(group) if group is not None else None
    if (
        group is not None
        and evaluator is not None
        and str(group.get(_PLANE_KEY, "")) == plane.name
        and str(evaluator.get(_PLANE_KEY, "")) == plane.name
        # A duplicated layer shares the groups of its source.
        and int(group.users) == 1
        and str(group.get(_CUT_KEY, "")) == repr((_FORMAT, detail))
    ):
        return group, evaluator, False
    evaluator = _new_group(f"{GROUP_PREFIX} Stack • {plane.name}", "STACK")
    evaluator[_PLANE_KEY] = plane.name
    evaluator[_STRUCTURE_KEY] = ""
    group = _new_group(f"{GROUP_PREFIX} • {plane.name}", "CUT")
    group[_PLANE_KEY] = plane.name
    _build_cut(group, evaluator, detail)
    previous = modifier.node_group
    previous_evaluator = _cut_evaluator(previous) if previous is not None else None
    modifier.node_group = group
    if previous is not None:
        _remove_group_if_unused(previous)
        _remove_group_if_unused(previous_evaluator)
    return group, evaluator, True


def fbp_solid_mask_sync(rig, *, detail=_MAX_LEVEL):
    """Add, refresh or remove the Solid view cut of one layer.

    Returns True when anything changed. Cheap when nothing did: the mask stack
    is read and compared with what the groups were built from. A Feather or
    mask-bounds change only rewrites node values; the cut pipeline itself is
    built once per layer.
    """
    if rig is None:
        return False
    plane = _plane_for_rig(rig)
    if plane is None or getattr(plane, "type", "") != "MESH":
        return False
    tree = _plane_mask_tree(plane)
    # Frame Stack slices read a second UV map the cut would not move.
    if tree is None or not _has_cut(tree) or _frame_stack_active(rig):
        return _remove_modifier(plane)
    structure, params = _describe(tree)
    modifier = solid_mask_modifier(plane)
    changed = False
    if modifier is None:
        try:
            modifier = plane.modifiers.new(MODIFIER_NAME, "NODES")
        except FBP_DATA_ERRORS as exc:
            fbp_warn("Could not add the Solid view mask cut", exc)
            return False
        modifier.show_render = False
        modifier.show_in_editmode = False
        modifier.show_expanded = False
        changed = True
    try:
        _group, evaluator, groups_changed = _owned_groups(plane, modifier, detail)
        changed = groups_changed or changed
        if str(evaluator.get(_STRUCTURE_KEY, "")) != structure:
            _build_evaluator(evaluator, tree, params)
            evaluator[_STRUCTURE_KEY] = structure
            changed = True
        elif _update_evaluator_params(evaluator, params):
            changed = True
    except (*FBP_DATA_ERRORS, StopIteration, KeyError) as exc:
        fbp_warn("Could not build the Solid view mask cut", exc)
        _remove_modifier(plane)
        return True
    if modifier.show_render:
        modifier.show_render = False
        changed = True
    # Masks read the final geometry, so the cut runs after every other effect.
    try:
        index = list(plane.modifiers).index(modifier)
        last = len(plane.modifiers) - 1
        if index != last:
            plane.modifiers.move(index, last)
            changed = True
    except FBP_DATA_ERRORS:
        pass
    _TRACKED.add(plane.name)
    return changed


def _expected_state(plane):
    """``(structure, params)`` the plane's evaluator should have, or ``None``."""
    tree = _plane_mask_tree(plane)
    if tree is None or not _has_cut(tree):
        return None
    return _describe(tree)

# --------------------------------------------------------------------------
# Scheduling
# --------------------------------------------------------------------------

def _run_pending():
    names = tuple(_PENDING)
    _PENDING.clear()
    if fbp_undo_guard_active():
        return None
    for name in names:
        rig = bpy.data.objects.get(name)
        if rig is None:
            continue
        try:
            fbp_solid_mask_sync(rig)
        except FBP_DATA_ERRORS as exc:
            fbp_warn("Could not refresh the Solid view mask cut", exc)
    return None


def fbp_solid_mask_schedule(rig):
    """Refresh one layer's cut from a safe task (never inside a callback)."""
    name = str(getattr(rig, "name", "") or "")
    if not name:
        return False
    _PENDING.add(name)
    try:
        from .safe_tasks import schedule_once
        return bool(schedule_once("solid_mask_view.sync", _run_pending, first_interval=0.0))
    except (ImportError, *FBP_DATA_ERRORS):
        return False


def fbp_solid_mask_schedule_material(material):
    """Schedule the owner layer of a rebuilt material."""
    try:
        owner = str(material.get("fbp_effect_rig_owner", "") or "")
    except FBP_DATA_ERRORS:
        return False
    rig = bpy.data.objects.get(owner) if owner else None
    if rig is None:
        return False
    return fbp_solid_mask_schedule(rig)


def fbp_solid_mask_schedule_all(scene=None):
    try:
        from .layers import iter_scene_fbp_rigs
        scene = scene or getattr(bpy.context, "scene", None)
        rigs = tuple(iter_scene_fbp_rigs(scene)) if scene is not None else ()
    except (ImportError, *FBP_DATA_ERRORS):
        return False
    for rig in rigs:
        fbp_solid_mask_schedule(rig)
    return bool(rigs)


def _rig_for_plane(plane):
    try:
        from .layers import fbp_resolve_rig_from_any_object
        return fbp_resolve_rig_from_any_object(plane)
    except (ImportError, *FBP_DATA_ERRORS):
        return None


@bpy.app.handlers.persistent
def fbp_solid_mask_frame_change(_scene, *_args):
    """Keyframed mask Invert/Factor: re-check the planes that carry a cut."""
    if not _TRACKED or fbp_undo_guard_active():
        return
    try:
        if bpy.app.is_job_running("RENDER"):
            return
    except FBP_DATA_ERRORS:
        pass
    for name in tuple(_TRACKED):
        plane = bpy.data.objects.get(name)
        if plane is None:
            _TRACKED.discard(name)
            continue
        modifier = solid_mask_modifier(plane)
        if modifier is None:
            _TRACKED.discard(name)
            continue
        evaluator = _cut_evaluator(modifier.node_group) if modifier.node_group else None
        expected = _expected_state(plane)
        current = None
        if evaluator is not None:
            current = (
                str(evaluator.get(_STRUCTURE_KEY, "")),
                str(evaluator.get(_PARAMS_KEY, "")),
            )
        wanted = (expected[0], repr(sorted(expected[1].items()))) if expected else None
        if current != wanted:
            rig = _rig_for_plane(plane)
            if rig is not None:
                fbp_solid_mask_schedule(rig)


@bpy.app.handlers.persistent
def fbp_solid_mask_load_post(*_args):
    _TRACKED.clear()
    _PENDING.clear()
    try:
        for obj in bpy.data.objects:
            if obj.type == "MESH" and solid_mask_modifier(obj) is not None:
                _TRACKED.add(obj.name)
    except FBP_DATA_ERRORS:
        pass
    # Files from before this feature get their cut on open.
    try:
        from .safe_tasks import schedule_once

        def _all():
            for scene in tuple(bpy.data.scenes):
                fbp_solid_mask_schedule_all(scene)
            return None

        schedule_once("solid_mask_view.load", _all, first_interval=0.5)
    except (ImportError, *FBP_DATA_ERRORS):
        pass


def register():
    append_handler_once(
        bpy.app.handlers.frame_change_post, fbp_solid_mask_frame_change,
        module_suffix=_MODULE_SUFFIX,
    )
    append_handler_once(
        bpy.app.handlers.load_post, fbp_solid_mask_load_post,
        module_suffix=_MODULE_SUFFIX,
    )
    fbp_solid_mask_load_post()


def unregister():
    for handler_list, name in (
        (bpy.app.handlers.frame_change_post, "fbp_solid_mask_frame_change"),
        (bpy.app.handlers.load_post, "fbp_solid_mask_load_post"),
    ):
        try:
            remove_handlers_by_name(handler_list, name, module_suffix=_MODULE_SUFFIX)
        except (TypeError, *FBP_DATA_ERRORS):
            pass
    _PENDING.clear()
    _TRACKED.clear()
