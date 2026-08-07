"""Deterministic content identities and provenance references."""

from __future__ import annotations

import dataclasses
import hashlib
import json
from datetime import date, datetime
from enum import Enum
from typing import Any


def _canonicalize(value: Any) -> Any:
    if dataclasses.is_dataclass(value):
        return {
            field.name: _canonicalize(getattr(value, field.name))
            for field in dataclasses.fields(value)
            if field.init
        }
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {str(key): _canonicalize(item) for key, item in sorted(value.items())}
    if isinstance(value, (list, tuple)):
        return [_canonicalize(item) for item in value]
    if isinstance(value, (set, frozenset)):
        return sorted(_canonicalize(item) for item in value)
    return value


def canonical_json(value: Any) -> str:
    """Serialize a value reproducibly, independent of dict insertion order."""
    return json.dumps(
        _canonicalize(value), ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )


def content_id(kind: str, value: Any) -> str:
    """Create a stable, namespaced SHA-256 content identifier."""
    payload = canonical_json(value).encode("utf-8")
    return f"{kind}:sha256:{hashlib.sha256(payload).hexdigest()}"
