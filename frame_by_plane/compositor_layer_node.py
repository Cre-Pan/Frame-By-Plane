"""Auditable health contract for the dynamic FBP compositor Layers node."""

from __future__ import annotations

from datetime import datetime, timezone

from bpy.props import BoolProperty
from bpy.types import Operator, Panel

from .compositor import (
    FBP_COMPOSITOR_LAYER_NODE_GENERATION_KEY,
    FBP_COMPOSITOR_LAYER_NODE_SCHEMA_KEY,
    FBP_COMPOSITOR_LAYER_NODE_SCHEMA_VERSION,
    FBP_COMPOSITOR_LAYER_TAG,
    FBP_COMPOSITOR_SOURCE_TREE_TAG,
    FBP_COMPOSITOR_TREE_TAG,
    fbp_compositor_layer_node_schema_status,
    fbp_sync_compositor,
)
from .diagnostics import write_diagnostic_report
from .feature_scope import fbp_feature_enabled
from .shortcut_runtime import primary_shortcut_label
from .registration import (
    register_classes,
    register_interactive_classes,
    unregister_classes,
)
from .runtime import FBP_DATA_ERRORS
from .ui_style import configure_layout, hint_row, section_header


COMPOSITOR_LAYER_NODE_REPORT_NAME = "FBP_Compositor_Layer_Node"


def _utc_now():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _safe_int(owner, key, default=0):
    try:
        return int(owner.get(key, default) or default)
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        return int(default)




def _safe_text(owner, attr, default=""):
    try:
        return str(getattr(owner, attr, default) or default)
    except FBP_DATA_ERRORS:
        return str(default or "")


def _safe_bool(owner, attr, default=False):
    try:
        return bool(getattr(owner, attr, default))
    except FBP_DATA_ERRORS:
        return bool(default)


def _safe_id_bool(owner, key, default=False):
    try:
        return bool(owner is not None and owner.get(key, default))
    except FBP_DATA_ERRORS:
        return bool(default)


def _role_nodes(tree, role):
    """Resolve native FBP group nodes without probing arbitrary node IDProperties."""
    if tree is None:
        return ()
    result = []
    for node in tuple(getattr(tree, "nodes", ()) or ()):
        try:
            if str(getattr(node, "bl_idname", "") or "") != "CompositorNodeGroup":
                continue
            child = getattr(node, "node_tree", None)
            child_name = str(getattr(child, "name", "") or "") if child is not None else ""
            node_name = str(getattr(node, "name", "") or "")
        except FBP_DATA_ERRORS:
            continue
        resolved_role = ""
        if child_name.startswith("FBP Layers") or node_name in {"FBP Layers", "FBP Layers & Groups"}:
            resolved_role = "layers_package"
        elif child_name.startswith("FBP Effects & Masks") or node_name == "FBP Effects & Masks":
            resolved_role = "effects_stage"
        if resolved_role == role:
            result.append(node)
    return tuple(result)


def _socket_artist_links(socket):
    """Return JSON-safe artist links without reading arbitrary node IDProperties."""
    result = []
    for link in tuple(getattr(socket, "links", ()) or ()):
        try:
            target = link.to_node
            if str(getattr(target, "bl_idname", "") or "") == "FBPCompositorLayerSetNode":
                continue
            result.append(
                {
                    "node": str(getattr(target, "name", "") or ""),
                    "socket": str(getattr(link.to_socket, "name", "") or ""),
                }
            )
        except FBP_DATA_ERRORS:
            continue
    return result


