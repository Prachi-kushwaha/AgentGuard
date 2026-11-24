import pytest

from agentguard.transition_validation import (
    validate_transition_payload,
    InvalidOperationTransitionPayload,
)

from agentguard.operation_record import OperationRecord


def make_record(status, error=None, result=None):

    return OperationRecord(
        function_name="work",
        status=status,
        error=error,
        result=result,
    )


def test_completed_cannot_contain_error():

    record = make_record("COMPLETED", error="failure")

    with pytest.raises(InvalidOperationTransitionPayload):

        validate_transition_payload(
            "RUNNING",
            record,
        )


def test_failed_requires_error():

    record = make_record("FAILED", error=None)

    with pytest.raises(InvalidOperationTransitionPayload):

        validate_transition_payload(
            "RUNNING",
            record,
        )


def test_unknown_requires_explanation():

    record = make_record("UNKNOWN", error=None)

    with pytest.raises(InvalidOperationTransitionPayload):

        validate_transition_payload(
            "RUNNING",
            record,
        )


def test_completed_allows_none_result():

    record = make_record("COMPLETED", result=None)

    validate_transition_payload(
        "RUNNING",
        record,
    )


def test_failed_allows_empty_error_message():

    record = make_record("FAILED", error="")

    validate_transition_payload(
        "RUNNING",
        record,
    )


def test_unknown_allows_empty_error_message():

    record = make_record("UNKNOWN", error="")

    validate_transition_payload(
        "RUNNING",
        record,
    )


def test_recovering_payload_is_not_overconstrained():

    record = make_record(
        "RECOVERING",
        error="previous outcome uncertain",
    )

    validate_transition_payload(
        "UNKNOWN",
        record,
    )