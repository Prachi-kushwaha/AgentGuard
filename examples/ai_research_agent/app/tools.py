"""External research tools. Each function is called through AgentGuard Engine."""
from __future__ import annotations
import os
import requests
from bs4 import BeautifulSoup
from . import config

TRANSIENT_USED = False


def web_search(query: str, max_results: int = 5) -> list[dict]:
    """Search the web using Tavily and return title, URL and snippet."""
    global TRANSIENT_USED
    if config.SIMULATE_TRANSIENT_SEARCH and not TRANSIENT_USED:
        TRANSIENT_USED = True
        raise ConnectionError("Injected one-time transient search failure")
    if not config.TAVILY_API_KEY:
        raise RuntimeError("TAVILY_API_KEY is not configured")
    response = requests.post(
        "https://api.tavily.com/search",
        json={"api_key": config.TAVILY_API_KEY, "query": query,
              "search_depth": "advanced", "max_results": max_results},
        timeout=20,
    )
    response.raise_for_status()
    payload = response.json()
    return [
        {"title": item.get("title", ""), "url": item.get("url", ""),
         "snippet": item.get("content", "")}
        for item in payload.get("results", [])
    ]


def fetch_source(url: str) -> dict:
    """Fetch and extract readable text from a source page."""
    response = requests.get(
        url,
        headers={"User-Agent": "AgentGuardResearchDemo/0.1 (+research example)"},
        timeout=20,
    )
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")
    for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
        tag.decompose()
    text = " ".join(soup.get_text(" ").split())
    return {"url": url, "title": soup.title.get_text(strip=True) if soup.title else url,
            "text": text[:12000]}