def compositor_layer_node_snapshot(scene):
    """Return a JSON-safe read-only snapshot without retaining RNA wrappers."""
    schema = fbp_compositor_layer_node_schema_status(scene)
    try:
        tree = getattr(scene, "compositing_node_group", None) if scene else None
    except FBP_DATA_ERRORS:
        tree = None
    layers_nodes = _role_nodes(tree, "layers_package")
    layers_node = layers_nodes[0] if len(layers_nodes) == 1 else None
    try:
        source_tree = getattr(layers_node, "node_tree", None) if layers_node is not None else None
    except FBP_DATA_ERRORS:
        source_tree = None

    outputs = []
    if layers_node is not None:
        try:
            sockets = tuple(getattr(layers_node, "outputs", ()) or ())
        except FBP_DATA_ERRORS:
            sockets = ()
        for index, socket in enumerate(sockets):
            try:
                outputs.append(
                    {
                        "index": index,
                        "name": _safe_text(socket, "name"),
                        "identifier": _safe_text(socket, "identifier"),
                        "type": _safe_text(socket, "type"),
                        "hidden": _safe_bool(socket, "hide"),
                        "linked": _safe_bool(socket, "is_linked"),
                        "artist_links": _socket_artist_links(socket),
                    }
                )
            except FBP_DATA_ERRORS:
                continue

    layer_rows = []
    if scene is not None:
        try:
            items = tuple(getattr(scene, "fbp_compositor_layers", ()) or ())
        except FBP_DATA_ERRORS:
            items = ()
        for index, item in enumerate(items):
            try:
                layer_rows.append(
                    {
                        "index": index,
                        "id": _safe_text(item, "layer_id"),
                        "name": _safe_text(item, "name"),
                        "row_type": _safe_text(item, "row_type", "LAYER"),
                        "view_layer": _safe_text(item, "view_layer_name"),
                        "socket": _safe_text(item, "output_socket_name"),
                        "exposed": _safe_bool(item, "expose_output"),
                    }
                )
            except FBP_DATA_ERRORS:
                continue

    return {
        "schema": schema,
        "enabled": _safe_bool(scene, "fbp_compositor_enabled"),
        "tree": _safe_text(tree, "name"),
        "tree_owned": _safe_id_bool(tree, FBP_COMPOSITOR_TREE_TAG),
        "tree_schema": _safe_int(tree, FBP_COMPOSITOR_LAYER_NODE_SCHEMA_KEY),
        "tree_generation": _safe_int(tree, FBP_COMPOSITOR_LAYER_NODE_GENERATION_KEY),
        "layers_node_count": len(layers_nodes),
        "source_tree": _safe_text(source_tree, "name"),
        "source_tree_owned": _safe_id_bool(source_tree, FBP_COMPOSITOR_SOURCE_TREE_TAG),
        "source_schema": _safe_int(source_tree, FBP_COMPOSITOR_LAYER_NODE_SCHEMA_KEY),
        "source_generation": _safe_int(source_tree, FBP_COMPOSITOR_LAYER_NODE_GENERATION_KEY),
        "outputs": outputs,
        "layers": layer_rows,
    }


def audit_compositor_layer_node(scene):
    """Validate the layer node and fail closed when Blender data changes mid-draw."""
    try:
        return _audit_compositor_layer_node(scene)
    except FBP_DATA_ERRORS as exc:
        snapshot = compositor_layer_node_snapshot(scene)
        return {
            "schema": FBP_COMPOSITOR_LAYER_NODE_SCHEMA_VERSION,
            "status": "FAIL",
            "issues": [f"Audit stopped safely: {type(exc).__name__}"],
            "warnings": [],
            "snapshot": snapshot,
            "metrics": {
                "layers": len(snapshot.get("layers", ())),
                "outputs": len(snapshot.get("outputs", ())),
                "dynamic_outputs": max(0, len(snapshot.get("outputs", ())) - 2),
                "artist_links": 0,
                "generation": int(snapshot.get("schema", {}).get("generation", 0) or 0),
            },
        }


