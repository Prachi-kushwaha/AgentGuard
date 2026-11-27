from abc import ABC, abstractmethod

from .recovery_models import RecoveryContext, RecoveryResult


class RecoveryHandler(ABC):

    @abstractmethod
    def recover(
        self,
        context: RecoveryContext,
    ) -> RecoveryResult:
        """
        Investigate an uncertain operation and return
        a recovery decision.

        The handler must not mutate AgentGuard operation
        records or ownership state directly.
        """
        raise NotImplementedError