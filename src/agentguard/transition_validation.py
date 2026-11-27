from .state_machine import OperationState


class InvalidOperationTransitionPayload(ValueError):
    """
    Raised when an updated operation record contains an invalid payload
    for its target lifecycle state.

    A transition may be structurally permitted by the state machine,
    yet the updated record may still violate state-specific invariants.

    This exception represents a payload-level validation failure rather
    than a state-transition topology or actor-authorization failure.
    """
    pass


def validate_transition_payload(
    current_status,
    updated_record,
):
    """
    Validate the record contents against the operation's target state.

    State-machine validation determines whether a transition is allowed.
    This function validates whether the record's payload is consistent
    with the state it is transitioning into.

    For example:
        - COMPLETED must not contain an error.
        - FAILED must contain an error.
        - UNKNOWN must contain an explanation of the uncertain outcome.

    Args:
        current_status: The current operation status.
        updated_record: The proposed updated operation record.

    Raises:
        InvalidOperationTransitionPayload: If the updated record violates
            a payload invariant associated with its target state.

    Note:
        current_status is currently unused. This function validates
        target-state payload invariants rather than transition-specific
        payload rules.
    """

    # Normalize the target status into an enum.
    # This ensures the state-specific checks operate on recognized states
    # rather than arbitrary status strings.
    target = OperationState(updated_record.status)

    # A completed operation represents a successfully resolved outcome.
    # Keeping error unset avoids representing a successful result and
    # execution error simultaneously under this record contract.
    if target is OperationState.COMPLETED:

        if updated_record.error is not None:
            raise InvalidOperationTransitionPayload(
                "COMPLETED operation cannot contain an error"
            )

    # FAILED indicates a definitive unsuccessful outcome.
    # An error description is required so the failure is observable and
    # distinguishable from an operation that merely stopped executing.
    elif target is OperationState.FAILED:

        if updated_record.error is None:
            raise InvalidOperationTransitionPayload(
                "FAILED operation must contain an error"
            )

    # UNKNOWN represents an execution outcome that cannot be confidently
    # determined, for example when an external side effect may have occurred
    # but confirmation was lost.
    #
    # The error field must explain why the outcome is uncertain so recovery
    # logic and operators have context for subsequent reconciliation.
    elif target is OperationState.UNKNOWN:

        if updated_record.error is None:
            raise InvalidOperationTransitionPayload(
                "UNKNOWN operation must contain an explanation"
            )