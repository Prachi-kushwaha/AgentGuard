class FunctionRegister:
    """
    Maintains a registry of callable functions available to the execution engine.

    The registry provides a central mapping between function names and their
    callable objects. The engine can use this mapping to retrieve a function
    by name without needing to manage function references throughout the
    execution lifecycle.

    This is particularly useful when functions need to be referenced
    dynamically, such as through recovery handlers, execution requests,
    serialized function identifiers, or orchestration logic.

    The registry currently uses function names as keys. This means function
    names must be unique within a single registry instance.
    """

    def __init__(self):
        """
        Initialize an empty function registry.

        Each registry instance maintains its own mapping. Functions registered
        in one instance are not automatically available in another.
        """
        self.functions = {}

    def register(self, func):
        """
        Register a callable under its function name.

        Duplicate names are rejected rather than silently overwritten.
        Overwriting an existing entry could unexpectedly change which
        implementation is executed when the engine retrieves a function.

        Returns:
            The original function, allowing register() to be used as a decorator.
        """

        # Function names act as registry identifiers.
        # Reject duplicates to avoid silently replacing an existing function.
        if func.__name__ in self.functions:
            raise ValueError(f"{func.__name__} already present in registry")

        self.functions[func.__name__] = func

        # Returning the original function preserves normal function behavior
        # and allows registration through decorator syntax.
        return func

    def retrieve(self, name):
        """
        Retrieve a registered function by its name.

        Raises:
            ValueError: If the requested name is not registered.
        """

        # The registry is the source of truth for which functions are
        # available to the execution engine.
        if name in self.functions:
            res = self.functions[name]
        else:
            raise ValueError(
                "given name is not present in our registry"
            )

        return res

    def unregister(self, name):
        """
        Remove a function from the registry.

        Unregistration removes the name-to-function mapping. It does not
        modify the function object itself or affect references to that
        function held elsewhere.

        Raises:
            ValueError: If the requested name is not registered.
        """

        # Explicitly reject missing names rather than silently treating
        # unregistration as successful. This makes registry operations
        # predictable for callers.
        if name in self.functions:
            del self.functions[name]
        else:
            raise ValueError(
                "Given name is not present in our registry"
            )

    def enlist(self):
        """
        Return the names of all currently registered functions.

        Returns a new list containing the registry keys rather than
        exposing the underlying dictionary directly.
        """
        return list(self.functions.keys())