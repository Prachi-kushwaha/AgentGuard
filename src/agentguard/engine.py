"""
AgentGuard execution engine.

This module is responsible for:

1. Routing normal and idempotent executions.
2. Managing execution attempts.
3. Enforcing execution deadlines and attempt timeouts.
4. Applying retry policies and backoff.
5. Persisting idempotent execution outcomes through the coordinator.
6. Delegating recovery orchestration to RecoveryEngine.
7. Executing operations after recovery ownership has been
   atomically transferred back to the execution actor.

Architectural boundaries
-----------------------

Engine:
    Executes registered Python functions and manages their
    in-process execution lifecycle.

IdempotencyCoordinator:
    Coordinates operation claims and durable operation mutations.

Backend:
    Enforces authoritative ownership, fencing, leases,
    expected status/version and atomic mutations.

RecoveryEngine:
    Investigates uncertain operations and decides whether
    operations should complete, resume, defer or require
    manual intervention.

Engine does NOT:
    - Automatically determine whether an external side effect occurred.
    - Recover arbitrary Python stack frames.
    - Forcefully interrupt synchronous Python functions.
    - Independently grant execution ownership.
    - Perform recovery-to-execution handoffs itself.
"""


import inspect
import math
import time

from uuid import uuid4

from .function_register import FunctionRegister
from .execution_context import (
    ExecutionContext,
    validate_execution,
    ExecutionRejected,
)
from .execution_policy import ExecutionPolicy
from .backoff import BackoffPolicy
from .transition import transition
from .storage.protocol import ClaimDisposition


class _AttemptTimeout(TimeoutError):
    """
    Internal timeout raised when AgentGuard detects that an
    execution attempt exceeded its configured time budget.

    This is intentionally distinct from an ordinary TimeoutError
    raised by the user function.

    Why?

    A user function may raise TimeoutError for its own reasons.
    AgentGuard cannot assume that every such exception means
    an external side effect has an uncertain outcome.

    This exception specifically represents AgentGuard's own
    post-execution timeout detection.

    IMPORTANT:

    This does not forcibly interrupt synchronous Python code.

    AgentGuard measures elapsed time after the function returns.
    If the function exceeds its time budget, the result is
    treated as an attempt timeout after the function returns.
    """


