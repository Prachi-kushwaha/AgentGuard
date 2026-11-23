def test_retry_history_records_failures(
    engine,
    retry_policy,
    no_delay_backoff,
):

    attempts = {"count": 0}

    def unstable_function():

        attempts["count"] += 1

        if attempts["count"] < 3:
            raise ConnectionError("Temporary failure")

        return "done"

    engine.registry.register(unstable_function)

    result = engine.execute(
        "unstable_function",
        policy=retry_policy,
        backoff=no_delay_backoff,
    )

    assert result == "done"

    context = next(iter(engine.executions.values()))

    assert len(context.retry_history) == 2

    assert context.retry_history[0]["retry_decision"] == "RETRY"
    assert context.retry_history[1]["retry_decision"] == "RETRY"


def test_terminal_failure_is_recorded(
    engine,
    retry_policy,
    no_delay_backoff,
):

    def failing_function():
        raise ConnectionError("Network error")

    engine.registry.register(failing_function)

    try:
        engine.execute(
            "failing_function",
            policy=retry_policy,
            backoff=no_delay_backoff,
        )
    except ConnectionError:
        pass

    context = next(iter(engine.executions.values()))

    assert len(context.retry_history) == 3

    assert context.retry_history[-1]["retry_decision"] == "FAIL"