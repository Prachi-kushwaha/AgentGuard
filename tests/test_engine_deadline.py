import time

import pytest

from agentguard import (
    ExecutionPolicy,
    BackoffPolicy,
    ExecutionRejected,
)


def test_execution_deadline_prevents_retry(engine):

    attempts = {"count": 0}

    def failing_function():

        attempts["count"] += 1

        time.sleep(0.04)

        raise ConnectionError("Temporary failure")

    engine.registry.register(failing_function)

    policy = ExecutionPolicy(
        max_attempts=5,
        retry_on=(ConnectionError,),
    )

    backoff = BackoffPolicy(
        initial_delay=0.03,
        multiplier=1,
        max_delay=0.03,
        jitter=False,
    )

    with pytest.raises(ExecutionRejected):
        engine.execute(
            "failing_function",
            policy=policy,
            backoff=backoff,
            timeout=0.05,
        )

    assert attempts["count"] == 1

    context = next(iter(engine.executions.values()))

    assert context.status == "FAILED"