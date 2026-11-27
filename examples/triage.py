"""Small end-to-end GitHub issue triage workflow powered by AgentGuard."""
from __future__ import annotations

import json
import os
import sys
from typing import Any

import requests
from openai import OpenAI

from agentguard import Engine, FunctionRegister, ExecutionPolicy, BackoffPolicy

GITHUB_API = "https://api.github.com"
TRANSIENT = {408, 429, 500, 502, 503, 504}
MARKER_PREFIX = "<!-- agentguard-triage -->"

class GitHubError(RuntimeError):
    pass

class TransientGitHubError(GitHubError):
    pass

class PermanentGitHubError(GitHubError):
    pass

class TriageTools:
    def __init__(self, token: str, repo: str):
        self.repo = repo
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        })
        self._simulated_failure_used = False

    def _request(self, method: str, path: str, **kwargs):
        response = self.session.request(method, f"{GITHUB_API}{path}", timeout=(3, 10), **kwargs)
        if response.status_code in TRANSIENT:
            raise TransientGitHubError(f"Temporary GitHub response: HTTP {response.status_code}")
        if not response.ok:
            raise PermanentGitHubError(f"GitHub API rejected request: HTTP {response.status_code}: {response.text[:250]}")
        return response.json() if response.content else None

    def fetch_issue(self, issue_number: int) -> dict[str, Any]:
        return self._request("GET", f"/repos/{self.repo}/issues/{issue_number}")

    def fetch_comments(self, issue_number: int) -> list[dict[str, Any]]:
        return self._request("GET", f"/repos/{self.repo}/issues/{issue_number}/comments", params={"per_page": 100})

    def apply_labels(self, issue_number: int, labels: list[str]) -> dict[str, Any]:
        # Optional demonstration switch: first label-write fails transiently.
        if os.getenv("TRIAGE_SIMULATE_TRANSIENT", "0") == "1" and not self._simulated_failure_used:
            self._simulated_failure_used = True
            raise TransientGitHubError("Simulated transient failure before GitHub label write")
        return self._request("POST", f"/repos/{self.repo}/issues/{issue_number}/labels", json={"labels": labels})

    def post_comment_once(self, issue_number: int, body: str) -> dict[str, Any] | None:
        marker = f"{MARKER_PREFIX} issue={issue_number}"
        existing = self.fetch_comments(issue_number)
        if any(marker in comment.get("body", "") for comment in existing):
            print("Comment marker already exists; skipping duplicate comment.")
            return None
        return self._request("POST", f"/repos/{self.repo}/issues/{issue_number}/comments", json={"body": f"{marker}\n\n{body}"})


def classify_issue(issue: dict[str, Any]) -> dict[str, Any]:
    """Use an LLM for suggestions; write actions remain deterministic and bounded."""
    client = OpenAI()
    prompt = f"""Triage this GitHub issue. Return JSON only with keys: category, priority, labels, summary.
category must be one of bug, feature, question, documentation, other.
priority must be one of P0, P1, P2, P3.
labels must be 1-3 short labels suitable for a GitHub repository (avoid labels that may not exist; use bug, enhancement, question, documentation, priority labels only if appropriate).
summary must be a concise Markdown triage summary, no more than 4 bullets.
Issue title: {issue.get('title','')}
Issue body: {issue.get('body') or '(empty)'}
Existing labels: {[label['name'] for label in issue.get('labels', [])]}"""
    response = client.responses.create(model=os.getenv("OPENAI_MODEL", "gpt-4.1-mini"), input=prompt)
    data = json.loads(response.output_text)
    allowed_categories = {"bug", "feature", "question", "documentation", "other"}
    allowed_priorities = {"P0", "P1", "P2", "P3"}
    if data.get("category") not in allowed_categories or data.get("priority") not in allowed_priorities:
        raise ValueError("Model returned invalid category or priority")
    labels = data.get("labels")
    if not isinstance(labels, list) or not all(isinstance(x, str) and x.strip() for x in labels):
        raise ValueError("Model returned malformed labels")
    data["labels"] = list(dict.fromkeys(labels))[:3]
    if not isinstance(data.get("summary"), str) or not data["summary"].strip():
        raise ValueError("Model returned malformed summary")
    return data


def build_engine(tools: TriageTools) -> Engine:
    registry = FunctionRegister()
    registry.register(tools.apply_labels)
    registry.register(tools.post_comment_once)
    return Engine(registry)


def execute_guarded(engine: Engine, function_name: str, *args, **kwargs):
    policy = ExecutionPolicy(max_attempts=4, retry_on=(TransientGitHubError, requests.Timeout, requests.ConnectionError))
    backoff = BackoffPolicy(initial_delay=0.5, multiplier=2, max_delay=4, jitter=False)
    return engine.execute(function_name, *args, policy=policy, backoff=backoff, timeout=15, attempt_timeout=10, **kwargs)


def run(repo: str, issue_number: int):
    token = os.environ["GITHUB_TOKEN"]
    tools = TriageTools(token, repo)
    engine = build_engine(tools)
    try:
        issue = tools.fetch_issue(issue_number)
        if issue.get("pull_request"):
            raise ValueError("This demo is for issues, not pull requests.")
        triage = classify_issue(issue)
        print("\n--- Proposed triage ---")
        print(json.dumps(triage, indent=2))
        if os.getenv("TRIAGE_AUTO_APPLY", "0") != "1":
            answer = input("Apply these labels and post the triage comment? [y/N] ").strip().lower()
            if answer != "y":
                print("Cancelled. No write actions performed.")
                return
        execute_guarded(engine, "apply_labels", issue_number, triage["labels"])
        execute_guarded(engine, "post_comment_once", issue_number, triage["summary"])
        print("\nTriage applied successfully.")
    finally:
        for execution in engine.executions.values():
            print(f"AgentGuard execution={execution.execution_id} status={execution.status} attempts={execution.attempt_number} retries={execution.retry_history}")
        tools.session.close()

if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: python triage.py owner/repo ISSUE_NUMBER")
        sys.exit(2)
    run(sys.argv[1], int(sys.argv[2]))
