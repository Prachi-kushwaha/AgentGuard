# Example 01 — Resilient Shipping Rate HTTP Integration

This example uses a real HTTP client (`requests`) and AgentGuard to control retries for a shipping-rate API integration.

The included local HTTP provider is a deterministic integration-test/demo server: it returns HTTP 503 twice, then returns a JSON rate response. This allows the retry path to be exercised without carrier credentials or network dependencies.

## Setup

From the AgentGuard repository root:

```powershell
pip install requests
pip install -e .
```

## Run the local provider

Terminal 1:

```powershell
python examples/01_resilient_api_call/local_provider.py
```

## Run the AgentGuard client

Terminal 2:

```powershell
python examples/01_resilient_api_call/shipping_client.py
```

Expected outcome: the client receives two transient HTTP 503 responses, AgentGuard retries, and the third request returns shipping rates.

## Use a real provider-compatible endpoint

Set `SHIPPING_API_URL` to an endpoint that implements the expected POST `/rates` contract:

```powershell
$env:SHIPPING_API_URL="https://your-provider.example/api"
python examples/01_resilient_api_call/shipping_client.py
```

The provider contract expected by this example is:

- POST `/rates`
- JSON request fields: `destination`, `postal_code`, `weight_kg`
- Successful JSON response with a `rates` list

This is a generic integration contract—not a claim that a carrier offers this exact endpoint.

## Important timeout note

AgentGuard's current timeout checks do not forcibly interrupt a running synchronous callable. The `requests` connect/read timeouts protect the HTTP request itself; AgentGuard's overall deadline controls whether another attempt/backoff can be started within the remaining execution budget.

## Known repository fix required

In `src/agentguard/engine.py`, the terminal failure branch currently calls:

```python
context.transition_to("FAILED")
```

Your transition function is module-level. Replace that call with:

```python
transition(context, "FAILED")
```

Also in `src/agentguard/transition.py`, correct the transition map typo:

```python
"RETRYING": {"RUNNING", "FAILED", "CANCELLED"},
```
