from datetime import datetime, timezone
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