class Engine:

    """
    Central execution orchestrator.

    The Engine is responsible for the in-process execution
    lifecycle. It routes operations to normal execution,
    idempotent execution or recovered execution.

    Parameters
    ----------
    registry:
        FunctionRegister containing the callable functions
        available to AgentGuard.

    idempotency_coordinator:
        Optional coordinator used for durable idempotent
        operation management.

    recovery_engine:
        Optional RecoveryEngine responsible for orchestrating
        operation recovery.

    The Engine intentionally does not directly manipulate
    backend records or ownership grants.
    """

    def __init__(
        self,
        registry,
        idempotency_coordinator=None,
        recovery_engine=None,
    ):

        # Validate the function registry early.
        # This prevents an invalid registry from being used
        # throughout the lifetime of the Engine.
        if not isinstance(registry, FunctionRegister):
            raise TypeError(
                "registry must be a FunctionRegister instance"
            )

        # Function registry containing executable functions.
        self.registry = registry

        # Execution contexts are tracked in memory by execution ID.
        #
        # This is in-process execution tracking.
        # It is NOT durable operation storage.
        self.executions = {}

        # Optional idempotency subsystem.
        #
        # The coordinator is responsible for claims, durable
        # operation transitions and coordinating backend mutations.
        self.idempotency_coordinator = idempotency_coordinator

        # Optional recovery subsystem.
        #
        # Recovery orchestration is deliberately delegated rather
        # than implemented inside this execution engine.
        self.recovery_engine = recovery_engine


    # PUBLIC EXECUTION API


    def execute(
        self,
        name,
        *args,
        policy=None,
        backoff=None,
        timeout=None,
        attempt_timeout=None,
        idempotency_key=None,
        owner_id=None,
        scope_id="default",
        **kwargs,
    ):

        """
        Execute a registered function.

        There are two primary execution paths:

        1. Normal execution
           No idempotency key is supplied.

        2. Idempotent execution
           An idempotency key is supplied and AgentGuard
           coordinates the operation with the backend.

        Parameters
        ----------
        name:
            Registered function name.

        args / kwargs:
            Function invocation arguments.

        policy:
            Retry policy.

        backoff:
            Retry backoff policy.

        timeout:
            Overall execution time budget.

        attempt_timeout:
            Maximum time budget for a single attempt.

        idempotency_key:
            Optional operation identity key.

        owner_id:
            Optional execution owner identifier.

        scope_id:
            Idempotency scope.

        Returns
        -------
        The function result.
        """


        # PATH 1: NORMAL EXECUTION


        # Without an idempotency key, execution is entirely
        # handled by the normal execution machinery.
        #
        # No durable operation claim is created by this path.
        if idempotency_key is None:

            return self._execute_normal(
                name,
                *args,
                policy=policy,
                backoff=backoff,
                timeout=timeout,
                attempt_timeout=attempt_timeout,
                **kwargs,
            )


        # PATH 2: IDEMPOTENT EXECUTION


        # Idempotent execution requires the coordinator because
        # operation identity, claims and persistence are handled
        # outside the normal execution loop.
        if self.idempotency_coordinator is None:

            raise RuntimeError(
                "Idempotency was requested but no "
                "IdempotencyCoordinator is configured"
            )

        # If the caller did not provide an owner ID,
        # generate one for this execution request.
        #
        # This identifies the execution owner.
        # The backend still generates and validates its
        # authoritative ownership token.
        if owner_id is None:
            owner_id = str(uuid4())

        # Resolve the callable before acquiring the operation.
        #
        # The coordinator uses the callable and invocation
        # arguments to construct or validate operation identity.
        func = self.registry.retrieve(name)

        # Acquire an idempotent operation.
        #
        # The coordinator/backend determine whether:
        #
        # - This operation is newly claimable.
        # - The operation was previously completed.
        # - Another owner currently holds it.
        # - Recovery is required.
        # - The supplied key conflicts with the identity.
        claim = self.idempotency_coordinator.acquire(
            func=func,
            args=args,
            kwargs=kwargs,
            idempotency_key=idempotency_key,
            owner_id=owner_id,
            scope_id=scope_id,
        )


        # COMPLETED OPERATION REPLAY


        # A previously completed operation should not execute
        # the function again.
        #
        # Return the persisted result.
        if claim.disposition is ClaimDisposition.COMPLETED:

            return claim.record.result


        # CLAIM VALIDATION


        # The execution path expects a claim.
        #
        # BUSY, RECOVERY_REQUIRED and KEY_CONFLICT should
        # normally be handled by the coordinator contract.
        # Unexpected dispositions are treated as errors.
        if claim.disposition is not ClaimDisposition.CLAIMED:

            raise RuntimeError(
                f"Unexpected claim disposition: "
                f"{claim.disposition}"
            )

        # A successfully claimed operation contains:
        #
        # - A record representing the claimed operation.
        # - A grant authorizing this owner to mutate it.
        #
        # The Engine does not manufacture or replace the grant.
        return self._execute_claimed(
            name=name,
            args=args,
            kwargs=kwargs,
            claim=claim,
            policy=policy,
            backoff=backoff,
            timeout=timeout,
            attempt_timeout=attempt_timeout,
        )


    # CLAIMED OPERATION EXECUTION


    def _execute_claimed(
        self,
        name,
        args,
        kwargs,
        claim,
        policy=None,
        backoff=None,
        timeout=None,
        attempt_timeout=None,
    ):

        """
        Execute an operation after idempotency claim.

        This method separates execution from the public routing
        logic in execute().

        It is responsible for:

        1. Running the function.
        2. Persisting the final operation outcome.

        The operation's grant and record come from the claim.

        The Engine must not independently create a grant.
        """

        # The claim supplies the authoritative grant and
        # operation record returned by the coordinator.
        grant = claim.grant
        record = claim.record


        # EXECUTE


        try:

            result = self._execute_normal(
                name,
                *args,
                policy=policy,
                backoff=backoff,
                timeout=timeout,
                attempt_timeout=attempt_timeout,
                **kwargs,
            )


        # AGENTGUARD ATTEMPT TIMEOUT


        # _AttemptTimeout represents AgentGuard's own
        # timeout detection.
        #
        # A synchronous function may have performed an external
        # side effect before returning late.
        #
        # Therefore the operation may have an uncertain outcome.
        #
        # The coordinator/backend determine whether UNKNOWN
        # can be persisted with this grant.
        except _AttemptTimeout as exc:

            self.idempotency_coordinator.record_unknown(
                operation_id=record.operation_id,
                error=exc,
                grant=grant,
                record=record,
            )

            raise


        # USER FUNCTION TIMEOUT


        # A normal TimeoutError raised by the user's function
        # is treated as an ordinary function failure here.
        #
        # AgentGuard cannot infer ambiguity merely from the
        # exception type.
        #
        # Applications should use provider idempotency keys
        # and explicit reconciliation when external outcomes
        # are genuinely uncertain.
        except TimeoutError as exc:

            self.idempotency_coordinator.record_failure(
                operation_id=record.operation_id,
                error=exc,
                grant=grant,
                record=record,
            )

            raise


        # OTHER FUNCTION EXECUTION FAILURES


        # Persist the failure through the coordinator.
        #
        # If the persistence mutation itself fails, that error
        # propagates. It is not silently converted into another
        # function failure.
        except Exception as exc:

            self.idempotency_coordinator.record_failure(
                operation_id=record.operation_id,
                error=exc,
                grant=grant,
                record=record,
            )

            raise


        # SUCCESSFUL EXECUTION


        # The function completed successfully.
        #
        # Persist the result before returning it to the caller.
        #
        # A persistence failure propagates because the function
        # result may exist without a durable COMPLETED record.
        self.idempotency_coordinator.record_success(
            operation_id=record.operation_id,
            result=result,
            grant=grant,
            record=record,
        )

        return result


    # NORMAL EXECUTION ENGINE


    def _execute_normal(
        self,
        name,
        *args,
        policy=None,
        backoff=None,
        timeout=None,
        attempt_timeout=None,
        **kwargs,
    ):

        """
        Execute a function using AgentGuard's retry engine.

        This is the shared execution machinery used by:

        - Normal execution.
        - Idempotent execution.
        - Recovered execution after ownership handoff.

        This method manages the in-process execution lifecycle.

        It does not directly persist idempotency operation
        records.
        """


        # DEFAULT EXECUTION POLICY


        # A single attempt is the default.
        #
        # Retries are opt-in through ExecutionPolicy.
        if policy is None:

            policy = ExecutionPolicy(
                max_attempts=1,
                retry_on=(),
            )

        # The policy must be the expected configuration object.
        if not isinstance(policy, ExecutionPolicy):

            raise TypeError(
                "policy must be an ExecutionPolicy instance"
            )


        # DEFAULT BACKOFF POLICY


        # Backoff controls the delay between retries.
        #
        # It is separate from retry eligibility.
        if backoff is None:

            backoff = BackoffPolicy()

        if not isinstance(backoff, BackoffPolicy):

            raise TypeError(
                "backoff must be a BackoffPolicy instance"
            )


        # TIMEOUT VALIDATION


        # Validate the overall execution time budget.
        self._validate_timeout(
            timeout,
            name="timeout",
        )

        # Validate the per-attempt time budget.
        self._validate_timeout(
            attempt_timeout,
            name="attempt_timeout",
        )


        # EXECUTION CONTEXT


        # The context tracks the in-process lifecycle:
        #
        # - Execution ID.
        # - Function name.
        # - Attempt number.
        # - Current state.
        # - Results.
        # - Errors.
        # - Retry history.
        # - Deadline.
        #
        # It is not a durable operation record.
        context = ExecutionContext(
            function_name=name,
            max_attempts=policy.max_attempts,
        )


        # OVERALL DEADLINE


        # A deadline uses monotonic time.
        #
        # Monotonic time is appropriate for measuring elapsed
        # time because it is not affected by wall-clock changes.
        if timeout is not None:

            context.deadline = (
                time.monotonic() + timeout
            )

        # Register the context for in-process inspection.
        self.executions[context.execution_id] = context


        # EXECUTION PREPARATION


        try:

            # Validate that the execution context is allowed
            # to begin execution.
            validate_execution(context)

            # Retrieve the callable.
            func = self.registry.retrieve(name)

            # Bind arguments to the callable signature.
            #
            # This catches invocation errors before the
            # function is actually called.
            signature = inspect.signature(func)

            signature.bind(
                *args,
                **kwargs,
            )

        except Exception as exc:

            # Record the preparation failure.
            context.last_error = str(exc)
            context.failure_reason = str(exc)

            # Move the context into FAILED if necessary.
            if context.status != "FAILED":

                transition(
                    context,
                    "FAILED",
                )

            raise


        # Execute until:
        #
        # - The function succeeds.
        # - A terminal failure occurs.
        # - The maximum attempt count is reached.
        # - Execution validation rejects another attempt.
        while (
            context.attempt_number
            < context.max_attempts
        ):
            # VALIDATE EXECUTION BEFORE EACH ATTEMP

            # This ensures the execution context is eligible
            # for another attempt.
            try:

                validate_execution(context)

            except Exception as exc:

                context.last_error = str(exc)
                context.failure_reason = str(exc)

                # CREATED or RETRYING contexts can be moved
                # into FAILED if validation rejects execution.
                if context.status in {
                    "CREATED",
                    "RETRYING",
                }:

                    transition(
                        context,
                        "FAILED",
                    )

                raise
            # START ATTEMP

            # Increment the attempt counter before execution.
            context.attempt_number += 1

            # Transition the execution context to RUNNING.
            transition(
                context,
                "RUNNING",
            )
            # ATTEMPT TIME MEASUREMEN

            # Monotonic time is used for attempt timing.
            attempt_started = time.monotonic()

            # Start with the explicit attempt timeout.
            effective_timeout = attempt_timeout
            # APPLY OVERALL DEADLIN

            # An attempt cannot exceed the remaining overall
            # execution time budget.
            if context.deadline is not None:

                deadline_remaining = (
                    context.deadline
                    - attempt_started
                )

                # If no explicit attempt timeout exists,
                # the overall deadline becomes the limit.
                if effective_timeout is None:

                    effective_timeout = (
                        deadline_remaining
                    )

                # Otherwise, use the stricter of the
                # attempt timeout and deadline.
                else:

                    effective_timeout = min(
                        effective_timeout,
                        deadline_remaining,
                    )
            # CHECK TIME BUDGET BEFORE EXECUTIO

            # Do not start an attempt when its effective
            # time budget has already expired.
            if (
                effective_timeout is not None
                and effective_timeout <= 0
            ):

                exc = ExecutionRejected(
                    "Execution time budget exhausted "
                    "before attempt started"
                )

                context.last_error = str(exc)
                context.failure_reason = str(exc)

                transition(
                    context,
                    "FAILED",
                )

                raise exc

            # FUNCTION EXECUTION

            try:

                # Call the actual user function.
                #
                # AgentGuard does not forcibly interrupt
                # synchronous Python functions.
                result = func(
                    *args,
                    **kwargs,
                )

                # Measure elapsed attempt time.
                attempt_elapsed = (
                    time.monotonic()
                    - attempt_started
                )

                # POST-EXECUTION TIMEOUT DETECTION

                # Because this implementation is synchronous,
                # the function may already have completed its
                # side effect before AgentGuard detects that
                # it exceeded its time budget.
                #
                # The timeout is detected after the function
                # returns, not by forcibly interrupting it.
                if (
                    effective_timeout is not None
                    and attempt_elapsed
                    >= effective_timeout
                ):

                    raise _AttemptTimeout(
                        "Attempt exceeded its time budget "
                        f"of {effective_timeout:.3f} seconds"
                    )

                # SUCCESS

                # Store the result in the execution context.
                context.results = result

                # Mark the execution as completed.
                transition(
                    context,
                    "COMPLETED",
                )

                return result

            # ATTEMPT FAILURE

            except Exception as exc:

                # Store the last error for observability.
                context.last_error = str(exc)

                # RETRY ELIGIBILITY

                # Only exceptions explicitly included in
                # policy.retry_on are retryable.
                retryable = isinstance(
                    exc,
                    policy.retry_on,
                )

                # Retry is possible only if another attempt
                # remains within the configured attempt count.
                attempts_remaining = (
                    context.attempt_number
                    < context.max_attempts
                )

                # A retry requires both:
                #
                # 1. The exception is retryable.
                # 2. Attempts remain.
                should_retry = (
                    retryable
                    and attempts_remaining
                )

                # BACKOFF CALCULATION

                # Calculate the delay only when a retry
                # has actually been considered eligible.
                delay = (

                    backoff.calculate_delay(
                        context.attempt_number
                    )

                    if should_retry

                    else None
                )

                # DEADLINE CHECK BEFORE RETRY

                # Even if the exception is retryable,
                # the next retry must fit within the
                # remaining overall deadline.
                if (
                    should_retry
                    and context.deadline is not None
                ):

                    remaining = (
                        context.deadline
                        - time.monotonic()
                    )

                    # If the deadline has already expired
                    # or the backoff delay cannot fit,
                    # the retry is rejected.
                    if (
                        remaining <= 0
                        or delay >= remaining
                    ):

                        retry_record = {
                            "attempt": (
                                context.attempt_number
                            ),
                            "exception": (
                                type(exc).__name__
                            ),
                            "message": str(exc),
                            "retryable": retryable,
                            "retry_decision": (
                                "FAIL_DEADLINE"
                            ),
                            "delay": None,
                        }

                        # Preserve the rejected retry decision.
                        context.retry_history.append(
                            retry_record
                        )

                        context.failure_reason = (
                            "Execution deadline exceeded "
                            "before next retry"
                        )

                        transition(
                            context,
                            "FAILED",
                        )

                        # Preserve the original exception
                        # as the causal exception.
                        raise ExecutionRejected(
                            context.failure_reason
                        ) from exc

                # RECORD RETRY DECISION

                # Every attempted retry decision is recorded.
                #
                # This history is part of the in-process
                # execution context.
                retry_record = {
                    "attempt": (
                        context.attempt_number
                    ),
                    "exception": (
                        type(exc).__name__
                    ),
                    "message": str(exc),
                    "retryable": retryable,
                    "retry_decision": (
                        "RETRY"
                        if should_retry
                        else "FAIL"
                    ),
                    "delay": delay,
                }

                context.retry_history.append(
                    retry_record
                )

                # RETRY

                if should_retry:

                    # Transition into RETRYING before waiting.
                    transition(
                        context,
                        "RETRYING",
                    )

                    # Apply the backoff delay.
                    #
                    # This is synchronous blocking sleep.
                    time.sleep(delay)

                    # Return to the attempt loop.
                    continue

                # TERMINAL FAILURE

                # No retry is permitted or no attempts remain.
                context.failure_reason = str(exc)

                transition(
                    context,
                    "FAILED",
                )

                # Preserve the original exception.
                raise


    # RECOVERY API


    def recover(
        self,
        operation_id,
        payload=None,
        owner_id=None,
    ):

        """
        Public recovery entry point.

        The Engine delegates recovery orchestration to
        RecoveryEngine.

        RecoveryEngine is responsible for:

        - Loading the durable operation.
        - Checking whether recovery is eligible.
        - Claiming recovery ownership.
        - Resolving the recovery handler.
        - Invoking reconciliation logic.
        - Persisting recovery decisions.
        - Performing an atomic handoff when RESUME is chosen.

        Engine does not independently claim recovery ownership.
        """

        # Recovery must be explicitly configured.
        if self.recovery_engine is None:

            raise RuntimeError(
                "Recovery was requested but no "
                "RecoveryEngine is configured"
            )

        # Delegate orchestration.
        #
        # RecoveryEngine owns recovery lifecycle decisions.
        return self.recovery_engine.recover(
            operation_id=operation_id,
            payload=payload,
            owner_id=owner_id,
        )


    # RECOVERED EXECUTION


    def _execute_recovered(
        self,
        record,
        grant,
        invocation,
    ):

        """
        Execute an operation after recovery has transferred
        ownership back to the execution actor.

        This method is an internal execution entry point.

        The RecoveryEngine/backend must have already performed
        an atomic recovery-to-execution handoff.

        Expected handoff result:

            RECOVERING -> RUNNING

        The handoff must also:

        - Invalidate the recovery ownership token.
        - Create a fresh execution grant.
        - Increment the operation version.
        - Commit the record and grant atomically.

        This method must NOT call coordinator.acquire().

        Why?

        The operation has already been claimed through
        the atomic handoff.

        A second claim would represent a new claim attempt,
        not continuation of the handed-off operation.
        """


        # REQUIRED IDEMPOTENCY INFRASTRUCTURE


        # Recovered execution requires the coordinator
        # because the final result or failure must be
        # persisted against the handed-off operation.
        if self.idempotency_coordinator is None:

            raise RuntimeError(
                "Recovered execution requires an "
                "IdempotencyCoordinator"
            )


        # BASIC INPUT VALIDATION


        if record is None:

            raise ValueError(
                "record must not be None"
            )

        if grant is None:

            raise ValueError(
                "execution grant must not be None"
            )

        if not isinstance(invocation, dict):

            raise TypeError(
                "invocation must be a dictionary"
            )


        # INVOCATION VALIDATION


        # The durable invocation must contain enough
        # information to reconstruct the call.
        required_fields = {
            "function_name",
            "args",
            "kwargs",
        }

        missing_fields = (
            required_fields
            - invocation.keys()
        )

        if missing_fields:

            raise ValueError(
                "Recovered invocation is missing fields: "
                f"{sorted(missing_fields)}"
            )

        function_name = invocation["function_name"]

        args = invocation["args"]

        kwargs = invocation["kwargs"]

        # Validate the reconstructed invocation.
        if not isinstance(
            function_name,
            str,
        ):

            raise TypeError(
                "function_name must be a string"
            )

        if not isinstance(
            args,
            (list, tuple),
        ):

            raise TypeError(
                "recovered args must be a list or tuple"
            )

        if not isinstance(
            kwargs,
            dict,
        ):

            raise TypeError(
                "recovered kwargs must be a dictionary"
            )


        # OPERATION IDENTITY VALIDATION


        # The record's function name is derived from the
        # operation identity.
        #
        # This assumes the OperationRecord identity exposes
        # identity.function_name, as in the AgentGuard
        # architecture discussed previously.
        record_function_name = (
            record.identity.function_name
        )

        # Prevent execution of a function that does not
        # correspond to the persisted operation identity.
        if function_name != record_function_name:

            raise ValueError(
                "Recovered function does not match "
                "the operation record identity"
            )


        # RECONSTRUCT EXECUTION CONFIGURATION


        # These fields are optional.
        #
        # The invocation payload must not blindly persist
        # arbitrary Python object instances.
        #
        # A durable payload should use a versioned,
        # validated representation of configuration.
        policy = invocation.get("policy")

        backoff = invocation.get("backoff")

        timeout = invocation.get("timeout")

        attempt_timeout = invocation.get(
            "attempt_timeout"
        )


        # EXECUTION


        # Execute through the shared normal execution
        # machinery.
        #
        # This reuses:
        #
        # - ExecutionContext.
        # - Retry eligibility.
        # - Backoff.
        # - Deadline enforcement.
        # - Attempt timeout detection.
        # - Lifecycle transitions.
        #
        # The execution grant is not passed into
        # _execute_normal because that method handles
        # in-process execution, not durable ownership.
        #
        # The grant is used for the durable outcome
        # mutation below.


        try:

                result = self._execute_normal(
                    function_name,
                    *args,
                    policy=policy,
                    backoff=backoff,
                    timeout=timeout,
                    attempt_timeout=attempt_timeout,
                    **kwargs,
                )

        except _AttemptTimeout as exc:

                # AgentGuard detected that the attempt exceeded
                # its budget. Its external outcome may be uncertain.
                self.idempotency_coordinator.record_unknown(
                    operation_id=record.operation_id,
                    error=exc,
                    grant=grant,
                    record=record,
                )

                raise

        except Exception as exc:

                # Ordinary execution failure.
                self.idempotency_coordinator.record_failure(
                    operation_id=record.operation_id,
                    error=exc,
                    grant=grant,
                    record=record,
                )

                raise

        # Persist successful execution separately from the
        # function's exception-handling boundary.
        self.idempotency_coordinator.record_success(
            operation_id=record.operation_id,
            result=result,
            grant=grant,
            record=record,
        )

        return result
        # SUCCESSFUL RECOVERED EXECUTION



    # VALIDATION HELPERS


    @staticmethod
    def _validate_timeout(
        value,
        name,
    ):

        """
        Validate a timeout value.

        Timeouts must:

        - Be numeric.
        - Not be bool.
        - Be finite.
        - Be greater than zero.

        bool is explicitly rejected because bool is a subclass
        of int in Python.
        """

        # None means that no explicit timeout was supplied.
        if value is None:
            return

        # Reject booleans.
        if isinstance(value, bool):

            raise TypeError(
                f"{name} must be an int or float"
            )

        # Reject non-numeric types.
        if not isinstance(
            value,
            (int, float),
        ):

            raise TypeError(
                f"{name} must be an int or float"
            )

        # Reject NaN and infinity.
        if not math.isfinite(value):

            raise ValueError(
                f"{name} must be finite"
            )

        # Require a positive timeout.
        if value <= 0:

            raise ValueError(
                f"{name} must be greater than zero"
            )