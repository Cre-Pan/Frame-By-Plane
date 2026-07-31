"""Atomic mutation helpers and persistent recovery journals.

The module is Blender-light by design. Transactions are synchronous, keep only
Python callables in process memory, and persist a compact primitive journal on
an optional Blender ID owner. A normal commit removes the journal; an interrupted
or partially rolled-back operation remains visible to Project Health.
"""

from __future__ import annotations

from dataclasses import dataclass
import importlib
import json
import time
import uuid

from .runtime import FBP_DATA_IO_ERRORS, fbp_error, fbp_warn

TRANSACTION_SCHEMA_VERSION = 1
TRANSACTION_JOURNAL_KEY = "fbp_transaction_journal"
TRANSACTION_CONTEXT_MAX_BYTES = 8192


class TransactionError(RuntimeError):
    """Base error raised by the transaction coordinator."""


class TransactionCommitError(TransactionError):
    """Raised when a deferred commit action fails."""


@dataclass(slots=True)
class _Action:
    callback: object
    args: tuple
    kwargs: dict
    label: str


_PREVIOUS_ACTIVE_TRANSACTIONS = globals().get("_ACTIVE", {})


def _retire_previous_transactions_early():
    """Rollback records owned by the former module generation on reload."""
    previous = _PREVIOUS_ACTIVE_TRANSACTIONS
    if not isinstance(previous, dict):
        return {"retired": 0, "failures": 0}
    retired = 0
    failures = 0
    for transaction in tuple(previous.values()):
        try:
            transaction.rollback(reason="add-on module reload")
            retired += 1
        except Exception as exc:
            failures += 1
            try:
                fbp_error(
                    "Could not retire a transaction from the previous module generation",
                    exc,
                    event="transaction.reload_teardown",
                )
            except Exception:
                pass
    previous.clear()
    return {"retired": retired, "failures": failures}


_PREVIOUS_TRANSACTIONS_RETIRED = _retire_previous_transactions_early()
_ACTIVE = {}
_FAILPOINTS = {}
_METRICS = {
    "started": 0,
    "committed": 0,
    "rolled_back": 0,
    "rollback_failed": 0,
    "recovered": 0,
    "recovery_failed": 0,
    "failpoints_triggered": 0,
    "active_peak": 0,
    "max_rollback_actions": 0,
    "last_label": "",
    "last_kind": "",
    "last_duration_ms": 0.0,
    "max_duration_ms": 0.0,
}


def _primitive(value, *, depth=0):
    if depth > 4:
        return repr(value)[:256]
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, dict):
        return {
            str(key)[:128]: _primitive(item, depth=depth + 1)
            for key, item in list(value.items())[:64]
        }
    if isinstance(value, (tuple, list, set, frozenset)):
        return [_primitive(item, depth=depth + 1) for item in list(value)[:128]]
    name = getattr(value, "name_full", getattr(value, "name", ""))
    return str(name or repr(value))[:256]


def _bounded_context(context):
    value = _primitive(dict(context or {}))
    try:
        encoded = json.dumps(value, sort_keys=True, separators=(",", ":"))
    except (TypeError, ValueError):
        return {}
    if len(encoded.encode("utf-8")) <= TRANSACTION_CONTEXT_MAX_BYTES:
        return value
    return {
        "truncated": True,
        "summary": encoded[:2048],
    }


def _read_owner_journal(owner):
    if owner is None:
        return None
    try:
        raw = owner.get(TRANSACTION_JOURNAL_KEY, "")
    except FBP_DATA_IO_ERRORS:
        return None
    if not raw:
        return None
    if isinstance(raw, dict):
        data = dict(raw)
    else:
        try:
            data = json.loads(str(raw))
        except (TypeError, ValueError, json.JSONDecodeError):
            return {
                "schema": 0,
                "state": "CORRUPT",
                "label": "Unknown transaction",
                "kind": "UNKNOWN",
                "raw": str(raw)[:512],
            }
    return data if isinstance(data, dict) else None


def transaction_journal(owner):
    """Return one sanitized persistent journal, or ``None``."""
    journal = _read_owner_journal(owner)
    return _primitive(journal) if journal else None


