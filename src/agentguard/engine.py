import inspect
import time
import math

from .function_register import FunctionRegister
from .execution_context import ExecutionContext, validate_execution, ExecutionRejected
from .execution_policy import ExecutionPolicy
from .backoff import BackoffPolicy
from .transition import transition
class Engine:

    def __init__(self, registry):

        if not isinstance(registry, FunctionRegister):
            raise TypeError("registry must be a FunctionRegister instance")

        self.registry = registry
        self.executions = {}

    def execute(self, name, *args, policy=None, backoff=None, timeout=None, attempt_timeout=None, **kwargs):

        if policy is None:
            policy = ExecutionPolicy(max_attempts=1, retry_on=())

        if not isinstance(policy, ExecutionPolicy):
            raise TypeError("policy must be an ExecutionPolicy instance")

        if backoff is None:
            backoff = BackoffPolicy()

        if not isinstance(backoff, BackoffPolicy):
            raise TypeError("backoff must be a BackoffPolicy instance")

        if timeout is not None:
            if isinstance(timeout, bool) or not isinstance(timeout, (int, float)):
                raise TypeError("timeout must be an int or float")

            if not math.isfinite(timeout):
                raise ValueError("timeout must be finite")

            if timeout <= 0:
                raise ValueError("timeout must be greater than zero")


        if attempt_timeout is not None:

            if isinstance(attempt_timeout, bool) or not isinstance(
                attempt_timeout, (int, float)
            ):
                raise TypeError("attempt_timeout must be an int or float")

            if not math.isfinite(attempt_timeout):
                raise ValueError("attempt_timeout must be finite")

            if attempt_timeout <= 0:
                raise ValueError("attempt_timeout must be greater than zero")

        # A. Create execution context
        context = ExecutionContext(
            function_name=name,
            max_attempts=policy.max_attempts
        )

        if timeout is not None:
            context.deadline = time.monotonic() + timeout

        self.executions[context.execution_id] = context

        # B Execution preparation
        try:

            validate_execution(context)

            func = self.registry.retrieve(name)

            signature = inspect.signature(func)
            signature.bind(*args, **kwargs)

        except Exception as exc:

            context.last_error = str(exc)
            context.failure_reason = str(exc)
            transition(context, "FAILED")

            raise

        while context.attempt_number < context.max_attempts:

            # Check execution eligibility before every attempt
            try:
                validate_execution(context)

            except Exception as exc:

                context.last_error = str(exc)
                context.failure_reason = str(exc)

                if context.status in {"CREATED", "RETRYING"}:
                    transition(context, "FAILED")

                raise

            context.attempt_number += 1
            transition(context, "RUNNING")

            try:

                attempt_started = time.monotonic()

                effective_timeout = attempt_timeout

                if context.deadline is not None:

                    deadline_remaining = (
                        context.deadline - attempt_started
                    )

                    if effective_timeout is None:
                        effective_timeout = deadline_remaining
                    else:
                        effective_timeout = min(
                            effective_timeout,
                            deadline_remaining
                        )
                if effective_timeout is not None and effective_timeout <= 0:
                            raise ExecutionRejected(
                            "Execution time budget exhausted before attempt started"
                        )

                result = func(*args, **kwargs)

                attempt_elapsed = time.monotonic() - attempt_started

                if (
                    effective_timeout is not None
                    and attempt_elapsed >= effective_timeout
                ):
                    raise TimeoutError(
                        f"Attempt exceeded its time budget "
                        f"of {effective_timeout:.3f} seconds"
                    )

                context.results = result
                transition(context, "COMPLETED")

                return result

            except Exception as exc:

                context.last_error = str(exc)

                retryable = isinstance(exc, policy.retry_on)

                attempts_remaining = (
                    context.attempt_number < context.max_attempts
                )

                should_retry = retryable and attempts_remaining

                delay = (
                    backoff.calculate_delay(context.attempt_number)
                    if should_retry
                    else None
                )

                # Check whether the retry delay fits within the deadline
                if should_retry and context.deadline is not None:

                    remaining = context.deadline - time.monotonic()

                    if remaining <= 0 or delay >= remaining:

                        retry_record = {
                            "attempt": context.attempt_number,
                            "exception": type(exc).__name__,
                            "message": str(exc),
                            "retryable": retryable,
                            "retry_decision": "FAIL_DEADLINE",
                            "delay": None,
                        }

                        context.retry_history.append(retry_record)

                        context.failure_reason = (
                            "Execution deadline exceeded before next retry"
                        )

                        transition(context, "FAILED")

                        raise ExecutionRejected(
                            context.failure_reason
                        ) from exc

                retry_record = {
                    "attempt": context.attempt_number,
                    "exception": type(exc).__name__,
                    "message": str(exc),
                    "retryable": retryable,
                    "retry_decision": "RETRY" if should_retry else "FAIL",
                    "delay": delay,
                }

                context.retry_history.append(retry_record)

                if should_retry:

                    transition(context, "RETRYING")

                    time.sleep(delay)

                    continue

                context.failure_reason = str(exc)
                context.transition_to("FAILED")

                raise

