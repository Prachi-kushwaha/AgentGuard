from enum import Enum


class OperationState(str, Enum):
    """
    Defines the lifecycle states an operation can occupy.

    Inheriting from str as well as Enum allows state values to behave
    conveniently as strings for serialization, logging, and storage,
    while retaining enum-based validation within the application.
    """

    PENDING = "PENDING"
    RUNNING = "RUNNING"
    UNKNOWN = "UNKNOWN"
    RECOVERING = "RECOVERING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class TransitionActor(str, Enum):
    """
    Identifies which subsystem is authorized to perform a state transition.

    Actor validation prevents a transition from being accepted merely
    because the target state is valid. The transition must also be performed
    by the subsystem responsible for that lifecycle action.
    """

    # Responsible for normal execution lifecycle transitions.
    EXECUTION = "EXECUTION"

    # Responsible for reconciling operations whose execution outcome
    # cannot be confidently determined.
    RECOVERY = "RECOVERY"

    # Responsible for initially claiming an operation and moving it
    # from PENDING into RUNNING.
    CLAIM = "CLAIM"


# Defines the state-machine topology.
#
# Each key represents the current state, and its associated set contains
# the states into which the operation is permitted to transition.
#
# This answers: "Is this transition structurally allowed?"
# It does not answer: "Which subsystem is authorized to perform it?"
# Actor authorization is handled separately by TRANSITION_ACTORS.
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
    # Terminal states have no outgoing transitions in this state machine.
    # A completed or failed operation cannot be reopened through this model.
    OperationState.COMPLETED: set(),
    OperationState.FAILED: set(),
}


# Maps each allowed state transition to the actor responsible for it.
#
# This answers: "Who is authorized to perform this particular transition?"
#
# Keeping actor authorization separate from the state topology makes
# transition rules easier to audit and prevents different subsystems from
# sharing transition permissions unintentionally.
TRANSITION_ACTORS = {
    # Initial execution ownership is established through the claim process.
    (OperationState.PENDING, OperationState.RUNNING):
        TransitionActor.CLAIM,

    # The execution subsystem owns normal execution outcomes.
    (OperationState.RUNNING, OperationState.COMPLETED):
        TransitionActor.EXECUTION,

    (OperationState.RUNNING, OperationState.FAILED):
        TransitionActor.EXECUTION,

    # UNKNOWN means the execution outcome could not be safely determined.
    # The execution subsystem records that uncertainty.
    (OperationState.RUNNING, OperationState.UNKNOWN):
        TransitionActor.EXECUTION,

    # Recovery is responsible for taking ownership of an uncertain operation.
    (OperationState.UNKNOWN, OperationState.RECOVERING):
        TransitionActor.RECOVERY,

    # Recovery may reconcile the operation into a definitive outcome.
    (OperationState.RECOVERING, OperationState.COMPLETED):
        TransitionActor.RECOVERY,

    (OperationState.RECOVERING, OperationState.FAILED):
        TransitionActor.RECOVERY,

    # Recovery may conclude that the outcome is still uncertain.
    # This allows the operation to return to UNKNOWN for future reconciliation.
    (OperationState.RECOVERING, OperationState.UNKNOWN):
        TransitionActor.RECOVERY,

    # Recovery may hand the operation back to normal execution.
    # This is a controlled recovery-to-execution handoff, rather than
    # an ordinary execution transition.
    (OperationState.RECOVERING, OperationState.RUNNING):
        TransitionActor.RECOVERY,
}


class InvalidOperationTransition(ValueError):
    """
    Raised when a requested state transition violates the state machine.

    This includes invalid state values, structurally forbidden transitions,
    and transitions attempted by an unauthorized actor.
    """
    pass


def validate_transition(
    current: str | OperationState,
    target: str | OperationState,
    actor: TransitionActor,
) -> None:
    """
    Validate whether a state transition is structurally allowed and
    authorized for the supplied actor.

    Args:
        current: The operation's current state.
        target: The requested destination state.
        actor: The subsystem attempting the transition.

    Raises:
        InvalidOperationTransition: If either state is invalid, the
            transition is forbidden, or the actor is unauthorized.
        TypeError: If actor is not a TransitionActor.

    This function validates transition policy only. It does not persist
    records, verify ownership tokens, perform atomic version checks, or
    guarantee that the current state has not changed concurrently.

    Those guarantees belong to the backend transition operation.
    """

    # Normalize string inputs into enum instances.
    # This allows callers to supply serialized state values while keeping
    # the rest of the validation logic enum-based.
    try:
        current_state = OperationState(current)
        target_state = OperationState(target)

    except ValueError as exc:
        # Preserve the original conversion error as the cause so debugging
        # can trace the failure back to the invalid state value.
        raise InvalidOperationTransition(
            f"Invalid operation state: {current!r} or {target!r}"
        ) from exc

    # Actor identity is part of the transition authorization contract.
    # We require the enum instead of accepting arbitrary strings so callers
    # cannot bypass the expected actor representation.
    if not isinstance(actor, TransitionActor):
        raise TypeError("actor must be a TransitionActor")

    # First validation layer: verify that the destination state exists
    # in the set of structurally permitted transitions from the current state.
    allowed = ALLOWED_TRANSITIONS[current_state]

    if target_state not in allowed:
        raise InvalidOperationTransition(
            f"Transition {current_state.value} -> "
            f"{target_state.value} is not allowed"
        )

    # Second validation layer: retrieve the actor authorized for this
    # exact transition. Authorization is transition-specific, not merely
    # based on the destination state or the actor's general capabilities.
    expected_actor = TRANSITION_ACTORS.get(
        (current_state, target_state)
    )

    # Require the supplied actor to match the policy exactly.
    # Even a structurally valid transition must not be performed by
    # a subsystem that is not responsible for that lifecycle action.
    if expected_actor is not actor:
        raise InvalidOperationTransition(
            f"Transition {current_state.value} -> "
            f"{target_state.value} requires actor "
            f"{expected_actor.value if expected_actor else 'UNKNOWN'}"
        )