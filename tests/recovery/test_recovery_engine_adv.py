
# tests/recovery/test_recovery_engine_adv.py

from types import SimpleNamespace

import pytest

from agentguard.operation_record import OperationStates
from agentguard.storage.protocol import ClaimDisposition

from agentguard.recovery.recovery_models import (
    RecoveryDecision,
    RecoveryResult,
)

# Reuse the fixtures from the original recovery test module.
from test_recovery_engine import (
    backend,
    handler,
    operation_record,
    recovery_grant,
    registry,
    policy,
    engine,
)


def claim_response(disposition, record=None, grant=None):
    """Create the backend claim-response object expected by RecoveryEngine."""
    return SimpleNamespace(
        disposition=disposition,
        record=record,
        grant=grant,
    )


# ---------------------------------------------------------------------------
# Claim rejection
# ---------------------------------------------------------------------------


def test_handler_not_called_when_claim_returns_busy(
    engine, backend, handler
):
    backend.claim_recovery.return_value = claim_response(
        ClaimDisposition.BUSY
    )

    outcome = engine.recover("op-123")

    assert outcome.decision == RecoveryDecision.DEFER
    handler.recover.assert_not_called()


def test_handler_not_called_when_claim_returns_completed(
    engine, backend, handler
):
    backend.claim_recovery.return_value = claim_response(
        ClaimDisposition.COMPLETED,
        record=SimpleNamespace(result={"existing": True}),
    )

    outcome = engine.recover("op-123")

    assert outcome.decision == RecoveryDecision.COMPLETED
    assert outcome.result == {"existing": True}
    handler.recover.assert_not_called()


def test_handler_not_called_when_claim_is_unavailable(
    engine, backend, handler
):
    backend.claim_recovery.return_value = claim_response(
        ClaimDisposition.RECOVERY_REQUIRED
    )

    outcome = engine.recover("op-123")

    assert outcome.decision == RecoveryDecision.DEFER
    handler.recover.assert_not_called()


def test_claim_is_attempted_before_handler_execution(
    engine, backend, handler
):
    engine.recover("op-123")

    backend.claim_recovery.assert_called_once()
    handler.recover.assert_called_once()


def test_claim_rejection_does_not_persist_completion(
    engine, backend, handler
):
    backend.claim_recovery.return_value = claim_response(
        ClaimDisposition.BUSY
    )

    engine.recover("op-123")

    backend.complete_recovery.assert_not_called()
    handler.recover.assert_not_called()


# ---------------------------------------------------------------------------
# Handler invocation
# ---------------------------------------------------------------------------


def test_handler_called_only_once_per_recover_invocation(
    engine, handler
):
    engine.recover("op-123")

    assert handler.recover.call_count == 1


def test_handler_receives_recovery_context(
    engine, handler
):
    payload = {"payment_id": "pay-123"}

    engine.recover("op-123", payload=payload)

    context = handler.recover.call_args.args[0]

    assert context.operation_id == "op-123"
    assert context.payload == payload
    assert context.record is not None


# ---------------------------------------------------------------------------
# Recovery attempt limits
# ---------------------------------------------------------------------------


def test_attempt_limit_prevents_handler_execution(
    engine, backend, handler, operation_record, policy
):
    operation_record.recovery_attempts = (
        policy.max_recovery_attempts + 1
    )

    outcome = engine.recover("op-123")

    assert outcome.decision == RecoveryDecision.MANUAL_INTERVENTION
    handler.recover.assert_not_called()
    backend.mark_manual_intervention.assert_called_once()


def test_attempts_above_limit_prevent_handler_execution(
    engine, backend, handler, operation_record, policy
):
    operation_record.recovery_attempts = (
        policy.max_recovery_attempts + 10
    )

    outcome = engine.recover("op-123")

    assert outcome.decision == RecoveryDecision.MANUAL_INTERVENTION
    handler.recover.assert_not_called()
    backend.mark_manual_intervention.assert_called_once()


def test_attempt_limit_is_checked_after_successful_claim(
    engine, backend, handler, operation_record, policy
):
    operation_record.recovery_attempts = (
        policy.max_recovery_attempts + 1
    )

    engine.recover("op-123")

    backend.claim_recovery.assert_called_once()
    backend.mark_manual_intervention.assert_called_once()
    handler.recover.assert_not_called()


# ---------------------------------------------------------------------------
# Invalid handler results
# ---------------------------------------------------------------------------


def test_handler_returning_none_is_not_marked_completed(
    engine, backend, handler
):
    handler.recover.return_value = None

    outcome = engine.recover("op-123")

    assert outcome.decision == RecoveryDecision.MANUAL_INTERVENTION
    backend.complete_recovery.assert_not_called()
    backend.mark_manual_intervention.assert_called_once()


def test_handler_returning_wrong_type_is_not_marked_completed(
    engine, backend, handler
):
    handler.recover.return_value = "invalid"

    outcome = engine.recover("op-123")

    assert outcome.decision == RecoveryDecision.MANUAL_INTERVENTION
    backend.complete_recovery.assert_not_called()
    backend.mark_manual_intervention.assert_called_once()


def test_invalid_decision_is_not_marked_completed(
    engine, backend, handler
):
    handler.recover.return_value = RecoveryResult(
        decision="INVALID",
        reason="Invalid decision",
    )

    outcome = engine.recover("op-123")

    assert outcome.decision == RecoveryDecision.MANUAL_INTERVENTION
    backend.complete_recovery.assert_not_called()
    backend.mark_manual_intervention.assert_called_once()


