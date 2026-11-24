from .state_machine import OperationState


class InvalidOperationTransitionPayload(ValueError):
    pass


def validate_transition_payload(
    current_status,
    updated_record,
):

    target = OperationState(updated_record.status)

    if target is OperationState.COMPLETED:

        if updated_record.error is not None:
            raise InvalidOperationTransitionPayload(
                "COMPLETED operation cannot contain an error"
            )

    elif target is OperationState.FAILED:

        if updated_record.error is None:
            raise InvalidOperationTransitionPayload(
                "FAILED operation must contain an error"
            )

    elif target is OperationState.UNKNOWN:

        if updated_record.error is None:
            raise InvalidOperationTransitionPayload(
                "UNKNOWN operation must contain an explanation"
            )