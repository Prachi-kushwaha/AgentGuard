from dataclasses import dataclass, field
from uuid import uuid4
from typing import Any
from datetime import datetime, timezone


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

    operation_id: str = field(default_factory=lambda: str(uuid4()))

    idempotency_key: str | None = None

    function_name: str = ""

    fingerprint: str | None = None

    status: str = "PENDING"

    result: Any = None

    error: str | None = None

    created_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

    updated_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    # Actual attempts to execute the operation
    attempt_number: int = 0
    # Attempts to resolve the uncertain operation state
    recovery_attempts: int = 0

    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        self.validate()

    def validate(self):

        if not isinstance(self.operation_id, str):
            raise TypeError("operation_id must be a string")

        if not self.operation_id.strip():
            raise ValueError("operation_id cannot be empty")

        if not isinstance(self.function_name, str):
            raise TypeError("function_name must be a string")

        if not self.function_name.strip():
            raise ValueError("function_name cannot be empty")

        if self.idempotency_key is not None:
            if not isinstance(self.idempotency_key, str):
                raise TypeError("idempotency_key must be a string")

            if not self.idempotency_key.strip():
                raise ValueError("idempotency_key cannot be empty")

        if self.fingerprint is not None:
            if not isinstance(self.fingerprint, str):
                raise TypeError("fingerprint must be a string")

            if not self.fingerprint.strip():
                raise ValueError("fingerprint cannot be empty")

        if self.status not in OPERATION_STATES:
            raise ValueError(
                f"Invalid operation status: {self.status}"
            )

        if isinstance(self.attempt_number, bool) or not isinstance(self.attempt_number, int):
            raise TypeError("attempt_number must be an integer")

        if self.attempt_number < 0:
            raise ValueError("attempt_number cannot be negative")

        if isinstance(self.recovery_attempts, bool) or not isinstance(self.recovery_attempts, int):
            raise TypeError("recovery_attempts must be an integer")

        if self.recovery_attempts < 0:
            raise ValueError("recovery_attempts cannot be negative")

        if self.error is not None and not isinstance(self.error, str):
            raise TypeError("error must be a string or None")

        if not isinstance(self.created_at, datetime):
            raise TypeError("created_at must be a datetime")

        if not isinstance(self.updated_at, datetime):
            raise TypeError("updated_at must be a datetime")

        if self.created_at.tzinfo is None or self.created_at.utcoffset() is None:
            raise ValueError("created_at must be timezone-aware")

        if self.updated_at.tzinfo is None or self.updated_at.utcoffset() is None:
            raise ValueError("updated_at must be timezone-aware")

        if not isinstance(self.metadata, dict):
            raise TypeError("metadata must be a dictionary")