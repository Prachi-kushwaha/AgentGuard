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