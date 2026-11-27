from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


class RecoveryDecision(str, Enum):
    """
    Represents the decision returned by a recovery handler.

    Each decision determines how the recovery engine
    proceeds with the operation.
    """

    # The operation has been reconciled and its result
    # can be persisted as completed.
    COMPLETED = "COMPLETED"

    # The operation can safely continue through the
    # normal execution path.
    RESUME = "RESUME"

    # Automated recovery should stop and require
    # human intervention.
    MANUAL_INTERVENTION = "MANUAL_INTERVENTION"

    # Recovery cannot proceed at this time and should
    # be reconsidered later.
    DEFER = "DEFER"


# Sentinel used to distinguish an explicitly supplied None
# from a result that was never supplied at all.
#
# This distinction matters because None can itself be a
# valid result returned by an operation.
_UNSET = object()


@dataclass(frozen=True)
class RecoveryResult:
    """
    Represents the result produced by a recovery handler.

    RecoveryResult communicates the handler's decision,
    an optional recovered result and an optional explanation.

    The result field uses a sentinel instead of None so that
    the framework can distinguish between a missing result
    and a legitimate None value.
    """

    decision: RecoveryDecision

    result: Any = _UNSET
    reason: str | None = None

    @property
    def has_result(self) -> bool:
        """
        Indicates whether a result was explicitly provided.

        A result of None is considered provided, whereas
        an omitted result is represented internally by _UNSET.
        """
        return self.result is not _UNSET


@dataclass(frozen=True)
class RecoveryContext:
    """
    Provides the recovery handler with the information
    needed to reconcile an interrupted operation.

    The context contains the operation identifier, its
    persisted record and optional application-specific
    recovery data.
    """

    operation_id: str
    record: Any
    payload: Any = None


@dataclass(frozen=True)
class RecoveryOutcome:
    """
    Represents the outcome of a recovery orchestration attempt.

    Unlike RecoveryResult, which is returned by the
    application-defined recovery handler, RecoveryOutcome
    represents the decision produced by the recovery engine
    after processing and applying the handler's decision.

    It provides convenience properties for inspecting
    the resulting recovery disposition.
    """

    operation_id: str
    decision: RecoveryDecision
    reason: str | None = None
    result: Any = None

    @property
    def completed(self) -> bool:
        """
        Indicates whether recovery resolved the operation
        as completed.
        """
        return self.decision == RecoveryDecision.COMPLETED

    @property
    def resumable(self) -> bool:
        """
        Indicates whether recovery successfully handed
        the operation back to the execution path.
        """
        return self.decision == RecoveryDecision.RESUME

    @property
    def deferred(self) -> bool:
        """
        Indicates whether recovery was deferred and
        should be reconsidered later.
        """
        return self.decision == RecoveryDecision.DEFER

    @property
    def requires_manual_intervention(self) -> bool:
        """
        Indicates whether automated recovery stopped
        and human intervention is required.
        """
        return (
            self.decision
            == RecoveryDecision.MANUAL_INTERVENTION
        )