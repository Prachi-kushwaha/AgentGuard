from datetime import datetime, timedelta, timezone
from threading import RLock
from uuid import uuid4
from dataclasses import replace

from ..operation_record import OperationRecord, OPERATION_STATES
from .protocol import (
    ClaimDisposition,
    ClaimResult,
    OperationIdentity,
    OwnershipGrant,
)
from ..state_machine import (
    OperationState,
    TransitionActor,
    validate_transition,
)
from ..transition_validation import (
    validate_transition_payload,
)

class BackendError(RuntimeError):
    """Base exception for backend errors."""


class OperationNotFoundError(BackendError):
    """Raised when an operation cannot be found."""


class OwnershipError(BackendError):
    """Raised when ownership validation fails."""


class LeaseExpiredError(OwnershipError):
    """Raised when the ownership lease has expired."""


class InvalidTransitionError(BackendError):
    """Raised when a conditional transition cannot be performed."""

class OptimisticConcurrencyError(BackendError):
    """Raised when a conditional transition cannot be performed."""

class InvalidStateError(BackendError):
    """Raised when a conditional transition cannot be performed."""


class InMemoryIdempotencyBackend:

    """Thread-safe in-memory backend for operation records, identity indexes, and ownership grants."""

    def __init__(self):

        """Initialize in-memory storage for operation records, identity lookup, and ownership grants. The lock protects mutations and reads that span shared backend state."""
        self._records: dict[str, OperationRecord] = {}
        self._identity_index: dict[OperationIdentity, str] = {}

        # operation_id -> OwnershipGrant
        self._ownership: dict[str, OwnershipGrant] = {}

        # Protect shared records, indexes, and ownership grants as one backend state.
        self._lock = RLock()

    @staticmethod
    def _now():
        """Return the current UTC time used for lease expiry and record timestamps."""
        return datetime.now(timezone.utc)

    @staticmethod
    def _validate_lease_seconds(lease_seconds):

        """Reject invalid lease durations before they are used to create or renew ownership."""
        if isinstance(lease_seconds, bool):
            raise TypeError("lease_seconds must be numeric")

        if not isinstance(lease_seconds, (int, float)):
            raise TypeError("lease_seconds must be numeric")

        if lease_seconds <= 0:
            raise ValueError("lease_seconds must be greater than zero")

    @staticmethod
    def _validate_owner_id(owner_id):

        """Validate that an ownership identifier is a non-empty string."""
        if not isinstance(owner_id, str):
            raise TypeError("owner_id must be a string")

        if not owner_id.strip():
            raise ValueError("owner_id cannot be empty")

    @staticmethod
    def _validate_identity(identity):

        """Ensure identity lookups use the backend's expected identity type."""
        if not isinstance(identity, OperationIdentity):
            raise TypeError("identity must be an OperationIdentity")

    @staticmethod
    def _identity_from_record(record):

        """Build the idempotency identity from the immutable identity fields stored in a record."""
        return OperationIdentity(
            scope_id=record.scope_id,
            function_name=record.function_name,
            idempotency_key=record.idempotency_key,
        )

    def _create_grant(self, operation_id, owner_id, lease_seconds, actor=TransitionActor.EXECUTION):

        """Create and store an ownership grant with a fresh token and bounded lease."""
        grant = OwnershipGrant(
            owner_id=owner_id,
            owner_token=str(uuid4()),
            lease_expires_at=self._now() + timedelta(
                seconds=lease_seconds
            ),
            actor = actor
        )

        self._ownership[operation_id] = grant

        return grant

    def _lease_is_active(self, operation_id):

        """Check whether the operation currently has an unexpired ownership lease."""
        grant = self._ownership.get(operation_id)

        if grant is None:
            return False

        return grant.lease_expires_at > self._now()

    def _remove_ownership(self, operation_id):

        """Remove an operation's ownership grant from the backend."""
        self._ownership.pop(operation_id, None)

    def _validate_ownership(
        self,
        operation_id,
        owner_token,
    ):

        """Validate the ownership token and lease before authorizing a mutation."""
        grant = self._ownership.get(operation_id)

        if grant is None:
            raise OwnershipError(
                "Operation has no active ownership grant"
            )

        if grant.owner_token != owner_token:
            raise OwnershipError(
                "Invalid owner token"
            )

        if grant.lease_expires_at <= self._now():

            # Remove expired ownership.
            self._remove_ownership(operation_id)

            raise LeaseExpiredError(
                "Ownership lease has expired"
            )

        return grant

    def claim(
        self,
        record,
        owner_id,
        lease_seconds,

    ):

        """Atomically claim a new operation or determine the disposition of an existing idempotent operation. The lock makes identity lookup, state checks, record updates, and grant creation consistent."""
        if not isinstance(record, OperationRecord):
            raise TypeError("record must be an OperationRecord")

        self._validate_owner_id(owner_id)
        self._validate_lease_seconds(lease_seconds)

        identity = self._identity_from_record(record)

        with self._lock:

            operation_id = self._identity_index.get(identity)

            # New operation

            if operation_id is None:

                claimed_record = record

                if claimed_record.status != "PENDING":
                    raise InvalidTransitionError(
                        "New operation must start in PENDING"
                    )

                claimed_record = replace(
                    claimed_record,
                    status="RUNNING",
                    attempt_number=max(
                        1,
                        claimed_record.attempt_number,
                    ),
                    updated_at=self._now(),
                    version=claimed_record.version + 1,
                )

                self._records[claimed_record.operation_id] = (
                    claimed_record
                )

                self._identity_index[identity] = (
                    claimed_record.operation_id
                )

                grant = self._create_grant(
                    claimed_record.operation_id,
                    owner_id,
                    lease_seconds,
                    actor=TransitionActor.EXECUTION
                )

                return ClaimResult(
                    disposition=ClaimDisposition.CLAIMED,
                    record=claimed_record,
                    grant=grant,
                )

            # Existing operation

            existing = self._records[operation_id]

            # Same idempotency key but different arguments.
            if existing.fingerprint != record.fingerprint:

                return ClaimResult(
                    disposition=ClaimDisposition.KEY_CONFLICT,
                    record=existing,
                )

            # Already completed

            if existing.status == "COMPLETED":

                return ClaimResult(
                    disposition=ClaimDisposition.COMPLETED,
                    record=existing,
                )

            # Uncertain state

            if existing.status in {
                "UNKNOWN",
                "RECOVERING",
            }:

                return ClaimResult(
                    disposition=ClaimDisposition.RECOVERY_REQUIRED,
                    record=existing,
                )

            # Existing active owner

            if self._lease_is_active(operation_id):

                return ClaimResult(
                    disposition=ClaimDisposition.BUSY,
                    record=existing,
                )

            # Expired RUNNING operation

            if existing.status == "RUNNING":

                return ClaimResult(
                    disposition=ClaimDisposition.RECOVERY_REQUIRED,
                    record=existing,
                )

            # Other terminal states

            if existing.status == "FAILED":

                return ClaimResult(
                    disposition=ClaimDisposition.RECOVERY_REQUIRED,
                    record=existing,
                )
            # revisit later
            if existing.status == "PENDING":

                # PENDING is only expected before an initial claim.
                # If an existing PENDING operation has no owner,
                # it can safely be claimed.
                claimed_record = replace(
                    existing,
                    status="RUNNING",
                    attempt_number=max(
                        1,
                        existing.attempt_number,
                    ),
                    updated_at=self._now(),
                    version=existing.version + 1,
                )

                self._records[operation_id] = claimed_record

                grant = self._create_grant(
                    operation_id,
                    owner_id,
                    lease_seconds,
                    actor=TransitionActor.EXECUTION
                )

                return ClaimResult(
                    disposition=ClaimDisposition.CLAIMED,
                    record=claimed_record,
                    grant=grant,
                )

            return ClaimResult(
                disposition=ClaimDisposition.RECOVERY_REQUIRED,
                record=existing,
            )

    def get(self, identity):

        """Retrieve an operation by its idempotency identity."""
        self._validate_identity(identity)

        with self._lock:

            operation_id = self._identity_index.get(identity)

            if operation_id is None:
                return None

            return self._records[operation_id]

    def get_by_id(self, operation_id):

        """Retrieve a persisted operation record by operation ID."""
        if not isinstance(operation_id, str):
            raise TypeError("operation_id must be a string")

        with self._lock:

            return self._records.get(operation_id)

    def renew_lease(
        self,
        operation_id,
        owner_token,
        lease_seconds,
    ):

        """Extend the lease of the current owner without changing its ownership token."""
        self._validate_lease_seconds(lease_seconds)

        if not isinstance(owner_token, str):
            raise TypeError("owner_token must be a string")

        with self._lock:

            if operation_id not in self._records:
                raise OperationNotFoundError(
                    "Operation not found"
                )

            grant = self._validate_ownership(
                operation_id,
                owner_token,
            )

            renewed_grant = OwnershipGrant(
                owner_id=grant.owner_id,
                owner_token=grant.owner_token,
                lease_expires_at=self._now() + timedelta(
                    seconds=lease_seconds
                ),
                actor=grant.actor
            )

            self._ownership[operation_id] = renewed_grant

            return renewed_grant

    def transition(
        self,
        operation_id,
        updated_record,
        expected_status,
        expected_version,
        owner_token
    ):

        """Apply a guarded state transition after validating ownership, actor permissions, transition payload, and optimistic concurrency expectations."""
        if not isinstance(updated_record, OperationRecord):
            raise TypeError(
                "updated_record must be an OperationRecord"
            )

        if not isinstance(owner_token, str):
            raise TypeError("owner_token must be a string")

        with self._lock:

            current = self._records.get(operation_id)

            if current is None:
                raise OperationNotFoundError(
                    "Operation not found"
                )

            grant = self._validate_ownership(
                operation_id,
                owner_token,
            )

            validate_transition(
                current=current.status,
                target=updated_record.status,
                actor=grant.actor,
            )

            validate_transition_payload(
                current_status=current.status,
                updated_record=updated_record,
            )

            # Optimistic concurrency checks prevent a stale caller from overwriting a newer state.
            if current.status != expected_status:

                raise InvalidTransitionError(
                    f"Expected status {expected_status}, "
                    f"found {current.status}"
                )

            if current.version != expected_version:

                raise InvalidTransitionError(
                    f"Expected version {expected_version}, "
                    f"found {current.version}"
                )

            if updated_record.operation_id != current.operation_id:

                raise InvalidTransitionError(
                    "Operation ID cannot be changed"
                )

            if self._identity_from_record(updated_record) != (
                self._identity_from_record(current)
            ):

                raise InvalidTransitionError(
                    "Operation identity cannot be changed"
                )

            if updated_record.version != current.version + 1:

                raise InvalidTransitionError(
                    "Version must increase by exactly one"
                )

            updated = updated_record

            self._records[operation_id] = updated

            # Terminal or uncertain outcomes relinquish ownership so the record can be reclaimed or reconciled.
            if updated.status in {
                "COMPLETED",
                "FAILED",
                "UNKNOWN",
            }:

                self._remove_ownership(operation_id)

            return updated

    def claim_recovery(
        self,
        operation_id,
        owner_id,
        lease_seconds,
    ):

        """Acquire recovery ownership and atomically transition an UNKNOWN operation into RECOVERING."""
        self._validate_owner_id(owner_id)
        self._validate_lease_seconds(lease_seconds)

        with self._lock:

            current = self._records.get(operation_id)

            if current is None:
                raise OperationNotFoundError(
                    "Operation not found"
                )

            # Completed operations are replayed without acquiring recovery ownership.

            if current.status == "COMPLETED":

                return ClaimResult(
                    disposition=ClaimDisposition.COMPLETED,
                    record=current,
                )

            # Recovery is initially restricted to UNKNOWN, where execution outcome is uncertain.

            if current.status != "UNKNOWN":

                return ClaimResult(
                    disposition=ClaimDisposition.RECOVERY_REQUIRED,
                    record=current,
                )

            # Do not compete with an active owner; recovery claims require an expired or absent lease.

            if self._lease_is_active(operation_id):

                return ClaimResult(
                    disposition=ClaimDisposition.BUSY,
                    record=current,
                )

            # Construct the proposed recovery transition

            recovering_record = replace(
                current,
                status="RECOVERING",
                recovery_attempts=current.recovery_attempts + 1,
                updated_at=self._now(),
                version=current.version + 1,
            )

            # Validate the state transition

            validate_transition(
                current=current.status,
                target=recovering_record.status,
                actor=TransitionActor.RECOVERY,
            )

            # Validate the transition payload

            validate_transition_payload(
                current_status=current.status,
                updated_record=recovering_record,
            )

            # Create recovery ownership

            grant = self._create_grant(
                operation_id,
                owner_id,
                lease_seconds,
                actor=TransitionActor.RECOVERY,
            )

            # Commit the record only after the transition and payload have been validated.

            self._records[operation_id] = recovering_record

            return ClaimResult(
                disposition=ClaimDisposition.CLAIMED,
                record=recovering_record,
                grant=grant,
            )


    def handoff_recovery(
    self,
    operation_id,
    recovery_token,
    execution_owner_id,
    lease_seconds,
    expected_version,
):
        """
        Transfer ownership from a recovery actor to an execution actor.

        This performs a guarded RECOVERING -> RUNNING transition and
        replaces the recovery grant with a fresh execution grant.
        """

        self._validate_owner_id(execution_owner_id)
        self._validate_lease_seconds(lease_seconds)

        if not isinstance(recovery_token, str):
            raise TypeError("recovery_token must be a string")

        if isinstance(expected_version, bool) or not isinstance(
            expected_version, int
        ):
            raise TypeError("expected_version must be an integer")

        with self._lock:

            current = self._records.get(operation_id)

            if current is None:
                raise OperationNotFoundError(
                    "Operation not found"
                )

            # Validate the recovery token and lease before transferring authority.
            recovery_grant = self._validate_ownership(
                operation_id,
                recovery_token,
            )

            # Only a recovery grant is allowed to initiate this handoff.
            if recovery_grant.actor != TransitionActor.RECOVERY:
                raise OwnershipError(
                    "Handoff requires recovery ownership"
                )

            # Optimistic concurrency checks prevent a stale caller from overwriting a newer state.
            if current.status != "RECOVERING":
                raise InvalidTransitionError(
                    "Handoff requires RECOVERING status, "
                    f"found {current.status}"
                )

            if current.version != expected_version:
                raise InvalidTransitionError(
                    f"Expected version {expected_version}, "
                    f"found {current.version}"
                )

            # Construct the proposed execution record.
            running_record = replace(
                current,
                status="RUNNING",
                updated_at=self._now(),
                version=current.version + 1,
            )

            # Validate the state-machine transition.
            validate_transition(
                current=current.status,
                target=running_record.status,
                actor=TransitionActor.RECOVERY,
            )

            # Validate record transition invariants.
            validate_transition_payload(
                current_status=current.status,
                updated_record=running_record,
            )

            # Build the new execution grant without mutating backend state.
            execution_grant = OwnershipGrant(
                owner_id=execution_owner_id,
                owner_token=str(uuid4()),
                lease_expires_at=self._now() + timedelta(
                    seconds=lease_seconds
                ),
                actor=TransitionActor.EXECUTION,
            )

            # Replace the record and ownership grant atomically while holding the lock.
            self._records[operation_id] = running_record
            self._ownership[operation_id] = execution_grant

            return ClaimResult(
                disposition=ClaimDisposition.CLAIMED,
                record=running_record,
                grant=execution_grant,
            )

    def release(
        self,
        operation_id,
        owner_token,
    ):

        """Release a valid ownership grant. Expired grants cannot be used to release a newer or otherwise valid grant."""
        if not isinstance(owner_token, str):
            raise TypeError("owner_token must be a string")

        with self._lock:

            if operation_id not in self._records:
                raise OperationNotFoundError(
                    "Operation not found"
                )

            grant = self._ownership.get(operation_id)

            if grant is None:
                return False

            if grant.owner_token != owner_token:

                raise OwnershipError(
                    "Invalid owner token"
                )

            # An expired grant is not allowed to release ownership as if it were still valid.
            if grant.lease_expires_at <= self._now():

                self._remove_ownership(operation_id)

                return False

            self._remove_ownership(operation_id)

            return True


    def _recovery_mutation(
        self,
        *,
        operation_id,
        recovery_token,
        expected_status,
        expected_version,
        target_status,
        result=None,
        reason=None,
    ):
        """Centralize guarded recovery state mutations so ownership, actor, status, and version checks are applied consistently."""
        with self._lock:

            current = self._records.get(operation_id)

            if current is None:
                raise OperationNotFoundError(
                    operation_id
                )

            grant = self._ownership.get(operation_id)

            if grant is None:
                raise OwnershipError(
                    "Recovery ownership grant missing"
                )

            self._validate_ownership(
                operation_id=operation_id,
                owner_token=recovery_token,
            )

            grant = self._ownership.get(operation_id)

            if grant.actor != TransitionActor.RECOVERY:
                raise OwnershipError(
                    "Recovery mutation requires RECOVERY actor"
                )

            if current.status != expected_status:
                raise OptimisticConcurrencyError(
                    "Unexpected operation status"
                )

            if current.version != expected_version:
                raise OptimisticConcurrencyError(
                    "Operation version mismatch"
                )

            # Build the updated record using the same record
            # structure and immutable identity conventions
            # already used in your memory.py.
            #
            # Use dataclasses.replace if OperationRecord
            # is a dataclass.

            updated = replace(
                current,
                status=target_status,
                result=result,
                version=current.version + 1,
                updated_at=datetime.now(timezone.utc),
                metadata={
                    **current.metadata,
                    "recovery_reason": reason,
                },
            )

            self._validate_transition(
                current.status,
                updated.status,
                actor=grant.actor,
            )

            self._validate_record_payload(updated)

            # Validate identity immutability here, using
            # the immutable fields in your OperationRecord.

            self._records[operation_id] = updated

            # Persist the state and remove recovery ownership in the same critical section.
            # within the same critical section.
            self._ownership.pop(operation_id, None)

            return updated


    def complete_recovery(
            self,
            *,
            operation_id,
            recovery_token,
            expected_status,
            expected_version,
            result,
            reason=None,
        ):
        """Persist a recovered result and transition the operation to COMPLETED."""
        return self._recovery_mutation(
                operation_id=operation_id,
                recovery_token=recovery_token,
                expected_status=expected_status,
                expected_version=expected_version,
                target_status=OPERATION_STATES.COMPLETED,
                result=result,
                reason=reason,
            )

    def defer_recovery(
            self,
            *,
            operation_id,
            recovery_token,
            expected_status,
            expected_version,
            reason,
        ):
        """Persist a recovery disposition that allows the operation to be considered again later."""
        return self._recovery_mutation(
                operation_id=operation_id,
                recovery_token=recovery_token,
                expected_status=expected_status,
                expected_version=expected_version,
                target_status=OPERATION_STATES.DEFERRED,
                reason=reason,
            )

    def mark_manual_intervention(
        self,
        *,
        operation_id,
        recovery_token,
        expected_status,
        expected_version,
        reason,
    ):
        """Persist a state indicating that automated recovery should stop and human intervention is required."""
        return self._recovery_mutation(
            operation_id=operation_id,
            recovery_token=recovery_token,
            expected_status=expected_status,
            expected_version=expected_version,
            target_status=OPERATION_STATES.MANUAL_INTERVENTION,
            reason=reason,
        )

    def reclaim_expired_recovery(
        self,
        *,
        operation_id,
        owner_id,
        lease_seconds,
    ):
        """Reclaim an RECOVERING operation when its previous recovery lease is absent or expired, granting new recovery ownership."""
        with self._lock:

            current = self._records.get(operation_id)

            if current is None:
                raise OperationNotFoundError(
                    operation_id
                )

            if current.status != OPERATION_STATES.RECOVERING:
                raise InvalidStateError(
                    "Operation is not RECOVERING"
                )

            existing_grant = self._ownership.get(
                operation_id
            )

            if existing_grant is not None:
                if self._lease_is_active(existing_grant):
                    return ClaimResult(
                        disposition=ClaimDisposition.BUSY,
                    )

            # The previous recovery grant is no longer valid; reclaim with a new token.
            # or absent. No old token can be used
            # to authorize mutations.

            updated = replace(
                current,
                recovery_attempts=(
                    current.recovery_attempts + 1
                ),
                version=current.version + 1,
                updated_at=datetime.now(timezone.utc),
            )

            self._validate_transition(
                current.status,
                updated.status,
                actor=TransitionActor.RECOVERY,
            )

            self._validate_record_payload(updated)

            new_grant = self._build_recovery_grant(
                operation_id=operation_id,
                owner_id=owner_id,
                lease_seconds=lease_seconds,
            )

            # Commit the updated record and replacement grant together.
            self._records[operation_id] = updated
            self._ownership[operation_id] = new_grant

            return ClaimResult(
                disposition=ClaimDisposition.CLAIMED,
                record=updated,
                grant=new_grant,
            )