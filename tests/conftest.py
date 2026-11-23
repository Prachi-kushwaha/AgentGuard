import pytest

from agentguard import (
    Engine,
    FunctionRegister,
    ExecutionPolicy,
    BackoffPolicy,
)


@pytest.fixture
def registry():
    return FunctionRegister()


@pytest.fixture
def engine(registry):
    return Engine(registry)


@pytest.fixture
def no_retry_policy():
    return ExecutionPolicy(
        max_attempts=1,
        retry_on=(),
    )


@pytest.fixture
def retry_policy():
    return ExecutionPolicy(
        max_attempts=3,
        retry_on=(ConnectionError,),
    )


@pytest.fixture
def no_delay_backoff():
    return BackoffPolicy(
        initial_delay=0.01,
        multiplier=1,
        max_delay=0.01,
        jitter=False,
    )