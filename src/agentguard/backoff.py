import math
import random
from dataclasses import dataclass


@dataclass(frozen=True)
class BackoffPolicy:

    initial_delay: float = 1.0
    multiplier: float = 2.0
    max_delay: float = 30.0
    jitter: bool = True

    def __post_init__(self):

        # Validate initial_delay
        if isinstance(self.initial_delay, bool) or not isinstance(
            self.initial_delay, (int, float)
        ):
            raise TypeError("initial_delay must be an int or float")

        if not math.isfinite(self.initial_delay):
            raise ValueError("initial_delay must be finite")

        if self.initial_delay <= 0:
            raise ValueError("initial_delay must be greater than zero")

        # Validate multiplier
        if isinstance(self.multiplier, bool) or not isinstance(
            self.multiplier, (int, float)
        ):
            raise TypeError("multiplier must be an int or float")

        if not math.isfinite(self.multiplier):
            raise ValueError("multiplier must be finite")

        if self.multiplier < 1:
            raise ValueError("multiplier must be greater than or equal to one")

        # Validate max_delay
        if isinstance(self.max_delay, bool) or not isinstance(
            self.max_delay, (int, float)
        ):
            raise TypeError("max_delay must be an int or float")

        if not math.isfinite(self.max_delay):
            raise ValueError("max_delay must be finite")

        if self.max_delay < self.initial_delay:
            raise ValueError(
                "max_delay must be greater than or equal to initial_delay"
            )

        # Validate jitter
        if not isinstance(self.jitter, bool):
            raise TypeError("jitter must be bool")

    def calculate_delay(self, retry_number):

        # Validate retry_number
        if isinstance(retry_number, bool) or not isinstance(retry_number, int):
            raise TypeError("retry_number must be an integer")

        if retry_number < 1:
            raise ValueError("retry_number must be >= 1")

        # Calculate exponential delay with maximum cap
        delay = min(
            self.initial_delay * (self.multiplier ** (retry_number - 1)),
            self.max_delay
        )

        # Apply Full Jitter
        if self.jitter:
            delay = random.uniform(0, delay)

        return delay