from __future__ import annotations

from uuid import uuid4

from ..operation_record import OPERATION_STATES
from ..storage.protocol import ClaimDisposition
from .recovery_models import (
    RecoveryContext,
    RecoveryDecision,
    RecoveryOutcome,
    RecoveryResult,
)
from .recovery_policy import RecoveryPolicy


class RecoveryEngine:
    """
    Coordinates recovery of previously interrupted or uncertain operations.

    The RecoveryEngine is responsible for orchestrating the recovery
    lifecycle, but it does not independently decide whether an operation
    is safe to execute again.

    Instead, it relies on:

    - A backend to provide atomic ownership and state transitions.
    - A registry to resolve the application-specific recovery handler.
    - A recovery policy to control recovery attempts and lease duration.
    - A handler to reconcile the operation with the external system.

    Recovery is deliberately separated from normal execution. An operation
    that enters recovery may have already produced side effects, so blindly
    rerunning it could result in duplicate mutations.

    The recovery handler is therefore responsible for determining whether
    the operation has already completed, can safely resume, should be
    deferred, or requires manual intervention.
    """

    def __init__(
        self,
        *,
        backend,
        registry,
        policy: RecoveryPolicy | None = None,
    ):
        """
        Initialize the recovery orchestration component.

        Args:
            backend:
                Storage backend responsible for durable operation state,
                recovery ownership, leases and atomic state transitions.

            registry:
                Registry mapping operation/function identities to
                application-defined recovery handlers.

            policy:
                Recovery configuration controlling recovery limits and
                ownership lease duration.

        If no policy is supplied, the default RecoveryPolicy is used.
        """
        self.backend = backend
        self.registry = registry
        self.policy = policy or RecoveryPolicy()

    def recover(
        self,
        operation_id: str,
        *,
        payload=None,
        owner_id: str | None = None,
    ) -> RecoveryOutcome:
        """
        Attempt to reconcile an operation whose execution outcome
        may be uncertain.

        This method orchestrates recovery rather than directly rerunning
        the original function.

        The recovery process:

        1. Validates the operation identifier.
        2. Loads the durable operation record.
        3. Returns immediately if the operation is already completed.
        4. Resolves the registered recovery handler.
        5. Obtains recovery ownership from the backend.
        6. Enforces the recovery attempt limit.
        7. Invokes the application-defined recovery handler.
        8. Validates the handler's result.
        9. Persists or processes the recovery decision.

        Recovery ownership is obtained before reconciliation so that
        concurrent recovery workers cannot independently reconcile
        the same operation without backend authorization.

        Args:
            operation_id:
                Unique identifier of the operation being recovered.

            payload:
                Optional application-specific recovery data.

            owner_id:
                Identifier of the recovery worker. If omitted, a new
                identifier is generated for this recovery invocation.

        Returns:
            RecoveryOutcome describing the resulting recovery decision.

        Raises:
            TypeError:
                If operation_id is not a string.

            ValueError:
                If operation_id is empty.

            LookupError:
                If the operation does not exist in the backend.
        """

        # Validate the operation identifier before interacting
        # with the storage backend.
        if not isinstance(operation_id, str):
            raise TypeError(
                "operation_id must be a string"
            )

        if not operation_id:
            raise ValueError(
                "operation_id must not be empty"
            )

        # Generate a unique recovery owner when the caller does
        # not explicitly provide one.
        #
        # The owner identifier helps the backend distinguish
        # competing recovery workers.
        owner_id = owner_id or str(uuid4())

        # Retrieve the durable operation record.
        #
        # Recovery decisions must be based on persisted state,
        # not on assumptions about what happened during the
        # previous execution attempt.
        record = self.backend.get_by_id(
            operation_id
        )

        if record is None:
            raise LookupError(
                f"Operation {operation_id!r} not found"
            )

        # Completed operations are terminal from the perspective
        # of recovery.
        #
        # Reconciliation is unnecessary because the operation's
        # result has already been persisted.
        if record.status == OPERATION_STATES.COMPLETED:

            return RecoveryOutcome(
                operation_id=operation_id,
                decision=RecoveryDecision.COMPLETED,
                reason="Operation already completed.",
                result=record.result,
            )

        # Resolve the recovery handler using the function identity
        # stored in the operation record.
        #
        # The registry allows the recovery framework to remain
        # generic while applications define their own
        # reconciliation logic.
        function_name = (
            record.identity.function_name
        )

        handler = self.registry.get(
            function_name
        )

        # Ask the backend to acquire recovery ownership.
        #
        # The backend is responsible for enforcing ownership,
        # lease validity and state-transition rules.
        #
        # Recovery ownership prevents competing workers from
        # independently modifying the same operation.
        claim = self.backend.claim_recovery(
            operation_id=operation_id,
            owner_id=owner_id,
            lease_seconds=(
                self.policy.lease_seconds
            ),
        )

        # The backend may discover that the operation completed
        # between the initial read and the recovery claim.
        #
        # The backend's state is authoritative, so return its
        # persisted result rather than continuing recovery.
        if claim.disposition == ClaimDisposition.COMPLETED:

            return RecoveryOutcome(
                operation_id=operation_id,
                decision=RecoveryDecision.COMPLETED,
                reason="Operation already completed.",
                result=claim.record.result,
            )

        # Another worker currently owns the operation.
        #
        # This worker must not proceed with reconciliation
        # without acquiring recovery authority.
        if claim.disposition == ClaimDisposition.BUSY:

            return RecoveryOutcome(
                operation_id=operation_id,
                decision=RecoveryDecision.DEFER,
                reason="Operation has active ownership.",
            )

        # Recovery proceeds only when the backend explicitly
        # grants recovery ownership.
        #
        # Other dispositions are treated as unavailable
        # recovery authority rather than being interpreted
        # as permission to execute.
        if claim.disposition != ClaimDisposition.CLAIMED:

            return RecoveryOutcome(
                operation_id=operation_id,
                decision=RecoveryDecision.DEFER,
                reason=(
                    "Recovery claim unavailable: "
                    f"{claim.disposition}"
                ),
            )

        # Use the record and grant returned by the successful
        # claim instead of relying on the earlier read.
        #
        # The claimed record represents the state associated
        # with the backend's ownership transition.
        record = claim.record
        grant = claim.grant

        # Enforce the configured recovery attempt limit.
        #
        # This check happens after obtaining recovery authority
        # so the backend can persist the manual-intervention
        # transition using the valid recovery grant.
        if (
            record.recovery_attempts
            > self.policy.max_recovery_attempts
        ):

            updated = self.backend.mark_manual_intervention(
                operation_id=operation_id,
                recovery_token=grant.owner_token,
                expected_status=record.status,
                expected_version=record.version,
                reason=(
                    "Maximum recovery attempts exceeded."
                ),
            )

            # Stop automated recovery when the attempt limit
            # has been exceeded.
            #
            # Manual intervention avoids repeatedly attempting
            # reconciliation without a bounded recovery policy.
            return RecoveryOutcome(
                operation_id=operation_id,
                decision=(
                    RecoveryDecision.MANUAL_INTERVENTION
                ),
                reason=(
                    "Maximum recovery attempts exceeded."
                ),
            )

        # Construct the recovery context passed to the
        # application-defined handler.
        #
        # The handler receives the operation's durable record
        # and any application-provided recovery payload.
        #
        # The framework does not assume how an external system
        # should be reconciled.
        context = RecoveryContext(
            operation_id=operation_id,
            record=record,
            payload=payload,
        )

        # Execute application-defined reconciliation.
        #
        # The handler is responsible for inspecting the
        # external system and determining the appropriate
        # recovery decision.
        try:

            recovery_result = handler.recover(
                context
            )

        except Exception as exc:

            # Handler failures do not automatically imply
            # that the original operation failed.
            #
            # Its external side effects may still exist, so
            # the operation is deferred instead of blindly
            # restarting the original execution.
            return self._handle_handler_failure(
                operation_id=operation_id,
                record=record,
                grant=grant,
                exc=exc,
            )

        # Enforce the recovery handler's return contract.
        #
        # Invalid handler output cannot safely be interpreted
        # as a recovery decision.
        if not isinstance(
            recovery_result,
            RecoveryResult,
        ):

            return self._handle_invalid_handler_result(
                operation_id=operation_id,
                record=record,
                grant=grant,
                reason=(
                    "Recovery handler did not return "
                    "RecoveryResult."
                ),
            )

        # Validate the decision independently of the
        # RecoveryResult container.
        #
        # This prevents unsupported values from entering
        # the recovery state-transition logic.
        if not isinstance(
            recovery_result.decision,
            RecoveryDecision,
        ):

            return self._handle_invalid_handler_result(
                operation_id=operation_id,
                record=record,
                grant=grant,
                reason=(
                    "Invalid recovery decision."
                ),
            )

        # Delegate the validated decision to the decision
        # processor, which is responsible for coordinating
        # the corresponding backend state transition.
        return self._process_decision(
            operation_id=operation_id,
            record=record,
            grant=grant,
            recovery_result=recovery_result,
        )

    def _process_decision(
        self,
        *,
        operation_id,
        record,
        grant,
        recovery_result,
    ):
        """
        Process a validated recovery decision.

        Each recovery decision corresponds to a different
        state-transition strategy:

        COMPLETED:
            Persist the reconciled result and mark the operation
            completed.

        RESUME:
            Atomically transfer recovery authority to execution.

        DEFER:
            Persist the deferred recovery disposition.

        MANUAL_INTERVENTION:
            Persist the state requiring human intervention.

        This method delegates state mutations to the backend,
        which enforces the operation's ownership and version
        requirements.
        """

        decision = recovery_result.decision

        # COMPLETED
        # The handler has established that the operation
        # completed or can be reconciled to a completed result.
        #
        # The result must be persisted before the framework
        # reports completion.
        if decision == RecoveryDecision.COMPLETED:

            # A completed operation must have a result to
            # persist. Without one, the completion claim
            # cannot satisfy the recovery contract.
            if not recovery_result.has_result:

                return self._persist_manual_intervention(
                    operation_id=operation_id,
                    record=record,
                    grant=grant,
                    reason=(
                        "COMPLETED decision did not "
                        "provide a result."
                    ),
                )

            # Persist the recovered result through the backend.
            #
            # The recovery token, expected status and expected
            # version allow the backend to validate that this
            # recovery worker is still authorized to perform
            # the state transition.
            updated = self.backend.complete_recovery(
                operation_id=operation_id,
                recovery_token=grant.owner_token,
                expected_status=record.status,
                expected_version=record.version,
                result=recovery_result.result,
                reason=recovery_result.reason,
            )

            # Return the result persisted by the backend.
            return RecoveryOutcome(
                operation_id=operation_id,
                decision=RecoveryDecision.COMPLETED,
                reason=recovery_result.reason,
                result=updated.result,
            )

        # RESUME
        # The recovery handler has determined that the
        # operation can safely continue through normal
        # execution.
        #
        # Recovery must not simply call the original function.
        # Recovery ownership needs to be transferred to
        # execution through an atomic backend transition.
        if decision == RecoveryDecision.RESUME:

            # Atomically hand recovery ownership to execution.
            #
            # The backend validates the recovery token and
            # expected record version while granting the
            # execution ownership.
            #
            # This handoff prevents an independent worker
            # from claiming recovery while execution resumes.
            handoff = self.backend.handoff_recovery(
                operation_id=operation_id,
                recovery_token=grant.owner_token,
                execution_owner_id=grant.owner_id,
                lease_seconds=(
                    self.policy.lease_seconds
                ),
                expected_version=record.version,
            )

            # If the backend cannot establish the execution
            # handoff, recovery must not assume that execution
            # is authorized.
            if handoff.disposition != ClaimDisposition.CLAIMED:

                return RecoveryOutcome(
                    operation_id=operation_id,
                    decision=RecoveryDecision.DEFER,
                    reason=(
                        "Execution handoff "
                        "was unsuccessful."
                    ),
                )

            # RESUME indicates that the recovery process
            # successfully handed authority to execution.
            #
            # The caller/orchestrator is responsible for
            # continuing through the recovered execution path.
            return RecoveryOutcome(
                operation_id=operation_id,
                decision=RecoveryDecision.RESUME,
                reason=recovery_result.reason,
            )

        # DEFER
        # The handler cannot safely reconcile the operation
        # at this moment.
        #
        # The backend persists the deferred disposition so
        # the operation can be considered for recovery later.
        if decision == RecoveryDecision.DEFER:

            self.backend.defer_recovery(
                operation_id=operation_id,
                recovery_token=grant.owner_token,
                expected_status=record.status,
                expected_version=record.version,
                reason=recovery_result.reason,
            )

            return RecoveryOutcome(
                operation_id=operation_id,
                decision=RecoveryDecision.DEFER,
                reason=recovery_result.reason,
            )

        # MANUAL_INTERVENTION
        # The handler has determined that automated recovery
        # should not continue.
        #
        # This decision is persisted so the operation does
        # not remain eligible for automatic recovery attempts.
        if (
            decision
            == RecoveryDecision.MANUAL_INTERVENTION
        ):

            self.backend.mark_manual_intervention(
                operation_id=operation_id,
                recovery_token=grant.owner_token,
                expected_status=record.status,
                expected_version=record.version,
                reason=recovery_result.reason,
            )

            return RecoveryOutcome(
                operation_id=operation_id,
                decision=decision,
                reason=recovery_result.reason,
            )

        # Any decision not explicitly handled above is
        # considered unsupported.
        #
        # Persisting manual intervention is safer than
        # silently interpreting an unknown decision.
        return self._persist_manual_intervention(
            operation_id=operation_id,
            record=record,
            grant=grant,
            reason="Unsupported recovery decision.",
        )

    def _handle_handler_failure(
        self,
        *,
        operation_id,
        record,
        grant,
        exc,
    ):
        """
        Handle exceptions raised by the recovery handler.

        A recovery handler failure does not necessarily mean
        the operation's external side effects were rolled back.

        Therefore, the operation is deferred instead of
        automatically rerunning the original function.

        If the backend cannot persist the deferred transition,
        the backend mutation failure is propagated. The
        operation may remain RECOVERING until its lease
        expires and recovery ownership can be reclaimed.
        """

        # Construct a reason that preserves the exception
        # type and message for recovery observability.
        reason = (
            f"Recovery handler failed: "
            f"{type(exc).__name__}: {exc}"
        )

        try:

            # Persist the deferred state using the recovery
            # token and expected record version.
            #
            # The backend remains responsible for enforcing
            # that the current recovery worker owns the record.
            self.backend.defer_recovery(
                operation_id=operation_id,
                recovery_token=grant.owner_token,
                expected_status=record.status,
                expected_version=record.version,
                reason=reason,
            )

        except Exception:

            # Do not hide backend mutation failures.
            #
            # If this transition fails, the operation may
            # remain RECOVERING.
            #
            # Its lease expiry and recovery reclaim
            # mechanism are responsible for safely
            # recovering from this situation.
            raise

        # Report that automated recovery was deferred.
        return RecoveryOutcome(
            operation_id=operation_id,
            decision=RecoveryDecision.DEFER,
            reason=reason,
        )

    def _handle_invalid_handler_result(
        self,
        *,
        operation_id,
        record,
        grant,
        reason,
    ):
        """
        Handle invalid recovery-handler output.

        Invalid output is treated as a recovery contract
        violation rather than an execution instruction.

        The operation is moved toward manual intervention
        instead of interpreting the malformed result.
        """

        return self._persist_manual_intervention(
            operation_id=operation_id,
            record=record,
            grant=grant,
            reason=reason,
        )

    def _persist_manual_intervention(
        self,
        *,
        operation_id,
        record,
        grant,
        reason,
    ):
        """
        Persist the manual-intervention disposition.

        This helper centralizes the transition so that
        invalid recovery output and unsupported decisions
        follow the same backend mutation path.

        The backend validates recovery ownership and
        the expected record version before applying
        the state transition.
        """

        self.backend.mark_manual_intervention(
            operation_id=operation_id,
            recovery_token=grant.owner_token,
            expected_status=record.status,
            expected_version=record.version,
            reason=reason,
        )

        return RecoveryOutcome(
            operation_id=operation_id,
            decision=(
                RecoveryDecision.MANUAL_INTERVENTION
            ),
            reason=reason,
        )