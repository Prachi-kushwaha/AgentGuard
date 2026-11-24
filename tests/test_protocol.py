import pytest
from datetime import datetime, timezone, timedelta
from agentguard.operation_record import OperationRecord

from agentguard.storage.protocol import (
    ClaimDisposition,
    ClaimResult,
    OperationIdentity,
    OwnershipGrant,
)

def test_valid_identity():
    identity = OperationIdentity(
        scope_id="tenant-1",
        function_name="charge_payment",
        idempotency_key="payment-123",
    )

    assert identity.scope_id == "tenant-1"


def test_empty_key_rejected():
    with pytest.raises(ValueError):
        OperationIdentity(
            scope_id="tenant-1",
            function_name="charge_payment",
            idempotency_key=" ",
        )

def test_valid_ownership_grant():

    grant = OwnershipGrant(
        owner_id="worker-1",
        owner_token="token-1",
        lease_expires_at=datetime.now(timezone.utc)
        + timedelta(seconds=30),
    )

    assert grant.owner_token == "token-1"

def test_claimed_requires_grant():

    record = OperationRecord(
        function_name="charge_payment",
    )

    with pytest.raises(ValueError):
        ClaimResult(
            disposition=ClaimDisposition.CLAIMED,
            record=record,
        )