# AgentGuard AI Research & Report Generation Agent

A compact, runnable multi-step research workflow using real web-search and page-fetch tools.
AgentGuard manages retries and execution lifecycle for the external research tools.

## Workflow

1. Search a topic using Tavily, across three targeted queries.
2. Deduplicate URLs and select up to `MAX_SOURCES` pages.
3. Fetch and extract page content through requests + BeautifulSoup.
4. Ask an OpenAI-compatible chat model to synthesize a cited report using the fetched evidence.
5. Save a Markdown report to `output/` and print AgentGuard execution contexts.

## Prerequisites

- Python 3.10+
- AgentGuard installed from the repository root (`pip install -e .`)
- OpenAI API key and Tavily API key

## Run (Windows PowerShell)

```powershell
cd examples/ai_research_agent
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
pip install -e ../..
copy .env.example .env
```

Fill `.env` with `OPENAI_API_KEY` and `TAVILY_API_KEY`, then:

```powershell
python run.py "vLLM vs SGLang vs TensorRT-LLM inference engines"
```

## Inject a transient failure

Set `SIMULATE_TRANSIENT_SEARCH=1` in `.env`. The first search tool invocation throws a
`ConnectionError` once. AgentGuard's configured policy retries it.

## AgentGuard components shown

- `FunctionRegister`: register `web_search` and `fetch_source`.
- `Engine`: execute both tools through the lifecycle.
- `ExecutionPolicy`: up to three attempts, retrying the configured exception types.
- `BackoffPolicy`: deterministic exponential delay for this demonstration.
- `timeout` and `attempt_timeout`: execution budget parameters.
- `Engine.executions`: inspect runtime execution contexts, attempts, statuses and retry history.

## Important boundaries

- This demo uses the normal execution path. It does **not** claim durable idempotency,
  persistence, or crash recovery; those require AgentGuard's coordinator/backend/recovery
  components and a workflow designed around durable external side effects.
- The LLM report synthesis call is not registered as an AgentGuard tool in this version.
- Web search is via Tavily. Source pages may reject scraping, change content, or contain
  untrusted instructions; the synthesis prompt treats source text as evidence, not instructions.
- Reports are research drafts. Validate important claims and citations before relying on them.