def clear_transaction_journal(owner):
    if owner is None:
        return False
    try:
        if TRANSACTION_JOURNAL_KEY in owner:
            del owner[TRANSACTION_JOURNAL_KEY]
            return True
    except FBP_DATA_IO_ERRORS:
        return False
    return False


def _write_owner_journal(owner, payload):
    if owner is None:
        return False
    try:
        owner[TRANSACTION_JOURNAL_KEY] = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
        )
        return True
    except FBP_DATA_IO_ERRORS:
        return False


def _invoke(action):
    try:
        return True, action.callback(*action.args, **action.kwargs), None
    except Exception as exc:
        fbp_warn(
            f"Transaction callback failed: {action.label}",
            exc,
            event="transaction.callback",
        )
        return False, None, exc


class FBPTransaction:
    """One synchronous atomic operation with reverse-order rollback."""

    def __init__(
        self,
        label,
        *,
        kind="GENERAL",
        journal_owner=None,
        context=None,
    ):
        self.id = uuid.uuid4().hex
        self.label = str(label or "Frame By Plane transaction")
        self.kind = str(kind or "GENERAL").upper()
        self.journal_owner = journal_owner
        self.context = _bounded_context(context)
        self.stage = "BEGIN"
        self.progress = 0.0
        self.state = "OPEN"
        self.started = time.perf_counter()
        self.started_wall = time.time()
        self._rollback_actions = []
        self._commit_actions = []
        self._rollback_failures = []
        _ACTIVE[self.id] = self
        _METRICS["started"] += 1
        _METRICS["active_peak"] = max(_METRICS["active_peak"], len(_ACTIVE))
        _METRICS["last_label"] = self.label
        _METRICS["last_kind"] = self.kind
        self._persist()

    @property
    def is_open(self):
        return self.state == "OPEN"

    def _payload(self):
        payload = {
            "schema": TRANSACTION_SCHEMA_VERSION,
            "id": self.id,
            "label": self.label,
            "kind": self.kind,
            "state": self.state,
            "stage": self.stage,
            "progress": round(self.progress, 6),
            "started_at": round(self.started_wall, 6),
            "context": self.context,
            "rollback_actions": len(self._rollback_actions),
        }
        if self._rollback_failures:
            payload["rollback_failures"] = tuple(self._rollback_failures[:16])
        return payload

    def _persist(self):
        _write_owner_journal(self.journal_owner, self._payload())

    def checkpoint(self, stage, *, progress=None, **context):
        if not self.is_open:
            return False
        self.stage = str(stage or "WORK")[:128]
        if progress is not None:
            self.progress = max(0.0, min(1.0, float(progress)))
        if context:
            merged = dict(self.context)
            merged.update(context)
            self.context = _bounded_context(merged)
        self._persist()
        if _consume_failpoint(self.kind, self.stage):
            _METRICS["failpoints_triggered"] += 1
            raise TransactionError(
                f"Injected transaction failpoint: {self.kind}:{self.stage}"
            )
        return True

    def cancel(self, reason="cancelled"):
        """Cancel an open operation and execute its reverse rollback."""
        return self.rollback(reason=str(reason or "cancelled"))

    def defer_rollback(self, callback, *args, label="", **kwargs):
        if not self.is_open or not callable(callback):
            return False
        self._rollback_actions.append(
            _Action(callback, tuple(args), dict(kwargs), str(label or getattr(callback, "__name__", "rollback")))
        )
        _METRICS["max_rollback_actions"] = max(
            _METRICS["max_rollback_actions"], len(self._rollback_actions)
        )
        self._persist()
        return True

    def defer_commit(self, callback, *args, label="", **kwargs):
        if not self.is_open or not callable(callback):
            return False
        self._commit_actions.append(
            _Action(callback, tuple(args), dict(kwargs), str(label or getattr(callback, "__name__", "commit")))
        )
        return True

    def _finish_metrics(self):
        elapsed_ms = max(0.0, (time.perf_counter() - self.started) * 1000.0)
        _METRICS["last_duration_ms"] = elapsed_ms
        _METRICS["max_duration_ms"] = max(_METRICS["max_duration_ms"], elapsed_ms)
        _ACTIVE.pop(self.id, None)

    def rollback(self, *, reason=""):
        if self.state in {"ROLLED_BACK", "COMMITTED"}:
            return self.state == "ROLLED_BACK"
        self.state = "ROLLING_BACK"
        self.stage = str(reason or self.stage or "ROLLBACK")[:128]
        self._persist()
        failures = []
        for action in reversed(self._rollback_actions):
            ok, _result, exc = _invoke(action)
            if ok:
                continue
            failures.append(f"{action.label}: {type(exc).__name__}: {exc}")
            fbp_error(
                f"Transaction rollback failed: {action.label}",
                exc,
                event="transaction.rollback_action",
                context={"transaction": self.label, "kind": self.kind},
            )
        self._rollback_failures = failures
        if failures:
            self.state = "ROLLBACK_FAILED"
            _METRICS["rollback_failed"] += 1
            self._persist()
        else:
            self.state = "ROLLED_BACK"
            _METRICS["rolled_back"] += 1
            clear_transaction_journal(self.journal_owner)
        self._finish_metrics()
        return not failures

    def commit(self):
        if not self.is_open:
            return self.state == "COMMITTED"
        self.stage = "COMMIT"
        self._persist()
        for action in self._commit_actions:
            ok, _result, exc = _invoke(action)
            if ok:
                continue
            self.rollback(reason=f"commit failed: {action.label}")
            raise TransactionCommitError(
                f"Commit action failed for {self.label}: {action.label}: {exc}"
            ) from exc
        self.state = "COMMITTED"
        _METRICS["committed"] += 1
        clear_transaction_journal(self.journal_owner)
        self._finish_metrics()
        return True

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, _traceback):
        if exc is not None:
            self.rollback(reason=f"{exc_type.__name__}: {exc}" if exc_type else str(exc))
            return False
        if self.is_open:
            self.rollback(reason="scope exited without commit")
        return False



