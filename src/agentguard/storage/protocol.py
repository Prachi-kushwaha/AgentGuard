from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from ..operation_record import OperationRecord
from ..state_machine import TransitionActor


class ClaimDisposition(Enum):
    """
    Describes the outcome of an attempt to acquire ownership of an operation.

    The backend uses this disposition to communicate what happened during the
    claim process. The execution engine should not independently infer ownership
    or operation state from the returned record; the disposition is the explicit
    contract describing the result of the claim attempt.
    """

    # The caller successfully acquired ownership and may proceed with execution.
    CLAIMED = "CLAIMED"

    # The operation has already reached a completed state.
    # The caller should return the previously persisted result rather than
    # executing the operation again.
    COMPLETED = "COMPLETED"

    # Another active owner currently holds the operation's execution lease.
    # The caller must not execute the operation concurrently with that owner.
    BUSY = "BUSY"

    # The operation cannot safely proceed through normal execution because its
    # persisted state requires recovery or reconciliation first.
    RECOVERY_REQUIRED = "RECOVERY_REQUIRED"

    # The same idempotency key was used, but the request identity conflicts
    # with the identity already associated with that key.
    # This prevents a key from silently being reused for a different operation.
    KEY_CONFLICT = "KEY_CONFLICT"


@dataclass(frozen=True)
class OwnershipGrant:
    """
    Represents the ownership authorization issued by the backend.

    An ownership grant is the authority that allows a caller to perform
    state-changing operations on a claimed record. It contains the owner
    identity, a token used to validate ownership, the lease expiry, and the
    actor responsible for the authorized transitions.

    The grant is immutable so that ownership credentials and their associated
    authorization context cannot be accidentally modified after issuance.
    """

    owner_id: str
    owner_token: str
    lease_expires_at: datetime
    actor: TransitionActor

    def __post_init__(self):
        """
        Validate the ownership grant at construction time.

        Grants are security- and concurrency-sensitive objects. Rejecting
        malformed values here prevents invalid ownership metadata from
        propagating into backend transition and lease-validation logic.
        """

        if not isinstance(self.owner_id, str):
            raise TypeError("owner_id must be a string")

        if not self.owner_id.strip():
            raise ValueError("owner_id cannot be empty")

        if not isinstance(self.owner_token, str):
            raise TypeError("owner_token must be a string")

        if not self.owner_token.strip():
            raise ValueError("owner_token cannot be empty")

        if not isinstance(self.lease_expires_at, datetime):
            raise TypeError("lease_expires_at must be a datetime")

        # A lease expiry must represent an unambiguous point in time.
        # Naive datetimes cannot reliably be compared across timezones,
        # which could lead to incorrect lease-expiration decisions.
        if (
            self.lease_expires_at.tzinfo is None
            or self.lease_expires_at.utcoffset() is None
        ):
            raise ValueError(
                "lease_expires_at must be timezone-aware"
            )


@dataclass(frozen=True)
class ClaimResult:
    """
    Encapsulates the backend's response to an operation claim attempt.

    The disposition communicates the outcome, while the operation record
    provides the persisted state associated with that outcome.

    An ownership grant is only valid when the caller has successfully claimed
    the operation. This class enforces that relationship so consumers do not
    have to repeatedly interpret or validate inconsistent claim responses.
    """

    disposition: ClaimDisposition
    record: OperationRecord
    grant: OwnershipGrant | None = None

    def __post_init__(self):
        """
        Enforce the structural invariants of a claim result.

        A CLAIMED result must carry authorization to operate on the record.
        Conversely, unsuccessful or non-owning outcomes must not carry a grant,
        because doing so could accidentally allow callers to treat a result as
        an ownership authorization.
        """

        if not isinstance(self.disposition, ClaimDisposition):
            raise TypeError(
                "disposition must be a ClaimDisposition"
            )

        if not isinstance(self.record, OperationRecord):
            raise TypeError(
                "record must be an OperationRecord"
            )

        # Ownership is required to proceed with execution.
        # A CLAIMED response without a grant would be an incomplete
        # authorization response from the backend.
        if self.disposition is ClaimDisposition.CLAIMED:
            if self.grant is None:
                raise ValueError(
                    "CLAIMED requires an ownership grant"
                )

        # All other dispositions represent outcomes where the caller has not
        # acquired execution ownership. Returning a grant in these cases would
        # create ambiguity about whether the caller is authorized to proceed.
        elif self.grant is not None:
            raise ValueError(
                f"{self.disposition.value} cannot include "
                "an ownership grant"
            )


@dataclass(frozen=True)
class OperationIdentity:
    """
    Defines the identity used to uniquely associate an operation with an
    idempotency key.

    The identity combines a scope, a function name, and an idempotency key.
    Together, these values allow the backend to distinguish operations while
    detecting accidental or intentional reuse of an idempotency key for a
    different operation.

    This object represents identity metadata rather than execution state.
    It is immutable because changing any of these fields after construction
    would alter which operation the identity refers to.
    """

    scope_id: str
    function_name: str
    idempotency_key: str

    def __post_init__(self):
        """
        Validate all identity components.

        Every component must be a non-empty string. Empty identity components
        would weaken the uniqueness and consistency guarantees expected by the
        idempotency backend and could result in ambiguous identity lookups.
        """

        for name, value in (
            ("scope_id", self.scope_id),
            ("function_name", self.function_name),
            ("idempotency_key", self.idempotency_key),
        ):
            if not isinstance(value, str):
                raise TypeError(f"{name} must be a string")

            if not value.strip():
                raise ValueError(f"{name} cannot be empty")