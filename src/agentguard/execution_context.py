from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4
import time


@dataclass
class ExecutionContext:
    """
    Represents the runtime context of a single execution.

    ExecutionContext carries the state and runtime metadata associated with
    an execution, including its identity, lifecycle timestamps, attempt
    tracking, deadline, cancellation state, results, and execution history.

    Unlike persisted OperationRecord, this context is primarily concerned
    with the execution lifecycle inside the runtime. It provides the
    information required by the engine to manage execution, retries,
    deadlines, cancellation, and observability.

    This context is mutable because the execution engine updates it as the
    execution progresses through different lifecycle stages.
    """

    # Links this execution to another execution when it is part of a
    # parent-child execution relationship, such as delegated work.
    parent_execution_id: str | None = None

    # Generates a unique execution identifier for this runtime instance.
    # A factory is used so every context receives its own UUID rather than
    # sharing a value generated when the class was defined.
    execution_id: str = field(default_factory=lambda: str(uuid4()))

    # Identifies the function currently associated with this execution.
    # The engine can use this for logging, tracing, and diagnostics.
    function_name: str = ""

    # Wall-clock timestamp indicating when this context was created.
    # UTC provides a consistent reference for timestamps across environments.
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    # Wall-clock timestamp recording when execution actually began.
    # This remains unset until the engine transitions into RUNNING.
    started_at: datetime | None = None

    # Monotonic timestamp captured when execution begins.
    # Unlike wall-clock time, monotonic time is not affected by clock
    # adjustments, making it suitable for measuring elapsed execution time.
    start_time_monotonic: float | None = None

    # Monotonic deadline representing the latest allowed execution time.
    # The engine compares this against time.monotonic() rather than
    # wall-clock timestamps to avoid clock-shift-related timing errors.
    deadline: float | None = None

    # Current execution lifecycle status.
    # This describes runtime execution rather than persisted operation state.
    status: str = "CREATED"

    # Tracks how many execution attempts have been performed or entered
    # according to the engine's attempt-numbering convention.
    attempt_number: int = 0

    # Maximum number of attempts permitted for this execution.
    # This includes the initial attempt, not just subsequent retries,
    # depending on the engine's attempt-counting convention.
    max_attempts: int = 1

    # Stores the most recent error encountered during execution.
    # Useful for diagnostics without requiring the caller to inspect
    # the entire retry history.
    last_error: str | None = None

    # Stores the reason the execution ultimately failed or was rejected.
    # This can be used to distinguish execution failures from lifecycle,
    # deadline, cancellation, or policy-related failures.
    failure_reason: str | None = None

    # Stores the execution result when available.
    # Any is used because the function's return type is not restricted
    # to a particular data structure.
    results: Any | None = None

    # Optional key connecting this runtime execution to an idempotent
    # logical operation managed by the idempotency subsystem.
    idempotency_key: str | None = None

    # Signals that cancellation has been requested.
    # A request flag allows the engine to observe and act on cancellation
    # without requiring the requester to directly manipulate execution.
    cancellation_requested: bool = False

    # Stores historical retry information rather than only the most
    # recent attempt. Each entry can contain attempt timing, errors,
    # delay information, and other retry-related observations.
    retry_history: list[dict[str, Any]] = field(default_factory=list)

    # Stores execution-specific extension data.
    # This allows integrations or application-specific execution features
    # to attach metadata without changing the core context structure.
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        """
        Validate the context immediately after dataclass initialization.

        This ensures that newly constructed contexts begin with a valid
        configuration and lifecycle state rather than allowing malformed
        execution data to propagate into the engine.
        """
        self.validate()

    def validate(self):
        """
        Validate execution identity, attempt configuration, and lifecycle state.

        The validation rules establish structural invariants for the context.
        They do not replace lifecycle transition enforcement by the engine;
        they ensure the context is internally consistent at validation time.
        """

        # An execution ID is required to correlate the execution across
        # logging, tracing, callbacks, and runtime lifecycle operations.
        if not self.execution_id:
            raise ValueError("execution id cannot be empty")

        # The engine needs a function identity to associate this context
        # with the work it is managing.
        if not self.function_name:
            raise ValueError("function_name cannot be empty")

        # At least one attempt must be permitted.
        # Zero attempts would represent a context that cannot execute.
        if self.max_attempts < 1:
            raise ValueError("max_attempty cannot be less than 1")

        # Attempt numbers start at zero before the execution begins.
        # Negative values would violate the attempt-counting convention.
        if self.attempt_number < 0:
            raise ValueError("attempt_number cannot be negative")

        # The context must not represent an attempt beyond its configured
        # execution limit.
        if self.attempt_number > self.max_attempts:
            raise ValueError("attempt_number cannot exceed max_attempts")

        # Restrict lifecycle state to the statuses understood by the
        # execution engine. This prevents arbitrary state values from
        # entering lifecycle logic.
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

        # Execution cannot logically begin before the context was created.
        # This catches inconsistent wall-clock lifecycle timestamps.
        if self.started_at is not None:
            if self.started_at < self.created_at:
                raise ValueError(
                    "started_at cannot be earlier than created_at"
                )

        # RUNNING represents active execution, so both the wall-clock
        # start timestamp and monotonic start timestamp must be present.
        # Having both supports human-readable timestamps and reliable
        # elapsed-time/deadline calculations.
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
    """
    Raised when the engine refuses to start an execution.

    This represents a lifecycle or policy rejection rather than an
    exception thrown by the user function itself.
    """
    pass


def validate_execution(context):
    """
    Determine whether an execution context is eligible to begin execution.

    This validation is performed before starting or restarting an execution.
    It checks cancellation, lifecycle state, attempt limits, and deadline
    expiration.

    The function does not start execution or mutate the context. It acts as
    a gate that either permits the caller to proceed or rejects execution.
    """

    # Cancellation takes precedence over starting new work.
    # Once cancellation has been requested, the engine should not begin
    # another attempt even if the remaining lifecycle conditions are valid.
    if context.cancellation_requested:
        raise ExecutionRejected("Execution cancellation was requested")

    # Only newly created executions or executions explicitly prepared
    # for retry are permitted to enter a new execution attempt.
    # RUNNING, COMPLETED, FAILED, and CANCELLED contexts must not
    # accidentally be started again through this validation path.
    allowed_statuses = {"CREATED", "RETRYING"}

    if context.status not in allowed_statuses:
        raise ExecutionRejected(
            f"Execution cannot start from status: {context.status}"
        )

    # attempt_number is checked against max_attempts before starting.
    # This prevents the engine from initiating an attempt after its
    # configured execution budget has been exhausted.
    if context.attempt_number >= context.max_attempts:
        raise ExecutionRejected("Maximum execution attempts exhausted")

    # The deadline is represented using monotonic time.
    # Comparing against time.monotonic() avoids problems caused by
    # wall-clock adjustments, such as NTP corrections or system-clock changes.
    if context.deadline is not None and time.monotonic() >= context.deadline:
        raise ExecutionRejected("Execution deadline has expired")

    # If no rejection condition was met, the context is eligible
    # to proceed to the engine's execution-start logic.
    return True