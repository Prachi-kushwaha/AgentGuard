from datetime import datetime, timezone
from threading import Barrier, Thread
from dataclasses import replace

import pytest

from agentguard.operation_record import OperationRecord
from agentguard.storage.memory import (
    InMemoryIdempotencyBackend,
    OwnershipError,
    InvalidTransitionError,
    LeaseExpiredError,
)
from agentguard.storage.protocol import (
    ClaimDisposition,
    OperationIdentity,
)


def make_record(
    idempotency_key="key-1",
    fingerprint="fingerprint-1",
    status="PENDING",
):

    return OperationRecord(
        idempotency_key=idempotency_key,
        scope_id="default",
        function_name="test_function",
        fingerprint=fingerprint,
        status=status,
        result=None,
        error=None,
        attempt_number=0,
        recovery_attempts=0,
        metadata={},
        created_at=datetime.now(timezone.utc),
        updated_at=None,
        version=0,
    )


@pytest.fixture
def backend():

    return InMemoryIdempotencyBackend()


@pytest.fixture
def record():

    return make_record()


# ---------------------------------------------------------
# CLAIM
# ---------------------------------------------------------


def test_claim_new_operation(backend, record):

    result = backend.claim(
        record,
        owner_id="worker-1",
        lease_seconds=30,
    )

    assert result.disposition == ClaimDisposition.CLAIMED
    assert result.grant is not None
    assert result.record.status == "RUNNING"
    assert result.record.version == 1
    assert result.record.attempt_number == 1


def test_duplicate_claim_returns_busy(
    backend,
    record,
):

    first = backend.claim(
        record,
        owner_id="worker-1",
        lease_seconds=30,
    )

    second = backend.claim(
        record,
        owner_id="worker-2",
        lease_seconds=30,
    )

    assert first.disposition == ClaimDisposition.CLAIMED
    assert second.disposition == ClaimDisposition.BUSY


def test_same_key_different_fingerprint(
    backend,
    record,
):

    backend.claim(
        record,
        owner_id="worker-1",
        lease_seconds=30,
    )

    conflicting_record = make_record(
        fingerprint="different-fingerprint",
    )

    result = backend.claim(
        conflicting_record,
        owner_id="worker-2",
        lease_seconds=30,
    )

    assert result.disposition == ClaimDisposition.KEY_CONFLICT


def test_completed_operation_returns_completed(
    backend,
    record,
):

    result = backend.claim(
        record,
        owner_id="worker-1",
        lease_seconds=30,
    )

    grant = result.grant
    running = result.record

    completed = replace(
        running,
        status="COMPLETED",
        result={"success": True},
        version=running.version + 1,
        updated_at=datetime.now(timezone.utc),
    )

    backend.transition(
        running.operation_id,
        completed,
        expected_status="RUNNING",
        expected_version=running.version,
        owner_token=grant.owner_token,
    )

    duplicate = backend.claim(
        record,
        owner_id="worker-2",
        lease_seconds=30,
    )

    assert duplicate.disposition == ClaimDisposition.COMPLETED
    assert duplicate.record.result == {"success": True}


# ---------------------------------------------------------
# LOOKUP
# ---------------------------------------------------------


def test_get_by_identity(backend, record):

    backend.claim(
        record,
        owner_id="worker-1",
        lease_seconds=30,
    )

    identity = OperationIdentity(
        scope_id="default",
        function_name="test_function",
        idempotency_key="key-1",
    )

    result = backend.get(identity)

    assert result is not None
    assert result.operation_id == record.operation_id


def test_get_by_id(backend, record):

    result = backend.claim(
        record,
        owner_id="worker-1",
        lease_seconds=30,
    )

    stored = backend.get_by_id(
        result.record.operation_id
    )

    assert stored is not None
    assert stored.status == "RUNNING"


def test_missing_identity_returns_none(backend):

    identity = OperationIdentity(
        scope_id="default",
        function_name="test_function",
        idempotency_key="missing",
    )

    assert backend.get(identity) is None


def test_missing_operation_returns_none(backend):

    assert backend.get_by_id("missing") is None


# ---------------------------------------------------------
# TRANSITION
# ---------------------------------------------------------


def test_transition_completed(backend, record):

    result = backend.claim(
        record,
        owner_id="worker-1",
        lease_seconds=30,
    )

    grant = result.grant
    running = result.record

    completed = replace(
        running,
        status="COMPLETED",
        result="result",
        version=running.version + 1,
        updated_at=datetime.now(timezone.utc),
    )

    persisted = backend.transition(
        running.operation_id,
        completed,
        expected_status="RUNNING",
        expected_version=running.version,
        owner_token=grant.owner_token,
    )

    assert persisted.status == "COMPLETED"
    assert persisted.result == "result"
    assert persisted.version == 2


def test_transition_rejects_wrong_version(
    backend,
    record,
):

    result = backend.claim(
        record,
        owner_id="worker-1",
        lease_seconds=30,
    )

    grant = result.grant
    running = result.record

    updated = replace(
        running,
        status="COMPLETED",
        version=running.version + 1,
    )

    with pytest.raises(InvalidTransitionError):

        backend.transition(
            running.operation_id,
            updated,
            expected_status="RUNNING",
            expected_version=999,
            owner_token=grant.owner_token,
        )