# ---------------------------------------------------------------------------
# Handler failures
# ---------------------------------------------------------------------------


def test_handler_exception_does_not_mark_operation_completed(
    engine, backend, handler
):
    handler.recover.side_effect = RuntimeError("Handler failed")

    outcome = engine.recover("op-123")

    assert outcome.decision == RecoveryDecision.DEFER
    backend.complete_recovery.assert_not_called()
    backend.defer_recovery.assert_called_once()


def test_handler_exception_is_not_silently_marked_successful(
    engine, backend, handler
):
    handler.recover.side_effect = RuntimeError("Handler failed")

    outcome = engine.recover("op-123")

    assert outcome.decision == RecoveryDecision.DEFER
    assert "RuntimeError" in outcome.reason
    assert "Handler failed" in outcome.reason
    backend.complete_recovery.assert_not_called()


def test_handler_exception_and_defer_persistence_failure_propagate(
    engine, backend, handler
):
    handler.recover.side_effect = RuntimeError("Handler failed")
    backend.defer_recovery.side_effect = RuntimeError(
        "Defer persistence failed"
    )

    with pytest.raises(RuntimeError, match="Defer persistence failed"):
        engine.recover("op-123")


# ---------------------------------------------------------------------------
# Decision persistence failures
# ---------------------------------------------------------------------------


def test_handoff_persistence_failure_is_not_resume_success(
    engine, backend, handler
):
    handler.recover.return_value = RecoveryResult(
        decision=RecoveryDecision.RESUME,
        reason="Resume",
    )

    backend.handoff_recovery.side_effect = RuntimeError(
        "Handoff persistence failed"
    )

    with pytest.raises(RuntimeError, match="Handoff persistence failed"):
        engine.recover("op-123")


def test_defer_persistence_failure_propagates(
    engine, backend, handler
):
    handler.recover.return_value = RecoveryResult(
        decision=RecoveryDecision.DEFER,
        reason="Wait",
    )

    backend.defer_recovery.side_effect = RuntimeError(
        "Defer persistence failed"
    )

    with pytest.raises(RuntimeError, match="Defer persistence failed"):
        engine.recover("op-123")


def test_manual_intervention_persistence_failure_propagates(
    engine, backend, handler
):
    handler.recover.return_value = RecoveryResult(
        decision=RecoveryDecision.MANUAL_INTERVENTION,
        reason="Requires human review",
    )

    backend.mark_manual_intervention.side_effect = RuntimeError(
        "Manual intervention persistence failed"
    )

    with pytest.raises(
        RuntimeError,
        match="Manual intervention persistence failed",
    ):
        engine.recover("op-123")


# ---------------------------------------------------------------------------
# COMPLETED decision
# ---------------------------------------------------------------------------


def test_completed_decision_persists_result(
    engine, backend, handler
):
    handler.recover.return_value = RecoveryResult(
        decision=RecoveryDecision.COMPLETED,
        result={"payment_id": "pay-123"},
        reason="Reconciled",
    )

    outcome = engine.recover("op-123")

    backend.complete_recovery.assert_called_once()
    assert outcome.decision == RecoveryDecision.COMPLETED


def test_completed_decision_without_result_requires_manual_intervention(
    engine, backend, handler
):
    handler.recover.return_value = RecoveryResult(
        decision=RecoveryDecision.COMPLETED,
        reason="No result",
    )

    outcome = engine.recover("op-123")

    assert outcome.decision == RecoveryDecision.MANUAL_INTERVENTION
    backend.complete_recovery.assert_not_called()
    backend.mark_manual_intervention.assert_called_once()


# ---------------------------------------------------------------------------
# RESUME decision
# ---------------------------------------------------------------------------


def test_resume_decision_hands_operation_back_to_execution(
    engine, backend, handler
):
    handler.recover.return_value = RecoveryResult(
        decision=RecoveryDecision.RESUME,
        reason="Resume execution",
    )

    backend.handoff_recovery.return_value = claim_response(
        ClaimDisposition.CLAIMED
    )

    outcome = engine.recover("op-123")

    backend.handoff_recovery.assert_called_once()
    assert outcome.decision == RecoveryDecision.RESUME


def test_resume_handoff_rejection_returns_defer(
    engine, backend, handler
):
    handler.recover.return_value = RecoveryResult(
        decision=RecoveryDecision.RESUME,
        reason="Resume execution",
    )

    backend.handoff_recovery.return_value = claim_response(
        ClaimDisposition.BUSY
    )

    outcome = engine.recover("op-123")

    assert outcome.decision == RecoveryDecision.DEFER


# ---------------------------------------------------------------------------
# DEFER decision
# ---------------------------------------------------------------------------


def test_defer_decision_persists_defer(
    engine, backend, handler
):
    handler.recover.return_value = RecoveryResult(
        decision=RecoveryDecision.DEFER,
        reason="Wait for confirmation",
    )

    outcome = engine.recover("op-123")

    backend.defer_recovery.assert_called_once()
    assert outcome.decision == RecoveryDecision.DEFER


# ---------------------------------------------------------------------------
# MANUAL_INTERVENTION decision
# ---------------------------------------------------------------------------


def test_manual_intervention_decision_persists_transition(
    engine, backend, handler
):
    handler.recover.return_value = RecoveryResult(
        decision=RecoveryDecision.MANUAL_INTERVENTION,
        reason="Requires human review",
    )

    outcome = engine.recover("op-123")

    backend.mark_manual_intervention.assert_called_once()
    assert outcome.decision == RecoveryDecision.MANUAL_INTERVENTION
