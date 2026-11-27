from dataclasses import dataclass


@dataclass(frozen=True)
class RecoveryPolicy:
    """
    Configuration controlling recovery attempts and recovery ownership leases.

    RecoveryPolicy defines the limits under which the recovery engine
    operates, preventing unlimited recovery attempts and specifying
    how long a recovery worker's ownership remains valid.
    """

    # Maximum number of recovery attempts permitted for an operation.
    max_recovery_attempts: int = 5

    # Duration for which a recovery worker holds its ownership lease.
    lease_seconds: float = 30.0

    def __post_init__(self):
        """
        Validate recovery configuration at initialization.

        Invalid policy values are rejected early so that the
        recovery engine does not operate with inconsistent limits
        or invalid lease durations.
        """

        # Booleans are explicitly rejected because bool is a subclass
        # of int in Python, but True/False are not meaningful attempt limits.
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

        # Accept integer or floating-point lease durations,
        # but reject booleans despite their numeric inheritance.
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