from dataclasses import dataclass


@dataclass(frozen=True)
class RecoveryPolicy:

    max_recovery_attempts: int = 5
    lease_seconds: float = 30.0

    def __post_init__(self):

        if isinstance(
            self.max_recovery_attempts,
            bool,
        ) or not isinstance(
            self.max_recovery_attempts,
            int,
        ):
            raise TypeError(
                "max_recovery_attempts must be an integer"
            )

        if self.max_recovery_attempts < 1:
            raise ValueError(
                "max_recovery_attempts must be >= 1"
            )

        if isinstance(
            self.lease_seconds,
            bool,
        ) or not isinstance(
            self.lease_seconds,
            (int, float),
        ):
            raise TypeError(
                "lease_seconds must be numeric"
            )

        if self.lease_seconds <= 0:
            raise ValueError(
                "lease_seconds must be positive"
            )