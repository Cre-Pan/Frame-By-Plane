"""Compact, deterministic keys for Blender IDProperty storage.

Blender limits IDProperty names to 63 characters.  Built-in Frame By Plane
identifiers stay readable and unchanged, while longer user-defined effect keys
are replaced by a stable namespace plus a collision-resistant digest.
"""

from __future__ import annotations

from functools import lru_cache
from hashlib import blake2s


FBP_IDPROPERTY_NAME_MAX = 63
_FBP_KEY_DIGEST_BYTES = 10


@lru_cache(maxsize=1024)
def _ascii_namespace(value: str) -> str:
    """Return an ASCII-safe namespace suitable for an IDProperty name."""
    result = []
    for char in str(value or "fbp"):
        if char.isascii() and (char.isalnum() or char == "_"):
            result.append(char.lower())
        else:
            result.append("_")
    return "".join(result).strip("_") or "fbp"


@lru_cache(maxsize=8192)
def fbp_compact_idproperty_key(raw_key: str, *, namespace: str = "fbp") -> str:
    """Return a deterministic Blender-safe IDProperty key.

    Keys already within Blender's 63-character limit are returned verbatim, so
    existing built-in properties and saved projects retain their exact names.
    Longer keys use an 80-bit BLAKE2 digest of the complete original key.
    """
    raw_key = str(raw_key or "")
    if len(raw_key) <= FBP_IDPROPERTY_NAME_MAX:
        return raw_key

    digest = blake2s(
        raw_key.encode("utf8", "replace"),
        digest_size=_FBP_KEY_DIGEST_BYTES,
    ).hexdigest()
    marker = "_h_"
    budget = FBP_IDPROPERTY_NAME_MAX - len(marker) - len(digest)
    prefix = _ascii_namespace(namespace)[:budget].rstrip("_") or "fbp"
    return f"{prefix}{marker}{digest}"


@lru_cache(maxsize=8192)
def fbp_effect_storage_key(prefix: str, effect_id: str, suffix: str = "") -> str:
    """Build a stable IDProperty/RNA key for one effect-specific value."""
    prefix = str(prefix or "fbp_effect_")
    effect_id = str(effect_id or "").lower()
    suffix = str(suffix or "")
    raw_key = f"{prefix}{effect_id}{suffix}"
    namespace = f"{prefix.rstrip('_')}{suffix}"
    return fbp_compact_idproperty_key(raw_key, namespace=namespace)