def arm_transaction_failpoint(kind, stage, *, count=1):
    """Inject a deterministic development failure at a transaction checkpoint."""
    key = (str(kind or "*").upper(), str(stage or "*").upper())
    _FAILPOINTS[key] = max(1, int(count or 1))
    return key


def clear_transaction_failpoints():
    count = len(_FAILPOINTS)
    _FAILPOINTS.clear()
    return count


def _consume_failpoint(kind, stage):
    candidates = (
        (str(kind or "").upper(), str(stage or "").upper()),
        ("*", str(stage or "").upper()),
        (str(kind or "").upper(), "*"),
    )
    for key in candidates:
        remaining = int(_FAILPOINTS.get(key, 0) or 0)
        if remaining <= 0:
            continue
        if remaining == 1:
            _FAILPOINTS.pop(key, None)
        else:
            _FAILPOINTS[key] = remaining - 1
        return True
    return False

def transaction_scope(label, **kwargs):
    return FBPTransaction(label, **kwargs)


def transaction_metrics(*, reset=False):
    snapshot = dict(_METRICS)
    snapshot["active"] = len(_ACTIVE)
    snapshot["active_transactions"] = tuple(
        {
            "id": tx.id,
            "label": tx.label,
            "kind": tx.kind,
            "stage": tx.stage,
            "progress": tx.progress,
            "rollback_actions": len(tx._rollback_actions),
        }
        for tx in tuple(_ACTIVE.values())
    )
    if reset:
        for key, value in tuple(_METRICS.items()):
            _METRICS[key] = "" if isinstance(value, str) else 0.0 if isinstance(value, float) else 0
    return snapshot


def _recover_effect(owner, journal):
    geometry = importlib.import_module(f"{__package__}.geometry_nodes")
    context = dict(journal.get("context", {}) or {})
    effect_id = str(context.get("effect_id", "") or "")
    instance_id = str(context.get("instance_id", "") or "")
    kind = str(journal.get("kind", "") or "").upper()
    if effect_id and instance_id and kind == "EFFECT_DUPLICATE":
        geometry.fbp_remove_effect_instance(owner, effect_id, instance_id, sync_items=False)
    elif effect_id and instance_id and kind == "EFFECT_REMOVE":
        if not geometry.fbp_recover_effect_instance_removal(
            owner, effect_id, instance_id
        ):
            return False
    geometry.fbp_repair_effect_assets(owner)
    geometry.fbp_effect_instance_records_for_rig(owner, ensure=True, sync_storage=True)
    geometry.fbp_sync_effect_items(owner)
    return True



