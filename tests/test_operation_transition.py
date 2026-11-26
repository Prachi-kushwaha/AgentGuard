
import pytest

from agentguard.operation_record import OperationRecord
from agentguard.state_machine import (
    TransitionActor,
    InvalidOperationTransition,
)
from agentguard.transition import operation_transition


def test_pending_to_running_requires_claim_actor():
    record = OperationRecord(
        function_name="charge_payment",
    )

    updated = operation_transition(
        record,
        "RUNNING",
        actor=TransitionActor.CLAIM,
    )

    assert updated.status == "RUNNING"
    assert record.status == "PENDING"


def test_running_to_completed_requires_execution_actor():
    record = OperationRecord(
        function_name="charge_payment",
        status="RUNNING",
        attempt_number=1,
    )

    updated = operation_transition(
        record,
        "COMPLETED",
        actor=TransitionActor.EXECUTION,
    )

    assert updated.status == "COMPLETED"


def test_completed_cannot_reopen():
    record = OperationRecord(
        function_name="charge_payment",
        status="COMPLETED",
    )

    with pytest.raises(InvalidOperationTransition):
        operation_transition(
            record,
            "RUNNING",
            actor=TransitionActor.CLAIM,
        )


def test_unknown_cannot_directly_run():
    record = OperationRecord(
        function_name="charge_payment",
        status="UNKNOWN",
    )

    with pytest.raises(InvalidOperationTransition):
        operation_transition(
            record,
            "RUNNING",
            actor=TransitionActor.EXECUTION,
        )


def test_recovery_to_running_requires_recovery_actor():
    record = OperationRecord(
        function_name="charge_payment",
        status="RECOVERING",
    )

    with pytest.raises(InvalidOperationTransition):
        operation_transition(
            record,
            "RUNNING",
            actor=TransitionActor.EXECUTION,
        )


def test_recovery_authorized_to_running():
    record = OperationRecord(
        function_name="charge_payment",
        status="RECOVERING",
    )

    updated = operation_transition(
        record,
        "RUNNING",
        actor=TransitionActor.RECOVERY,
    )

    assert updated.status == "RUNNING"


def test_pending_to_running_rejects_execution_actor():
    record = OperationRecord(
        function_name="charge_payment",
    )

    with pytest.raises(InvalidOperationTransition):
        operation_transition(
            record,
            "RUNNING",
            actor=TransitionActor.EXECUTION,
        )


def test_running_to_completed_rejects_recovery_actor():
    record = OperationRecord(
        function_name="charge_payment",
        status="RUNNING",
        attempt_number=1,
    )

    with pytest.raises(InvalidOperationTransition):
        operation_transition(
            record,
            "COMPLETED",
            actor=TransitionActor.RECOVERY,
        )
