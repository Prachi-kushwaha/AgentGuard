# tests/recovery/test_recovery_engine.py

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from agentguard.operation_record import OperationStates
from agentguard.storage.protocol import ClaimDisposition

from agentguard.recovery.recovery_engine import RecoveryEngine
from agentguard.recovery.recovery_models import (
    RecoveryDecision,
    RecoveryResult,
)
from agentguard.recovery.recovery_policy import RecoveryPolicy


# Fixtures


@pytest.fixture
def operation_record():
    return SimpleNamespace(
        operation_id="op-123",
        status="FAILED",
        version=3,
        recovery_attempts=1,
        result=None,
        identity=SimpleNamespace(
            function_name="process_payment",
        ),
    )


@pytest.fixture
def recovery_grant():
    return SimpleNamespace(
        owner_token="recovery-token-123",
        owner_id="worker-recovery-123",
    )


@pytest.fixture
def backend(operation_record, recovery_grant):
    backend = MagicMock()

    backend.get_by_id.return_value = operation_record

    backend.claim_recovery.return_value = SimpleNamespace(
        disposition=ClaimDisposition.CLAIMED,
        record=operation_record,
        grant=recovery_grant,
    )

    backend.complete_recovery.return_value = SimpleNamespace(
        result={"payment_id": "pay-123"},
    )

    backend.handoff_recovery.return_value = SimpleNamespace(
        disposition=ClaimDisposition.CLAIMED,
    )

    return backend


@pytest.fixture
def handler():
    handler = MagicMock()

    handler.recover.return_value = RecoveryResult(
        decision=RecoveryDecision.COMPLETED,
        result={"payment_id": "pay-123"},
        reason="Payment reconciliation successful.",
    )

    return handler


@pytest.fixture
def registry(handler):
    registry = MagicMock()
    registry.get.return_value = handler
    return registry


@pytest.fixture
def policy():
    return RecoveryPolicy()


@pytest.fixture
def engine(backend, registry, policy):
    return RecoveryEngine(
        backend=backend,
        registry=registry,
        policy=policy,
    )


# Input validation


def test_recover_rejects_non_string_operation_id(engine):
    with pytest.raises(TypeError):
        engine.recover(123)


def test_recover_rejects_empty_operation_id(engine):
    with pytest.raises(ValueError):
        engine.recover("")


# Operation lookup


def test_recover_raises_when_operation_does_not_exist(
    engine,
    backend,
):
    backend.get_by_id.return_value = None

    with pytest.raises(LookupError):
        engine.recover("missing-operation")

    backend.claim_recovery.assert_not_called()


def test_recover_returns_completed_when_operation_already_completed(
    engine,
    backend,
    operation_record,
):
    operation_record.status = OperationStates.COMPLETED
    operation_record.result = {"existing": True}

    outcome = engine.recover("op-123")

    assert outcome.decision == RecoveryDecision.COMPLETED
    assert outcome.result == {"existing": True}

    backend.claim_recovery.assert_not_called()


# Recovery claim


def test_recover_returns_completed_when_claim_reports_completed(
    engine,
    backend,
):
    backend.claim_recovery.return_value = SimpleNamespace(
        disposition=ClaimDisposition.COMPLETED,
        record=SimpleNamespace(
            result={"existing": True},
        ),
    )

    outcome = engine.recover("op-123")

    assert outcome.decision == RecoveryDecision.COMPLETED
    assert outcome.result == {"existing": True}


def test_recover_defers_when_claim_is_busy(
    engine,
    backend,
):
    backend.claim_recovery.return_value = SimpleNamespace(
        disposition=ClaimDisposition.BUSY,
    )

    outcome = engine.recover("op-123")

    assert outcome.decision == RecoveryDecision.DEFER

    backend.claim_recovery.assert_called_once()


def test_recover_defers_when_claim_is_unavailable(
    engine,
    backend,
):
    backend.claim_recovery.return_value = SimpleNamespace(
        disposition=ClaimDisposition.RECOVERY_REQUIRED,
    )

    outcome = engine.recover("op-123")

    assert outcome.decision == RecoveryDecision.DEFER
    assert "claim unavailable" in outcome.reason.lower()


