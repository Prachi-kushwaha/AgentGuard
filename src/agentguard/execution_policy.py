from dataclasses import dataclass


@dataclass(frozen=True)
class ExecutionPolicy:
    """
    Defines the execution and retry rules for a managed operation.

    ExecutionPolicy determines how many total execution attempts are permitted
    and which exception types qualify for a retry.

    The policy separates retry configuration from execution logic. The engine
    consumes this policy to decide whether a failed attempt should result in
    another attempt or whether the failure should propagate.

    This object is immutable so retry configuration cannot be accidentally
    altered while an execution is in progress.
    """

    # Maximum number of execution attempts permitted, including the initial
    # attempt. The engine uses this limit to prevent unbounded execution.
    max_attempts: int

    # Exception types considered eligible for retry.
    # Exceptions outside this tuple should not trigger retry behavior
    # unless another part of the engine explicitly handles them.
    retry_on: tuple[type[Exception], ...]

    def __post_init__(self):
        """
        Validate the execution policy at construction time.

        These checks ensure the retry configuration is structurally valid
        before the execution engine consumes it. Invalid configuration
        should fail early rather than produce unexpected retry behavior
        during runtime.
        """

        # bool is a subclass of int in Python. Explicitly reject booleans
        # so True or False cannot accidentally be used as an attempt limit.
        if isinstance(self.max_attempts, bool) or not isinstance(
            self.max_attempts, int
        ):
            raise TypeError("max_attempts must be an integer")

        # At least one attempt must be allowed.
        # A value below 1 would make the execution policy unusable.
        if self.max_attempts < 1:
            raise ValueError("max_attempts must be >= 1")

        # Using a tuple provides a fixed collection of exception types
        # that the engine can inspect when determining retry eligibility.
        if not isinstance(self.retry_on, tuple):
            raise TypeError("retry_on must be a tuple")

        # Every configured entry must be an Exception subclass.
        # This allows the engine to use exception matching safely,
        # for example: isinstance(error, retry_on).
        #
        # Exception classes themselves must be supplied, not exception
        # instances. BaseException subclasses such as SystemExit and
        # KeyboardInterrupt are intentionally excluded.
        for exc in self.retry_on:
            if not isinstance(exc, type) or not issubclass(exc, Exception):
                raise TypeError("retry_on must contain Exception subclasses")