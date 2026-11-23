
import pytest


def test_successful_execution_lifecycle(engine):

    def simple_function():
        return "ok"

    engine.registry.register(simple_function)

    engine.execute("simple_function")

    context = next(iter(engine.executions.values()))

    assert context.status == "COMPLETED"
    assert context.started_at is not None
    assert context.start_time_monotonic is not None


def test_failed_execution_lifecycle(engine):

    def failing_function():
        raise ValueError("Failure")

    engine.registry.register(failing_function)

    with pytest.raises(ValueError):
        engine.execute("failing_function")

    context = next(iter(engine.executions.values()))

    assert context.status == "FAILED"
    assert context.failure_reason == "Failure"