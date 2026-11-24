import pytest

from agentguard.state_machine import (
    OperationState,
    TransitionActor,
    InvalidOperationTransition,
    validate_transition,
)


@pytest.mark.parametrize(
    ("current", "target", "actor"),
    [
        ("PENDING", "RUNNING", TransitionActor.CLAIM),
        ("RUNNING", "COMPLETED", TransitionActor.EXECUTION),
        ("RUNNING", "FAILED", TransitionActor.EXECUTION),
        ("RUNNING", "UNKNOWN", TransitionActor.EXECUTION),
        ("UNKNOWN", "RECOVERING", TransitionActor.RECOVERY),
        ("RECOVERING", "COMPLETED", TransitionActor.RECOVERY),
        ("RECOVERING", "FAILED", TransitionActor.RECOVERY),
        ("RECOVERING", "UNKNOWN", TransitionActor.RECOVERY),
        ("RECOVERING", "RUNNING", TransitionActor.RECOVERY),
    ],
)
def test_valid_transitions(current, target, actor):

    validate_transition(current, target, actor)


@pytest.mark.parametrize(
    ("current", "target"),
    [
        ("COMPLETED", "RUNNING"),
        ("COMPLETED", "FAILED"),
        ("FAILED", "RUNNING"),
        ("FAILED", "COMPLETED"),
        ("UNKNOWN", "COMPLETED"),
        ("UNKNOWN", "RUNNING"),
        ("PENDING", "COMPLETED"),
        ("PENDING", "FAILED"),
        ("RUNNING", "RECOVERING"),
    ],
)
def test_invalid_transitions(current, target):

    with pytest.raises(InvalidOperationTransition):

        validate_transition(
            current,
            target,
            TransitionActor.EXECUTION,
        )


def test_wrong_actor_rejected():

    with pytest.raises(InvalidOperationTransition):

        validate_transition(
            "UNKNOWN",
            "RECOVERING",
            TransitionActor.EXECUTION,
        )


def test_wrong_actor_for_initial_claim_rejected():

    with pytest.raises(InvalidOperationTransition):

        validate_transition(
            "PENDING",
            "RUNNING",
            TransitionActor.EXECUTION,
        )


def test_unknown_state_rejected():

    with pytest.raises(InvalidOperationTransition):

        validate_transition(
            "INVALID",
            "RUNNING",
            TransitionActor.CLAIM,
        )


def test_invalid_actor_type_rejected():

    with pytest.raises(TypeError):

        validate_transition(
            "PENDING",
            "RUNNING",
            "CLAIM",
        )