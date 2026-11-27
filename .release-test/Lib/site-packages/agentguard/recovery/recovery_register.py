from .recovery_handler import RecoveryHandler


class RecoveryRegistry:
    """
    Registry for mapping operation function names to recovery handlers.

    The registry provides a centralized mechanism for resolving
    application-defined recovery handlers during recovery.
    """

    def __init__(self):
        # Store handlers by function name to allow direct lookup
        # when an operation needs to be reconciled.
        self._handlers: dict[str, RecoveryHandler] = {}

    def register(
        self,
        function_name: str,
        handler: RecoveryHandler,
    ) -> None:
        """
        Register a recovery handler for a function.

        Each function name can have only one registered handler
        to avoid ambiguous recovery behavior.
        """

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

        # Prevent accidental replacement of an existing handler.
        # Explicit registration conflicts are safer than silently
        # changing recovery behavior.
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
        """
        Retrieve the handler registered for a function.

        Raises LookupError when no handler is registered,
        allowing callers to handle missing recovery configuration
        explicitly.
        """

        try:
            return self._handlers[function_name]

        except KeyError:
            # Suppress the internal KeyError so callers receive
            # a domain-specific error instead of a dictionary error.
            raise LookupError(
                f"No recovery handler registered "
                f"for {function_name!r}"
            ) from None

    def has(
        self,
        function_name: str,
    ) -> bool:
        """Check whether a handler is registered for a function."""
        return function_name in self._handlers

    def unregister(
        self,
        function_name: str,
    ) -> None:
        """
        Remove a registered recovery handler.

        Raises LookupError if the function has no registered handler.
        """

        if function_name not in self._handlers:
            raise LookupError(
                f"No recovery handler registered "
                f"for {function_name!r}"
            )

        del self._handlers[function_name]