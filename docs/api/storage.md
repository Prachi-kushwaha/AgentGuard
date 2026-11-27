# Storage API Reference

AgentGuard's storage subsystem provides the mechanisms for storing and managing operation state. It defines the storage protocols and implementations responsible for maintaining operation records and supporting the coordination lifecycle.

The storage layer separates storage contracts from their implementations, allowing AgentGuard to work with different storage backends while maintaining a consistent interface for operation state management.

## Modules

### Memory Storage

Provides an in-memory storage implementation for managing operation records. This implementation is useful for testing, development, and scenarios where persistent storage is not required.

::: agentguard.storage.memory

### Storage Protocol

Defines the storage protocol and expected contract for storage implementations. It establishes the interface that storage backends must follow to support AgentGuard's operation lifecycle and coordination mechanisms.

::: agentguard.storage.protocol
