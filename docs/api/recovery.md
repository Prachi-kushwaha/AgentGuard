# Recovery API Reference

AgentGuard's recovery subsystem is responsible for reconciling operations whose execution outcomes cannot be confidently determined.

Recovery is designed to handle uncertain execution outcomes without blindly re-executing operations that may have already produced external side effects.

## Modules

### Recovery Engine

The recovery engine coordinates the recovery lifecycle, including identifying operations requiring recovery, invoking registered recovery handlers, and applying recovery decisions.

::: agentguard.recovery.recovery_engine.RecoveryEngine

### Recovery Handler

Defines the recovery handler interface and the contract for application-specific recovery logic.

::: agentguard.recovery.recovery_handler.RecoveryHandler

### Recovery Models

Defines the models used to represent recovery decisions, results, and recovery context.

::: agentguard.recovery.recovery_models.RecoveryContext

::: agentguard.recovery.recovery_models.RecoveryDecision

::: agentguard.recovery.recovery_models.RecoveryOutcome

::: agentguard.recovery.recovery_models.RecoveryResult

### Recovery Policy

Defines the policy governing recovery behavior, including configuration and constraints applied during the recovery process.

::: agentguard.recovery.recovery_policy.RecoveryPolicy

### Recovery Registry

Provides the registry for associating operations with their corresponding recovery handlers.

::: agentguard.recovery.recovery_register.RecoveryRegistry