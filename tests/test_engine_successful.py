
def test_successful_execution(engine, no_retry_policy):

    def add(a, b):
        return a + b

    engine.registry.register(add)

    result = engine.execute(
        "add",
        10,
        20,
        policy=no_retry_policy,
    )

    assert result == 30


def test_execution_with_keyword_arguments(engine):

    def greet(name, message="Hello"):
        return f"{message}, {name}"

    engine.registry.register(greet)

    result = engine.execute(
        "greet",
        name="Alice",
        message="Welcome",
    )

    assert result == "Welcome, Alice"


def test_execution_context_records_result(engine):

    def multiply(a, b):
        return a * b

    engine.registry.register(multiply)

    result = engine.execute(
        "multiply",
        4,
        5,
    )

    assert result == 20

    context = next(iter(engine.executions.values()))

    assert context.results == 20
    assert context.status == "COMPLETED"
    assert context.attempt_number == 1

def test_execution_with_keyword_arguments(engine):

    def greet(name, message="Hello"):
        return f"{message}, {name}"

    engine.registry.register(greet)

    result = engine.execute(
        "greet",
        # name="Alice",
        message="Welcome",
    )

    assert result == "Welcome"


def test_execution_context_records_result(engine):

    def multiply(a, b):
        return a * b

    engine.registry.register(multiply)

    result = engine.execute(
        "multiply",
        4,
        5,
    )

    assert result == 20

    context = next(iter(engine.executions.values()))

    assert context.results == 20
    assert context.status == "COMPLETED"
    assert context.attempt_number == 1