def _audit_compositor_layer_node(scene):
    """Validate dynamic outputs, mandatory sockets and root synchronization."""
    snapshot = compositor_layer_node_snapshot(scene)
    issues = []
    warnings = []
    schema = snapshot["schema"]
    if schema["unsupported_future"]:
        issues.append(
            f"Stored schema v{schema['stored']} is newer than supported "
            f"v{schema['current']}"
        )
    if not snapshot["enabled"]:
        issues.append("Compositor Layer Node is not built for this Scene")
    if not snapshot["tree_owned"]:
        issues.append("The active compositor is not the Scene-owned FBP tree")
    if snapshot["layers_node_count"] != 1:
        issues.append(
            "Expected exactly one FBP Layers node, found "
            f"{snapshot['layers_node_count']}"
        )
    if not snapshot["source_tree_owned"]:
        issues.append("FBP Layers does not reference its owned source group")

    expected_schema = FBP_COMPOSITOR_LAYER_NODE_SCHEMA_VERSION
    for label, value in (
        ("Scene", schema["stored"]),
        ("root tree", snapshot["tree_schema"]),
        ("source tree", snapshot["source_schema"]),
    ):
        if int(value or 0) != expected_schema:
            issues.append(
                f"{label} schema is v{int(value or 0)}; expected "
                f"v{expected_schema}"
            )
    generation = int(schema["generation"] or 0)
    if generation < 1:
        issues.append("Synchronization generation is missing")
    if (
        snapshot["tree_generation"] != generation
        or snapshot["source_generation"] != generation
    ):
        issues.append("Scene, root tree and source tree generations differ")

    outputs = snapshot["outputs"]
    output_names = [item["name"] for item in outputs]
    output_identifiers = [item["identifier"] for item in outputs]
    if output_names[:2] != ["TOT", "MASK"]:
        issues.append("Mandatory outputs are not ordered as TOT, MASK")
    if len(output_names) != len(set(output_names)):
        issues.append("Layer output names are not unique")
    if len(output_identifiers) != len(set(output_identifiers)):
        issues.append("Layer output identifiers are not unique")
    by_name = {item["name"]: item for item in outputs}
    total = by_name.get("TOT")
    mask = by_name.get("MASK")
    if total is None:
        issues.append("TOT output is missing")
    elif total["type"] != "RGBA":
        issues.append(f"TOT uses {total['type'] or '<unknown>'}, expected RGBA")
    if mask is None:
        issues.append("MASK output is missing")
    elif mask["type"] != "VALUE":
        issues.append(
            f"MASK uses {mask['type'] or '<unknown>'}, expected VALUE"
        )
    if total is not None and total["hidden"]:
        issues.append("TOT output is hidden")
    if mask is not None and mask["hidden"]:
        issues.append("MASK output is hidden")

    layer_ids = [item["id"] for item in snapshot["layers"]]
    sockets = [item["socket"] for item in snapshot["layers"]]
    if any(not value for value in layer_ids):
        issues.append("At least one compositor layer has no persistent ID")
    if len(layer_ids) != len(set(layer_ids)):
        issues.append("Compositor layer persistent IDs are not unique")
    if any(not value for value in sockets):
        issues.append("At least one compositor layer has no dynamic output")
    if len(sockets) != len(set(sockets)):
        issues.append("Dynamic layer output names are not unique")
    expected_order = ["TOT", "MASK", *sockets]
    if output_names != expected_order:
        issues.append("Dynamic outputs do not follow the Scene layer order")
    for row in snapshot["layers"]:
        socket = by_name.get(row["socket"])
        if socket is None:
            issues.append(
                f"Dynamic output is missing for {row['name'] or row['id']}"
            )
            continue
        if row["exposed"] and socket["hidden"]:
            issues.append(
                f"Exposed output is hidden for {row['name'] or row['id']}"
            )
        if (
            not row["exposed"]
            and not socket["artist_links"]
            and not socket["hidden"]
        ):
            warnings.append(
                f"Unrequested output remains visible: "
                f"{row['name'] or row['id']}"
            )

    tree = getattr(scene, "compositing_node_group", None) if scene else None
    layers_node = (
        _role_nodes(tree, "layers_package")[0]
        if snapshot["layers_node_count"] == 1
        else None
    )
    effects_nodes = _role_nodes(tree, "effects_stage")
    if layers_node is not None:
        if len(effects_nodes) != 1:
            issues.append(
                "Expected exactly one Effects / Masks stage, found "
                f"{len(effects_nodes)}"
            )
        else:
            effects = effects_nodes[0]
            for output_name, input_name in (
                ("TOT", "Image"),
                ("MASK", "Mask"),
            ):
                output_socket = layers_node.outputs.get(output_name)
                input_socket = effects.inputs.get(input_name)
                if (
                    output_socket is None
                    or input_socket is None
                    or not input_socket.is_linked
                    or input_socket.links[0].from_socket != output_socket
                ):
                    issues.append(
                        f"{output_name} is not synchronized to "
                        f"Effects / Masks {input_name}"
                    )

        for row in snapshot["layers"]:
            if row["row_type"] == "FOLDER":
                continue
            view_layer = (
                scene.view_layers.get(row["view_layer"])
                if scene is not None and row["view_layer"]
                else None
            )
            if view_layer is None:
                issues.append(
                    f"Generated View Layer is missing for "
                    f"{row['name'] or row['id']}"
                )
            elif (
                str(view_layer.get(FBP_COMPOSITOR_LAYER_TAG, "") or "")
                != row["id"]
            ):
                issues.append(
                    f"View Layer identity does not match "
                    f"{row['name'] or row['id']}"
                )

    return {
        "schema": FBP_COMPOSITOR_LAYER_NODE_SCHEMA_VERSION,
        "status": "PASS" if not issues else "FAIL",
        "issues": issues,
        "warnings": warnings,
        "snapshot": snapshot,
        "metrics": {
            "layers": len(snapshot["layers"]),
            "outputs": len(snapshot["outputs"]),
            "dynamic_outputs": max(0, len(snapshot["outputs"]) - 2),
            "artist_links": sum(
                len(item["artist_links"]) for item in snapshot["outputs"]
            ),
            "generation": generation,
        },
    }


