from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4
import time

@dataclass
class ExecutionContext:

    parent_execution_id: str | None = None
    execution_id: str = field(default_factory=lambda: str(uuid4()))
    function_name: str = ""

    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    started_at: datetime | None = None
    start_time_monotonic: float | None = None
    deadline: float | None = None

    status: str = "CREATED"
    attempt_number: int = 0
    max_attempts: int = 1

    last_error: str | None = None
    failure_reason: str | None = None

    results: Any | None = None
    idempotency_key: str | None = None
    cancellation_requested: bool = False

    retry_history: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        self.validate()

    def validate(self):

        if not self.execution_id:
            raise ValueError("execution id cannot be empty")

        if not self.function_name:
            raise ValueError("function_name cannot be empty")

        if self.max_attempts < 1:
            raise ValueError("max_attempty cannot be less than 1")

        if self.attempt_number < 0:
            raise ValueError("attempt_number cannot be negative")

        if self.attempt_number > self.max_attempts:
            raise ValueError( "attempt_number cannot exceed max_attempts")

        allowed_status = {
            "CREATED",
            "RUNNING",
            "COMPLETED",
            "FAILED",
            "CANCELLED",
            "RETRYING",
        }

        if self.status not in allowed_status:
            raise ValueError(f"Invalid status: {self.status}")

        if self.started_at is not None:
            if self.started_at < self.created_at:
                raise ValueError(
                    "started_at cannot be earlier than created_at"
                )

        if self.status == "RUNNING":
            if self.started_at is None:
                raise ValueError(
                    "RUNNING context requires started_at"
                )

            if self.start_time_monotonic is None:
                raise ValueError(
                    "RUNNING context requires start_time_monotonic"
                )

        return True



class ExecutionRejected(Exception):
    pass


def validate_execution(context):

    if context.cancellation_requested:
        raise ExecutionRejected("Execution cancellation was requested")

    allowed_statuses = {"CREATED", "RETRYING"}

    if context.status not in allowed_statuses:
        raise ExecutionRejected(
            f"Execution cannot start from status: {context.status}"
        )

    if context.attempt_number >= context.max_attempts:
        raise ExecutionRejected("Maximum execution attempts exhausted")

    if context.deadline is not None and time.monotonic() >= context.deadline:
        raise ExecutionRejected("Execution deadline has expired")

    return True