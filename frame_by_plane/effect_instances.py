"""Persistent Effect Data Model v2 for Frame By Plane.

This module is deliberately Blender-light. It owns the serialized stack schema,
normalization, validation and reconciliation rules while Blender-specific owner
discovery remains in :mod:`geometry_nodes`.

The registry defaults to ``SINGLE`` while an explicitly declared set uses
concrete ``MULTI`` shader instances. Each node or modifier owns its identity,
and the serialized stack stores only current 7.1 contracts.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Callable, Iterable, Mapping


FBP_EFFECT_DATA_MODEL_VERSION = 2
FBP_EFFECT_STACK_KEY = "fbp_effect_stack_v2"
FBP_EFFECT_STACK_VERSION_KEY = "fbp_effect_stack_v2_version"
FBP_EFFECT_STACK_MAX_INSTANCES = 512
FBP_EFFECT_STACK_MAX_JSON_BYTES = 512 * 1024

_ALLOWED_KINDS = {"BASE", "SHADER", "GEOMETRY"}
_ALLOWED_POLICIES = {"SINGLE", "MULTI"}


def _text(value: Any) -> str:
    return str(value or "").strip()


def effect_instance_token(effect_id: str, instance_id: str) -> str:
    """Return an unambiguous UI/runtime token for one concrete instance."""
    effect_id = _text(effect_id)
    instance_id = _text(instance_id)
    if not effect_id:
        return ""
    return f"{effect_id}::{instance_id}" if instance_id else effect_id


def split_effect_instance_token(token: str) -> tuple[str, str]:
    """Split a v2 token; SINGLE effects intentionally omit an instance id."""
    token = _text(token)
    if "::" not in token:
        return token, ""
    effect_id, instance_id = token.split("::", 1)
    return _text(effect_id), _text(instance_id)


def normalize_effect_instance_record(
    record: Mapping[str, Any] | None,
    *,
    index: int = 0,
    definition: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Return one deterministic, JSON-safe effect instance record."""
    source = dict(record or {})
    definition = dict(definition or {})
    effect_id = _text(source.get("effect_id"))
    kind = _text(source.get("kind") or definition.get("kind")).upper()
    if kind not in _ALLOWED_KINDS:
        kind = ""
    policy = _text(
        source.get("instance_policy") or definition.get("instance_policy") or "SINGLE"
    ).upper()
    if policy not in _ALLOWED_POLICIES:
        policy = "SINGLE"
    settings = source.get("settings", {})
    if not isinstance(settings, Mapping):
        settings = {}
    # Keep only primitive JSON-safe values. Blender pointers and RNA values must
    # never become persistent references in the data model.
    normalized_settings: dict[str, Any] = {}
    for key, value in sorted(settings.items(), key=lambda item: str(item[0])):
        key_text = _text(key)
        if not key_text:
            continue
        if value is None or isinstance(value, (bool, int, float, str)):
            normalized_settings[key_text] = value
        elif isinstance(value, (list, tuple)) and all(
            item is None or isinstance(item, (bool, int, float, str)) for item in value
        ):
            normalized_settings[key_text] = list(value)

    return {
        "schema": FBP_EFFECT_DATA_MODEL_VERSION,
        "instance_id": _text(source.get("instance_id")),
        "effect_id": effect_id,
        "kind": kind,
        "instance_policy": policy,
        "order": max(0, int(source.get("order", index) or 0)),
        "group_id": _text(source.get("group_id")),
        "label": _text(source.get("label")),
        "settings": normalized_settings,
    }


