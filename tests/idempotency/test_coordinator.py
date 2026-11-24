
from dataclasses import replace
from datetime import datetime, timezone, timedelta

import pytest

from agentguard.coordinator import (
    IdempotencyCoordinator,
    IdempotencyError,
    KeyConflictError,
    OperationBusyError,
    RecoveryRequiredError,
)
from agentguard.storage.protocol import (
    ClaimDisposition,
    ClaimResult,
    OwnershipGrant,
)
from agentguard.operation_record import OperationRecord


def sample_function(amount, currency="USD"):
    return amount, currency


class FakeBackend:

    def __init__(self, disposition=ClaimDisposition.CLAIMED):
        self.disposition = disposition
        self.last_claim = None
        self.last_transition = None

    def claim(self, record, owner_id, lease_seconds):
        self.last_claim = (record, owner_id, lease_seconds)

        grant = OwnershipGrant(
            owner_id=owner_id,
            owner_token="token-123",
            lease_expires_at=datetime.now(timezone.utc)
            + timedelta(seconds=lease_seconds),
        )

        if self.disposition is ClaimDisposition.CLAIMED:
            claimed_record = replace(record, status="RUNNING")

            return ClaimResult(
                disposition=self.disposition,
                record=claimed_record,
                grant=grant,
            )

        if self.disposition is ClaimDisposition.COMPLETED:
            completed_record = replace(
                record,
                status="COMPLETED",
                result="previous-result",
            )

            return ClaimResult(
                disposition=self.disposition,
                record=completed_record,
            )

        return ClaimResult(
            disposition=self.disposition,
            record=record,
        )

    def transition(
        self,
        operation_id,
        updated_record,
        expected_status,
        expected_version,
        owner_token,
    ):
        self.last_transition = (
            operation_id,
            updated_record,
            expected_status,
            expected_version,
            owner_token,
        )

        return updated_record


@pytest.fixture
def coordinator():
    backend = FakeBackend()

    return IdempotencyCoordinator(
        backend=backend,
        lease_seconds=30,
    )


def test_acquire_claims_operation(coordinator):
    result = coordinator.acquire(
        func=sample_function,
        args=(100,),
        kwargs={},
        idempotency_key="key-001",
        owner_id="worker-1",
    )

    assert result.disposition is ClaimDisposition.CLAIMED
    assert result.grant is not None
    assert result.record.status == "RUNNING"


def test_acquire_uses_default_arguments(coordinator):
    result = coordinator.acquire(
        func=sample_function,
        args=(100,),
        kwargs={},
        idempotency_key="key-001",
        owner_id="worker-1",
    )

    assert result.record.fingerprint is not None


def test_busy_disposition_raises():
    backend = FakeBackend(ClaimDisposition.BUSY)

    coordinator = IdempotencyCoordinator(backend)

    with pytest.raises(OperationBusyError):
        coordinator.acquire(
            sample_function,
            (100,),
            {},
            "key-001",
            "worker-1",
        )


def test_key_conflict_disposition_raises():
    backend = FakeBackend(ClaimDisposition.KEY_CONFLICT)

    coordinator = IdempotencyCoordinator(backend)

    with pytest.raises(KeyConflictError):
        coordinator.acquire(
            sample_function,
            (100,),
            {},
            "key-001",
            "worker-1",
        )


def test_recovery_required_disposition_raises():
    backend = FakeBackend(ClaimDisposition.RECOVERY_REQUIRED)

    coordinator = IdempotencyCoordinator(backend)

    with pytest.raises(RecoveryRequiredError):
        coordinator.acquire(
            sample_function,
            (100,),
            {},
            "key-001",
            "worker-1",
        )


def test_completed_disposition_is_returned():
    backend = FakeBackend(ClaimDisposition.COMPLETED)

    coordinator = IdempotencyCoordinator(backend)

    result = coordinator.acquire(
        sample_function,
        (100,),
        {},
        "key-001",
        "worker-1",
    )

    assert result.disposition is ClaimDisposition.COMPLETED
    assert result.record.result == "previous-result"


def test_record_success():
    backend = FakeBackend()
    coordinator = IdempotencyCoordinator(backend)

    record = OperationRecord(
        idempotency_key="key-001",
        function_name="sample_function",
        fingerprint="fingerprint",
        status="RUNNING",
        result=None,
        error=None,
        attempt_number=1,
        recovery_attempts=0,
        scope_id="default",
        version=0,
        metadata={},
    )

    grant = OwnershipGrant(
        owner_id="worker-1",
        owner_token="token-123",
        lease_expires_at=datetime.now(timezone.utc)
        + timedelta(seconds=30),
    )

    updated = coordinator.record_success(
        operation_id=record.operation_id,
        result="success",
        grant=grant,
        record=record,
    )

    assert updated.status == "COMPLETED"
    assert updated.result == "success"
    assert backend.last_transition is not None


def test_record_failure():
    backend = FakeBackend()
    coordinator = IdempotencyCoordinator(backend)

    record = OperationRecord(
        idempotency_key="key-001",
        function_name="sample_function",
        fingerprint="fingerprint",
        status="RUNNING",
        result=None,
        error=None,
        attempt_number=1,
        recovery_attempts=0,
        scope_id="default",
        version=0,
        metadata={},
    )

    grant = OwnershipGrant(
        owner_id="worker-1",
        owner_token="token-123",
        lease_expires_at=datetime.now(timezone.utc)
        + timedelta(seconds=30),
    )

    updated = coordinator.record_failure(
        record.operation_id,
        RuntimeError("failure"),
        grant,
        record,
    )

    assert updated.status == "FAILED"
    assert updated.error == "failure"


def test_record_unknown():
    backend = FakeBackend()
    coordinator = IdempotencyCoordinator(backend)

    record = OperationRecord(
        idempotency_key="key-001",
        function_name="sample_function",
        fingerprint="fingerprint",
        status="RUNNING",
        result=None,
        error=None,
        attempt_number=1,
        recovery_attempts=0,
        scope_id="default",
        version=0,
        metadata={},
    )

    grant = OwnershipGrant(
        owner_id="worker-1",
        owner_token="token-123",
        lease_expires_at=datetime.now(timezone.utc)
        + timedelta(seconds=30),
    )

    updated = coordinator.record_unknown(
        record.operation_id,
        TimeoutError("outcome uncertain"),
        grant,
        record,
    )

    assert updated.status == "UNKNOWN"
    assert updated.error == "outcome uncertain"


def test_invalid_lease():
    with pytest.raises(ValueError):
        IdempotencyCoordinator(
            FakeBackend(),
            lease_seconds=0,
        )


def test_boolean_lease_rejected():
    with pytest.raises(TypeError):
        IdempotencyCoordinator(
            FakeBackend(),
            lease_seconds=True,
        )


def test_empty_idempotency_key_rejected():
    coordinator = IdempotencyCoordinator(FakeBackend())

    with pytest.raises(ValueError):
        coordinator.acquire(
            sample_function,
            (100,),
            {},
            "",
            "worker-1",
        )


def test_empty_owner_rejected():
    coordinator = IdempotencyCoordinator(FakeBackend())

    with pytest.raises(ValueError):
        coordinator.acquire(
            sample_function,
            (100,),
            {},
            "key-001",
            "",
        )
