from datetime import datetime, timedelta, timezone
from threading import RLock
from uuid import uuid4
from dataclasses import replace

from ..operation_record import OperationRecord
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


class InMemoryIdempotencyBackend:

    def __init__(self):

        self._records: dict[str, OperationRecord] = {}
        self._identity_index: dict[OperationIdentity, str] = {}

        # operation_id -> OwnershipGrant
        self._ownership: dict[str, OwnershipGrant] = {}

        # Protect all shared backend state.
        self._lock = RLock()

    @staticmethod
    def _now():
        return datetime.now(timezone.utc)

    @staticmethod
    def _validate_lease_seconds(lease_seconds):

        if isinstance(lease_seconds, bool):
            raise TypeError("lease_seconds must be numeric")

        if not isinstance(lease_seconds, (int, float)):
            raise TypeError("lease_seconds must be numeric")

        if lease_seconds <= 0:
            raise ValueError("lease_seconds must be greater than zero")

    @staticmethod
    def _validate_owner_id(owner_id):

        if not isinstance(owner_id, str):
            raise TypeError("owner_id must be a string")

        if not owner_id.strip():
            raise ValueError("owner_id cannot be empty")

    @staticmethod
    def _validate_identity(identity):

        if not isinstance(identity, OperationIdentity):
            raise TypeError("identity must be an OperationIdentity")

    @staticmethod
    def _identity_from_record(record):

        return OperationIdentity(
            scope_id=record.scope_id,
            function_name=record.function_name,
            idempotency_key=record.idempotency_key,
        )

    def _create_grant(self, operation_id, owner_id, lease_seconds):

        grant = OwnershipGrant(
            owner_id=owner_id,
            owner_token=str(uuid4()),
            lease_expires_at=self._now() + timedelta(
                seconds=lease_seconds
            ),
            actor = TransitionActor.EXECUTION
        )

        self._ownership[operation_id] = grant

        return grant

    def _lease_is_active(self, operation_id):

        grant = self._ownership.get(operation_id)

        if grant is None:
            return False

        return grant.lease_expires_at > self._now()

    def _remove_ownership(self, operation_id):

        self._ownership.pop(operation_id, None)

    def _validate_ownership(
        self,
        operation_id,
        owner_token,
    ):

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

        self._validate_identity(identity)

        with self._lock:

            operation_id = self._identity_index.get(identity)

            if operation_id is None:
                return None

            return self._records[operation_id]

    def get_by_id(self, operation_id):

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
                action=grant.actor
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

            # Optimistic concurrency checks.
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

            # Release ownership for terminal/uncertain states.
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

        self._validate_owner_id(owner_id)
        self._validate_lease_seconds(lease_seconds)

        with self._lock:

            current = self._records.get(operation_id)

            if current is None:
                raise OperationNotFoundError(
                    "Operation not found"
                )

            # Completed operation

            if current.status == "COMPLETED":

                return ClaimResult(
                    disposition=ClaimDisposition.COMPLETED,
                    record=current,
                )

            # Only UNKNOWN can initially be recovered

            if current.status != "UNKNOWN":

                return ClaimResult(
                    disposition=ClaimDisposition.RECOVERY_REQUIRED,
                    record=current,
                )

            # Recovery ownership

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

            # Commit the record

            self._records[operation_id] = recovering_record

            return ClaimResult(
                disposition=ClaimDisposition.CLAIMED,
                record=recovering_record,
                grant=grant,
            )


    def release(
        self,
        operation_id,
        owner_token,
    ):

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

            # A stale/expired owner cannot release a new grant.
            if grant.lease_expires_at <= self._now():

                self._remove_ownership(operation_id)

                return False

            self._remove_ownership(operation_id)

            return True