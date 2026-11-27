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

    The coordinator acts as an orchestration layer between the execution
    system and the storage backend. It prepares the data required to identify
    an operation, requests ownership, interprets the backend's response, and
    constructs records representing execution outcomes.

    The coordinator deliberately does not own the storage-level concurrency
    guarantees. Atomic claiming, ownership validation, lease enforcement,
    and optimistic concurrency must be enforced by the backend because the
    backend is the authoritative source of persisted state.

    Responsibilities:
        - Validate acquisition inputs.
        - Generate operation fingerprints.
        - Construct operation identities and records.
        - Delegate operation claims to the backend.
        - Interpret claim dispositions.
        - Construct outcome records.
        - Delegate state mutations to the backend.

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
        """
        Initialize the coordinator with its storage backend and lease duration.

        The backend is injected rather than created internally so the
        coordinator can operate with different storage implementations,
        such as an in-memory backend or a durable database backend.

        lease_seconds determines how long the backend grants ownership
        when an operation is successfully claimed.
        """

        # bool is a subclass of int in Python. Explicitly rejecting it avoids
        # accepting True or False as accidental lease-duration values.
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
        """
        Acquire ownership of a logical operation.

        The coordinator creates a fingerprint representing the function and
        its inputs, then combines that fingerprint with the identity metadata
        to construct the initial operation record.

        The backend performs the actual claim. It is responsible for
        atomically determining whether this caller may execute the operation,
        whether the operation is already completed, whether another owner
        holds it, or whether recovery is required.

        Args:
            func: Function associated with the operation.
            args: Positional arguments passed to the function.
            kwargs: Keyword arguments passed to the function.
            idempotency_key: Key identifying the logical operation.
            owner_id: Identifier of the requesting owner.
            scope_id: Namespace used to scope operation identity.

        Returns:
            ClaimResult containing the backend claim outcome.

        Raises:
            KeyConflictError: If the idempotency key is reused with
                different operation inputs.
            OperationBusyError: If the operation is currently
                owned by another worker.
            RecoveryRequiredError: If the operation requires
                recovery before execution.
            ValueError: If required inputs are invalid.
        """

        # Validate caller-provided identity fields before constructing
        # fingerprints or submitting a claim to the backend.
        if not isinstance(idempotency_key, str) or not idempotency_key.strip():
            raise ValueError("idempotency_key must be a non-empty string")

        if not isinstance(owner_id, str) or not owner_id.strip():
            raise ValueError("owner_id must be a non-empty string")

        if not isinstance(scope_id, str) or not scope_id.strip():
            raise ValueError("scope_id must be a non-empty string")

        # The fingerprint represents the logical request inputs.
        # The backend uses it to detect when the same idempotency key
        # is reused for a different request.
        fingerprint = generate_fingerprint(func, args, kwargs)

        # OperationIdentity separates identity lookup concerns from the
        # record's execution state. The combination of scope, function,
        # and idempotency key defines the identity namespace.
        identity = OperationIdentity(
            scope_id=scope_id,
            function_name=func.__name__,
            idempotency_key=idempotency_key,
        )

        # Construct the initial record before claiming.
        # This represents the operation's initial persisted state and
        # provides the backend with the identity and fingerprint needed
        # to perform its atomic claim decision.
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

        # The backend is the authority on ownership and persisted state.
        # The coordinator does not perform a separate lookup followed by
        # a claim, because that pattern would introduce a race condition.
        claim_result = self.backend.claim(
            record=record,
            owner_id=owner_id,
            lease_seconds=self.lease_seconds,
        )

        # Validate the backend's response contract before interpreting it.
        # This protects the coordinator from malformed backend responses.
        self._validate_claim_result(claim_result)

        # The backend has determined that this identity conflicts with
        # an existing operation using the same key but different inputs.
        if claim_result.disposition is ClaimDisposition.KEY_CONFLICT:
            raise KeyConflictError(
                "Idempotency key was reused with different arguments"
            )

        # Another worker currently owns the operation. Executing it here
        # would violate the ownership guarantee and could cause duplicate
        # side effects.
        if claim_result.disposition is ClaimDisposition.BUSY:
            raise OperationBusyError(
                "Operation is currently owned by another worker"
            )

        # The existing operation cannot proceed through the normal
        # execution path until its persisted state has been reconciled.
        if claim_result.disposition is ClaimDisposition.RECOVERY_REQUIRED:
            raise RecoveryRequiredError(
                "Operation requires recovery before execution"
            )

        # CLAIMED and COMPLETED are returned to the execution layer.
        # The execution layer can proceed when it has a grant, or reuse
        # the previously persisted result when the operation is completed.
        return claim_result

    def record_success(
        self,
        operation_id: str,
        result,
        grant: OwnershipGrant,
        record: OperationRecord,
    ) -> OperationRecord:
        """
        Construct and persist a successful execution outcome.

        This method prepares the completed record but does not directly
        mutate storage. The backend validates ownership, the expected
        state/version, and the transition before committing the update.

        Using replace preserves the other record fields while producing
        a new immutable record with the success-specific fields updated.
        """

        updated = replace(
            record,
            status="COMPLETED",
            result=result,
            error=None,
            updated_at=datetime.now(timezone.utc),
            version=record.version + 1,
        )

        # The expected status and version are derived from the record
        # supplied to this method. The backend must reject the mutation
        # if the persisted record has changed since this record was read.
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
        """
        Construct and persist a known execution failure.

        FAILED represents an execution failure whose outcome is known
        to the execution system. It differs from UNKNOWN, where the
        system cannot reliably determine whether the operation's
        side effects occurred.
        """

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
        """
        Persist an outcome whose completion status cannot be determined.

        UNKNOWN is particularly important for operations involving external
        side effects. For example, a remote API might successfully process
        a request while the client loses the response.

        Marking such an operation UNKNOWN prevents the execution system
        from incorrectly assuming that the side effect definitely failed
        and blindly executing it again.
        """

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
        """
        Delegate an execution-owned state transition to the backend.

        The coordinator supplies the ownership token rather than making
        ownership decisions itself. The backend must validate the token,
        lease, actor, expected state, and version before accepting the
        mutation.

        This delegation keeps the coordinator independent of the
        backend's synchronization and persistence implementation.
        """

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
        """
        Validate the structural contract returned by the backend.

        This method checks that the backend returned the expected result
        type and that certain dispositions are consistent with their
        associated record and ownership data.

        These checks validate the response structure; they do not replace
        backend-side enforcement of atomicity or ownership.
        """

        if not isinstance(result, ClaimResult):
            raise TypeError("Backend must return ClaimResult")

        # A successful claim must provide the ownership authorization
        # required for subsequent execution-owned transitions.
        if result.disposition is ClaimDisposition.CLAIMED:
            if result.grant is None:
                raise IdempotencyError(
                    "CLAIMED result must include an ownership grant"
                )

        # COMPLETED must represent a record that is actually completed.
        # Otherwise, the disposition and record would contradict each other,
        # potentially causing the caller to reuse an invalid result.
        if result.disposition is ClaimDisposition.COMPLETED:
            if result.record.status != "COMPLETED":
                raise IdempotencyError(
                    "COMPLETED disposition must contain a completed record"
                )