def compositor_layer_node_report_lines(scene, audit):
    metrics = audit["metrics"]
    lines = [
        "Frame By Plane — Compositor Layer Node Health",
        "================================================",
        f"Generated: {_utc_now()}",
        f"Scene: {getattr(scene, 'name', '<none>')}",
        f"Schema: {audit['schema']}",
        f"Generation: {metrics['generation']}",
        f"Layers: {metrics['layers']}",
        f"Outputs: {metrics['outputs']}",
        f"Dynamic outputs: {metrics['dynamic_outputs']}",
        f"Artist links: {metrics['artist_links']}",
        "",
        "Issues",
        "------",
    ]
    lines.extend(f"- {message}" for message in audit["issues"])
    if not audit["issues"]:
        lines.append("- None")
    lines.extend(("", "Warnings", "--------"))
    lines.extend(f"- {message}" for message in audit["warnings"])
    if not audit["warnings"]:
        lines.append("- None")
    lines.extend(
        (
            "",
            "Result",
            "------",
            "PASS" if audit["status"] == "PASS" else "REVIEW REQUIRED",
        )
    )
    return lines


def write_compositor_layer_node_report(scene, audit):
    return write_diagnostic_report(
        scene,
        COMPOSITOR_LAYER_NODE_REPORT_NAME,
        compositor_layer_node_report_lines(scene, audit),
        summary=(
            f"Compositor Layer Node · "
            f"{len(audit['issues'])} issue(s) · "
            f"{len(audit['warnings'])} warning(s)"
        ),
        status=(
            "PASS"
            if audit["status"] == "PASS" and not audit["warnings"]
            else "WARNING"
            if audit["status"] == "PASS"
            else "ERROR"
        ),
    )


def sync_compositor_layer_node(
    scene,
    *,
    context=None,
    native_group=False,
):
    """Synchronize the current layer node, then audit the result."""
    result = fbp_sync_compositor(
        scene,
        context=context,
        native_group=native_group,
    )
    audit = audit_compositor_layer_node(scene)
    return {
        **result,
        "audit": audit,
        "status": audit["status"],
    }


class _FBP_CompositorLayerNodePoll:
    @classmethod
    def poll(cls, context):
        scene = getattr(context, "scene", None)
        return bool(
            scene is not None
            and fbp_feature_enabled(scene, "compositor_layers")
        )


class FBP_OT_SyncCompositorLayerNodePrototype(
    _FBP_CompositorLayerNodePoll,
    Operator,
):
    bl_idname = "fbp.sync_compositor_layer_node_prototype"
    bl_label = "Sync Layer Node"
    bl_description = "Synchronize the versioned dynamic Layers node, mandatory TOT/MASK outputs and generated View Layers"
    bl_options = {"REGISTER", "UNDO"}

    native_group: BoolProperty(
        name=f"Use Native {primary_shortcut_label('G')}",
        description="Finalize FBP Layers through Blender's native group operator",
        default=True,
        options={"HIDDEN"},
    )

    def execute(self, context):
        try:
            result = sync_compositor_layer_node(
                context.scene,
                context=context,
                native_group=bool(self.native_group),
            )
        except (
            AttributeError,
            ReferenceError,
            RuntimeError,
            TypeError,
            ValueError,
        ) as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        audit = result["audit"]
        write_compositor_layer_node_report(context.scene, audit)
        if audit["status"] != "PASS":
            self.report({"ERROR"}, "; ".join(audit["issues"]))
            return {"CANCELLED"}
        self.report(
            {"INFO"},
            f"Layer Node v{audit['schema']} · "
            f"{audit['metrics']['dynamic_outputs']} dynamic output(s)",
        )
        return {"FINISHED"}


