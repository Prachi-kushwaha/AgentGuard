from dataclasses import dataclass

@dataclass(frozen=True)
class ExecutionPolicy:
    max_attempts:int
    retry_on: tuple[type[Exception], ...]

    def __post_init__(self):

        if isinstance(self.max_attempts, bool) or not isinstance(self.max_attempts, int):
            raise TypeError("max_attempts must be an integer")

        if self.max_attempts < 1:
            raise ValueError("max_attempts must be >= 1")

        if not isinstance(self.retry_on, tuple):
            raise TypeError("retry_on must be a tuple")

        for exc in self.retry_on:
            if not isinstance(exc, type) or not issubclass(exc, Exception):
                raise TypeError("retry_on must contain Exception subclasses")

