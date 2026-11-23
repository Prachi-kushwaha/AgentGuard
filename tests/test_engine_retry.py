import pytest

def test_retries_after_retryable_exception(
    engine,
    retry_policy,
    no_delay_backoff,
):

    attempts = {"count": 0}

    def unstable_function():

        attempts["count"] += 1

        if attempts["count"] < 3:
            raise ConnectionError("Temporary failure")

        return "success"

    engine.registry.register(unstable_function)

    result = engine.execute(
        "unstable_function",
        policy=retry_policy,
        backoff=no_delay_backoff,
    )

    assert result == "success"
    assert attempts["count"] == 3

    context = next(iter(engine.executions.values()))

    assert context.status == "COMPLETED"
    assert context.attempt_number == 3


def test_non_retryable_exception_is_not_retried(
    engine,
    retry_policy,
    no_delay_backoff,
):

    attempts = {"count": 0}

    def failing_function():

        attempts["count"] += 1

        raise ValueError("Invalid data")

    engine.registry.register(failing_function)

    with pytest.raises(ValueError):
        engine.execute(
            "failing_function",
            policy=retry_policy,
            backoff=no_delay_backoff,
        )

    assert attempts["count"] == 1

    context = next(iter(engine.executions.values()))

    assert context.status == "FAILED"
    assert context.attempt_number == 1


def test_max_attempts_is_respected(
    engine,
    retry_policy,
    no_delay_backoff,
):

    attempts = {"count": 0}

    def always_fails():

        attempts["count"] += 1

        raise ConnectionError("Still failing")

    engine.registry.register(always_fails)

    with pytest.raises(ConnectionError):
        engine.execute(
            "always_fails",
            policy=retry_policy,
            backoff=no_delay_backoff,
        )

    assert attempts["count"] == 3

    context = next(iter(engine.executions.values()))

    assert context.attempt_number == 3
    assert context.status == "FAILED"