# Contributing to AgentGuard

Thank you for your interest in contributing to AgentGuard!

AgentGuard is an open-source project focused on reliable execution, idempotency, coordination, state management, and recovery. Contributions that improve correctness, reliability, documentation, testing, and usability are welcome.

## Getting Started

### 1. Fork the repository

Fork AgentGuard on GitHub and clone your fork:

```bash
git clone https://github.com/<YOUR-USERNAME>/AgentGuard.git
cd AgentGuard
```

### 2. Create a virtual environment

```bash
python -m venv .venv
```

Activate it:

**Windows (PowerShell):**

```powershell
.venv\Scripts\Activate.ps1
```

**Linux/macOS:**

```bash
source .venv/bin/activate
```

### 3. Install AgentGuard in development mode

```bash
pip install -e .
```

Install development dependencies:

```bash
pip install -r requirements-dev.txt
```

## Development Workflow

### 1. Create a branch

Avoid working directly on the main branch.

```bash
git checkout -b feat/your-feature
```

Suggested branch naming:

- `feat/` — new functionality
- `fix/` — bug fixes
- `docs/` — documentation changes
- `test/` — test-related changes
- `refactor/` — refactoring
- `chore/` — maintenance tasks

### 2. Make your changes

Keep changes focused and avoid combining unrelated features or fixes in a single pull request.

For changes involving execution lifecycle, state transitions, coordination, idempotency, or recovery, consider the failure scenarios and edge cases alongside the normal execution path.

### 3. Run tests

Run the test suite:

```bash
pytest
```

If applicable, run tests with coverage:

```bash
pytest --cov=agentguard
```

Ensure that your changes do not break existing functionality.

### 4. Check code quality

Run the project's configured linting and type-checking tools when applicable.

For example:

```bash
ruff check .
```

### 5. Commit your changes

Write clear and descriptive commit messages.

```bash
git add .
git commit -m "fix: handle recovery state transition"
```

### 6. Push your branch

```bash
git push origin feat/your-feature
```

### 7. Open a Pull Request

Submit a pull request against the main branch of the AgentGuard repository.

Your pull request should include:

- A clear description of the problem or change.
- The motivation behind the change.
- Relevant tests.
- Any documentation updates required.
- Relevant issues, if applicable.

## Reporting Bugs

When reporting a bug, include:

- A clear description of the issue.
- Steps to reproduce it.
- Expected behavior.
- Actual behavior.
- Python version and operating system.
- Relevant logs, traceback, or minimal reproducible example.

## Proposing Features

For substantial changes, open an issue before implementing the feature.

This helps discuss the design, scope, compatibility, and expected behavior before significant work begins.

## Contribution Guidelines

- Keep pull requests focused and reasonably small.
- Add tests for new functionality and bug fixes.
- Avoid breaking public APIs without prior discussion.
- Document public functionality and meaningful behavioral changes.
- Do not include unrelated changes.
- Be respectful and constructive in discussions and reviews.

## Questions

If you have questions, open a GitHub issue or start a discussion in the repository.

Thank you for helping make AgentGuard better!