def test_recover_passes_owner_and_lease_to_backend(
    engine,
    backend,
    policy,
):
    engine.recover(
        "op-123",
        owner_id="worker-42",
    )

    backend.claim_recovery.assert_called_once_with(
        operation_id="op-123",
        owner_id="worker-42",
        lease_seconds=policy.lease_seconds,
    )


# Recovery attempt limit


def test_recover_marks_manual_intervention_when_attempt_limit_exceeded(
    engine,
    backend,
    operation_record,
    recovery_grant,
    policy,
):
    operation_record.recovery_attempts = (
        policy.max_recovery_attempts + 1
    )

    outcome = engine.recover("op-123")

    assert (
        outcome.decision
        == RecoveryDecision.MANUAL_INTERVENTION
    )

    backend.mark_manual_intervention.assert_called_once_with(
        operation_id="op-123",
        recovery_token=recovery_grant.owner_token,
        expected_status=operation_record.status,
        expected_version=operation_record.version,
        reason="Maximum recovery attempts exceeded.",
    )


# Handler execution


def test_recover_invokes_registered_handler(
    engine,
    registry,
    handler,
):
    engine.recover("op-123")

    registry.get.assert_called_once_with(
        "process_payment",
    )

    handler.recover.assert_called_once()


def test_recover_passes_context_to_handler(
    engine,
    handler,
):
    payload = {"payment_id": "pay-123"}

    engine.recover(
        "op-123",
        payload=payload,
    )

    context = handler.recover.call_args.args[0]

    assert context.operation_id == "op-123"
    assert context.payload == payload


def test_recover_generates_owner_id_when_not_provided(
    engine,
    backend,
):
    engine.recover("op-123")

    kwargs = backend.claim_recovery.call_args.kwargs

    assert isinstance(kwargs["owner_id"], str)
    assert kwargs["owner_id"]


# Handler failure


def test_recover_defers_when_handler_raises(
    engine,
    backend,
    handler,
    operation_record,
    recovery_grant,
):
    handler.recover.side_effect = RuntimeError(
        "External service unavailable",
    )

    outcome = engine.recover("op-123")

    assert outcome.decision == RecoveryDecision.DEFER
    assert "RuntimeError" in outcome.reason
    assert "External service unavailable" in outcome.reason

    backend.defer_recovery.assert_called_once_with(
        operation_id="op-123",
        recovery_token=recovery_grant.owner_token,
        expected_status=operation_record.status,
        expected_version=operation_record.version,
        reason=outcome.reason,
    )


def test_recover_propagates_defer_failure_after_handler_failure(
    engine,
    backend,
    handler,
):
    handler.recover.side_effect = RuntimeError(
        "Handler failed",
    )

    backend.defer_recovery.side_effect = RuntimeError(
        "Backend mutation failed",
    )

    with pytest.raises(RuntimeError, match="Backend mutation failed"):
        engine.recover("op-123")


# Invalid handler results


def test_recover_marks_manual_intervention_for_invalid_result(
    engine,
    backend,
    handler,
):
    handler.recover.return_value = "invalid-result"

    outcome = engine.recover("op-123")

    assert (
        outcome.decision
        == RecoveryDecision.MANUAL_INTERVENTION
    )

    backend.mark_manual_intervention.assert_called_once()


def test_recover_marks_manual_intervention_for_invalid_decision(
    engine,
    backend,
    handler,
):
    handler.recover.return_value = RecoveryResult(
        decision="INVALID",
        reason="Invalid decision",
    )

    outcome = engine.recover("op-123")

    assert (
        outcome.decision
        == RecoveryDecision.MANUAL_INTERVENTION
    )

    backend.mark_manual_intervention.assert_called_once()


# COMPLETED decision