def test_transition_rejects_wrong_status(
    backend,
    record,
):

    result = backend.claim(
        record,
        owner_id="worker-1",
        lease_seconds=30,
    )

    grant = result.grant
    running = result.record

    updated = replace(
        running,
        status="COMPLETED",
        version=running.version + 1,
    )

    with pytest.raises(InvalidTransitionError):

        backend.transition(
            running.operation_id,
            updated,
            expected_status="PENDING",
            expected_version=running.version,
            owner_token=grant.owner_token,
        )


def test_transition_rejects_wrong_owner(
    backend,
    record,
):

    result = backend.claim(
        record,
        owner_id="worker-1",
        lease_seconds=30,
    )

    running = result.record

    updated = replace(
        running,
        status="COMPLETED",
        version=running.version + 1,
    )

    with pytest.raises(OwnershipError):

        backend.transition(
            running.operation_id,
            updated,
            expected_status="RUNNING",
            expected_version=running.version,
            owner_token="wrong-token",
        )


def test_transition_rejects_operation_id_change(
    backend,
    record,
):

    result = backend.claim(
        record,
        owner_id="worker-1",
        lease_seconds=30,
    )

    grant = result.grant
    running = result.record

    updated = replace(
        running,
        operation_id="different-operation",
        status="COMPLETED",
        version=running.version + 1,
    )

    with pytest.raises(InvalidTransitionError):

        backend.transition(
            running.operation_id,
            updated,
            expected_status="RUNNING",
            expected_version=running.version,
            owner_token=grant.owner_token,
        )


# ---------------------------------------------------------
# LEASE
# ---------------------------------------------------------


def test_renew_lease(backend, record):

    result = backend.claim(
        record,
        owner_id="worker-1",
        lease_seconds=30,
    )

    grant = result.grant

    renewed = backend.renew_lease(
        result.record.operation_id,
        grant.owner_token,
        lease_seconds=60,
    )

    assert renewed.owner_token == grant.owner_token
    assert renewed.lease_expires_at > grant.lease_expires_at


def test_release_ownership(backend, record):

    result = backend.claim(
        record,
        owner_id="worker-1",
        lease_seconds=30,
    )

    grant = result.grant

    released = backend.release(
        result.record.operation_id,
        grant.owner_token,
    )

    assert released is True


def test_release_wrong_owner(backend, record):

    result = backend.claim(
        record,
        owner_id="worker-1",
        lease_seconds=30,
    )

    with pytest.raises(OwnershipError):

        backend.release(
            result.record.operation_id,
            "wrong-token",
        )


# ---------------------------------------------------------
# RECOVERY CLAIM
# ---------------------------------------------------------


def test_claim_recovery(backend):

    unknown = make_record(status="UNKNOWN")

    # Seed an UNKNOWN operation into storage.
    backend._records[unknown.operation_id] = unknown

    identity = backend._identity_from_record(unknown)

    backend._identity_index[identity] = unknown.operation_id

    result = backend.claim_recovery(
        unknown.operation_id,
        owner_id="recovery-worker",
        lease_seconds=30,
    )

    assert result.disposition == ClaimDisposition.CLAIMED
    assert result.record.status == "RECOVERING"
    assert result.record.version == 1
    assert result.record.recovery_attempts == 1
    assert result.grant is not None


def test_recovery_claim_is_busy(backend):

    unknown = make_record(status="UNKNOWN")

    backend._records[unknown.operation_id] = unknown

    identity = backend._identity_from_record(unknown)

    backend._identity_index[identity] = unknown.operation_id

    first = backend.claim_recovery(
        unknown.operation_id,
        owner_id="worker-1",
        lease_seconds=30,
    )

    second = backend.claim_recovery(
        unknown.operation_id,
        owner_id="worker-2",
        lease_seconds=30,
    )

    assert first.disposition == ClaimDisposition.CLAIMED
    assert second.disposition == ClaimDisposition.BUSY


def test_completed_operation_does_not_need_recovery(
    backend,
):

    completed = make_record(status="COMPLETED")

    backend._records[completed.operation_id] = completed

    identity = backend._identity_from_record(completed)

    backend._identity_index[identity] = completed.operation_id

    result = backend.claim_recovery(
        completed.operation_id,
        owner_id="worker-1",
        lease_seconds=30,
    )

    assert result.disposition == ClaimDisposition.COMPLETED


# ---------------------------------------------------------
# CONCURRENCY
# ---------------------------------------------------------


def test_concurrent_claims_only_one_worker_wins():

    backend = InMemoryIdempotencyBackend()

    record = make_record()

    barrier = Barrier(10)

    results = []

    def worker(worker_id):

        barrier.wait()

        result = backend.claim(
            record,
            owner_id=worker_id,
            lease_seconds=30,
        )

        results.append(result.disposition)

    threads = [
        Thread(
            target=worker,
            args=(f"worker-{i}",),
        )
        for i in range(10)
    ]

    for thread in threads:
        thread.start()

    for thread in threads:
        thread.join()

    assert results.count(ClaimDisposition.CLAIMED) == 1

    assert results.count(ClaimDisposition.BUSY) == 9