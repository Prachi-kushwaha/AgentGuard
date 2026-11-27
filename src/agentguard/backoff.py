import math
import random
from dataclasses import dataclass


@dataclass(frozen=True)
class BackoffPolicy:
    """
    Defines the retry delay strategy used when an operation needs to be retried.

    The policy uses exponential backoff to progressively increase the delay
    between retries. A maximum delay prevents the wait from growing
    indefinitely, while jitter helps distribute retries across time when
    multiple callers encounter failures simultaneously.

    This is an immutable configuration object. Once constructed, its retry
    behavior cannot be changed accidentally during execution.
    """

    initial_delay: float = 1.0
    multiplier: float = 2.0
    max_delay: float = 30.0
    jitter: bool = True

    def __post_init__(self):
        """
        Validate the configuration before it can be used.

        Invalid numeric values such as NaN, infinity, booleans, or negative
        delays can produce unpredictable retry schedules. Validation here
        ensures the policy operates only with well-defined parameters.
        """

        # Validate initial_delay
        # The first retry establishes the base delay from which subsequent
        # exponential delays are calculated.
        if isinstance(self.initial_delay, bool) or not isinstance(
            self.initial_delay, (int, float)
        ):
            raise TypeError("initial_delay must be an int or float")

        # NaN and infinity are technically floats but cannot reliably be
        # used in delay calculations or comparisons.
        if not math.isfinite(self.initial_delay):
            raise ValueError("initial_delay must be finite")

        # A zero or negative initial delay would eliminate the intended
        # waiting period and make the backoff policy meaningless.
        if self.initial_delay <= 0:
            raise ValueError("initial_delay must be greater than zero")

        # Validate multiplier
        # The multiplier controls how aggressively the delay grows.
        # For example, 2.0 doubles the delay after each retry.
        if isinstance(self.multiplier, bool) or not isinstance(
            self.multiplier, (int, float)
        ):
            raise TypeError("multiplier must be an int or float")

        if not math.isfinite(self.multiplier):
            raise ValueError("multiplier must be finite")

        # A multiplier below 1 would decrease the delay with each retry,
        # which contradicts the intended exponential backoff behavior.
        # A value of 1 is allowed for a constant-delay retry strategy.
        if self.multiplier < 1:
            raise ValueError("multiplier must be greater than or equal to one")

        # Validate max_delay
        # The cap limits how long the caller can be forced to wait between
        # retries, even when the exponential calculation grows very large.
        if isinstance(self.max_delay, bool) or not isinstance(
            self.max_delay, (int, float)
        ):
            raise TypeError("max_delay must be an int or float")

        if not math.isfinite(self.max_delay):
            raise ValueError("max_delay must be finite")

        # The cap cannot be lower than the initial delay. Otherwise, the
        # configured first retry would already exceed the allowed maximum.
        if self.max_delay < self.initial_delay:
            raise ValueError(
                "max_delay must be greater than or equal to initial_delay"
            )

        # Validate jitter
        # Jitter is a behavioral switch, not a numeric configuration.
        # Rejecting non-boolean values avoids ambiguous configuration such
        # as strings, integers, or truthy objects.
        if not isinstance(self.jitter, bool):
            raise TypeError("jitter must be bool")

    def calculate_delay(self, retry_number):
        """
        Calculate the waiting time before a specific retry attempt.

        Retry numbering starts at 1, where retry 1 uses initial_delay.
        Each subsequent retry increases the delay exponentially until the
        max_delay cap is reached. Optional full jitter then randomizes the
        delay between zero and the calculated upper bound.

        Args:
            retry_number: The retry attempt number, starting from 1.

        Returns:
            The delay in seconds before the specified retry.
        """

        # Validate retry_number
        # Explicitly reject bool because bool is a subclass of int in Python.
        # Without this check, True would silently behave like retry number 1.
        if isinstance(retry_number, bool) or not isinstance(retry_number, int):
            raise TypeError("retry_number must be an integer")

        if retry_number < 1:
            raise ValueError("retry_number must be >= 1")

        # Calculate exponential delay with maximum cap.
        #
        # retry_number = 1 -> initial_delay
        # retry_number = 2 -> initial_delay * multiplier
        # retry_number = 3 -> initial_delay * multiplier**2
        #
        # The cap ensures the delay never exceeds max_delay, regardless
        # of how many retries occur.
        delay = min(
            self.initial_delay * (self.multiplier ** (retry_number - 1)),
            self.max_delay,
        )

        # Apply Full Jitter.
        # Instead of every caller waiting for the exact same delay, each
        # caller receives a random delay between 0 and the calculated delay.
        #
        # This helps prevent synchronized retries (thundering herd), where
        # many workers retry simultaneously after a shared failure.
        if self.jitter:
            delay = random.uniform(0, delay)

        return delay