def test_recover_persists_completed_result(
    engine,
    backend,
    handler,
    operation_record,
    recovery_grant,
):
    handler.recover.return_value = RecoveryResult(
        decision=RecoveryDecision.COMPLETED,
        result={"payment_id": "pay-123"},
        reason="Reconciled",
    )

    outcome = engine.recover("op-123")

    backend.complete_recovery.assert_called_once_with(
        operation_id="op-123",
        recovery_token=recovery_grant.owner_token,
        expected_status=operation_record.status,
        expected_version=operation_record.version,
        result={"payment_id": "pay-123"},
        reason="Reconciled",
    )

    assert outcome.decision == RecoveryDecision.COMPLETED


def test_recover_requires_result_for_completed_decision(
    engine,
    backend,
    handler,
):
    handler.recover.return_value = RecoveryResult(
        decision=RecoveryDecision.COMPLETED,
        reason="No result supplied",
    )

    outcome = engine.recover("op-123")

    assert (
        outcome.decision
        == RecoveryDecision.MANUAL_INTERVENTION
    )

    backend.mark_manual_intervention.assert_called_once()
    backend.complete_recovery.assert_not_called()


# RESUME decision


def test_recover_hands_operation_back_to_execution(
    engine,
    backend,
    handler,
    recovery_grant,
    operation_record,
    policy,
):
    handler.recover.return_value = RecoveryResult(
        decision=RecoveryDecision.RESUME,
        reason="Execution should resume",
    )

    outcome = engine.recover("op-123")

    backend.handoff_recovery.assert_called_once_with(
        operation_id="op-123",
        recovery_token=recovery_grant.owner_token,
        execution_owner_id=recovery_grant.owner_id,
        lease_seconds=policy.lease_seconds,
        expected_version=operation_record.version,
    )

    assert outcome.decision == RecoveryDecision.RESUME


def test_recover_defers_when_execution_handoff_fails(
    engine,
    backend,
    handler,
):
    handler.recover.return_value = RecoveryResult(
        decision=RecoveryDecision.RESUME,
        reason="Resume",
    )

    backend.handoff_recovery.return_value = SimpleNamespace(
        disposition=ClaimDisposition.BUSY,
    )

    outcome = engine.recover("op-123")

    assert outcome.decision == RecoveryDecision.DEFER
    assert "handoff" in outcome.reason.lower()


# DEFER decision


def test_recover_persists_defer_decision(
    engine,
    backend,
    handler,
    recovery_grant,
    operation_record,
):
    handler.recover.return_value = RecoveryResult(
        decision=RecoveryDecision.DEFER,
        reason="Wait for external confirmation",
    )

    outcome = engine.recover("op-123")

    backend.defer_recovery.assert_called_once_with(
        operation_id="op-123",
        recovery_token=recovery_grant.owner_token,
        expected_status=operation_record.status,
        expected_version=operation_record.version,
        reason="Wait for external confirmation",
    )

    assert outcome.decision == RecoveryDecision.DEFER


# MANUAL_INTERVENTION decision


def test_recover_persists_manual_intervention_decision(
    engine,
    backend,
    handler,
    recovery_grant,
    operation_record,
):
    handler.recover.return_value = RecoveryResult(
        decision=RecoveryDecision.MANUAL_INTERVENTION,
        reason="Cannot safely reconcile",
    )

    outcome = engine.recover("op-123")

    backend.mark_manual_intervention.assert_called_once_with(
        operation_id="op-123",
        recovery_token=recovery_grant.owner_token,
        expected_status=operation_record.status,
        expected_version=operation_record.version,
        reason="Cannot safely reconcile",
    )

    assert (
        outcome.decision
        == RecoveryDecision.MANUAL_INTERVENTION
    )


# Unsupported decision


def test_recover_marks_manual_intervention_for_unsupported_decision(
    engine,
    backend,
    handler,
):
    handler.recover.return_value = RecoveryResult(
        decision=None,
        reason="Unsupported",
    )

    outcome = engine.recover("op-123")

    assert (
        outcome.decision
        == RecoveryDecision.MANUAL_INTERVENTION
    )

    backend.mark_manual_intervention.assert_called_once()