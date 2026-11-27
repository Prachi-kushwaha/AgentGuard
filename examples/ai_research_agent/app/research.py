"""Research workflow using AgentGuard to manage external tool executions."""
from __future__ import annotations
import json
import requests
from pathlib import Path
from openai import OpenAI
from agentguard import Engine, FunctionRegister, ExecutionPolicy, BackoffPolicy
from . import config
from .tools import web_search, fetch_source

RETRY_POLICY = ExecutionPolicy(max_attempts=3, retry_on=(
    ConnectionError, TimeoutError, OSError, requests.exceptions.RequestException,
))
BACKOFF = BackoffPolicy(initial_delay=0.5, multiplier=2, max_delay=3, jitter=False)


def build_engine() -> Engine:
    registry = FunctionRegister()
    registry.register(web_search)
    registry.register(fetch_source)
    return Engine(registry)


def run_research(topic: str) -> Path:
    if not config.OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEY is not configured")
    engine = build_engine()
    client = OpenAI(api_key=config.OPENAI_API_KEY)

    queries = [
        f"{topic} architecture and technical overview",
        f"{topic} benchmarks performance and evaluation",
        f"{topic} recent developments limitations and tradeoffs",
    ]
    print("\n[1/4] Searching sources (AgentGuard-managed)...")
    search_results: list[dict] = []
    for query in queries:
        results = engine.execute("web_search", query, 4, policy=RETRY_POLICY,
                                backoff=BACKOFF, timeout=45, attempt_timeout=25)
        search_results.extend(results)

    # Deduplicate URLs and prioritize the sources returned by search.
    seen: set[str] = set()
    unique = []
    for result in search_results:
        url = result.get("url")
        if url and url not in seen:
            seen.add(url)
            unique.append(result)
    selected = unique[:config.MAX_SOURCES]

    print(f"\n[2/4] Fetching {len(selected)} sources (AgentGuard-managed)...")
    fetched = []
    for item in selected:
        try:
            page = engine.execute("fetch_source", item["url"], policy=RETRY_POLICY,
                                 backoff=BACKOFF, timeout=45, attempt_timeout=25)
            page["search_snippet"] = item.get("snippet", "")
            fetched.append(page)
            print(f"  ✓ {page['title'][:100]}")
        except Exception as exc:
            print(f"  ! Source skipped after managed execution failure: {item['url']} ({exc})")

    print("\n[3/4] Synthesizing evidence into a report...")
    evidence = json.dumps(fetched, ensure_ascii=False)
    prompt = f"""Create a well-structured research report about: {topic}
Use ONLY the source evidence provided below for factual claims. If evidence is absent,
explicitly label a claim as uncertain or omit it. Include an executive summary, scope,
technical comparison or thematic analysis, findings, trade-offs, limitations, conclusion,
and a source list with the exact URLs. Avoid fabricated benchmarks or citations.

SOURCE EVIDENCE (JSON):\n{evidence}"""
    completion = client.chat.completions.create(
        model=config.OPENAI_MODEL,
        temperature=0.2,
        messages=[
            {"role": "system", "content": "You are a careful technical research analyst. Cite source URLs inline and do not invent evidence."},
            {"role": "user", "content": prompt},
        ],
    )
    report = completion.choices[0].message.content or "No report content returned."

    print("\n[4/4] Saving report...")
    output_dir = Path(__file__).resolve().parents[1] / "output"
    output_dir.mkdir(parents=True, exist_ok=True)
    slug = "-".join(topic.lower().split())[:70]
    path = output_dir / f"research-{slug}.md"
    path.write_text(f"# Research report: {topic}\n\n{report}\n", encoding="utf-8")

    # Print in-process execution contexts for visibility into AgentGuard lifecycle.
    print("\nAgentGuard execution summary:")
    for context in engine.executions.values():
        print(f"- function={context.function_name} status={context.status} attempts={context.attempt_number} id={context.execution_id}")
        if context.retry_history:
            print(f"  retry_history={context.retry_history}")
    print(f"\nReport saved: {path}")
    return path
