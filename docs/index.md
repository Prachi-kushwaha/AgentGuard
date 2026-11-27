# AgentGuard

**Reliable execution for operations that should not fail silently.**

AgentGuard is a Python library for building resilient execution workflows. It helps manage idempotent operations, execution state, retries, recovery, and coordination—so failures don't automatically mean repeating work blindly.

Whether you're building API integrations, background jobs, distributed workflows, or AI agents that execute external actions, AgentGuard provides primitives to make execution more predictable.

---

## Why AgentGuard?

A function call isn't always as simple as success or failure.

What happens when:

- An API request succeeds, but your process crashes before recording the result?
- A worker retries an operation that already completed?
- Two workers attempt to execute the same operation simultaneously?
- An operation times out, and you don't know whether the external side effect occurred?
- An operation needs to be recovered instead of blindly executed again?

AgentGuard is designed to help you manage these situations through structured execution state, idempotency coordination, and recovery mechanisms.

## Installation

Install AgentGuard using pip:

```bash
pip install agentguard
```

> If you're installing from source during development:

```bash
git clone https://github.com/<YOUR-USERNAME>/AgentGuard.git
cd AgentGuard
pip install -e .
```

---

## Quick Start

```python
from agentguard import idempotent

@idempotent
def create_payment(customer_id: str, amount: int):
    # Your operation
    return {
        "customer_id": customer_id,
        "amount": amount,
    }

result = create_payment("customer_123", 5000)

print(result)
```

The decorator provides an interface for applying idempotency to operations, helping prevent unnecessary duplicate execution when the same operation is retried.

> See the API documentation for configuration, execution semantics, and supported behavior.

---

## Core Capabilities

### Idempotent Execution

Manage repeated requests without blindly executing the same operation again.

### Execution State Management

Track operation lifecycle states and transitions to make execution behavior explicit.

### Retry Management

Use structured retry strategies to handle transient failures rather than relying on uncontrolled retry loops.

### Recovery

Handle uncertain execution outcomes with recovery mechanisms that help determine what should happen next.

### Coordination

Coordinate operation claims and execution to reduce conflicts between competing workers.

---

## Architecture

AgentGuard is organized around several core components:

- **Coordinator** — coordinates operation claims and execution.
- **Execution Engine** — manages execution flow and lifecycle.
- **Storage** — persists or manages operation records through storage abstractions.
- **Recovery** — handles recovery decisions and execution recovery workflows.
- **Policies** — define behavior such as retry and recovery strategies.

Explore the [Architecture documentation](engine/overview.md) to understand how these components interact.

---

## Documentation

- [Execution Engine](engine/overview.md)
- [Coordinator API](api/coordinator.md)
- [Engine API](api/engine.md)
- [Recovery API](api/recovery.md)
- [Storage API](api/storage.md)

---

## Contributing

Contributions, discussions, bug reports, and ideas are welcome.

If you're interested in reliability, idempotency, fault tolerance, execution systems, and resilient AI agents, you're welcome to contribute.

---

**AgentGuard — Guard your execution.**
