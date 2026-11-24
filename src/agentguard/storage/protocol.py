from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from ..operation_record import OperationRecord


class ClaimDisposition(Enum):
    CLAIMED = "CLAIMED"
    COMPLETED = "COMPLETED"
    BUSY = "BUSY"
    RECOVERY_REQUIRED = "RECOVERY_REQUIRED"
    KEY_CONFLICT = "KEY_CONFLICT"

@dataclass(frozen=True)
class OwnershipGrant:

    owner_id: str
    owner_token: str
    lease_expires_at: datetime

    def __post_init__(self):

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

        if (
            self.lease_expires_at.tzinfo is None
            or self.lease_expires_at.utcoffset() is None
        ):
            raise ValueError(
                "lease_expires_at must be timezone-aware"
            )

@dataclass(frozen=True)
class ClaimResult:

    disposition: ClaimDisposition
    record: OperationRecord
    grant: OwnershipGrant | None = None

    def __post_init__(self):

        if not isinstance(self.disposition, ClaimDisposition):
            raise TypeError(
                "disposition must be a ClaimDisposition"
            )

        if not isinstance(self.record, OperationRecord):
            raise TypeError(
                "record must be an OperationRecord"
            )

        if self.disposition is ClaimDisposition.CLAIMED:
            if self.grant is None:
                raise ValueError(
                    "CLAIMED requires an ownership grant"
                )

        elif self.grant is not None:
            raise ValueError(
                f"{self.disposition.value} cannot include "
                "an ownership grant"
            )


@dataclass(frozen=True)
class OperationIdentity:

    scope_id: str
    function_name: str
    idempotency_key: str

    def __post_init__(self):
        for name, value in (
            ("scope_id", self.scope_id),
            ("function_name", self.function_name),
            ("idempotency_key", self.idempotency_key),
        ):
            if not isinstance(value, str):
                raise TypeError(f"{name} must be a string")

            if not value.strip():
                raise ValueError(f"{name} cannot be empty")