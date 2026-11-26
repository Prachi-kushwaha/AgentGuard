
from dataclasses import replace
from datetime import datetime, timezone

from .fingerprint import generate_fingerprint
from .operation_record import OperationRecord
from .storage.protocol import (
    ClaimDisposition,
    ClaimResult,
    OperationIdentity,
    OwnershipGrant,
)
from .state_machine import TransitionActor


class IdempotencyError(RuntimeError):
    """Base exception for coordinator errors."""


class KeyConflictError(IdempotencyError):
    """Raised when an idempotency key is reused with different inputs."""


class OperationBusyError(IdempotencyError):
    """Raised when an operation is currently owned by another worker."""


class RecoveryRequiredError(IdempotencyError):
    """Raised when an operation requires recovery before execution."""


class IdempotencyCoordinator:
    """
    Coordinates idempotent operation acquisition and outcome recording.

    The coordinator acts as an orchestration layer between the
    execution system and the storage backend.

    Responsibilities:
        - Validate acquisition inputs.
        - Generate operation fingerprints.
        - Construct operation identities and records.
        - Delegate operation claims to the backend.
        - Interpret claim dispositions.
        - Construct outcome records.
        - Delegate state mutations to the backend.

    The coordinator does not independently enforce storage
    atomicity, ownership validation, lease validity, or
    optimistic concurrency. These guarantees are enforced
    by the backend.

    Lifecycle:
        1. Validate operation inputs.
        2. Generate a fingerprint.
        3. Construct an operation identity.
        4. Construct the initial operation record.
        5. Request a claim from the backend.
        6. Interpret the claim result.
        7. Record the execution outcome through the backend.
    """
    
    def __init__(self, backend, lease_seconds: float = 30.0):
        if isinstance(lease_seconds, bool) or not isinstance(
            lease_seconds, (int, float)
        ):
            raise TypeError("lease_seconds must be numeric")

        if lease_seconds <= 0:
            raise ValueError("lease_seconds must be greater than zero")

        self.backend = backend
        self.lease_seconds = lease_seconds

    def acquire(
        self,
        func,
        args,
        kwargs,
        idempotency_key: str,
        owner_id: str,
        scope_id: str = "default",
    ) -> ClaimResult:

        if not isinstance(idempotency_key, str) or not idempotency_key.strip():
            raise ValueError("idempotency_key must be a non-empty string")

        if not isinstance(owner_id, str) or not owner_id.strip():
            raise ValueError("owner_id must be a non-empty string")

        if not isinstance(scope_id, str) or not scope_id.strip():
            raise ValueError("scope_id must be a non-empty string")

        fingerprint = generate_fingerprint(func, args, kwargs)

        identity = OperationIdentity(
            scope_id=scope_id,
            function_name=func.__name__,
            idempotency_key=idempotency_key,
        )

        record = OperationRecord(
            idempotency_key=idempotency_key,
            function_name=func.__name__,
            fingerprint=fingerprint,
            status="PENDING",
            result=None,
            error=None,
            attempt_number=0,
            recovery_attempts=0,
            scope_id=scope_id,
            version=0,
            metadata={},
        )

        claim_result = self.backend.claim(
            record=record,
            owner_id=owner_id,
            lease_seconds=self.lease_seconds,
        )

        self._validate_claim_result(claim_result)

        if claim_result.disposition is ClaimDisposition.KEY_CONFLICT:
            raise KeyConflictError(
                "Idempotency key was reused with different arguments"
            )

        if claim_result.disposition is ClaimDisposition.BUSY:
            raise OperationBusyError(
                "Operation is currently owned by another worker"
            )

        if claim_result.disposition is ClaimDisposition.RECOVERY_REQUIRED:
            raise RecoveryRequiredError(
                "Operation requires recovery before execution"
            )

        return claim_result

    def record_success(
        self,
        operation_id: str,
        result,
        grant: OwnershipGrant,
        record: OperationRecord,
    ) -> OperationRecord:

        updated = replace(
            record,
            status="COMPLETED",
            result=result,
            error=None,
            updated_at=datetime.now(timezone.utc),
            version=record.version + 1,
        )

        return self._transition(
            operation_id=operation_id,
            updated_record=updated,
            expected_status=record.status,
            expected_version=record.version,
            grant=grant,
        )

    def record_failure(
        self,
        operation_id: str,
        error: Exception,
        grant: OwnershipGrant,
        record: OperationRecord,
    ) -> OperationRecord:

        updated = replace(
            record,
            status="FAILED",
            result=None,
            error=str(error),
            updated_at=datetime.now(timezone.utc),
            version=record.version + 1,
        )

        return self._transition(
            operation_id=operation_id,
            updated_record=updated,
            expected_status=record.status,
            expected_version=record.version,
            grant=grant,
        )

    def record_unknown(
        self,
        operation_id: str,
        error: Exception,
        grant: OwnershipGrant,
        record: OperationRecord,
    ) -> OperationRecord:

        updated = replace(
            record,
            status="UNKNOWN",
            error=str(error),
            updated_at=datetime.now(timezone.utc),
            version=record.version + 1,
        )

        return self._transition(
            operation_id=operation_id,
            updated_record=updated,
            expected_status=record.status,
            expected_version=record.version,
            grant=grant,
        )

    def _transition(
        self,
        operation_id: str,
        updated_record: OperationRecord,
        expected_status: str,
        expected_version: int,
        grant: OwnershipGrant,
    ) -> OperationRecord:

        return self.backend.transition(
            operation_id=operation_id,
            updated_record=updated_record,
            expected_status=expected_status,
            expected_version=expected_version,
            owner_token=grant.owner_token,
            actor=TransitionActor.EXECUTION,
        )

    @staticmethod
    def _validate_claim_result(result: ClaimResult):

        if not isinstance(result, ClaimResult):
            raise TypeError("Backend must return ClaimResult")

        if result.disposition is ClaimDisposition.CLAIMED:
            if result.grant is None:
                raise IdempotencyError(
                    "CLAIMED result must include an ownership grant"
                )

        if result.disposition is ClaimDisposition.COMPLETED:
            if result.record.status != "COMPLETED":
                raise IdempotencyError(
                    "COMPLETED disposition must contain a completed record"
                )



