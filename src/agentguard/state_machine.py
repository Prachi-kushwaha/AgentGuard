from enum import Enum


class OperationState(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    UNKNOWN = "UNKNOWN"
    RECOVERING = "RECOVERING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class TransitionActor(str, Enum):
    EXECUTION = "EXECUTION"
    RECOVERY = "RECOVERY"
    CLAIM = "CLAIM"


ALLOWED_TRANSITIONS = {
    OperationState.PENDING: {
        OperationState.RUNNING,
    },
    OperationState.RUNNING: {
        OperationState.COMPLETED,
        OperationState.FAILED,
        OperationState.UNKNOWN,
    },
    OperationState.UNKNOWN: {
        OperationState.RECOVERING,
    },
    OperationState.RECOVERING: {
        OperationState.COMPLETED,
        OperationState.FAILED,
        OperationState.UNKNOWN,
        OperationState.RUNNING,
    },
    OperationState.COMPLETED: set(),
    OperationState.FAILED: set(),
}


TRANSITION_ACTORS = {
    (OperationState.PENDING, OperationState.RUNNING):
        TransitionActor.CLAIM,

    (OperationState.RUNNING, OperationState.COMPLETED):
        TransitionActor.EXECUTION,

    (OperationState.RUNNING, OperationState.FAILED):
        TransitionActor.EXECUTION,

    (OperationState.RUNNING, OperationState.UNKNOWN):
        TransitionActor.EXECUTION,

    (OperationState.UNKNOWN, OperationState.RECOVERING):
        TransitionActor.RECOVERY,

    (OperationState.RECOVERING, OperationState.COMPLETED):
        TransitionActor.RECOVERY,

    (OperationState.RECOVERING, OperationState.FAILED):
        TransitionActor.RECOVERY,

    (OperationState.RECOVERING, OperationState.UNKNOWN):
        TransitionActor.RECOVERY,

    (OperationState.RECOVERING, OperationState.RUNNING):
        TransitionActor.RECOVERY,
}


class InvalidOperationTransition(ValueError):
    pass


def validate_transition(
    current: str | OperationState,
    target: str | OperationState,
    actor: TransitionActor,
) -> None:

    try:
        current_state = OperationState(current)
        target_state = OperationState(target)

    except ValueError as exc:
        raise InvalidOperationTransition(
            f"Invalid operation state: {current!r} or {target!r}"
        ) from exc

    if not isinstance(actor, TransitionActor):
        raise TypeError("actor must be a TransitionActor")

    allowed = ALLOWED_TRANSITIONS[current_state]

    if target_state not in allowed:
        raise InvalidOperationTransition(
            f"Transition {current_state.value} -> "
            f"{target_state.value} is not allowed"
        )

    expected_actor = TRANSITION_ACTORS.get(
        (current_state, target_state)
    )

    if expected_actor is not actor:
        raise InvalidOperationTransition(
            f"Transition {current_state.value} -> "
            f"{target_state.value} requires actor "
            f"{expected_actor.value if expected_actor else 'UNKNOWN'}"
        )