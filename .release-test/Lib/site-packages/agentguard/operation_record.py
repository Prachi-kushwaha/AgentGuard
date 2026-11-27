from dataclasses import dataclass, field
from uuid import uuid4
from typing import Any
from datetime import datetime, timezone


# Defines the states an operation record is allowed to represent.
# This validates the record's state value, but does not enforce legal
# state transitions. Transition enforcement belongs to the coordinator/backend.
OPERATION_STATES = {
    "PENDING",
    "RUNNING",
    "UNKNOWN",
    "RECOVERING",
    "COMPLETED",
    "FAILED",
}


@dataclass(frozen=True)
class OperationRecord:
    """
    Immutable snapshot of an operation's persisted execution state.

    OperationRecord represents the identity, execution outcome, retry/recovery
    history, and metadata associated with a logical operation.

    The record is frozen so callers cannot mutate its fields after creation.
    State changes must instead produce a new record, typically using
    dataclasses.replace(), allowing the backend to validate and persist
    explicit state transitions.

    The record itself validates structural invariants. It does not determine
    whether a transition such as RUNNING -> COMPLETED is permitted; that
    responsibility belongs to the state-management layer.
    """

    # Identifies the logical namespace in which an operation exists.
    # Different scopes can reuse the same idempotency key without necessarily
    # referring to the same logical operation.
    scope_id: str = "default"

    # Unique identifier for this operation record.
    # Generated independently of the idempotency key, which identifies a
    # logical request rather than the physical record itself.
    operation_id: str = field(default_factory=lambda: str(uuid4()))

    # Caller-provided identifier used to recognize repeated requests.
    # None allows the record to represent an operation without idempotency.
    idempotency_key: str | None = None

    # Name of the function associated with the operation.
    # This provides a human-readable and potentially registry-resolvable
    # identifier for execution and recovery.
    function_name: str = ""

    # Fingerprint of the operation's inputs.
    # Used alongside the idempotency key to detect reuse of the same key
    # with different arguments.
    fingerprint: str | None = None

    # Current lifecycle state of the operation.
    # This represents the persisted state, not necessarily the state of an
    # executing thread or process at the moment this record is read.
    status: str = "PENDING"

    # Stores the successful execution result when available.
    # Any is used because execution results can vary by function.
    # Persistence backends may impose additional serialization constraints.
    result: Any = None

    # Stores a textual description of the last relevant error, if available.
    # This is descriptive state rather than a complete exception object,
    # avoiding dependence on retaining live exception instances.
    error: str | None = None

    # Monotonically increasing record version, typically advanced whenever
    # a persisted state transition occurs.
    # Backends can use this for optimistic concurrency control, preventing
    # stale updates from silently overwriting newer records.
    version: int = 0

    # Timestamp representing when this logical operation record was created.
    # UTC-aware timestamps avoid ambiguity when records are compared,
    # persisted, or read across machines and time zones.
    created_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

    # Timestamp of the most recent persisted update, if one has occurred.
    # None allows newly created records to have no update timestamp yet.
    updated_at: datetime | None = None

    # Counts actual execution attempts.
    # This should not be conflated with recovery attempts, because attempting
    # to reconcile an uncertain operation is not necessarily re-executing
    # the original function.
    attempt_number: int = 0

    # Counts attempts to resolve an uncertain operation state.
    # This tracks recovery work separately from normal execution retries,
    # making the two lifecycle dimensions independently observable.
    recovery_attempts: int = 0

    # Arbitrary operation-associated metadata.
    # A fresh dictionary is created for every record to avoid sharing mutable
    # metadata across independently created records.
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        """
        Validate the record immediately after dataclass initialization.

        Since the record is frozen, validation does not modify its fields.
        Invalid records are rejected before they can enter the coordinator
        or backend workflow.
        """
        self.validate()

    def validate(self):
        """
        Validate the structural invariants of this operation record.

        Validation checks field types, required non-empty identifiers,
        lifecycle-state membership, attempt counters, and timestamp validity.

        These checks establish that the record is structurally well-formed.
        They do not guarantee that the record is semantically consistent
        with every lifecycle rule or backend transition policy.
        """

        # Scope must be a valid string identifier.
        if not isinstance(self.scope_id, str):
            raise TypeError("scope_id must be a string")

        if not self.scope_id.strip():
            raise ValueError("scope_id cannot be empty")

        # The operation identifier is required because records need a stable
        # identity independent of the caller-provided idempotency key.
        if not isinstance(self.operation_id, str):
            raise TypeError("operation_id must be a string")

        if not self.operation_id.strip():
            raise ValueError("operation_id cannot be empty")

        # Function name is required for identifying the operation's
        # associated callable in execution and recovery workflows.
        if not isinstance(self.function_name, str):
            raise TypeError("function_name must be a string")

        if not self.function_name.strip():
            raise ValueError("function_name cannot be empty")

        # If an idempotency key is supplied, it must be a valid identifier.
        # None is permitted because not every operation must be idempotent.
        if self.idempotency_key is not None:
            if not isinstance(self.idempotency_key, str):
                raise TypeError("idempotency_key must be a string")

            if not self.idempotency_key.strip():
                raise ValueError("idempotency_key cannot be empty")

        # Fingerprints are optional, but a supplied fingerprint must be
        # represented by a non-empty string.
        if self.fingerprint is not None:
            if not isinstance(self.fingerprint, str):
                raise TypeError("fingerprint must be a string")

            if not self.fingerprint.strip():
                raise ValueError("fingerprint cannot be empty")

        # The record may only represent a state recognized by AgentGuard.
        # This prevents arbitrary status strings from entering the system.
        # It does not validate transition legality.
        if self.status not in OPERATION_STATES:
            raise ValueError(
                f"Invalid operation status: {self.status}"
            )

        # Execution attempts must be integers.
        # bool is explicitly rejected because bool is a subclass of int.
        if isinstance(self.attempt_number, bool) or not isinstance(self.attempt_number, int):
            raise TypeError("attempt_number must be an integer")

        if self.attempt_number < 0:
            raise ValueError("attempt_number cannot be negative")

        # Recovery attempts are tracked independently from execution attempts.
        # Keeping these counters separate makes recovery behavior observable
        # without incorrectly inflating normal execution retry statistics.
        if isinstance(self.recovery_attempts, bool) or not isinstance(self.recovery_attempts, int):
            raise TypeError("recovery_attempts must be an integer")

        if self.recovery_attempts < 0:
            raise ValueError("recovery_attempts cannot be negative")

        # Error information is optional, but if present it must be textual.
        if self.error is not None and not isinstance(self.error, str):
            raise TypeError("error must be a string or None")

        # Creation timestamp is required for lifecycle tracking and auditing.
        if not isinstance(self.created_at, datetime):
            raise TypeError("created_at must be a datetime")

        # An update timestamp is optional, but must be a valid datetime
        # and timezone-aware when supplied.
        if self.updated_at is not None:
            if not isinstance(self.updated_at, datetime):
                raise TypeError("updated_at must be a datetime or None")

            if self.updated_at.tzinfo is None or self.updated_at.utcoffset() is None:
                raise ValueError("updated_at must be timezone-aware")

        # Reject naive creation timestamps because they cannot be reliably
        # compared with timestamps from other systems or time zones.
        if self.created_at.tzinfo is None or self.created_at.utcoffset() is None:
            raise ValueError("created_at must be timezone-aware")

        # Metadata must be a dictionary so the record has a predictable
        # container for additional operation-associated information.
        if not isinstance(self.metadata, dict):
            raise TypeError("metadata must be a dictionary")