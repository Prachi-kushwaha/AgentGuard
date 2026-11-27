import hashlib
import pickle
import time
from dataclasses import dataclass
from threading import Condition
from typing import Any


class IdempotencyConflict(Exception):
    """
    Raised when an idempotency key is reused for a request with different inputs.

    The idempotency key represents the identity of a logical operation.
    Reusing that key with a different fingerprint means the caller is
    attempting to associate a different operation with the same identity.
    """
    pass


class IdempotencyWaitTimeout(TimeoutError):
    """
    Raised when a caller waiting for an existing execution exceeds its
    configured wait deadline.

    This timeout applies to waiting for another execution to finish.
    It does not necessarily mean the underlying execution itself timed out.
    """
    pass


@dataclass
class IdempotencyEntry:
    """
    Represents the state associated with a single idempotency key.

    The store uses this entry to track whether an operation is currently
    executing or has completed, and to retain the result for subsequent
    requests using the same key and inputs.
    """

    # Fingerprint of the original request's arguments.
    # Used to detect idempotency-key reuse with different inputs.
    fingerprint: str

    # Tracks the lifecycle of the operation within this store.
    # IN_PROGRESS prevents concurrent callers from executing the same
    # operation simultaneously; COMPLETED allows result reuse.
    status: str = "IN_PROGRESS"

    # The cached result becomes available after successful completion.
    # Any caller reusing the same key and fingerprint can receive this result.
    result: Any = None


class IdempotencyStore:
    """
    Provides in-memory idempotency coordination for concurrent function calls.

    The store associates an idempotency key with a fingerprint and execution
    state. When a caller begins an operation:

        - A new key is admitted and marked IN_PROGRESS.
        - A matching key whose execution is still in progress causes the
          caller to wait.
        - A matching key whose execution is completed returns the cached result.
        - A key associated with a different fingerprint raises a conflict.

    A Condition is used to coordinate concurrent threads. Threads waiting
    for an operation can sleep until the original execution changes state,
    instead of repeatedly polling the store.

    This implementation is process-local and in-memory. It does not provide
    persistence across restarts or coordination across multiple processes.
    """

    def __init__(self, wait_timeout: float = 30.0):
        """
        Initialize the store and its synchronization mechanism.

        Args:
            wait_timeout: Maximum duration a caller may wait for an existing
                in-progress operation to finish.

        The timeout is validated at initialization so invalid configurations
        are rejected before the store begins handling requests.
        """

        # bool is technically a subclass of int in Python, so explicitly
        # reject it to avoid accepting True or False as timeout values.
        if isinstance(wait_timeout, bool) or not isinstance(wait_timeout, (int, float)):
            raise TypeError("wait_timeout must be an int or float")

        if wait_timeout <= 0:
            raise ValueError("wait_timeout must be greater than zero")

        self.wait_timeout = wait_timeout

        # Maps idempotency keys to their corresponding execution entries.
        # All state mutations and coordinated reads happen under the Condition.
        self.entries = {}

        # Condition combines a lock with a notification mechanism.
        # The lock protects shared state while notify_all() wakes waiting threads
        # after an execution transitions to a new state.
        self.condition = Condition()

    @staticmethod
    def fingerprint(args, kwargs):
        """
        Generate a SHA-256 fingerprint from positional and keyword arguments.

        Pickle serializes the argument structure into bytes, which are then
        hashed. The digest provides a compact representation for comparing
        requests associated with the same idempotency key.

        Note:
            Pickle-based fingerprints are dependent on serialization behavior
            and are not intended as a cross-version or cross-language canonical
            representation.
        """

        payload = pickle.dumps((args, kwargs))
        return hashlib.sha256(payload).hexdigest()

    def begin(self, key, fingerprint):
        """
        Determine whether a request can execute, should wait, or can reuse
        a previously completed result.

        Returns:
            (True, None): The caller has been admitted as the initial executor.
            (False, result): A previous matching execution has completed.

        Raises:
            IdempotencyConflict: The key exists but has a different fingerprint.
            IdempotencyWaitTimeout: The matching execution is still running
                after the configured wait deadline.

        The deadline is computed before entering the waiting loop so the
        timeout represents a total waiting budget rather than resetting every
        time the thread wakes up.
        """

        # monotonic() is used because it measures elapsed time independently
        # of system clock adjustments, making it appropriate for deadlines.
        deadline = time.monotonic() + self.wait_timeout

        # The condition lock ensures the check-and-insert operation is atomic
        # relative to other threads using this store. Without synchronization,
        # multiple threads could observe the same missing key and all become
        # executors for the same logical operation.
        with self.condition:

            # Re-check state after every wakeup. Condition.wait() can wake
            # because of notifications or spurious wakeups, so notification
            # alone does not imply that the operation has completed.
            while True:

                entry = self.entries.get(key)

                # First request using this key.
                # This caller becomes the executor by atomically inserting
                # an IN_PROGRESS entry while holding the condition lock.
                if entry is None:

                    self.entries[key] = IdempotencyEntry(
                        fingerprint=fingerprint
                    )

                    return True, None

                # The same key must identify the same logical request.
                # A different fingerprint is a conflict rather than a
                # request that should wait or receive a cached result.
                if entry.fingerprint != fingerprint:

                    raise IdempotencyConflict(
                        "Idempotency key reused with different inputs"
                    )

                # Previous execution completed successfully.
                # Return its stored result instead of executing again.
                if entry.status == "COMPLETED":

                    return False, entry.result

                # The original execution is still in progress.
                # Calculate remaining time against the original deadline
                # rather than granting a fresh timeout after each wakeup.
                remaining = deadline - time.monotonic()

                if remaining <= 0:

                    raise IdempotencyWaitTimeout(
                        "Timed out waiting for the original execution"
                    )

                # Releases the underlying lock while the thread waits.
                # When awakened, the lock is reacquired before execution
                # continues, allowing shared state to be safely inspected.
                self.condition.wait(timeout=remaining)

    def complete(self, key, result):
        """
        Mark an operation as completed and publish its result to waiters.

        The state transition and result assignment occur under the condition
        lock. Waiters are notified only after the completed state and result
        are visible, ensuring they can observe the updated entry when they
        reacquire the lock.
        """

        with self.condition:

            entry = self.entries.get(key)

            if entry is None:
                raise KeyError("Idempotency key not found")

            # Publish the result before marking the entry completed.
            # Both mutations occur while holding the lock, so other threads
            # cannot observe an intermediate state through this store.
            entry.result = result
            entry.status = "COMPLETED"

            # Wake all threads waiting on this key. They will re-enter the
            # begin() loop and inspect the entry's new state.
            self.condition.notify_all()

    def fail(self, key):
        """
        Remove an in-progress entry after an execution failure.

        Removing the entry allows a future request using the same key to
        become the executor again.

        This implementation does not retain failure information. Therefore,
        a failure effectively resets the key rather than caching the failure.
        """

        with self.condition:

            entry = self.entries.get(key)

            # Only remove an in-progress entry.
            # A completed entry should not be deleted through this method,
            # because doing so would discard an already published result.
            if entry is not None and entry.status == "IN_PROGRESS":

                del self.entries[key]

                # Wake waiting threads so they can re-check the key.
                # After deletion, one of them may become the new executor.
                self.condition.notify_all()

    def get(self, key):
        """
        Return the current entry associated with a key, if one exists.

        The lock protects the lookup against concurrent state mutations.
        The returned entry itself is still a mutable object, however, so
        callers should avoid modifying it outside the store's synchronization
        mechanism.
        """

        with self.condition:

            return self.entries.get(key)