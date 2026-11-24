import math
from datetime import datetime, timezone, timedelta

import pytest


from agentguard.fingerprint import (
    FingerprintError,
    bind_arguments,
    canonicalize,
    generate_fingerprint,
)



def charge_customer(amount, currency="USD", *, customer_id):
    pass


def test_bind_positional_and_keyword_arguments():
    result = bind_arguments(
        charge_customer,
        (100,),
        {"customer_id": "cust_123"},
    )

    assert result == {
        "amount": 100,
        "currency": "USD",
        "customer_id": "cust_123",
    }


def test_bind_explicit_default():
    result = bind_arguments(
        charge_customer,
        (100, "USD"),
        {"customer_id": "cust_123"},
    )

    assert result == {
        "amount": 100,
        "currency": "USD",
        "customer_id": "cust_123",
    }


def test_missing_required_argument():
    with pytest.raises(TypeError):
        bind_arguments(
            charge_customer,
            (100,),
            {},
        )


def test_equivalent_calls_produce_same_fingerprint():
    first = generate_fingerprint(
        charge_customer,
        (100,),
        {"customer_id": "cust_123"},
    )

    second = generate_fingerprint(
        charge_customer,
        (),
        {
            "amount": 100,
            "currency": "USD",
            "customer_id": "cust_123",
        },
    )

    assert first == second


def test_different_arguments_produce_different_fingerprints():
    first = generate_fingerprint(
        charge_customer,
        (100,),
        {"customer_id": "cust_123"},
    )

    second = generate_fingerprint(
        charge_customer,
        (200,),
        {"customer_id": "cust_123"},
    )

    assert first != second


def test_dictionary_order_does_not_change_fingerprint():
    def process(data):
        pass

    first = generate_fingerprint(
        process,
        ({"a": 1, "b": 2},),
        {},
    )

    second = generate_fingerprint(
        process,
        ({"b": 2, "a": 1},),
        {},
    )

    assert first == second


def test_bool_and_int_are_different():
    assert canonicalize(True) != canonicalize(1)


def test_list_and_tuple_are_different():
    assert canonicalize([1, 2]) != canonicalize((1, 2))


def test_bytes_canonicalization():
    assert canonicalize(b"hello") == {
        "type": "bytes",
        "value": "aGVsbG8=",
    }


def test_negative_zero_is_preserved():
    assert canonicalize(-0.0) != canonicalize(0.0)


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_non_finite_floats_are_rejected(value):
    with pytest.raises(FingerprintError):
        canonicalize(value)


def test_non_string_dict_keys_are_rejected():
    with pytest.raises(FingerprintError):
        canonicalize({1: "value"})


def test_circular_list_is_rejected():
    data = []
    data.append(data)

    with pytest.raises(FingerprintError):
        canonicalize(data)


def test_shared_references_are_allowed():
    shared = [1, 2]
    data = [shared, shared]

    result = canonicalize(data)

    assert result["type"] == "list"
    assert len(result["value"]) == 2


def test_naive_datetime_is_rejected():
    value = datetime(2026, 11, 25, 12, 0)

    with pytest.raises(FingerprintError):
        canonicalize(value)


def test_equivalent_timezones_have_same_canonicalization():
    utc_time = datetime(
        2026, 11, 25, 12, 0,
        tzinfo=timezone.utc,
    )

    offset_time = datetime(
        2026, 11, 25, 17, 30,
        tzinfo=timezone(timedelta(hours=5, minutes=30)),
    )

    assert canonicalize(utc_time) == canonicalize(offset_time)


def test_unsupported_objects_are_rejected():
    with pytest.raises(FingerprintError):
        canonicalize(object())


def test_maximum_depth_is_enforced():
    value = 1

    for _ in range(102):
        value = [value]

    with pytest.raises(FingerprintError):
        canonicalize(value)