def normalize_effect_stack_payload(
    payload: Mapping[str, Any] | None,
    *,
    definitions: Callable[[str], Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Normalize a complete stack and drop unsafe or duplicate records."""
    source = dict(payload or {})
    raw_instances = source.get("instances", ())
    if not isinstance(raw_instances, (list, tuple)):
        raw_instances = ()

    candidates: list[tuple[int, dict[str, Any]]] = []
    for index, raw in enumerate(raw_instances[:FBP_EFFECT_STACK_MAX_INSTANCES]):
        if not isinstance(raw, Mapping):
            continue
        effect_id = _text(raw.get("effect_id"))
        definition = definitions(effect_id) if definitions and effect_id else {}
        record = normalize_effect_instance_record(raw, index=index, definition=definition)
        if not record["effect_id"] or not record["instance_id"] or not record["kind"]:
            continue
        candidates.append((index, record))

    # Sort before enforcing SINGLE so the record with the earliest explicit
    # stack order wins, independently from JSON insertion order.
    candidates.sort(
        key=lambda item: (
            int(item[1]["order"]),
            item[0],
            item[1]["effect_id"],
            item[1]["instance_id"],
        )
    )
    result: list[dict[str, Any]] = []
    seen_instances: set[str] = set()
    seen_single_effects: set[str] = set()
    for _source_index, record in candidates:
        effect_id = record["effect_id"]
        instance_id = record["instance_id"]
        if instance_id in seen_instances:
            continue
        if record["instance_policy"] == "SINGLE" and effect_id in seen_single_effects:
            continue
        seen_instances.add(instance_id)
        if record["instance_policy"] == "SINGLE":
            seen_single_effects.add(effect_id)
        result.append(record)

    for order, record in enumerate(result):
        record["order"] = order
    return {
        "schema": FBP_EFFECT_DATA_MODEL_VERSION,
        "owner_id": _text(source.get("owner_id")),
        "instances": result,
    }


def _decode_effect_stack_source(
    raw: str | bytes | Mapping[str, Any] | None,
) -> tuple[Mapping[str, Any] | None, str]:
    """Return the unnormalized source payload and a deterministic error."""
    if isinstance(raw, Mapping):
        return dict(raw), ""
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8", errors="replace")
    raw_text = _text(raw)
    if not raw_text:
        return {}, ""
    if len(raw_text.encode("utf-8")) > FBP_EFFECT_STACK_MAX_JSON_BYTES:
        return None, "Effect stack v2 exceeds the safe serialized size"
    try:
        payload = json.loads(raw_text)
    except (json.JSONDecodeError, TypeError, ValueError):
        return None, "Effect stack v2 is not valid JSON"
    if not isinstance(payload, Mapping):
        return None, "Effect stack v2 root must be an object"
    return payload, ""


def encode_effect_stack(payload: Mapping[str, Any] | None) -> str:
    """Encode a canonical stack using stable separators and key ordering."""
    normalized = normalize_effect_stack_payload(payload)
    encoded = json.dumps(
        normalized,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    if len(encoded.encode("utf-8")) > FBP_EFFECT_STACK_MAX_JSON_BYTES:
        raise ValueError("Effect stack v2 exceeds the safe serialized size")
    return encoded


def decode_effect_stack(
    raw: str | bytes | Mapping[str, Any] | None,
    *,
    definitions: Callable[[str], Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Decode v2 data; malformed values become an empty stack."""
    payload, _error = _decode_effect_stack_source(raw)
    if payload is None:
        return normalize_effect_stack_payload({}, definitions=definitions)
    return normalize_effect_stack_payload(payload, definitions=definitions)


def effect_stack_digest(payload: Mapping[str, Any] | str | bytes | None) -> str:
    """Return a compact deterministic digest suitable for cache signatures."""
    encoded = payload if isinstance(payload, str) else encode_effect_stack(payload)
    if isinstance(encoded, bytes):
        encoded = encoded.decode("utf-8", errors="replace")
    return hashlib.sha256(str(encoded).encode("utf-8")).hexdigest()[:20]


def reconcile_effect_stack(
    stored: Mapping[str, Any] | str | bytes | None,
    discovered: Iterable[Mapping[str, Any]],
    *,
    owner_id: str = "",
    definitions: Callable[[str], Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Merge runtime owners into the persistent mixed Effect Stack order.

    Concrete Blender owners remain authoritative for presence, kind and policy.
    The v2 payload is authoritative for the cross-backend order because shader
    nodes and Geometry Nodes modifiers cannot encode their relative positions
    in either native collection alone.
    """
    stored_payload = decode_effect_stack(stored, definitions=definitions)
    stored_by_instance = {
        item["instance_id"]: item for item in stored_payload["instances"]
    }
    discovered_records = [
        dict(raw)
        for raw in tuple(discovered)[:FBP_EFFECT_STACK_MAX_INSTANCES]
        if isinstance(raw, Mapping) and _text(raw.get("instance_id"))
    ]
    discovered_by_instance = {
        _text(raw.get("instance_id")): raw for raw in discovered_records
    }
    ordered_discovered = []
    seen = set()
    for previous in stored_payload["instances"]:
        instance_id = _text(previous.get("instance_id"))
        raw = discovered_by_instance.get(instance_id)
        if raw is not None and instance_id not in seen:
            ordered_discovered.append(raw)
            seen.add(instance_id)
    for raw in discovered_records:
        instance_id = _text(raw.get("instance_id"))
        if instance_id not in seen:
            ordered_discovered.append(raw)
            seen.add(instance_id)

    merged = []
    for index, raw in enumerate(ordered_discovered):
        instance_id = _text(raw.get("instance_id"))
        previous = stored_by_instance.get(instance_id, {})
        combined = dict(previous)
        combined.update(dict(raw))
        # Group ownership is concrete runtime metadata and an empty value can
        # represent an intentional Ungroup action. Only user labels and future
        # per-instance settings survive when runtime discovery omits them.
        if not _text(raw.get("label")) and _text(previous.get("label")):
            combined["label"] = previous["label"]
        runtime_settings = dict(raw.get("settings", {}) or {})
        combined["settings"] = (
            runtime_settings
            if runtime_settings
            else dict(previous.get("settings", {}) or {})
        )
        combined["order"] = index
        effect_id = _text(combined.get("effect_id"))
        definition = definitions(effect_id) if definitions and effect_id else {}
        merged.append(
            normalize_effect_instance_record(
                combined,
                index=index,
                definition=definition,
            )
        )
    return normalize_effect_stack_payload(
        {
            "schema": FBP_EFFECT_DATA_MODEL_VERSION,
            "owner_id": owner_id or stored_payload.get("owner_id", ""),
            "instances": merged,
        },
        definitions=definitions,
    )


def validate_effect_stack(
    payload: Mapping[str, Any] | str | bytes | None,
    *,
    definitions: Callable[[str], Mapping[str, Any]] | None = None,
) -> tuple[str, ...]:
    """Return deterministic structural issues without mutating the input."""
    source, source_error = _decode_effect_stack_source(payload)
    issues: list[str] = []
    if source_error:
        return (source_error,)
    source = dict(source or {})
    if source and int(source.get("schema", 0) or 0) != FBP_EFFECT_DATA_MODEL_VERSION:
        issues.append(
            f"Effect stack schema {int(source.get('schema', 0) or 0)} does not match "
            f"{FBP_EFFECT_DATA_MODEL_VERSION}"
        )
    raw_instances = source.get("instances", ())
    if not isinstance(raw_instances, (list, tuple)):
        issues.append("Effect stack v2 instances must be an array")
        raw_instances = ()
    if len(raw_instances) > FBP_EFFECT_STACK_MAX_INSTANCES:
        issues.append(
            f"Effect stack v2 exceeds {FBP_EFFECT_STACK_MAX_INSTANCES} instances"
        )
    raw_seen_instances: set[str] = set()
    raw_single_effects: set[str] = set()
    for index, raw_record in enumerate(raw_instances[:FBP_EFFECT_STACK_MAX_INSTANCES]):
        if not isinstance(raw_record, Mapping):
            issues.append(f"Effect stack row {index + 1} must be an object")
            continue
        effect_id = _text(raw_record.get("effect_id"))
        definition = definitions(effect_id) if definitions and effect_id else {}
        record = normalize_effect_instance_record(
            raw_record, index=index, definition=definition
        )
        instance_id = record["instance_id"]
        if instance_id and instance_id in raw_seen_instances:
            issues.append(f"Duplicate effect instance id {instance_id}")
        if instance_id:
            raw_seen_instances.add(instance_id)
        if record["instance_policy"] == "SINGLE" and effect_id:
            if effect_id in raw_single_effects:
                issues.append(f"{effect_id}: multiple instances violate SINGLE policy")
            raw_single_effects.add(effect_id)

    normalized = decode_effect_stack(source, definitions=definitions)
    owner_id = _text(normalized.get("owner_id"))
    if normalized.get("instances") and not owner_id:
        issues.append("Effect stack v2 has no owner id")
    seen: set[str] = set()
    single_effects: set[str] = set()
    for index, record in enumerate(normalized.get("instances", ())):
        instance_id = _text(record.get("instance_id"))
        effect_id = _text(record.get("effect_id"))
        kind = _text(record.get("kind")).upper()
        policy = _text(record.get("instance_policy")).upper()
        if not instance_id:
            issues.append(f"Effect stack row {index + 1} has no instance id")
        elif instance_id in seen:
            issues.append(f"Duplicate effect instance id {instance_id}")
        seen.add(instance_id)
        if not effect_id:
            issues.append(f"Effect stack row {index + 1} has no effect id")
        if kind not in _ALLOWED_KINDS:
            issues.append(f"{effect_id or '<unknown>'}: unsupported effect kind {kind!r}")
        if policy not in _ALLOWED_POLICIES:
            issues.append(f"{effect_id or '<unknown>'}: unsupported instance policy {policy!r}")
        if policy == "SINGLE" and effect_id:
            if effect_id in single_effects:
                issues.append(f"{effect_id}: multiple instances violate SINGLE policy")
            single_effects.add(effect_id)
        if int(record.get("order", -1)) != index:
            issues.append(f"{effect_id or '<unknown>'}: non-canonical stack order")
        if definitions and effect_id:
            definition = dict(definitions(effect_id) or {})
            if not definition:
                issues.append(f"{effect_id}: missing registry definition")
            else:
                expected_kind = _text(definition.get("kind")).upper()
                if expected_kind and expected_kind != kind:
                    issues.append(
                        f"{effect_id}: stored kind {kind} does not match registry {expected_kind}"
                    )
                expected_policy = _text(definition.get("instance_policy") or "SINGLE").upper()
                if expected_policy != policy:
                    issues.append(
                        f"{effect_id}: stored policy {policy} does not match registry {expected_policy}"
                    )
    return tuple(dict.fromkeys(issues))


def register():
    return None


def unregister():
    return None
