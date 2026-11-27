# Engine API Reference

AgentGuard's execution engine is responsible for managing the execution lifecycle of functions, including execution validation, retries, timeout handling, and coordination of execution state.

The engine integrates execution policies, runtime context management, and lifecycle transitions to provide controlled and reliable function execution. It handles execution attempts and their outcomes while maintaining the execution context throughout the lifecycle.

## Modules

### Execution Engine

The execution engine coordinates function execution, manages the execution lifecycle, and applies the configured execution policies. It handles execution validation, retry behavior, timeout management, and lifecycle state transitions.

::: agentguard.engine
    options:
      show_source: true
      show_root_heading: true
      show_root_full_path: false
