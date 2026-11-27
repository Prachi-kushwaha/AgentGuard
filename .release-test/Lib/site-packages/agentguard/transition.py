from datetime import datetime, timezone
from dataclasses import replace
from datetime import datetime, timezone
from .operation_record import OperationRecord
from .state_machine import validate_transition, TransitionActor
import time

ALLOWED_TRANSITIONS = {
    "CREATED" : {"RUNNING", "CANCELLED", "FAILED"},
    "RUNNING" : {"FAILED", "COMPLETED", "CANCELLED", "RETRYING"},
    "RETRYING": {"RUNNING","FAILED" "CANCELLED"},
    "CANCELLED": set(),
    "FAILED": set(),
    "COMPLETED": set(),
}


def transition(context, new_status):
    """
    Transition a mutable ExecutionContext into a new runtime state.

    This function validates the requested transition against the runtime
    state transition rules and updates the context in place.

    When transitioning into RUNNING, it initializes the execution start
    timestamps. The wall-clock timestamp provides an externally meaningful
    time, while the monotonic timestamp is suitable for measuring elapsed
    time and enforcing execution deadlines.

    Args:
        context: The mutable execution context being transitioned.
        new_status: The requested runtime destination state.

    Raises:
        ValueError: If the requested transition is not permitted.

    Note:
        This function modifies the supplied context directly. It does not
        create an immutable snapshot or persist the transition.
    """

    if new_status not in ALLOWED_TRANSITIONS[context.status]:
        raise ValueError(
            f"{new_status} is not allowed to transition "
            f"when you are in {context.status}"
        )

    if new_status == "RUNNING":
        if context.started_at is None:
            context.started_at = datetime.now(timezone.utc)

        context.start_time_monotonic = time.monotonic()

    context.status = new_status


def operation_transition(
    record: OperationRecord,
    new_status: str,
    *,
    actor: TransitionActor,
) -> OperationRecord:

    validate_transition(
        current=record.status,
        target=new_status,
        actor=actor,
    )

    return replace(
        record,
        status=new_status,
        updated_at=datetime.now(timezone.utc),
    )