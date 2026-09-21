# Dramatic GIFs in the PR comment bot 🎭

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Tracks:** [GitHub issue #63](https://github.com/ferminhg/mergency/issues/63). Design: `docs/adr/0023-dramatic-gifs-in-pr-comments.md`.

**Goal:** Make the PR comment bot's warn/breach comment harder to ignore by adding a severity-scaled headline and a GIF (live-searched via Giphy, with a hardcoded fallback), while the recovery comment stays sober per the ADR.

**Architecture:** A new severity concept (`BudgetSeverity`: warn/breach) derived from the existing `BudgetStatus.remaining_pct` — no new config, reusing what ADR 0007 already computes. A new port `domain/ports/gif_provider.py` and its adapter `adapters/giphy/giphy_client.py` (Giphy search, hardcoded per-severity fallback on failure/timeout). `domain/pr_comment_formatter.py` and `worker/evaluate_pr_budget.py` (both from plan 0012) are extended, not replaced.

**Tech Stack:** Python, `httpx` (moved from dev-only to a runtime dependency for the Giphy HTTP call), pytest. No other new dependencies.

---

## Status

proposed

## Context

This plan builds directly on top of plan `docs/plan/0012-pr-comment-bot.md`, which is already implemented on `main`. It does not re-derive that plan's API — verify these exist in `src/mergency/` before starting (they do, as of this writing):

- `mergency.domain.models.budget_status.BudgetStatus(owner, window_days, limit, consumed, remaining_pct)` — `remaining_pct` is already clamped to `>= 0.0` by `BudgetCalculator.status_for` (`src/mergency/domain/budget_calculator.py:29`), so "budget fully consumed" always reads as exactly `0.0`, never negative.
- `mergency.domain.pr_budget_evaluator.PrBudgetEvaluator.evaluate(...) -> list[BudgetStatus]` returning only owners at or below `warn_threshold_pct` — this plan's severity split happens *within* that already-filtered list, it does not change what counts as "shrinking".
- `mergency.domain.pr_comment_formatter.format_shrinking_budget_comment(statuses) -> str` and `format_recovered_comment() -> str`, and `mergency.worker.evaluate_pr_budget` orchestrating create/update/recover — both are modified by this plan (see Tasks 7–8), not replaced.
- `mergency.api.deps.reset_dependency_caches()` — extended with the new `get_gif_provider` factory.

**Severity is derived, not configured.** ADR 0023 says "this ADR does not introduce a new severity concept" — but the codebase as it stands only has a single `warn_threshold_pct` cutoff (binary shrinking/healthy), no existing warn/breach split. This plan adds the smallest derivation that satisfies the ADR without inventing new config: `BudgetSeverity.BREACH` when `remaining_pct <= 0` (budget fully consumed), `BudgetSeverity.WARN` otherwise. Since `PrBudgetEvaluator` already only returns owners at or below `warn_threshold_pct`, every status reaching the formatter is already at least a warn — this split only decides whether it escalates to breach. No new `TenantConfig` field is introduced.

**Headline is comment-wide, not per-owner.** The ADR's example wording (`"⚠️ Budget getting tight for <owner>"`) illustrates a single-owner case, but the existing comment format (plan 0012) already lists every shrinking owner in one shared markdown table under one headline. This plan keeps that shape: one headline for the whole comment, chosen by the **worst** severity across all shrinking owners (`worst_severity(statuses)`), with the per-owner table underneath unchanged. `<owner>` is dropped from the headline text since the table already names every owner.

**Fallback GIF URLs are adapter-level constants, not `Settings` fields.** The ADR frames them as "a small, curated fallback asset list to maintain" (code, not a secret) — only the Giphy API key is a secret and goes through `Settings`/env var, per "never hardcoded". The fallback URLs live as a plain dict in `adapters/giphy/giphy_client.py`, same file that owns the severity → search-keyword mapping.

**`httpx` needs to move from dev-only to a runtime dependency.** It's currently listed only under `[dependency-groups].dev` (used by `TestClient`/`httpx.ASGITransport` in tests) — this plan's adapter needs it in production code, so it moves to `[project].dependencies`.

**New required setting.** `giphy_api_key` is added to `Settings` as a required field (same pattern as `github_app_id`/`github_webhook_secret` — no default, real value only via `.env`). This means your local `.env` (untracked) must set `MERGENCY_GIPHY_API_KEY=...` before running the test suite from Task 5 onward, the same way it already must set `MERGENCY_DATABASE_URL` and the GitHub secrets. `.env.example` is updated to document the new var; you provide the actual value locally.

## Directory structure (new/changed files)

```
src/mergency/
├── domain/
│   ├── models/
│   │   └── budget_severity.py       # NEW: BudgetSeverity enum (warn/breach)
│   ├── ports/
│   │   └── gif_provider.py          # NEW: GifProvider port
│   ├── severity_resolver.py         # NEW: severity_for() / worst_severity()
│   └── pr_comment_formatter.py      # MODIFIED: severity headline + gif embed
├── adapters/
│   └── giphy/
│       ├── __init__.py              # NEW
│       └── giphy_client.py          # NEW: GiphyClient (search + fallback)
├── worker/
│   └── evaluate_pr_budget.py        # MODIFIED: resolve severity, fetch gif
└── api/
    ├── settings.py                  # MODIFIED: + giphy_api_key
    └── deps.py                      # MODIFIED: + get_gif_provider factory

pyproject.toml                       # MODIFIED: httpx -> runtime dependency
.env.example                         # MODIFIED: + MERGENCY_GIPHY_API_KEY

tests/  (mirrors src/, one test file per new/changed module — see tasks below)
```

---

## Task 1: `BudgetSeverity` model + severity resolver

**Files:** Create `tests/domain/models/test_budget_severity.py`, `tests/domain/test_severity_resolver.py`, `src/mergency/domain/models/budget_severity.py`, `src/mergency/domain/severity_resolver.py`.

- [ ] **Step 1: Write the tests**

```python
# tests/domain/models/test_budget_severity.py
from mergency.domain.models.budget_severity import BudgetSeverity


def test_budget_severity_has_warn_and_breach_values():
    assert BudgetSeverity.WARN.value == "warn"
    assert BudgetSeverity.BREACH.value == "breach"
```

```python
# tests/domain/test_severity_resolver.py
from mergency.domain.models.budget_severity import BudgetSeverity
from mergency.domain.models.budget_status import BudgetStatus
from mergency.domain.severity_resolver import severity_for, worst_severity


def _status(remaining_pct: float) -> BudgetStatus:
    return BudgetStatus(
        owner="@org/team-a", window_days=28, limit=5, consumed=2, remaining_pct=remaining_pct
    )


def test_severity_for_is_warn_when_budget_still_has_headroom():
    assert severity_for(_status(20.0)) == BudgetSeverity.WARN


def test_severity_for_is_breach_when_budget_is_fully_consumed():
    assert severity_for(_status(0.0)) == BudgetSeverity.BREACH


def test_worst_severity_is_breach_when_any_status_has_breached():
    statuses = [_status(20.0), _status(0.0)]

    assert worst_severity(statuses) == BudgetSeverity.BREACH


def test_worst_severity_is_warn_when_no_status_has_breached():
    statuses = [_status(20.0), _status(30.0)]

    assert worst_severity(statuses) == BudgetSeverity.WARN
```

Run: `docker compose run --rm app pytest tests/domain/models/test_budget_severity.py tests/domain/test_severity_resolver.py -v`
Expected: both files fail with `ModuleNotFoundError`.

- [ ] **Step 2: Implement**

```python
# src/mergency/domain/models/budget_severity.py
from enum import Enum


class BudgetSeverity(str, Enum):
    WARN = "warn"
    BREACH = "breach"
```

```python
# src/mergency/domain/severity_resolver.py
from mergency.domain.models.budget_severity import BudgetSeverity
from mergency.domain.models.budget_status import BudgetStatus


def severity_for(status: BudgetStatus) -> BudgetSeverity:
    return BudgetSeverity.BREACH if status.remaining_pct <= 0 else BudgetSeverity.WARN


def worst_severity(statuses: list[BudgetStatus]) -> BudgetSeverity:
    if any(severity_for(status) == BudgetSeverity.BREACH for status in statuses):
        return BudgetSeverity.BREACH
    return BudgetSeverity.WARN
```

Run: `docker compose run --rm app pytest tests/domain/models/test_budget_severity.py tests/domain/test_severity_resolver.py -v`
Expected: 6 passed.

- [ ] **Step 3:** commit: `feat: add BudgetSeverity model and severity resolver`.

---

## Task 2: `GifProvider` port

**Files:** Create `src/mergency/domain/ports/gif_provider.py`.

This is a `Protocol` with no behavior of its own — same convention as every other port in `domain/ports/` (e.g. `pr_comment_client.py`), none of which have a standalone test file; they're exercised through their adapter's tests (Task 4) and through the worker task test's stub (Task 8).

- [ ] **Step 1: Implement**

```python
# src/mergency/domain/ports/gif_provider.py
from typing import Protocol

from mergency.domain.models.budget_severity import BudgetSeverity


class GifProvider(Protocol):
    async def gif_for_severity(self, severity: BudgetSeverity) -> str: ...
```

- [ ] **Step 2: Verify it imports cleanly**

Run: `docker compose run --rm app python -c "from mergency.domain.ports.gif_provider import GifProvider; print('ok')"`
Expected: `ok`.

- [ ] **Step 3:** commit: `feat: add GifProvider port`.

---

## Task 3: Move `httpx` to runtime dependencies

**Files:** Modify `pyproject.toml`.

- [ ] **Step 1: Implement**

In `pyproject.toml`, add `"httpx>=0.27"` to `[project].dependencies` and remove it from `[dependency-groups].dev` (it stays available to tests transitively as a main dependency):

```toml
[project]
name = "mergency"
version = "0.1.0"
description = "Error budget bot for pull requests"
requires-python = ">=3.12"
dependencies = [
    "fastapi>=0.115",
    "pydantic-settings>=2.5",
    "pygithub>=2.4",
    "celery[redis]>=5.4",
    "uvicorn[standard]>=0.32",
    "pyyaml>=6.0",
    "codeowners>=0.9",
    "sqlalchemy[asyncio]>=2.0",
    "asyncpg>=0.29",
    "alembic>=1.13",
    "httpx>=0.27",
]

[dependency-groups]
dev = [
    "pytest>=8.3",
    "pytest-asyncio>=0.24",
    "ruff>=0.7",
]
```

- [ ] **Step 2: Rebuild and verify**

Run: `docker compose build app && docker compose run --rm app python -c "import httpx; print('ok')"`
Expected: `ok`.

- [ ] **Step 3:** commit: `build: move httpx to runtime dependencies`.

---

## Task 4: `GiphyClient` adapter

**Files:** Create `tests/adapters/giphy/test_giphy_client.py`, `src/mergency/adapters/giphy/__init__.py`, `src/mergency/adapters/giphy/giphy_client.py`.

- [ ] **Step 1: Write the tests**

```python
# tests/adapters/giphy/test_giphy_client.py
import httpx

from mergency.adapters.giphy.giphy_client import _FALLBACK_GIF_URLS, GiphyClient
from mergency.domain.models.budget_severity import BudgetSeverity


class _StubResponse:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        pass

    def json(self) -> dict:
        return self._payload


class _StubAsyncClient:
    def __init__(self, response: _StubResponse | None = None, error: Exception | None = None) -> None:
        self._response = response
        self._error = error

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args) -> bool:
        return False

    async def get(self, url, params):
        if self._error is not None:
            raise self._error
        return self._response


def _payload_with_url(url: str) -> dict:
    return {"data": [{"images": {"original": {"url": url}}}]}


async def test_returns_the_first_search_result_url(monkeypatch):
    stub_client = _StubAsyncClient(
        response=_StubResponse(_payload_with_url("https://giphy.example/alarm.gif"))
    )
    monkeypatch.setattr(
        "mergency.adapters.giphy.giphy_client.httpx.AsyncClient", lambda **kwargs: stub_client
    )

    gif_url = await GiphyClient("test-api-key").gif_for_severity(BudgetSeverity.WARN)

    assert gif_url == "https://giphy.example/alarm.gif"


async def test_falls_back_to_the_configured_gif_when_giphy_times_out(monkeypatch):
    stub_client = _StubAsyncClient(error=httpx.TimeoutException("timed out"))
    monkeypatch.setattr(
        "mergency.adapters.giphy.giphy_client.httpx.AsyncClient", lambda **kwargs: stub_client
    )

    gif_url = await GiphyClient("test-api-key").gif_for_severity(BudgetSeverity.BREACH)

    assert gif_url == _FALLBACK_GIF_URLS[BudgetSeverity.BREACH]


async def test_falls_back_when_giphy_returns_no_results(monkeypatch):
    stub_client = _StubAsyncClient(response=_StubResponse({"data": []}))
    monkeypatch.setattr(
        "mergency.adapters.giphy.giphy_client.httpx.AsyncClient", lambda **kwargs: stub_client
    )

    gif_url = await GiphyClient("test-api-key").gif_for_severity(BudgetSeverity.WARN)

    assert gif_url == _FALLBACK_GIF_URLS[BudgetSeverity.WARN]


async def test_falls_back_on_an_unexpected_response_shape(monkeypatch):
    stub_client = _StubAsyncClient(response=_StubResponse({"data": [{"images": {}}]}))
    monkeypatch.setattr(
        "mergency.adapters.giphy.giphy_client.httpx.AsyncClient", lambda **kwargs: stub_client
    )

    gif_url = await GiphyClient("test-api-key").gif_for_severity(BudgetSeverity.BREACH)

    assert gif_url == _FALLBACK_GIF_URLS[BudgetSeverity.BREACH]
```

Run: `docker compose run --rm app pytest tests/adapters/giphy/test_giphy_client.py -v`
Expected: fails with `ModuleNotFoundError`.

- [ ] **Step 2: Implement**

```python
# src/mergency/adapters/giphy/__init__.py
```

```python
# src/mergency/adapters/giphy/giphy_client.py
import logging

import httpx

from mergency.domain.models.budget_severity import BudgetSeverity

logger = logging.getLogger(__name__)

_SEARCH_URL = "https://api.giphy.com/v1/gifs/search"
_TIMEOUT_SECONDS = 2.0

_SEARCH_KEYWORDS = {
    BudgetSeverity.WARN: "alarm",
    BudgetSeverity.BREACH: "disaster",
}

_FALLBACK_GIF_URLS = {
    BudgetSeverity.WARN: "https://media.giphy.com/media/l0MYt5jPR6QX5pnqM/giphy.gif",
    BudgetSeverity.BREACH: "https://media.giphy.com/media/3o7TKSjRrfIPjeiVyM/giphy.gif",
}


class GiphyClient:
    def __init__(self, api_key: str) -> None:
        self._api_key = api_key

    async def gif_for_severity(self, severity: BudgetSeverity) -> str:
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT_SECONDS) as client:
                response = await client.get(
                    _SEARCH_URL,
                    params={
                        "api_key": self._api_key,
                        "q": _SEARCH_KEYWORDS[severity],
                        "limit": 1,
                    },
                )
                response.raise_for_status()
                results = response.json()["data"]
                return results[0]["images"]["original"]["url"]
        except (httpx.HTTPError, KeyError, IndexError) as error:
            logger.warning(
                "giphy lookup failed, using fallback gif",
                extra={"severity": severity.value, "error": str(error)},
            )
            return _FALLBACK_GIF_URLS[severity]
```

Run: `docker compose run --rm app pytest tests/adapters/giphy/test_giphy_client.py -v`
Expected: 4 passed.

- [ ] **Step 3:** commit: `feat: add GiphyClient adapter with per-severity fallback`.

---

## Task 5: `Settings.giphy_api_key`

**Files:** Modify `src/mergency/api/settings.py`, `.env.example`.

- [ ] **Step 1: Implement**

```python
# src/mergency/api/settings.py
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="MERGENCY_")

    github_app_id: str
    github_private_key: str
    github_webhook_secret: str
    database_url: str
    giphy_api_key: str
```

```
# .env.example
MERGENCY_GITHUB_APP_ID=
MERGENCY_GITHUB_PRIVATE_KEY=
MERGENCY_GITHUB_WEBHOOK_SECRET=
MERGENCY_DATABASE_URL=postgresql+asyncpg://mergency:mergency@postgres:5432/mergency
MERGENCY_GIPHY_API_KEY=
```

**Before running any test after this step**, add `MERGENCY_GIPHY_API_KEY=<a-real-or-placeholder-value>` to your local `.env` (untracked) — every test that constructs `Settings()` will otherwise fail with a `pydantic` `ValidationError` for the missing required field, exactly as it already would if `MERGENCY_DATABASE_URL` were missing.

- [ ] **Step 2: Verify**

Run: `docker compose run --rm app python -c "from mergency.api.settings import Settings; print(Settings().giphy_api_key)"`
Expected: prints whatever value your local `.env` sets (no crash).

- [ ] **Step 3:** commit: `feat: add giphy_api_key setting`.

---

## Task 6: Wire `get_gif_provider` in `deps.py`

**Files:** Modify `src/mergency/api/deps.py`, `tests/api/test_deps.py`.

- [ ] **Step 1: Add the test** (append to `tests/api/test_deps.py`, reusing the module's existing `_set_required_env` helper)

```python
def test_get_gif_provider_is_cached_and_resettable(monkeypatch):
    from mergency.adapters.giphy.giphy_client import GiphyClient

    _set_required_env(monkeypatch, "test-app-id")
    monkeypatch.setenv("MERGENCY_GIPHY_API_KEY", "test-giphy-key")

    first = deps.get_gif_provider()
    assert deps.get_gif_provider() is first
    assert isinstance(first, GiphyClient)

    deps.reset_dependency_caches()
    assert deps.get_gif_provider() is not first
```

Run: `docker compose run --rm app pytest tests/api/test_deps.py -v`
Expected: the new test fails with `AttributeError: module 'mergency.api.deps' has no attribute 'get_gif_provider'`; existing tests still pass (assuming `MERGENCY_GIPHY_API_KEY` is set in your local `.env` per Task 5).

- [ ] **Step 2: Implement** — modify `src/mergency/api/deps.py`.

Add these imports alongside the existing ones:

```python
from mergency.adapters.giphy.giphy_client import GiphyClient
from mergency.domain.ports.gif_provider import GifProvider
```

Add this factory, alongside `get_pr_comment_client`:

```python
@lru_cache
def get_gif_provider() -> GifProvider:
    return GiphyClient(get_settings().giphy_api_key)
```

Extend `reset_dependency_caches()` with one more line:

```python
    get_gif_provider.cache_clear()
```

(keep every existing line in `reset_dependency_caches()` — just append this one.)

Run: `docker compose run --rm app pytest tests/api/test_deps.py -v`
Expected: all passed.

- [ ] **Step 3:** commit: `feat: wire get_gif_provider dependency`.

---

## Task 7: `pr_comment_formatter` — severity headline + GIF embed

**Files:** Modify `tests/domain/test_pr_comment_formatter.py`, `src/mergency/domain/pr_comment_formatter.py`.

This changes `format_shrinking_budget_comment`'s signature (adds a required `gif_url` argument) — Task 8 updates its one caller (`worker/evaluate_pr_budget.py`) to match.

- [ ] **Step 1: Replace the test file**

```python
# tests/domain/test_pr_comment_formatter.py
from mergency.domain.models.budget_status import BudgetStatus
from mergency.domain.pr_comment_formatter import (
    MARKER,
    format_recovered_comment,
    format_shrinking_budget_comment,
)

_GIF_URL = "https://giphy.example/alarm.gif"


def _status(owner: str, remaining_pct: float = 20.0) -> BudgetStatus:
    return BudgetStatus(
        owner=owner, window_days=28, limit=5, consumed=4, remaining_pct=remaining_pct
    )


def test_shrinking_comment_starts_with_the_marker():
    body = format_shrinking_budget_comment([_status("@org/team-a")], _GIF_URL)

    assert body.startswith(MARKER)


def test_shrinking_comment_lists_every_shrinking_owner():
    body = format_shrinking_budget_comment(
        [_status("@org/team-a"), _status("@org/team-b")], _GIF_URL
    )

    assert "@org/team-a" in body
    assert "@org/team-b" in body


def test_shrinking_comment_includes_consumed_limit_and_remaining_pct():
    body = format_shrinking_budget_comment([_status("@org/team-a")], _GIF_URL)

    assert "4/5" in body
    assert "20" in body


def test_shrinking_comment_embeds_the_gif_url():
    body = format_shrinking_budget_comment([_status("@org/team-a")], _GIF_URL)

    assert _GIF_URL in body


def test_shrinking_comment_uses_the_warn_headline_when_no_owner_has_breached():
    body = format_shrinking_budget_comment([_status("@org/team-a", remaining_pct=20.0)], _GIF_URL)

    assert "Budget getting tight" in body


def test_shrinking_comment_uses_the_breach_headline_when_an_owner_has_breached():
    body = format_shrinking_budget_comment([_status("@org/team-a", remaining_pct=0.0)], _GIF_URL)

    assert "Budget blown" in body


def test_recovered_comment_starts_with_the_marker_and_mentions_recovery():
    body = format_recovered_comment()

    assert body.startswith(MARKER)
    assert "recovered" in body.lower()


def test_recovered_comment_has_no_gif():
    body = format_recovered_comment()

    assert "![" not in body
```

Run: `docker compose run --rm app pytest tests/domain/test_pr_comment_formatter.py -v`
Expected: fails — `format_shrinking_budget_comment()` doesn't yet accept a second argument, and the headline/gif assertions have nothing to match.

- [ ] **Step 2: Implement**

```python
# src/mergency/domain/pr_comment_formatter.py
from mergency.domain.models.budget_severity import BudgetSeverity
from mergency.domain.models.budget_status import BudgetStatus
from mergency.domain.severity_resolver import worst_severity

MARKER = "<!-- mergency:budget-status -->"

_HEADLINES = {
    BudgetSeverity.WARN: "⚠️ Budget getting tight",
    BudgetSeverity.BREACH: "🚨 Budget blown",
}


def format_shrinking_budget_comment(statuses: list[BudgetStatus], gif_url: str) -> str:
    headline = _HEADLINES[worst_severity(statuses)]
    header = "| Team | Window | Consumed/Limit | Remaining | Status |"
    separator = "| --- | --- | --- | --- | --- |"
    rows = [
        f"| {status.owner} | {status.window_days}d | {status.consumed}/{status.limit} "
        f"| {status.remaining_pct:.0f}% | ⚠️ |"
        for status in statuses
    ]
    table = "\n".join([header, separator, *rows])
    return f"{MARKER}\n### {headline}\n\n![]({gif_url})\n\n{table}\n"


def format_recovered_comment() -> str:
    return f"{MARKER}\n### ✅ Budget recovered\n\nAll touched teams are back within budget.\n"
```

Run: `docker compose run --rm app pytest tests/domain/test_pr_comment_formatter.py -v`
Expected: 8 passed.

- [ ] **Step 3:** commit: `feat: scale PR comment headline by severity and embed a GIF`.

---

## Task 8: `evaluate_pr_budget` — resolve severity, fetch the GIF

**Files:** Modify `tests/worker/test_evaluate_pr_budget.py`, `src/mergency/worker/evaluate_pr_budget.py`.

- [ ] **Step 1: Replace the test file**

```python
# tests/worker/test_evaluate_pr_budget.py
from mergency.domain.models.budget_severity import BudgetSeverity
from mergency.domain.models.budget_status import BudgetStatus
from mergency.domain.models.tenant_config import TenantConfig
from mergency.domain.pr_comment_formatter import MARKER
from mergency.worker import evaluate_pr_budget as task_module


def _payload(action: str = "opened") -> dict:
    return {
        "action": action,
        "installation": {"id": 1},
        "repository": {"full_name": "acme/widgets"},
        "number": 42,
    }


class _StubFilesProvider:
    async def files_changed_in_pull_request(self, installation_id, repo, pr_number):
        return ["src/a.py"]


class _StubConfigResolver:
    async def resolve(self, installation_id, repo):
        return TenantConfig(installation_id, 28, "unassigned", 5, 50)


class _StubEvaluator:
    def __init__(self, shrinking: list[BudgetStatus]) -> None:
        self._shrinking = shrinking

    async def evaluate(self, installation_id, repo, changed_files, default_team, warn_threshold_pct):
        return self._shrinking


class _RecordingCommentClient:
    def __init__(self, existing_comment_id: int | None) -> None:
        self._existing_comment_id = existing_comment_id
        self.created: list[tuple] = []
        self.updated: list[tuple] = []

    async def find_marked_comment(self, installation_id, repo, pr_number):
        return self._existing_comment_id

    async def create_comment(self, installation_id, repo, pr_number, body):
        self.created.append((installation_id, repo, pr_number, body))

    async def update_comment(self, installation_id, repo, comment_id, body):
        self.updated.append((installation_id, repo, comment_id, body))


class _RecordingGifProvider:
    def __init__(self, url: str = "https://giphy.example/gif.gif") -> None:
        self.url = url
        self.calls: list[BudgetSeverity] = []

    async def gif_for_severity(self, severity):
        self.calls.append(severity)
        return self.url


def _shrinking_status(remaining_pct: float = 20.0) -> BudgetStatus:
    return BudgetStatus(
        owner="@org/team-a", window_days=28, limit=5, consumed=4, remaining_pct=remaining_pct
    )


def _wire(monkeypatch, *, shrinking: list[BudgetStatus], existing_comment_id: int | None):
    comment_client = _RecordingCommentClient(existing_comment_id)
    gif_provider = _RecordingGifProvider()
    monkeypatch.setattr(task_module, "get_pull_request_files_provider", lambda: _StubFilesProvider())
    monkeypatch.setattr(task_module, "get_config_resolver", lambda: _StubConfigResolver())
    monkeypatch.setattr(task_module, "get_pr_budget_evaluator", lambda: _StubEvaluator(shrinking))
    monkeypatch.setattr(task_module, "get_pr_comment_client", lambda: comment_client)
    monkeypatch.setattr(task_module, "get_gif_provider", lambda: gif_provider)
    return comment_client, gif_provider


def test_creates_a_comment_with_a_gif_when_an_owner_is_shrinking_and_none_exists_yet(monkeypatch):
    comment_client, gif_provider = _wire(
        monkeypatch, shrinking=[_shrinking_status()], existing_comment_id=None
    )

    task_module.evaluate_pr_budget(_payload())

    assert len(comment_client.created) == 1
    assert comment_client.updated == []
    installation_id, repo, pr_number, body = comment_client.created[0]
    assert (installation_id, repo, pr_number) == (1, "acme/widgets", 42)
    assert MARKER in body
    assert "@org/team-a" in body
    assert gif_provider.url in body
    assert gif_provider.calls == [BudgetSeverity.WARN]


def test_updates_the_existing_comment_when_still_shrinking(monkeypatch):
    comment_client, gif_provider = _wire(
        monkeypatch, shrinking=[_shrinking_status()], existing_comment_id=999
    )

    task_module.evaluate_pr_budget(_payload())

    assert comment_client.created == []
    assert len(comment_client.updated) == 1
    installation_id, repo, comment_id, body = comment_client.updated[0]
    assert (installation_id, repo, comment_id) == (1, "acme/widgets", 999)
    assert "@org/team-a" in body
    assert gif_provider.url in body


def test_uses_the_breach_severity_gif_when_an_owner_has_fully_consumed_its_budget(monkeypatch):
    _comment_client, gif_provider = _wire(
        monkeypatch, shrinking=[_shrinking_status(remaining_pct=0.0)], existing_comment_id=None
    )

    task_module.evaluate_pr_budget(_payload())

    assert gif_provider.calls == [BudgetSeverity.BREACH]


def test_updates_the_existing_comment_to_recovered_when_no_longer_shrinking(monkeypatch):
    comment_client, gif_provider = _wire(monkeypatch, shrinking=[], existing_comment_id=999)

    task_module.evaluate_pr_budget(_payload())

    assert comment_client.created == []
    assert len(comment_client.updated) == 1
    _, _, comment_id, body = comment_client.updated[0]
    assert comment_id == 999
    assert "recovered" in body.lower()
    assert gif_provider.calls == []


def test_does_nothing_when_healthy_and_no_existing_comment(monkeypatch):
    comment_client, gif_provider = _wire(monkeypatch, shrinking=[], existing_comment_id=None)

    task_module.evaluate_pr_budget(_payload())

    assert comment_client.created == []
    assert comment_client.updated == []
    assert gif_provider.calls == []


def test_malformed_payload_is_dropped_without_error():
    task_module.evaluate_pr_budget({"action": "opened"})
```

Run: `docker compose run --rm app pytest tests/worker/test_evaluate_pr_budget.py -v`
Expected: fails — `task_module.get_gif_provider` doesn't exist yet, and `format_shrinking_budget_comment` is called with the old one-argument signature.

- [ ] **Step 2: Implement**

```python
# src/mergency/worker/evaluate_pr_budget.py
import asyncio
import logging

from mergency.adapters.github.pull_request_signal_parser import parse_pull_request_signal
from mergency.api.deps import (
    get_config_resolver,
    get_gif_provider,
    get_pr_budget_evaluator,
    get_pr_comment_client,
    get_pull_request_files_provider,
)
from mergency.domain.models.pull_request_signal import PullRequestSignal
from mergency.domain.pr_comment_formatter import (
    format_recovered_comment,
    format_shrinking_budget_comment,
)
from mergency.domain.severity_resolver import worst_severity
from mergency.worker.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(name="evaluate_pr_budget")
def evaluate_pr_budget(payload: dict) -> None:
    try:
        signal = parse_pull_request_signal(payload)
    except (KeyError, ValueError, TypeError) as error:
        logger.warning(
            "pull_request payload could not be parsed, dropped", extra={"error": str(error)}
        )
        return

    asyncio.run(_evaluate_and_comment(signal))


async def _evaluate_and_comment(signal: PullRequestSignal) -> None:
    changed_files = await get_pull_request_files_provider().files_changed_in_pull_request(
        signal.installation_id, signal.repo, signal.pr_number
    )
    config = await get_config_resolver().resolve(signal.installation_id, signal.repo)
    shrinking = await get_pr_budget_evaluator().evaluate(
        signal.installation_id,
        signal.repo,
        changed_files,
        config.default_team,
        config.warn_threshold_pct,
    )

    comment_client = get_pr_comment_client()
    existing_comment_id = await comment_client.find_marked_comment(
        signal.installation_id, signal.repo, signal.pr_number
    )

    if shrinking:
        gif_url = await get_gif_provider().gif_for_severity(worst_severity(shrinking))
        body = format_shrinking_budget_comment(shrinking, gif_url)
        if existing_comment_id is not None:
            await comment_client.update_comment(
                signal.installation_id, signal.repo, existing_comment_id, body
            )
        else:
            await comment_client.create_comment(
                signal.installation_id, signal.repo, signal.pr_number, body
            )
    elif existing_comment_id is not None:
        await comment_client.update_comment(
            signal.installation_id, signal.repo, existing_comment_id, format_recovered_comment()
        )
```

Run: `docker compose run --rm app pytest tests/worker/test_evaluate_pr_budget.py -v`
Expected: 6 passed.

- [ ] **Step 3: Full-suite check**

Run: `docker compose run --rm app pytest -v`
Expected: all tests pass (old and new).

- [ ] **Step 4:** commit: `feat: fetch a severity-scaled GIF for the PR comment bot`.

---

## Verification (full suite, after all tasks)

1. Full suite: `docker compose run --rm app pytest -v` — all tests pass, old and new.
2. Lint: `docker compose run --rm app ruff check src tests` — no errors.
3. Domain purity: `docker compose run --rm app grep -rniE "httpx|celery|fastapi|sqlalchemy|pygithub|^from github|^import github" src/mergency/domain/` — no matches (confirms `BudgetSeverity`, `severity_resolver.py`, `GifProvider`, and the updated `pr_comment_formatter.py` stay framework- and HTTP-free; the Giphy HTTP call lives only in `adapters/giphy/giphy_client.py`).
4. Config check: `docker compose run --rm app grep -n "giphy_api_key" src/mergency/api/settings.py src/mergency/api/deps.py` — one required field, one factory reading it; no hardcoded API key anywhere in `src/`.
5. `git diff tests/domain/test_pr_comment_formatter.py tests/worker/test_evaluate_pr_budget.py` shows the signature/behavior changes are additive on top of plan 0012's tests, not a rewrite of unrelated assertions.
6. Manual smoke (optional, not part of CI): with a real installation, a Giphy API key in `.env`, and a `mergency.yml` low `budget.max_events_per_window`, open a PR touching a team already at warn (`remaining_pct` between 0 and `warn_threshold_pct`) — confirm the comment shows the "Budget getting tight" headline and an embedded GIF. Push more failing events until that team's budget hits `remaining_pct == 0` and confirm a `synchronize` updates the same comment to "Budget blown" with a different GIF. Then let the team recover and confirm the comment flips to "Budget recovered" with **no** GIF. Temporarily break the Giphy API key (or block network to `api.giphy.com`) and confirm the comment still gets a GIF — the fallback one for that severity — never a comment with no image.