class FBP_OT_AuditCompositorLayerNodePrototype(
    _FBP_CompositorLayerNodePoll,
    Operator,
):
    bl_idname = "fbp.audit_compositor_layer_node_prototype"
    bl_label = "Audit Layer Node"
    bl_description = "Inspect schema, dynamic outputs, TOT/MASK and View Layer synchronization without rebuilding"
    bl_options = {"INTERNAL"}

    def execute(self, context):
        audit = audit_compositor_layer_node(context.scene)
        write_compositor_layer_node_report(context.scene, audit)
        if audit["status"] != "PASS":
            self.report({"WARNING"}, "; ".join(audit["issues"]))
        else:
            self.report(
                {"INFO"},
                f"Layer Node audit passed · "
                f"{audit['metrics']['dynamic_outputs']} dynamic output(s)",
            )
        return {"FINISHED"}




def _compositor_layer_node_header_status(scene):
    """Return a lightweight header status without traversing node sockets."""
    if scene is None:
        return False
    try:
        schema = fbp_compositor_layer_node_schema_status(scene)
        tree = getattr(scene, "compositing_node_group", None)
        return bool(
            getattr(scene, "fbp_compositor_enabled", False)
            and tree is not None
            and not schema["outdated"]
            and not schema["unsupported_future"]
            and int(schema["generation"] or 0) > 0
        )
    except FBP_DATA_ERRORS:
        return False

class FBP_PT_CompositorLayerNodePrototype(Panel):
    bl_label = "Layer Node Status"
    bl_description = "Versioned dynamic compositor layer outputs with mandatory TOT and MASK"
    bl_idname = "FBP_PT_compositor_layer_node_prototype"
    bl_space_type = "PROPERTIES"
    bl_region_type = "WINDOW"
    bl_context = "view_layer"
    bl_parent_id = "VIEWLAYER_PT_context_layer"
    bl_options = {"DEFAULT_CLOSED"}
    bl_order = 1

    @classmethod
    def poll(cls, context):
        return _FBP_CompositorLayerNodePoll.poll(context)

    def draw_header(self, context):
        self.layout.label(
            text="",
            icon=(
                "CHECKMARK"
                if _compositor_layer_node_header_status(context.scene)
                else "NODETREE"
            ),
        )

    def draw(self, context):
        layout = configure_layout(self.layout)
        scene = context.scene
        audit = audit_compositor_layer_node(scene)
        schema = audit["snapshot"]["schema"]
        section_header(layout, "Layers Node", icon="NODETREE")
        summary = layout.row(align=False)
        summary.label(
            text=f"{audit['metrics']['dynamic_outputs']} layer outputs",
            icon="OUTPUT",
        )
        summary.label(
            text="Up to date" if audit["status"] == "PASS" else "Needs sync",
            icon="CHECKMARK" if audit["status"] == "PASS" else "FILE_REFRESH",
        )
        if schema["unsupported_future"]:
            hint_row(
                layout,
                f"Future schema v{schema['stored']}: use the matching add-on",
                icon="ERROR",
                disabled=False,
            )
        elif audit["status"] == "PASS":
            hint_row(
                layout,
                "Outputs and View Layers are synchronized",
                icon="CHECKMARK",
                disabled=False,
            )
        else:
            hint_row(
                layout,
                audit["issues"][0] if audit["issues"] else "Not built",
                icon="INFO",
                disabled=False,
            )
        actions = layout.row(align=True)
        sync = actions.operator(
            "fbp.sync_compositor_layer_node_prototype",
            text="Sync",
            icon="FILE_REFRESH",
        )
        sync.native_group = True
        actions.operator(
            "fbp.audit_compositor_layer_node_prototype",
            text="Check",
            icon="VIEWZOOM",
        )


_MODEL_CLASSES = (
    FBP_OT_SyncCompositorLayerNodePrototype,
    FBP_OT_AuditCompositorLayerNodePrototype,
)
_INTERACTIVE_CLASSES = (FBP_PT_CompositorLayerNodePrototype,)
_registered_classes = globals().get("_registered_classes", [])
if not isinstance(_registered_classes, list):
    _registered_classes = []


def register():
    _registered_classes.clear()
    try:
        _registered_classes.extend(register_classes(_MODEL_CLASSES))
        _registered_classes.extend(
            register_interactive_classes(_INTERACTIVE_CLASSES)
        )
    except Exception:
        unregister_classes(tuple(_registered_classes))
        _registered_classes.clear()
        raise


def unregister():
    unregister_classes(tuple(_registered_classes))
    _registered_classes.clear()


__all__ = [
    "COMPOSITOR_LAYER_NODE_REPORT_NAME",
    "audit_compositor_layer_node",
    "compositor_layer_node_report_lines",
    "compositor_layer_node_snapshot",
    "sync_compositor_layer_node",
    "write_compositor_layer_node_report",
]
