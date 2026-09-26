"""Serialize `to_doc()` shapes to JSON-able dicts: datetimes -> ISO 8601 strings."""

from __future__ import annotations

from dataclasses import is_dataclass
from datetime import datetime
from typing import Any


def to_jsonable(value: Any) -> Any:
    """Recursively convert a `to_doc()` dict/dataclass/list into JSON-safe values."""
    if isinstance(value, datetime):
        return value.isoformat()
    if is_dataclass(value) and not isinstance(value, type):
        return to_jsonable(value.to_doc())  # type: ignore[union-attr]
    if isinstance(value, dict):
        return {k: to_jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [to_jsonable(v) for v in value]
    return value


def doc(obj: Any) -> dict[str, Any]:
    """`obj.to_doc()` with nested datetimes converted to ISO strings."""
    return to_jsonable(obj.to_doc())