def _recover_effect_group(owner, journal):
    context = dict(journal.get("context", {}) or {})
    group_id = str(context.get("group_id", "") or "")
    group_name = str(context.get("group_name", "") or "")
    effect_refs = tuple(str(value or "") for value in context.get("effect_refs", ()) or ())
    rig_names = tuple(str(value or "") for value in context.get("rig_names", ()) or ())
    if not group_id or not effect_refs:
        return False
    bpy = importlib.import_module("bpy")
    geometry = importlib.import_module(f"{__package__}.geometry_nodes")
    rigs = []
    for name in rig_names:
        rig = bpy.data.objects.get(name) if name else None
        if rig is not None and rig not in rigs:
            rigs.append(rig)
    if owner is not None and owner not in rigs:
        rigs.insert(0, owner)
    if not rigs:
        return False
    for rig in rigs:
        for token in effect_refs:
            effect_id, instance_id = geometry._fbp_effect_ref_parts(token)
            if not geometry._fbp_effect_ref_is_active(rig, token):
                return False
            geometry.fbp_set_effect_group_id(
                rig,
                effect_id,
                group_id,
                instance_id=instance_id,
                group_name=group_name,
            )
        geometry.fbp_sync_effect_groups(rig)
        geometry.fbp_sync_effect_items(rig, rigs if rig is rigs[0] else [rig])
    return all(
        geometry.fbp_effect_group_id_for_rig(
            rig,
            *geometry._fbp_effect_ref_parts(token),
            normalize=False,
        ) == group_id
        for rig in rigs
        for token in effect_refs
    )

def _recover_sequence(owner, _journal):
    core = importlib.import_module(f"{__package__}.core")
    return bool(
        core.fbp_refresh_sequence_backend_from_rig(owner)
        or core.fbp_rebuild_sequence_backend_from_rig(owner)
    )


def _recover_mask(owner, journal):
    masks = importlib.import_module(f"{__package__}.object_masks")
    context = dict(journal.get("context", {}) or {})
    shape = str(context.get("shape", "") or "")
    if shape:
        masks.remove_object_mask_helper(owner, shape)
    result = masks.audit_object_masks((owner,), repair=True)
    return not tuple(result.get("issues", ()) or ())


def _recover_collection(owner, journal):
    context = dict(journal.get("context", {}) or {})
    scene_name = str(context.get("scene_name", "") or "")
    parent_tokens = tuple(context.get("original_parent_tokens", ()) or ())
    if not scene_name or not parent_tokens:
        return False
    bpy = importlib.import_module("bpy")
    scene = bpy.data.scenes.get(scene_name)
    if scene is None:
        return False
    layers = importlib.import_module(f"{__package__}.operator_layers")
    layers._fbp_restore_collection_parents(scene, owner, parent_tokens)
    root = getattr(scene, "collection", None)
    parents = layers._fbp_collection_parents(root, owner) if root is not None else []
    restored = tuple(
        "__SCENE_ROOT__" if parent == root else str(getattr(parent, "name", "") or "")
        for parent in parents
    ) or ("__SCENE_ROOT__",)
    return restored == parent_tokens



def _recover_layered_import(owner, journal):
    """Accept a completed staged setup; leave incomplete rows visible for repair."""
    context = dict(journal.get("context", {}) or {})
    source_path = str(context.get("source_path", "") or "")
    expected_rows = max(0, int(context.get("expected_rows", 0) or 0))
    rows = tuple(getattr(owner, "fbp_pending_planes", ()) or ())
    if len(rows) != expected_rows:
        return False
    if expected_rows and any(
        not bool(getattr(item, "source_from_layered", False))
        or str(getattr(item, "source_document", "") or "") != source_path
        for item in rows
    ):
        return False
    operator_import = importlib.import_module(f"{__package__}.operator_import")
    bpy = importlib.import_module("bpy")
    context = getattr(bpy, "context", None)
    if context is not None and getattr(context, "scene", None) == owner:
        operator_import._fbp_refresh_pending_tree(context)
    return True

