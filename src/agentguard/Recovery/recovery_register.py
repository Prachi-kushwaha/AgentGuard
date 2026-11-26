from .recovery_handler import RecoveryHandler


class RecoveryRegistry:

    def __init__(self):
        self._handlers: dict[str, RecoveryHandler] = {}

    def register(
        self,
        function_name: str,
        handler: RecoveryHandler,
    ) -> None:

        if not isinstance(function_name, str):
            raise TypeError(
                "function_name must be a string"
            )

        if not function_name:
            raise ValueError(
                "function_name must not be empty"
            )

        if not isinstance(handler, RecoveryHandler):
            raise TypeError(
                "handler must be a RecoveryHandler instance"
            )

        if function_name in self._handlers:
            raise ValueError(
                f"Recovery handler already registered "
                f"for {function_name!r}"
            )

        self._handlers[function_name] = handler

    def get(
        self,
        function_name: str,
    ) -> RecoveryHandler:

        try:
            return self._handlers[function_name]

        except KeyError:
            raise LookupError(
                f"No recovery handler registered "
                f"for {function_name!r}"
            ) from None

    def has(
        self,
        function_name: str,
    ) -> bool:
        return function_name in self._handlers

    def unregister(
        self,
        function_name: str,
    ) -> None:

        if function_name not in self._handlers:
            raise LookupError(
                f"No recovery handler registered "
                f"for {function_name!r}"
            )

        del self._handlers[function_name]