from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


class RecoveryDecision(str, Enum):
    COMPLETED = "COMPLETED"
    RESUME = "RESUME"
    MANUAL_INTERVENTION = "MANUAL_INTERVENTION"
    DEFER = "DEFER"


_UNSET = object()


@dataclass(frozen=True)
class RecoveryResult:
    decision: RecoveryDecision

    result: Any = _UNSET
    reason: str | None = None

    @property
    def has_result(self) -> bool:
        return self.result is not _UNSET


@dataclass(frozen=True)
class RecoveryContext:
    operation_id: str
    record: Any
    payload: Any = None


@dataclass(frozen=True)
class RecoveryOutcome:
    operation_id: str
    decision: RecoveryDecision
    reason: str | None = None
    result: Any = None

    @property
    def completed(self) -> bool:
        return self.decision == RecoveryDecision.COMPLETED

    @property
    def resumable(self) -> bool:
        return self.decision == RecoveryDecision.RESUME

    @property
    def deferred(self) -> bool:
        return self.decision == RecoveryDecision.DEFER

    @property
    def requires_manual_intervention(self) -> bool:
        return (
            self.decision
            == RecoveryDecision.MANUAL_INTERVENTION
        )