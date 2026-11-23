"""Resilient shipping-rate HTTP client controlled by AgentGuard."""
import os
import requests

from agentguard import Engine, FunctionRegister, ExecutionPolicy, BackoffPolicy, ExecutionRejected

TRANSIENT_STATUS_CODES = {408, 429, 500, 502, 503, 504}

class ShippingAPIError(Exception):
    pass

class TransientShippingAPIError(ShippingAPIError):
    pass

class PermanentShippingAPIError(ShippingAPIError):
    pass

class ShippingClient:
    def __init__(self, base_url: str, connect_timeout: float = 1.5, read_timeout: float = 2.0):
        self.base_url = base_url.rstrip("/")
        self.http_timeout = (connect_timeout, read_timeout)
        self.session = requests.Session()

    def fetch_rates(self, destination: str, postal_code: str, weight_kg: float):
        response = self.session.post(
            f"{self.base_url}/rates",
            json={
                "destination": destination,
                "postal_code": postal_code,
                "weight_kg": weight_kg,
            },
            timeout=self.http_timeout,
        )

        if response.status_code in TRANSIENT_STATUS_CODES:
            raise TransientShippingAPIError(
                f"Temporary provider response: HTTP {response.status_code}"
            )

        if not response.ok:
            raise PermanentShippingAPIError(
                f"Provider rejected request: HTTP {response.status_code} "
                f"- {response.text[:300]}"
            )

        payload = response.json()
        if "rates" not in payload or not isinstance(payload["rates"], list):
            raise PermanentShippingAPIError("Provider response missing valid 'rates' list")
        return payload


def build_engine(client: ShippingClient):
    registry = FunctionRegister()

    # The registered callable is the real HTTP integration.
    registry.register(client.fetch_rates)
    return Engine(registry)


def get_rates(engine: Engine, destination: str, postal_code: str, weight_kg: float):
    policy = ExecutionPolicy(
        max_attempts=4,
        retry_on=(TransientShippingAPIError, requests.exceptions.Timeout,
                   requests.exceptions.ConnectionError),
    )
    backoff = BackoffPolicy(
        initial_delay=0.25,
        multiplier=2.0,
        max_delay=2.0,
        jitter=False,
    )
    return engine.execute(
        "fetch_rates",
        destination=destination,
        postal_code=postal_code,
        weight_kg=weight_kg,
        policy=policy,
        backoff=backoff,
        timeout=5.0,
        attempt_timeout=2.5,
    )


def main():
    endpoint = os.getenv("SHIPPING_API_URL", "http://127.0.0.1:8089")
    client = ShippingClient(endpoint)
    engine = build_engine(client)

    try:
        data = get_rates(engine, "IN", "560001", 1.2)
        print("Rates returned to checkout:", data["rates"])
    except ExecutionRejected as exc:
        print("AgentGuard rejected/terminated execution:", exc)
    except ShippingAPIError as exc:
        print("Shipping integration failed:", exc)
    except requests.exceptions.RequestException as exc:
        print("Network error:", exc)
    finally:
        # Inspect execution telemetry programmatically.
        if engine.executions:
            context = next(iter(engine.executions.values()))
            print("Execution status:", context.status)
            print("Attempts:", context.attempt_number)
            print("Retry history:", context.retry_history)
        client.session.close()


if __name__ == "__main__":
    main()
