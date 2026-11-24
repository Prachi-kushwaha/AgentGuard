import pytest

from agentguard.engine import Engine
from agentguard.function_register import FunctionRegister
from agentguard.execution_policy import ExecutionPolicy
from agentguard.backoff import BackoffPolicy

from agentguard.coordinator import (
    IdempotencyCoordinator,
    KeyConflictError,
    OperationBusyError,
    RecoveryRequiredError,
)

from agentguard.storage.memory import (
    InMemoryIdempotencyBackend,
)

from agentguard.storage.protocol import (
    ClaimDisposition,
)


@pytest.fixture
def setup_engine():

    backend = InMemoryIdempotencyBackend()
    coordinator = IdempotencyCoordinator(backend)

    registry = FunctionRegister()

    engine = Engine(
        registry,
        idempotency_coordinator=coordinator,
    )

    return engine, registry, backend, coordinator


def test_successful_execution_is_persisted(setup_engine):

    engine, registry, backend, coordinator = setup_engine

    execution_count = 0

    def add(a, b):

        nonlocal execution_count
        execution_count += 1

        return a + b

    registry.register(add)

    result = engine.execute(
        "add",
        10,
        20,
        idempotency_key="operation-001",
    )

    assert result == 30
    assert execution_count == 1

    identity = next(iter(backend._identity_index))

    record = backend.get(identity)

    assert record.status == "COMPLETED"
    assert record.result == 30


def test_completed_operation_is_replayed(setup_engine):

    engine, registry, backend, coordinator = setup_engine

    execution_count = 0

    def add(a, b):

        nonlocal execution_count
        execution_count += 1

        return a + b

    registry.register(add)

    first_result = engine.execute(
        "add",
        10,
        20,
        idempotency_key="operation-002",
    )

    second_result = engine.execute(
        "add",
        10,
        20,
        idempotency_key="operation-002",
    )

    assert first_result == 30
    assert second_result == 30
    assert execution_count == 1


def test_same_key_with_different_arguments_is_rejected(setup_engine):

    engine, registry, backend, coordinator = setup_engine

    execution_count = 0

    def add(a, b):

        nonlocal execution_count
        execution_count += 1

        return a + b

    registry.register(add)

    engine.execute(
        "add",
        10,
        20,
        idempotency_key="operation-003",
    )

    with pytest.raises(KeyConflictError):

        engine.execute(
            "add",
            100,
            200,
            idempotency_key="operation-003",
        )

    assert execution_count == 1


def test_different_keys_execute_independently(setup_engine):

    engine, registry, backend, coordinator = setup_engine

    execution_count = 0

    def add(a, b):

        nonlocal execution_count
        execution_count += 1

        return a + b

    registry.register(add)

    first = engine.execute(
        "add",
        10,
        20,
        idempotency_key="operation-004-a",
    )

    second = engine.execute(
        "add",
        10,
        20,
        idempotency_key="operation-004-b",
    )

    assert first == 30
    assert second == 30
    assert execution_count == 2


def test_busy_operation_is_rejected(setup_engine):

    engine, registry, backend, coordinator = setup_engine

    execution_count = 0

    def add(a, b):

        nonlocal execution_count
        execution_count += 1

        return a + b

    registry.register(add)

    # The first acquisition deliberately holds ownership.
    func = registry.retrieve("add")

    coordinator.acquire(
        func=func,
        args=(10, 20),
        kwargs={},
        idempotency_key="operation-005",
        owner_id="worker-1",
    )

    # The Engine should not execute while another owner holds the operation.
    with pytest.raises(OperationBusyError):

        engine.execute(
            "add",
            10,
            20,
            idempotency_key="operation-005",
            owner_id="worker-2",
        )

    assert execution_count == 0


def test_failed_operation_is_persisted(setup_engine):

    engine, registry, backend, coordinator = setup_engine

    def fail():

        raise ValueError("deliberate failure")

    registry.register(fail)

    with pytest.raises(ValueError, match="deliberate failure"):

        engine.execute(
            "fail",
            idempotency_key="operation-006",
        )

    identity = next(iter(backend._identity_index))

    record = backend.get(identity)

    assert record.status == "FAILED"
    assert record.error == "deliberate failure"


def test_timeout_is_recorded_as_unknown(setup_engine):

    engine, registry, backend, coordinator = setup_engine

    def timeout():

        raise TimeoutError("operation timed out")

    registry.register(timeout)

    with pytest.raises(TimeoutError, match="operation timed out"):

        engine.execute(
            "timeout",
            idempotency_key="operation-007",
        )

    identity = next(iter(backend._identity_index))

    record = backend.get(identity)

    assert record.status == "UNKNOWN"
    assert record.error == "operation timed out"


def test_unknown_operation_requires_recovery(setup_engine):

    engine, registry, backend, coordinator = setup_engine

    def work():

        return "done"

    registry.register(work)

    # Seed an UNKNOWN operation using the real coordinator/backend.
    func = registry.retrieve("work")

    claim = coordinator.acquire(
        func=func,
        args=(),
        kwargs={},
        idempotency_key="operation-008",
        owner_id="worker-1",
    )

    coordinator.record_unknown(
        operation_id=claim.record.operation_id,
        error=TimeoutError("uncertain outcome"),
        grant=claim.grant,
        record=claim.record,
    )

    # A second execution must not simply run the function.
    with pytest.raises(RecoveryRequiredError):

        engine.execute(
            "work",
            idempotency_key="operation-008",
        )


def test_execution_without_idempotency_still_works(setup_engine):

    engine, registry, backend, coordinator = setup_engine

    execution_count = 0

    def add(a, b):

        nonlocal execution_count
        execution_count += 1

        return a + b

    registry.register(add)

    result = engine.execute("add", 10, 20)

    assert result == 30
    assert execution_count == 1
    assert len(backend._records) == 0