def recover_transaction_journal(owner):
    """Repair one stale transaction journal and clear it only on success."""
    journal = _read_owner_journal(owner)
    if not journal:
        return True
    kind = str(journal.get("kind", "UNKNOWN") or "UNKNOWN").upper()
    if kind == "EFFECT_GROUP":
        callback = _recover_effect_group
    elif kind.startswith("EFFECT_"):
        callback = _recover_effect
    elif kind.startswith("SEQUENCE_") or kind == "MEDIA_RELINK":
        callback = _recover_sequence
    elif kind.startswith("MASK_"):
        callback = _recover_mask
    elif kind == "COLLECTION_RELINK":
        callback = _recover_collection
    elif kind == "LAYERED_IMPORT_PREPARE":
        callback = _recover_layered_import
    else:
        callback = None
    if callback is None:
        _METRICS["recovery_failed"] += 1
        return False
    action = _Action(callback, (owner, journal), {}, f"recover {kind}")
    ok, result, exc = _invoke(action)
    if ok and bool(result):
        clear_transaction_journal(owner)
        _METRICS["recovered"] += 1
        return True
    _METRICS["recovery_failed"] += 1
    if exc is not None:
        fbp_error(
            f"Could not recover stale {kind} transaction",
            exc,
            event="transaction.recovery",
            context={"kind": kind, "label": journal.get("label", "")},
        )
    else:
        fbp_warn(
            f"Could not recover stale {kind} transaction",
            event="transaction.recovery",
            context={"kind": kind, "label": journal.get("label", "")},
        )
    return False


def abort_active_transactions(*, reason="add-on teardown"):
    """Rollback every live transaction before RNA owners can be unregistered.

    Transactions are synchronous by design, but an operator failure or an
    interrupted development reload can leave one in the process-local registry.
    Retire those records while Blender classes and properties are still alive;
    never carry rollback callbacks or RNA owners into module teardown.
    """
    retired = 0
    failures = 0
    for transaction in tuple(_ACTIVE.values()):
        try:
            transaction.rollback(reason=str(reason or "add-on teardown"))
            retired += 1
        except Exception as exc:
            failures += 1
            _ACTIVE.pop(getattr(transaction, "id", ""), None)
            fbp_error(
                "Could not retire an active Frame By Plane transaction",
                exc,
                event="transaction.teardown",
                context={
                    "label": str(getattr(transaction, "label", "") or ""),
                    "kind": str(getattr(transaction, "kind", "") or ""),
                },
            )
    return {"retired": retired, "failures": failures, "remaining": len(_ACTIVE)}


def register():
    # Never inherit transaction objects and rollback closures from an in-place
    # module reload. Normal operation should already have committed them; a
    # surviving record is safer to roll back before accepting new work.
    abort_active_transactions(reason="add-on register/reload")
    try:
        from .service_registry import register_service
        register_service("transactions.metrics", transaction_metrics, owner=__name__)
        register_service("transactions.recover", recover_transaction_journal, owner=__name__)
    except (ImportError, AttributeError, RuntimeError, TypeError, ValueError):
        pass


def unregister():
    clear_transaction_failpoints()
    abort_active_transactions(reason="add-on unregister")
    try:
        from .service_registry import unregister_service
        unregister_service("transactions.metrics")
        unregister_service("transactions.recover")
    except (ImportError, AttributeError, RuntimeError, TypeError, ValueError):
        pass


__all__ = [
    "TRANSACTION_SCHEMA_VERSION",
    "TRANSACTION_JOURNAL_KEY",
    "TransactionError",
    "TransactionCommitError",
    "FBPTransaction",
    "transaction_scope",
    "abort_active_transactions",
    "arm_transaction_failpoint",
    "clear_transaction_failpoints",
    "transaction_metrics",
    "transaction_journal",
    "clear_transaction_journal",
    "recover_transaction_journal",
]
