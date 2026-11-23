
import pytest


def test_invalid_function_arguments_fail_before_execution(engine):

    def add(a, b):
        return a + b

    engine.registry.register(add)

    with pytest.raises(TypeError):
        engine.execute("add", 10)

    context = next(iter(engine.executions.values()))

    assert context.status == "FAILED"
    assert context.attempt_number == 0

def test_unknown_function_fails(engine):

    with pytest.raises(ValueError):
        engine.execute("does_not_exist")

    context = next(iter(engine.executions.values()))

    assert context.status == "FAILED"
    assert context.attempt_number == 0


@pytest.mark.parametrize(
    "timeout",
    [0, -1, float("inf"), float("nan"), True, "10"],
)
def test_invalid_timeout_rejected(engine, timeout):

    with pytest.raises((TypeError, ValueError)):
        engine.execute(
            "anything",
            timeout=timeout,
        )


@pytest.mark.parametrize(
    "attempt_timeout",
    [0, -1, float("inf"), float("nan"), True, "3"],
)
def test_invalid_attempt_timeout_rejected(
    engine,
    attempt_timeout,
):

    with pytest.raises((TypeError, ValueError)):
        engine.execute(
            "anything",
            attempt_timeout=attempt_timeout,
        )