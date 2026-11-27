import base64
import hashlib
import inspect
import json
import math
from datetime import datetime, timezone
from typing import Any


class FingerprintError(ValueError):
    """
    Raised when an argument cannot be fingerprinted.

    Fingerprinting requires arguments to be converted into a deterministic
    representation. Unsupported types, circular references, or values that
    cannot be safely normalized raise this exception rather than silently
    producing an unreliable fingerprint.
    """


def bind_arguments(func, args, kwargs):
    """
    Normalize the arguments supplied to a function call.

    Python allows functions to receive arguments through positional
    arguments, keyword arguments, and default values. Binding them to the
    function signature converts these different calling forms into a
    consistent parameter mapping.

    Applying defaults ensures that explicitly supplied default values and
    omitted default values produce the same logical argument representation.
    """

    # Use the function's signature to resolve positional and keyword
    # arguments according to its declared parameter structure.
    signature = inspect.signature(func)

    # bind() performs Python-like argument validation. It raises an error
    # for missing required arguments, unexpected keyword arguments,
    # duplicate argument assignment, and invalid argument combinations.
    bound = signature.bind(*args, **kwargs)

    # Populate omitted parameters with their declared default values.
    # Without this step, calls such as func(x=10) and func() could produce
    # different fingerprints even when the default x is 10.
    bound.apply_defaults()

    return bound.arguments


def canonicalize(value: Any, active_ids: set[int] | None = None, depth: int = 0):
    """
    Convert supported Python values into a deterministic,
    type-tagged canonical representation.

    Canonicalization transforms values into a representation that can be
    consistently serialized and hashed. Type tags preserve distinctions
    between values that might otherwise appear equivalent after serialization.

    For example, the integer 1, boolean True, and string "1" must not
    produce the same canonical representation.

    Recursive structures are supported, but circular references and excessive
    nesting are rejected to prevent infinite traversal or uncontrolled recursion.
    """

    # Track containers currently being traversed rather than every container
    # encountered globally. This allows shared references that are not
    # circular while still detecting cycles in the active traversal path.
    if active_ids is None:
        active_ids = set()

    # Bound recursion depth to prevent excessively nested structures from
    # consuming unbounded recursion resources during canonicalization.
    if depth > 100:
        raise FingerprintError("Maximum canonicalization depth exceeded")

    # None
    # Use an explicit type tag rather than relying on JSON's native null
    # representation alone, keeping the canonical format type-aware.
    if value is None:
        return {"type": "none"}

    # bool must be checked before int because bool subclasses int.
    # Explicit type checking preserves the distinction between True and 1.
    if type(value) is bool:
        return {"type": "bool", "value": value}

    # int
    # Serialize integers as strings to avoid relying on JSON numeric
    # representation or precision behavior across implementations.
    if type(value) is int:
        return {"type": "int", "value": str(value)}

    # float
    # repr() provides a representation suitable for preserving the
    # floating-point value's representation consistently in Python.
    # Non-finite values are rejected because NaN and infinity do not have
    # normal JSON-compatible or reliable equality semantics.
    if type(value) is float:
        if not math.isfinite(value):
            raise FingerprintError(
                "NaN and infinity are not supported"
            )

        return {"type": "float", "value": repr(value)}

    # str
    # Strings are represented directly with a type tag so they cannot
    # collide structurally with other supported value types.
    if type(value) is str:
        return {"type": "str", "value": value}

    # bytes
    # JSON cannot directly represent bytes. Base64 converts the binary
    # content into a deterministic ASCII representation without losing data.
    if type(value) is bytes:
        encoded = base64.b64encode(value).decode("ascii")
        return {"type": "bytes", "value": encoded}

    # datetime
    # Datetimes are normalized to UTC so equivalent instants expressed
    # using different timezone offsets produce the same fingerprint.
    if isinstance(value, datetime):
        # Naive datetimes have no unambiguous timezone or instant.
        # Rejecting them avoids silently assuming a local timezone.
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
    # These containers are traversed recursively so their contents,
    # rather than their object identities, contribute to the fingerprint.
    if type(value) in (list, tuple, dict):

        # Object identity is used only for cycle detection.
        # It is not included in the fingerprint because memory addresses
        # are process-specific and would destroy fingerprint determinism.
        object_id = id(value)

        # A container encountered again while it is still being traversed
        # indicates a circular reference in the active traversal path.
        if object_id in active_ids:
            raise FingerprintError(
                "Circular reference detected"
            )

        active_ids.add(object_id)

        try:
            # list
            # List ordering is meaningful, so elements are canonicalized
            # in their original order.
            if type(value) is list:
                return {
                    "type": "list",
                    "value": [
                        canonicalize(item, active_ids, depth + 1)
                        for item in value
                    ],
                }

            # tuple
            # Tuples are kept distinct from lists because they represent
            # different Python types, even if their contents are identical.
            if type(value) is tuple:
                return {
                    "type": "tuple",
                    "value": [
                        canonicalize(item, active_ids, depth + 1)
                        for item in value
                    ],
                }

            # dict
            # Restrict keys to strings to avoid ambiguity when ordering,
            # serializing, or representing different key types.
            if type(value) is dict:
                if not all(type(key) is str for key in value):
                    raise FingerprintError(
                        "Dictionary keys must be strings"
                    )

                # Dictionary insertion order should not affect the
                # fingerprint. Sorting keys produces a deterministic
                # representation regardless of the original insertion order.
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
            # Remove the container from the active traversal path after
            # processing it. This is important because repeated references
            # to the same non-circular object are valid.
            active_ids.remove(object_id)

    # Unsupported objects are rejected rather than serialized using
    # potentially unstable representations such as memory-address-based
    # repr() output or arbitrary user-defined serialization behavior.
    raise FingerprintError(
        f"Unsupported type: {type(value).__name__}"
    )


def generate_fingerprint(func, args, kwargs) -> str:
    """
    Generate a deterministic SHA-256 fingerprint for a function call.

    The fingerprint is derived from the function's bound arguments after
    canonicalization. Equivalent supported argument values should produce
    the same canonical payload, regardless of whether arguments were
    supplied positionally or by keyword.

    The fingerprint format is versioned so canonicalization rules can evolve
    without silently changing the meaning of fingerprints created under
    earlier versions.
    """

    # Normalize the function call into a parameter mapping, including
    # omitted default values.
    bound_arguments = bind_arguments(func, args, kwargs)

    # Convert the bound argument structure into a deterministic,
    # type-aware representation.
    canonical_arguments = canonicalize(bound_arguments)

    # Include a format version to make the fingerprint contract explicit.
    # Future changes to canonicalization can introduce a new format version,
    # allowing systems to distinguish fingerprints generated under different
    # serialization rules.
    payload = {
        "format": "agentguard-fingerprint-v1",
        "arguments": canonical_arguments,
    }

    # Produce deterministic JSON:
    # - sort_keys ensures dictionary ordering is stable.
    # - compact separators avoid unnecessary whitespace differences.
    # - ensure_ascii provides consistent escaped-string representation.
    # - allow_nan=False prevents non-standard JSON numeric values.
    serialized = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    )

    # SHA-256 converts the canonical serialized payload into a fixed-length
    # hexadecimal digest. The digest is suitable for comparing operation
    # input identities without storing the full serialized argument payload.
    return hashlib.sha256(
        serialized.encode("utf-8")
    ).hexdigest()