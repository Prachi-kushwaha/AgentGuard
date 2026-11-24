import pytest

from agentguard.operation_record import OperationRecord
from agentguard.transition import operation_transition


def test_pending_to_running():

    record = OperationRecord(
        function_name="charge_payment",
    )

    updated = operation_transition(record, "RUNNING")

    assert updated.status == "RUNNING"
    assert record.status == "PENDING"


def test_running_to_completed():

    record = OperationRecord(
        function_name="charge_payment",
        status="RUNNING",
        attempt_number=1,
    )

    updated = operation_transition(record, "COMPLETED")

    assert updated.status == "COMPLETED"


def test_completed_cannot_reopen():

    record = OperationRecord(
        function_name="charge_payment",
        status="COMPLETED",
    )

    with pytest.raises(ValueError):
        operation_transition(record, "RUNNING")


def test_unknown_cannot_directly_run():

    record = OperationRecord(
        function_name="charge_payment",
        status="UNKNOWN",
    )

    with pytest.raises(ValueError):
        operation_transition(record, "RUNNING")


def test_recovery_to_running_requires_authorization():

    record = OperationRecord(
        function_name="charge_payment",
        status="RECOVERING",
    )

    with pytest.raises(ValueError):
        operation_transition(record, "RUNNING")


def test_recovery_authorized_to_running():

    record = OperationRecord(
        function_name="charge_payment",
        status="RECOVERING",
    )

    updated = operation_transition(
        record,
        "RUNNING",
        recovery_authorized=True,
    )

    assert updated.status == "RUNNING"