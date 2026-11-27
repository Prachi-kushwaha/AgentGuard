from functools import wraps

def guard(
    self,
    *,
    policy=None,
    backoff=None,
    timeout=None,
    attempt_timeout=None,
):
    def decorator(func):

        # Register the original function
        self.registry.register(func)

        @wraps(func)
        def wrapper(*args, **kwargs):

            return self.execute(
                func.__name__,
                *args,
                policy=policy,
                backoff=backoff,
                timeout=timeout,
                attempt_timeout=attempt_timeout,
                **kwargs,
            )

        return wrapper

    return decorator