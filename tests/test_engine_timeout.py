import time

import pytest

from agentguard import ExecutionPolicy, BackoffPolicy


def test_attempt_timeout_detected(engine):

    def slow_function():
        time.sleep(0.05)
        return "finished"

    engine.registry.register(slow_function)

    with pytest.raises(TimeoutError):
        engine.execute(
            "slow_function",
            attempt_timeout=0.01,
        )

    context = next(iter(engine.executions.values()))

    assert context.status == "FAILED"
    assert context.attempt_number == 1

def test_attempt_timeout_can_trigger_retry(engine):

    attempts = {"count": 0}

    def unstable_function():

        attempts["count"] += 1

        if attempts["count"] == 1:
            time.sleep(0.05)

        return "success"

    engine.registry.register(unstable_function)

    policy = ExecutionPolicy(
        max_attempts=2,
        retry_on=(TimeoutError,),
    )

    backoff = BackoffPolicy(
        initial_delay=0.01,
        multiplier=1,
        max_delay=0.01,
        jitter=False,
    )

    result = engine.execute(
        "unstable_function",
        policy=policy,
        backoff=backoff,
        attempt_timeout=0.02,
    )

    assert result == "success"
    assert attempts["count"] == 2

    context = next(iter(engine.executions.values()))

    assert context.status == "COMPLETED"
    assert context.attempt_number == 2