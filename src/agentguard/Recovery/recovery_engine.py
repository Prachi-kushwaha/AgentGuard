from __future__ import annotations

from uuid import uuid4
from operation_record import OPERATION_STATES
from storage.protocol import ClaimDisposition
from recovery_models import (
    RecoveryContext,
    RecoveryDecision,
    RecoveryOutcome,
    RecoveryResult,
)
from .recovery_policy import RecoveryPolicy


class RecoveryEngine:

    def __init__(
        self,
        *,
        backend,
        registry,
        policy: RecoveryPolicy | None = None,
    ):

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

        if not isinstance(operation_id, str):
            raise TypeError(
                "operation_id must be a string"
            )

        if not operation_id:
            raise ValueError(
                "operation_id must not be empty"
            )

        owner_id = owner_id or str(uuid4())

        record = self.backend.get_by_id(
            operation_id
        )

        if record is None:
            raise LookupError(
                f"Operation {operation_id!r} not found"
            )

        # Completed operations do not need recovery.
        if record.status == OPERATION_STATES.COMPLETED:

            return RecoveryOutcome(
                operation_id=operation_id,
                decision=RecoveryDecision.COMPLETED,
                reason="Operation already completed.",
                result=record.result,
            )

        function_name = (
            record.identity.function_name
        )

        handler = self.registry.get(
            function_name
        )

        # Claim or reclaim recovery authority.
        claim = self.backend.claim_recovery(
            operation_id=operation_id,
            owner_id=owner_id,
            lease_seconds=(
                self.policy.lease_seconds
            ),
        )

        if claim.disposition == ClaimDisposition.COMPLETED:

            return RecoveryOutcome(
                operation_id=operation_id,
                decision=RecoveryDecision.COMPLETED,
                reason="Operation already completed.",
                result=claim.record.result,
            )

        if claim.disposition == ClaimDisposition.BUSY:

            return RecoveryOutcome(
                operation_id=operation_id,
                decision=RecoveryDecision.DEFER,
                reason="Operation has active ownership.",
            )

        if claim.disposition != ClaimDisposition.CLAIMED:

            return RecoveryOutcome(
                operation_id=operation_id,
                decision=RecoveryDecision.DEFER,
                reason=(
                    "Recovery claim unavailable: "
                    f"{claim.disposition}"
                ),
            )

        record = claim.record
        grant = claim.grant

        # The attempt limit is checked after obtaining
        # authority, allowing the backend to persist
        # the manual-intervention disposition safely.
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

            return RecoveryOutcome(
                operation_id=operation_id,
                decision=(
                    RecoveryDecision.MANUAL_INTERVENTION
                ),
                reason=(
                    "Maximum recovery attempts exceeded."
                ),
            )

        context = RecoveryContext(
            operation_id=operation_id,
            record=record,
            payload=payload,
        )

        # Execute application-defined reconciliation.
        try:

            recovery_result = handler.recover(
                context
            )

        except Exception as exc:

            return self._handle_handler_failure(
                operation_id=operation_id,
                record=record,
                grant=grant,
                exc=exc,
            )

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

        decision = recovery_result.decision

        if decision == RecoveryDecision.COMPLETED:

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

            updated = self.backend.complete_recovery(
                operation_id=operation_id,
                recovery_token=grant.owner_token,
                expected_status=record.status,
                expected_version=record.version,
                result=recovery_result.result,
                reason=recovery_result.reason,
            )

            return RecoveryOutcome(
                operation_id=operation_id,
                decision=RecoveryDecision.COMPLETED,
                reason=recovery_result.reason,
                result=updated.result,
            )

        if decision == RecoveryDecision.RESUME:

            handoff = self.backend.handoff_recovery(
                operation_id=operation_id,
                recovery_token=grant.owner_token,
                execution_owner_id=grant.owner_id,
                lease_seconds=(
                    self.policy.lease_seconds
                ),
                expected_version=record.version,
            )

            if handoff.disposition != ClaimDisposition.CLAIMED:

                return RecoveryOutcome(
                    operation_id=operation_id,
                    decision=RecoveryDecision.DEFER,
                    reason=(
                        "Execution handoff "
                        "was unsuccessful."
                    ),
                )

            return RecoveryOutcome(
                operation_id=operation_id,
                decision=RecoveryDecision.RESUME,
                reason=recovery_result.reason,
            )

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

        reason = (
            f"Recovery handler failed: "
            f"{type(exc).__name__}: {exc}"
        )

        try:

            self.backend.defer_recovery(
                operation_id=operation_id,
                recovery_token=grant.owner_token,
                expected_status=record.status,
                expected_version=record.version,
                reason=reason,
            )

        except Exception:

            # Do not hide backend mutation failures.
            # The operation may remain RECOVERING.
            #
            # Its lease expiry and recovery reclaim
            # mechanism are responsible for safely
            # recovering from this situation.
            raise

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