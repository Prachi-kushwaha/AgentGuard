
import base64
import hashlib
import inspect
import json
import math
from datetime import datetime, timezone
from typing import Any


class FingerprintError(ValueError):
    """Raised when an argument cannot be fingerprinted."""


def bind_arguments(func, args, kwargs):
    signature = inspect.signature(func)
    bound = signature.bind(*args, **kwargs)
    bound.apply_defaults()
    return bound.arguments


def canonicalize(value: Any, active_ids: set[int] | None = None, depth: int = 0):
    """
    Convert supported Python values into a deterministic,
    type-tagged canonical representation.
    """

    if active_ids is None:
        active_ids = set()

    if depth > 100:
        raise FingerprintError("Maximum canonicalization depth exceeded")

    # None
    if value is None:
        return {"type": "none"}

    # bool must be checked before int because bool subclasses int.
    if type(value) is bool:
        return {"type": "bool", "value": value}

    # int
    if type(value) is int:
        return {"type": "int", "value": str(value)}

    # float
    if type(value) is float:
        if not math.isfinite(value):
            raise FingerprintError(
                "NaN and infinity are not supported"
            )

        return {"type": "float", "value": repr(value)}

    # str
    if type(value) is str:
        return {"type": "str", "value": value}

    # bytes
    if type(value) is bytes:
        encoded = base64.b64encode(value).decode("ascii")
        return {"type": "bytes", "value": encoded}

    # datetime
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise FingerprintError(
                "Naive datetime objects are not supported"
            )

        normalized = value.astimezone(timezone.utc)

        return {
            "type": "datetime",
            "value": normalized.isoformat(timespec="microseconds"),
        }

    # Recursive structures: list, tuple, dict
    if type(value) in (list, tuple, dict):

        object_id = id(value)

        if object_id in active_ids:
            raise FingerprintError(
                "Circular reference detected"
            )

        active_ids.add(object_id)

        try:
            # list
            if type(value) is list:
                return {
                    "type": "list",
                    "value": [
                        canonicalize(item, active_ids, depth + 1)
                        for item in value
                    ],
                }

            # tuple
            if type(value) is tuple:
                return {
                    "type": "tuple",
                    "value": [
                        canonicalize(item, active_ids, depth + 1)
                        for item in value
                    ],
                }

            # dict
            if type(value) is dict:
                if not all(type(key) is str for key in value):
                    raise FingerprintError(
                        "Dictionary keys must be strings"
                    )

                return {
                    "type": "dict",
                    "value": [
                        [
                            key,
                            canonicalize(
                                value[key],
                                active_ids,
                                depth + 1,
                            ),
                        ]
                        for key in sorted(value)
                    ],
                }

        finally:
            active_ids.remove(object_id)

    raise FingerprintError(
        f"Unsupported type: {type(value).__name__}"
    )


def generate_fingerprint(func, args, kwargs) -> str:
    """
    Generate a deterministic SHA-256 fingerprint for a function call.
    """

    bound_arguments = bind_arguments(func, args, kwargs)

    canonical_arguments = canonicalize(bound_arguments)

    payload = {
        "format": "agentguard-fingerprint-v1",
        "arguments": canonical_arguments,
    }

    serialized = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    )

    return hashlib.sha256(
        serialized.encode("utf-8")
    ).hexdigest()

