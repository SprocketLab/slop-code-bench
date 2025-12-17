"""Utility primitives shared by evaluation configuration and runners.

Only generic helpers live here to avoid circular dependencies between config,
normalizers, adapters, and verifiers.
"""

import functools
import hashlib
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Annotated, Any

from pydantic import BaseModel
from pydantic import JsonValue

ResultValueType = Annotated[
    str
    | int
    | float
    | None
    | bytes
    | dict[str, "ResultValueType"]
    | list["ResultValueType"],
    "Result value type",
]


class CheckpointValidationError(Exception):
    """Raised when a checkpoint configuration fails validation."""


def set_object_attr(obj: BaseModel | Mapping, attr_name: str, value: ResultValueType):
    """Set ``attr_name`` on either a Pydantic model or mapping-like object."""
    if isinstance(obj, Mapping):
        obj[attr_name] = value
        return
    setattr(obj, attr_name, value)


def get_object_attr(obj: BaseModel | Mapping, attr_name: str):
    """Retrieve ``attr_name`` from a model or mapping treating both uniformly."""
    if isinstance(obj, Mapping):
        return obj[attr_name]
    return getattr(obj, attr_name)


def get_nested_attr(
    obj: BaseModel | Mapping, attr_name: str, key_path: list[str] | None = None
) -> Any:
    """Return an attribute or nested mapping value from ``obj``."""
    value = get_object_attr(obj, attr_name)
    if key_path is None or len(key_path) == 0:
        return value

    if not isinstance(value, Mapping):
        raise TypeError(f"value must be a mapping: {attr_name}={value}")
    return functools.reduce(lambda dct, key: dct[key], key_path, value)  # type: ignore[arg-type]


def set_nested_value(
    obj: BaseModel | Mapping,
    attr_name: str,
    value: ResultValueType,
    key_path: list[str] | None = None,
):
    """Set a top-level or nested attribute value.

    Args:
        attr_name: Name of a top-level field on ``CaseResult``.
        value: Value to assign.
        key_path: Optional nested path for mapping-typed values.

    Raises:
        ValueError: If the attribute is missing or a non-mapping is
            targeted with a ``key_path``.
    """
    # Only setting at the top level -> just check if the attribute exists and set it
    if key_path is None or len(key_path) == 0:
        set_object_attr(obj, attr_name, value)
        return
    v = get_object_attr(obj, attr_name)
    if not isinstance(v, Mapping):
        raise TypeError(f"value must be a mapping: {attr_name}={type(v).__name__}")
    v = functools.reduce(lambda dct, key: dct[key], key_path[:-1], v)
    v[key_path[-1]] = value  # type: ignore[index]


def maybe_set_nested(dct: dict[str, Any], keys: list[str] | str, value: Any) -> None:
    """Assign ``value`` into ``dct`` at a nested path if possible.

    When ``keys`` is a list, dictionaries are created along the way as
    necessary. If ``keys`` is a single string, it behaves like a direct
    assignment.

    This differs from `set_nested_value` in that it does not raise an error
    when the value is not a mapping.

    Args:
        dct: Destination mapping that will be mutated in-place.
        keys: Either a single key or a list representing a nested path.
        value: Value to assign at the final key.
    """
    if isinstance(keys, str):
        dct[keys] = value
        return
    for key in keys[:-1]:
        nxt = dct.get(key)
        if not isinstance(nxt, dict):
            nxt = {}
            dct[key] = nxt
        dct = nxt
    dct[keys[-1]] = value


def nested_priority_merge(base: dict, override: dict) -> dict:
    """Recursively merge two dictionaries with ``override`` precedence.

    For nested dicts, merge continues recursively; for other types, values
    from ``override`` replace those in ``base``.

    Args:
        base: Baseline mapping.
        override: Mapping whose values take precedence.

    Returns:
        A new dictionary with merged results.
    """
    result: dict[str, Any] = {}
    for key in base.keys() | override.keys():
        if key in base and key in override:
            v_base = base[key]
            v_over = override[key]
            if isinstance(v_base, dict) and isinstance(v_over, dict):
                result[key] = nested_priority_merge(v_base, v_over)
            else:
                result[key] = v_over
        elif key in override:
            result[key] = override[key]
        else:
            result[key] = base[key]
    return result


def serialize_value(value: Any) -> JsonValue:
    """Normalize nested values so they can be serialized as JSON.

    Pydantic leaves some values (``Path`` objects, tuples, raw bytes) in
    Python-native forms that do not round-trip through JSON without additional
    handling. This helper converts them into string or list equivalents.
    """
    if isinstance(value, str | int | float | bool | None):
        return value

    if isinstance(value, bytes):
        try:
            return value.decode("utf-8")
        except UnicodeDecodeError:
            return f"sha256:{hashlib.sha256(value).hexdigest()}"

    if isinstance(value, Path):
        return str(value)
    if isinstance(value, Mapping):
        return {str(k): serialize_value(v) for k, v in value.items()}
    if isinstance(value, tuple):
        return [serialize_value(v) for v in value]
    if isinstance(value, list):
        return [serialize_value(v) for v in value]
    raise ValueError(f"Cannot serialize value: {type(value)}")


def ensure_json_string(value: Any) -> str:
    """Ensure a value is a JSON string."""
    if isinstance(value, str):
        return value
    if isinstance(value, bytes):
        try:
            return value.decode("utf-8")
        except UnicodeDecodeError:
            return f"sha256:{hashlib.sha256(value).hexdigest()}"
    value = serialize_value(value)
    return json.dumps(value)
