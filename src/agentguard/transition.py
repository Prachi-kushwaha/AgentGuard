from datetime import datetime, timezone
from dataclasses import replace
from datetime import datetime, timezone
from .operation_record import OperationRecord
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


OPERATION_TRANSITIONS = {
    "PENDING": {"RUNNING", "FAILED"},
    "RUNNING": {"COMPLETED", "FAILED", "UNKNOWN"},
    "UNKNOWN": {"RECOVERING"},
    "RECOVERING": {"COMPLETED", "FAILED", "UNKNOWN", "RUNNING"},
    "COMPLETED": set(),
    "FAILED": set(),
}


def operation_transition(
    record: OperationRecord,
    new_status: str,
    *,
    recovery_authorized: bool = False,
) -> OperationRecord:

    current_status = record.status

    if new_status not in OPERATION_TRANSITIONS:
        raise ValueError(f"Invalid operation status: {new_status}")

    allowed = OPERATION_TRANSITIONS[current_status]

    if new_status not in allowed:
        raise ValueError(
            f"Illegal operation transition: "
            f"{current_status} -> {new_status}"
        )

    if current_status == "RECOVERING" and new_status == "RUNNING":
        if not recovery_authorized:
            raise ValueError(
                "RECOVERING -> RUNNING requires explicit "
                "recovery authorization"
            )

    return replace(
        record,
        status=new_status,
        updated_at=datetime.now(timezone.utc),
    )