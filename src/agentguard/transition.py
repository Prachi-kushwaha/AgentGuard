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

def transition_to(self, new_status):

    if new_status in ALLOWED_TRANSITIONS[self.status]:
        if new_status == "RUNNING":
            if self.started_at is None:
                self.started_at = datetime.now(timezone.utc)
            self.start_time_monotonic = time.monotonic()
        self.status = new_status
    else:
        raise ValueError(
            f"{new_status} is not allowed to transition when you are in {self.status}"
        )
