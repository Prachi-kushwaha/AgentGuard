
import hashlib
import pickle
import time
from dataclasses import dataclass
from threading import Condition
from typing import Any


class IdempotencyConflict(Exception):
    """Raised when the same idempotency key is used for different inputs."""


class IdempotencyWaitTimeout(TimeoutError):
    """Raised when waiting for an in-progress execution takes too long."""


@dataclass
class IdempotencyEntry:
    fingerprint: str
    status: str = "IN_PROGRESS"
    result: Any = None


class IdempotencyStore:

    def __init__(self, wait_timeout: float = 30.0):

        if isinstance(wait_timeout, bool) or not isinstance(wait_timeout, (int, float)):
            raise TypeError("wait_timeout must be an int or float")

        if wait_timeout <= 0:
            raise ValueError("wait_timeout must be greater than zero")

        self.wait_timeout = wait_timeout
        self.entries = {}
        self.condition = Condition()

    @staticmethod
    def fingerprint(args, kwargs):

        payload = pickle.dumps((args, kwargs))
        return hashlib.sha256(payload).hexdigest()

    def begin(self, key, fingerprint):

        deadline = time.monotonic() + self.wait_timeout

        with self.condition:

            while True:

                entry = self.entries.get(key)

                # First request using this key
                if entry is None:

                    self.entries[key] = IdempotencyEntry(
                        fingerprint=fingerprint
                    )

                    return True, None

                # The key has already been used with different inputs
                if entry.fingerprint != fingerprint:

                    raise IdempotencyConflict(
                        "Idempotency key reused with different inputs"
                    )

                # Previous execution completed successfully
                if entry.status == "COMPLETED":

                    return False, entry.result

                # First execution is still running
                remaining = deadline - time.monotonic()

                if remaining <= 0:

                    raise IdempotencyWaitTimeout(
                        "Timed out waiting for the original execution"
                    )

                self.condition.wait(timeout=remaining)

    def complete(self, key, result):

        with self.condition:

            entry = self.entries.get(key)

            if entry is None:
                raise KeyError("Idempotency key not found")

            entry.result = result
            entry.status = "COMPLETED"

            self.condition.notify_all()

    def fail(self, key):

        with self.condition:

            entry = self.entries.get(key)

            if entry is not None and entry.status == "IN_PROGRESS":

                del self.entries[key]

                self.condition.notify_all()

    def get(self, key):

        with self.condition:

            return self.entries.get(key)
