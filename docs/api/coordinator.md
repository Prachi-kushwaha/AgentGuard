# Coordinator API Reference

AgentGuard's idempotency coordinator manages the coordination of operations associated with idempotency keys. It works with the backend to claim operations, detect duplicate requests, handle conflicting inputs, and manage execution outcomes.

The coordinator ensures that repeated requests with the same idempotency key and matching inputs can be handled consistently, while requests with conflicting inputs or operations that require recovery are handled appropriately.

## Modules

### Idempotency Coordinator

The idempotency coordinator manages the lifecycle of idempotent operations. It coordinates operation claims, validates request identity, and communicates with the backend to manage operation execution state.

::: agentguard.coordinator.IdempotencyCoordinator

### Coordinator Exceptions

Defines the exceptions raised by the coordinator when an operation cannot be acquired or processed under the expected idempotency rules.

::: agentguard.coordinator.IdempotencyError

::: agentguard.coordinator.KeyConflictError

::: agentguard.coordinator.OperationBusyError

::: agentguard.coordinator.RecoveryRequiredError
