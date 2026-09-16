# Deploy-to-Incident Traceability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement ADR 0011's generic incident-reporting path — an authenticated `POST /api/v1/installations/{installation_id}/incidents` endpoint that lets an external CD pipeline, PagerDuty, or Opsgenie report a production incident tied to a commit range, so Mergency attributes it to owners (via ADR 0006's CODEOWNERS resolution, applied per commit in the range) and counts it against budget as a new `EventType.INCIDENT`.

**Architecture:** The endpoint validates the installation and its bearer token (reusing ADR 0009's `token_matches`), then enqueues a new Celery task instead of doing GitHub calls inline — the same request/response shape the webhook receiver already uses for `push`/`check_run`. The task resolves the reported `base_sha..head_sha` range to a list of commit SHAs via a new `CommitRangeProvider` port (backed by GitHub's compare API), then re-runs the existing per-commit pipeline already used by `classify_activity_event.py` — changed files, `OwnershipResolver`, `ConfigResolver` — to attribute one `Event(event_type=INCIDENT)` per `(commit, owner)` pair. `BudgetCalculator` counts `INCIDENT` alongside `BUILD_FAILURE`/`REVERT` by default, per the ADR.

**Tech Stack:** Python 3.12, FastAPI, Celery, PyGithub, SQLAlchemy (async, Postgres), pytest/pytest-asyncio/httpx, Docker Compose — no new dependencies.

---

## Status

proposed

## Context

`docs/adr/0011-deploy-to-incident-traceability-v2.md` sketches two incident sources and defers the concrete design ("left open, deliberately") of correlation logic, severity weighting, and endpoint auth to "the real implementation plan, once this becomes an active priority." This plan is that priority, scoped down from the ADR as follows (confirmed during scoping, not re-litigated here):

- 🎯 **Only the generic `POST /incidents` endpoint** ships in this plan. The GitHub-native `deployment_status` webhook path stays unimplemented — it needs its own plan once an org that actually uses GitHub Deployments asks for it, so this plan doesn't guess at its payload shape today.
- 🔗 **Correlation attributes every commit in the reported range**, not just the range's head. Mirrors ADR 0006's existing per-commit CODEOWNERS resolution (already how `push` events are attributed) rather than requiring the caller to already know which single commit is at fault.
- ⚖️ **No severity weighting.** Every `INCIDENT` event counts as one unit against budget, exactly like `BUILD_FAILURE`/`REVERT` today. The request body still accepts an optional `severity` string and it is persisted nowhere in this plan (there is no incident-detail table yet, only the existing `events` row) — accepting it now costs nothing and avoids a breaking request-shape change if severity-aware weighting is designed later, but nothing reads it yet.
- 🔑 **Auth reuses ADR 0009's installation-scoped bearer token** (`api/auth.py::token_matches`) — the same mechanism the historical query API already uses. No new auth surface.

This plan follows the existing `push`/`check_run` pipeline shape closely: `worker/classify_activity_event.py`'s `_classify_resolve_and_persist` already does "resolve changed files → resolve owners → save one `Event` per owner" for a single commit. The new `worker/report_incident.py` task does the same thing per commit in a range, so no existing files need behavioral changes beyond the two one-line additions in Task 1.

## Directory structure (additions only)

```
src/mergency/
├── api/
│   └── incidents.py                       # NEW — POST /api/v1/installations/{id}/incidents
├── domain/
│   ├── models/
│   │   └── incident_report.py             # NEW — IncidentReport(installation_id, repo, base_sha, head_sha, severity, occurred_at)
│   └── ports/
│       └── commit_range_provider.py       # NEW — CommitRangeProvider protocol
├── adapters/
│   └── github/
│       └── commit_range_provider.py       # NEW — GithubCommitRangeProvider (compare API)
└── worker/
    └── report_incident.py                 # NEW — Celery task, orchestrates correlation + attribution

tests/
├── api/
│   └── test_incidents.py                  # NEW
├── domain/
│   └── models/
│       └── test_incident_report.py        # NEW
├── adapters/
│   └── github/
│       └── test_commit_range_provider.py  # NEW
└── worker/
    └── test_report_incident.py            # NEW
```

Modified (existing) files: `src/mergency/domain/models/event_type.py`, `src/mergency/domain/budget_calculator.py`, `src/mergency/api/deps.py`, `src/mergency/api/app.py`, `src/mergency/worker/celery_app.py`, `tests/domain/models/test_event.py`, `tests/domain/test_budget_calculator.py`, `tests/api/test_deps.py`.

No new database migration: the `events` table's `event_type` column is already a plain `String` (see `src/mergency/adapters/db/tables.py`), so the new `"incident"` value needs no schema change.

---

## Task 1: `EventType.INCIDENT`, counted by default

**Files:**
- Modify: `src/mergency/domain/models/event_type.py`
- Modify: `src/mergency/domain/budget_calculator.py`
- Modify: `tests/domain/models/test_event.py`
- Modify: `tests/domain/test_budget_calculator.py`

- [ ] **Step 1: Write the failing test for the new enum value**

```python
# tests/domain/models/test_event.py (add this assertion to the existing test)
def test_event_type_values_match_adr():
    assert EventType.BUILD_FAILURE == "build_failure"
    assert EventType.REVERT == "revert"
    assert EventType.INCIDENT == "incident"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker compose run --rm app pytest tests/domain/models/test_event.py -v`
Expected: FAIL with `AttributeError: INCIDENT`

- [ ] **Step 3: Add the enum value**

```python
# src/mergency/domain/models/event_type.py
from enum import Enum


class EventType(str, Enum):
    BUILD_FAILURE = "build_failure"
    REVERT = "revert"
    INCIDENT = "incident"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `docker compose run --rm app pytest tests/domain/models/test_event.py -v`
Expected: PASS

- [ ] **Step 5: Write the failing test for budget counting**

```python
# tests/domain/test_budget_calculator.py (add this test)
async def test_status_for_counts_incident_events_alongside_build_failure_and_revert():
    event_repository = InMemoryEventRepository()
    config_repository = InMemoryTenantConfigRepository()
    await config_repository.upsert(
        TenantConfig(1, rolling_window_days=28, default_team="unassigned", max_events_per_window=5, warn_threshold_pct=50)
    )
    now = datetime.now(timezone.utc)
    await event_repository.save_if_new(_event(EventType.INCIDENT, "sha1", "@org/backend-team", now))
    calculator = BudgetCalculator(event_repository, config_repository)

    status = await calculator.status_for(1, "@org/backend-team")

    assert status.consumed == 1
```

- [ ] **Step 6: Run test to verify it fails**

Run: `docker compose run --rm app pytest tests/domain/test_budget_calculator.py -v`
Expected: FAIL with `assert 0 == 1`

- [ ] **Step 7: Add `INCIDENT` to the counted event types**

```python
# src/mergency/domain/budget_calculator.py (change this line only)
_COUNTED_EVENT_TYPES = (EventType.BUILD_FAILURE, EventType.REVERT, EventType.INCIDENT)
```

- [ ] **Step 8: Run test to verify it passes**

Run: `docker compose run --rm app pytest tests/domain/test_budget_calculator.py -v`
Expected: PASS

- [ ] **Step 9: Commit**

```bash
git add src/mergency/domain/models/event_type.py src/mergency/domain/budget_calculator.py tests/domain/models/test_event.py tests/domain/test_budget_calculator.py
git commit -m "feat: add EventType.INCIDENT, counted against budget by default"
```

---

## Task 2: `IncidentReport` domain model

**Files:**
- Create: `src/mergency/domain/models/incident_report.py`
- Test: `tests/domain/models/test_incident_report.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/domain/models/test_incident_report.py
import dataclasses
from datetime import datetime, timezone

import pytest

from mergency.domain.models.incident_report import IncidentReport


def _report(severity: str | None = None) -> IncidentReport:
    return IncidentReport(
        installation_id=1,
        repo="acme/widgets",
        base_sha="base123",
        head_sha="head456",
        severity=severity,
        occurred_at=datetime.now(timezone.utc),
    )


def test_incident_report_holds_the_reported_commit_range_and_severity():
    report = _report(severity="P1")

    assert report.repo == "acme/widgets"
    assert report.base_sha == "base123"
    assert report.head_sha == "head456"
    assert report.severity == "P1"


def test_severity_is_optional():
    report = _report(severity=None)

    assert report.severity is None


def test_incident_report_is_immutable():
    report = _report()

    with pytest.raises(dataclasses.FrozenInstanceError):
        report.head_sha = "other"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker compose run --rm app pytest tests/domain/models/test_incident_report.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'mergency.domain.models.incident_report'`

- [ ] **Step 3: Write the model**

```python
# src/mergency/domain/models/incident_report.py
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class IncidentReport:
    installation_id: int
    repo: str
    base_sha: str
    head_sha: str
    severity: str | None
    occurred_at: datetime
```

- [ ] **Step 4: Run test to verify it passes**

Run: `docker compose run --rm app pytest tests/domain/models/test_incident_report.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/mergency/domain/models/incident_report.py tests/domain/models/test_incident_report.py
git commit -m "feat: add IncidentReport domain model"
```

---

## Task 3: `CommitRangeProvider` port

**Files:**
- Create: `src/mergency/domain/ports/commit_range_provider.py`

This is a `Protocol` definition, like every other port in this codebase (`ChangedFilesProvider`, `CodeownersProvider`) — no runtime behavior, so no dedicated test file (matching the existing convention: none of the other port files under `src/mergency/domain/ports/` have a `tests/domain/ports/` counterpart either).

- [ ] **Step 1: Write the port**

```python
# src/mergency/domain/ports/commit_range_provider.py
from typing import Protocol


class CommitRangeProvider(Protocol):
    async def commits_between(
        self, installation_id: int, repo: str, base_sha: str, head_sha: str
    ) -> list[str]: ...
```

- [ ] **Step 2: Verify it imports cleanly**

Run: `docker compose run --rm app python -c "from mergency.domain.ports.commit_range_provider import CommitRangeProvider"`
Expected: no output, exit code 0

- [ ] **Step 3: Commit**

```bash
git add src/mergency/domain/ports/commit_range_provider.py
git commit -m "feat: add CommitRangeProvider port"
```

---

## Task 4: `GithubCommitRangeProvider` adapter

**Files:**
- Create: `src/mergency/adapters/github/commit_range_provider.py`
- Test: `tests/adapters/github/test_commit_range_provider.py`

Uses PyGithub's `Repository.compare(base, head)`, the same client-construction pattern as `GithubChangedFilesProvider` (`Github(auth=Auth.Token(token))`, blocking call wrapped in `asyncio.to_thread`). `base_sha == head_sha` is special-cased to return `[head_sha]` directly — GitHub's compare API returns an empty `commits` list for identical refs, and a single-commit incident (no real range) should still attribute to that one commit.

- [ ] **Step 1: Write the failing tests**

```python
# tests/adapters/github/test_commit_range_provider.py
from unittest.mock import MagicMock

from mergency.adapters.github.commit_range_provider import GithubCommitRangeProvider


class _StubTokenProvider:
    async def get_token(self, installation_id: int) -> str:
        return "test-token"


async def test_returns_shas_of_every_commit_in_the_range(monkeypatch):
    provider = GithubCommitRangeProvider(_StubTokenProvider())
    commit_a = MagicMock(sha="sha-a")
    commit_b = MagicMock(sha="sha-b")
    client = MagicMock()
    client.get_repo.return_value.compare.return_value.commits = [commit_a, commit_b]
    monkeypatch.setattr(
        "mergency.adapters.github.commit_range_provider.Github", lambda **kwargs: client
    )

    shas = await provider.commits_between(1, "acme/widgets", "base123", "head456")

    assert shas == ["sha-a", "sha-b"]
    client.get_repo.assert_called_once_with("acme/widgets")
    client.get_repo.return_value.compare.assert_called_once_with("base123", "head456")


async def test_returns_the_single_sha_when_base_and_head_are_identical(monkeypatch):
    provider = GithubCommitRangeProvider(_StubTokenProvider())
    client = MagicMock()
    monkeypatch.setattr(
        "mergency.adapters.github.commit_range_provider.Github", lambda **kwargs: client
    )

    shas = await provider.commits_between(1, "acme/widgets", "same-sha", "same-sha")

    assert shas == ["same-sha"]
    client.get_repo.assert_not_called()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `docker compose run --rm app pytest tests/adapters/github/test_commit_range_provider.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'mergency.adapters.github.commit_range_provider'`

- [ ] **Step 3: Write the adapter**

```python
# src/mergency/adapters/github/commit_range_provider.py
import asyncio

from github import Auth, Github

from mergency.domain.ports.installation_token_provider import InstallationTokenProvider


class GithubCommitRangeProvider:
    def __init__(self, token_provider: InstallationTokenProvider) -> None:
        self._token_provider = token_provider

    async def commits_between(
        self, installation_id: int, repo: str, base_sha: str, head_sha: str
    ) -> list[str]:
        if base_sha == head_sha:
            return [head_sha]

        token = await self._token_provider.get_token(installation_id)
        client = Github(auth=Auth.Token(token))

        def _fetch() -> list[str]:
            comparison = client.get_repo(repo).compare(base_sha, head_sha)
            return [commit.sha for commit in comparison.commits]

        return await asyncio.to_thread(_fetch)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `docker compose run --rm app pytest tests/adapters/github/test_commit_range_provider.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/mergency/adapters/github/commit_range_provider.py tests/adapters/github/test_commit_range_provider.py
git commit -m "feat: add GithubCommitRangeProvider adapter"
```

---

## Task 5: `report_incident` Celery task

**Files:**
- Create: `src/mergency/worker/report_incident.py`
- Test: `tests/worker/test_report_incident.py`

Mirrors `worker/classify_activity_event.py::_classify_resolve_and_persist`: for every SHA in the resolved range, look up changed files, resolve owners via `OwnershipResolver` + `ConfigResolver`, and persist one `Event(event_type=INCIDENT)` per `(sha, owner)` pair. The task takes plain JSON-serializable kwargs (Celery's broker requirement), not the `IncidentReport` object itself — `occurred_at` travels as an ISO string and is parsed back into a `datetime` inside the task, the same reasoning `classify_activity_event` applies by taking a raw `payload: dict` instead of a domain object.

- [ ] **Step 1: Write the failing test**

```python
# tests/worker/test_report_incident.py
from datetime import datetime, timezone

from mergency.adapters.memory.event_repository import InMemoryEventRepository
from mergency.adapters.memory.tenant_config_repository import InMemoryTenantConfigRepository
from mergency.domain.config_resolver import ConfigResolver
from mergency.domain.models.event_type import EventType
from mergency.domain.ownership_resolver import OwnershipResolver
from mergency.worker import report_incident as task_module


class _StubContentProvider:
    async def get_file(self, installation_id, repo, path):
        return None


class _StubCodeownersProvider:
    def __init__(self, owners_by_path: dict[str, list[tuple[str, str]]]) -> None:
        self._owners_by_path = owners_by_path

    async def owners_for(self, installation_id, repo, path):
        return self._owners_by_path.get(path, [])


class _StubChangedFilesProvider:
    def __init__(self, files_by_sha: dict[str, list[str]]) -> None:
        self._files_by_sha = files_by_sha

    async def files_changed_in_commit(self, installation_id, repo, sha):
        return self._files_by_sha.get(sha, [])


class _StubCommitRangeProvider:
    def __init__(self, shas: list[str]) -> None:
        self._shas = shas

    async def commits_between(self, installation_id, repo, base_sha, head_sha):
        return self._shas


def _wire(monkeypatch, *, shas, files_by_sha, codeowners_by_path):
    event_repository = InMemoryEventRepository()
    monkeypatch.setattr(
        task_module, "get_commit_range_provider", lambda: _StubCommitRangeProvider(shas)
    )
    monkeypatch.setattr(task_module, "get_event_repository", lambda: event_repository)
    monkeypatch.setattr(
        task_module,
        "get_config_resolver",
        lambda: ConfigResolver(_StubContentProvider(), InMemoryTenantConfigRepository()),
    )
    monkeypatch.setattr(
        task_module,
        "get_ownership_resolver",
        lambda: OwnershipResolver(_StubCodeownersProvider(codeowners_by_path)),
    )
    monkeypatch.setattr(
        task_module,
        "get_changed_files_provider",
        lambda: _StubChangedFilesProvider(files_by_sha),
    )
    return event_repository


async def test_persists_one_incident_event_per_commit_and_owner_in_the_range(monkeypatch):
    event_repository = _wire(
        monkeypatch,
        shas=["sha-a", "sha-b"],
        files_by_sha={"sha-a": ["src/a.py"], "sha-b": ["src/b.py"]},
        codeowners_by_path={
            "src/a.py": [("TEAM", "@org/team-a")],
            "src/b.py": [("TEAM", "@org/team-b")],
        },
    )
    occurred_at = datetime(2026, 1, 1, tzinfo=timezone.utc)

    await task_module._correlate_resolve_and_persist(
        installation_id=1,
        repo="acme/widgets",
        base_sha="base123",
        head_sha="head456",
        severity="P1",
        occurred_at_iso=occurred_at.isoformat(),
    )

    stored_a = await event_repository.get(1, "acme/widgets", "sha-a", EventType.INCIDENT, "@org/team-a")
    stored_b = await event_repository.get(1, "acme/widgets", "sha-b", EventType.INCIDENT, "@org/team-b")
    assert stored_a is not None
    assert stored_a.ts == occurred_at
    assert stored_b is not None


async def test_falls_back_to_default_team_when_no_codeowners_match(monkeypatch):
    event_repository = _wire(
        monkeypatch,
        shas=["sha-a"],
        files_by_sha={"sha-a": ["src/a.py"]},
        codeowners_by_path={},
    )

    await task_module._correlate_resolve_and_persist(
        installation_id=1,
        repo="acme/widgets",
        base_sha="base123",
        head_sha="head456",
        severity=None,
        occurred_at_iso=datetime.now(timezone.utc).isoformat(),
    )

    stored = await event_repository.get(1, "acme/widgets", "sha-a", EventType.INCIDENT, "unassigned")
    assert stored is not None


async def test_report_incident_task_delegates_to_the_async_pipeline(monkeypatch):
    captured = {}

    async def _fake(**kwargs):
        captured.update(kwargs)

    monkeypatch.setattr(task_module, "_correlate_resolve_and_persist", _fake)

    task_module.report_incident(
        installation_id=1,
        repo="acme/widgets",
        base_sha="base123",
        head_sha="head456",
        occurred_at="2026-01-01T00:00:00+00:00",
        severity="P2",
    )

    assert captured["installation_id"] == 1
    assert captured["occurred_at_iso"] == "2026-01-01T00:00:00+00:00"
    assert captured["severity"] == "P2"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `docker compose run --rm app pytest tests/worker/test_report_incident.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'mergency.worker.report_incident'`

- [ ] **Step 3: Write the task**

```python
# src/mergency/worker/report_incident.py
import asyncio
from datetime import datetime

from mergency.api.deps import (
    get_changed_files_provider,
    get_commit_range_provider,
    get_config_resolver,
    get_event_repository,
    get_ownership_resolver,
)
from mergency.domain.models.event import Event
from mergency.domain.models.event_type import EventType
from mergency.worker.celery_app import celery_app


@celery_app.task(name="report_incident")
def report_incident(
    installation_id: int,
    repo: str,
    base_sha: str,
    head_sha: str,
    occurred_at: str,
    severity: str | None = None,
) -> None:
    asyncio.run(
        _correlate_resolve_and_persist(
            installation_id=installation_id,
            repo=repo,
            base_sha=base_sha,
            head_sha=head_sha,
            severity=severity,
            occurred_at_iso=occurred_at,
        )
    )


async def _correlate_resolve_and_persist(
    *,
    installation_id: int,
    repo: str,
    base_sha: str,
    head_sha: str,
    severity: str | None,
    occurred_at_iso: str,
) -> None:
    occurred_at = datetime.fromisoformat(occurred_at_iso)

    shas = await get_commit_range_provider().commits_between(
        installation_id, repo, base_sha, head_sha
    )
    config = await get_config_resolver().resolve(installation_id, repo)
    event_repository = get_event_repository()

    for sha in shas:
        changed_files = await get_changed_files_provider().files_changed_in_commit(
            installation_id, repo, sha
        )
        owners = await get_ownership_resolver().resolve_owners(
            installation_id, repo, changed_files, config.default_team
        )
        for owner in owners:
            await event_repository.save_if_new(
                Event(
                    installation_id=installation_id,
                    repo=repo,
                    sha=sha,
                    event_type=EventType.INCIDENT,
                    owner=owner,
                    ts=occurred_at,
                )
            )
```

Note: `severity` is accepted as a parameter on both `report_incident` and `_correlate_resolve_and_persist` for forward-compatibility with the request shape (see Context — severity is accepted and threaded through today, not yet persisted or used in any decision). This is intentional, not dead code to clean up later: it keeps the public task signature stable so a future severity-weighting design doesn't need to change the call site in `api/incidents.py` again.

- [ ] **Step 4: Run tests to verify they pass, and lint is clean**

Run: `docker compose run --rm app pytest tests/worker/test_report_incident.py -v && docker compose run --rm app ruff check src/mergency/worker/report_incident.py`
Expected: all tests PASS; `ruff` reports no issues

- [ ] **Step 5: Commit**

```bash
git add src/mergency/worker/report_incident.py tests/worker/test_report_incident.py
git commit -m "feat: add report_incident worker task for commit-range attribution"
```

---

## Task 6: Wire `CommitRangeProvider` and the new task into `deps.py` / `celery_app.py`

**Files:**
- Modify: `src/mergency/api/deps.py`
- Modify: `src/mergency/worker/celery_app.py`
- Modify: `tests/api/test_deps.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/api/test_deps.py (add this test, following the existing get_changed_files_provider test's shape)
def test_get_commit_range_provider_is_cached_and_resettable(monkeypatch):
    from mergency.adapters.github.commit_range_provider import GithubCommitRangeProvider

    first = deps.get_commit_range_provider()
    second = deps.get_commit_range_provider()
    assert first is second
    assert isinstance(first, GithubCommitRangeProvider)

    deps.reset_dependency_caches()
    assert deps.get_commit_range_provider() is not first
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker compose run --rm app pytest tests/api/test_deps.py -v`
Expected: FAIL with `AttributeError: module 'mergency.api.deps' has no attribute 'get_commit_range_provider'`

- [ ] **Step 3: Wire the factory**

```python
# src/mergency/api/deps.py — add this import alongside the other adapters/github imports
from mergency.adapters.github.commit_range_provider import GithubCommitRangeProvider
```

```python
# src/mergency/api/deps.py — add this import alongside the other domain/ports imports
from mergency.domain.ports.commit_range_provider import CommitRangeProvider
```

```python
# src/mergency/api/deps.py — add this factory, next to get_changed_files_provider
@lru_cache
def get_commit_range_provider() -> CommitRangeProvider:
    return GithubCommitRangeProvider(get_installation_token_provider())
```

```python
# src/mergency/api/deps.py — add this line inside reset_dependency_caches(), next to get_changed_files_provider.cache_clear()
    get_commit_range_provider.cache_clear()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `docker compose run --rm app pytest tests/api/test_deps.py -v`
Expected: PASS

- [ ] **Step 5: Register the task module with Celery**

```python
# src/mergency/worker/celery_app.py
from celery import Celery

celery_app = Celery(
    "mergency",
    broker="redis://localhost:6379/0",
    backend="redis://localhost:6379/0",
    include=[
        "mergency.worker.classify_activity_event",
        "mergency.worker.evaluate_pr_budget",
        "mergency.worker.report_incident",
    ],
)
```

- [ ] **Step 6: Verify the app still boots with the new task registered**

Run: `docker compose run --rm app python -c "from mergency.worker.celery_app import celery_app; assert 'report_incident' in celery_app.tasks"`
Expected: no output, exit code 0

- [ ] **Step 7: Commit**

```bash
git add src/mergency/api/deps.py src/mergency/worker/celery_app.py tests/api/test_deps.py
git commit -m "feat: wire CommitRangeProvider and register report_incident with Celery"
```

---

## Task 7: `POST /api/v1/installations/{installation_id}/incidents` endpoint

**Files:**
- Create: `src/mergency/api/incidents.py`
- Modify: `src/mergency/api/app.py`
- Test: `tests/api/test_incidents.py`

Follows `api/budget_query.py`'s exact shape: look up the `Installation`, 404 if missing, check `token_matches`, 401 if it fails. On success, enqueue `report_incident.delay(...)` and return `202 Accepted` — the endpoint itself never calls GitHub, keeping the request/response cycle as fast as the webhook receiver's. The request body is a stdlib `dataclass` (FastAPI ≥0.115 supports these as request bodies natively, same as pydantic models), matching this codebase's existing preference for dataclasses over introducing pydantic `BaseModel`s.

- [ ] **Step 1: Write the failing tests**

```python
# tests/api/test_incidents.py
from datetime import datetime, timezone

import pytest
from httpx import ASGITransport, AsyncClient

from mergency.adapters.memory.tenant_repository import InMemoryTenantRepository
from mergency.api.app import app
from mergency.api.deps import get_tenant_repository
from mergency.domain.models.installation import Installation
from mergency.domain.models.tenant_status import TenantStatus
from mergency.worker import report_incident as task_module


def _installation(api_token: str | None = "the-real-token") -> Installation:
    return Installation(
        installation_id=42,
        account_login="acme",
        account_type="Organization",
        status=TenantStatus.ACTIVE,
        repository_selection="all",
        api_token=api_token,
    )


@pytest.fixture(autouse=True)
def override_dependencies():
    tenant_repository = InMemoryTenantRepository()
    app.dependency_overrides[get_tenant_repository] = lambda: tenant_repository
    yield tenant_repository
    app.dependency_overrides.clear()


async def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def test_accepts_a_valid_incident_report_and_enqueues_the_task(monkeypatch, override_dependencies):
    await override_dependencies.upsert(_installation())
    captured = {}
    monkeypatch.setattr(
        task_module.report_incident, "delay", lambda **kwargs: captured.update(kwargs)
    )

    async with await _client() as client:
        response = await client.post(
            "/api/v1/installations/42/incidents",
            json={
                "repo": "acme/widgets",
                "base_sha": "base123",
                "head_sha": "head456",
                "severity": "P1",
                "occurred_at": "2026-01-01T00:00:00Z",
            },
            headers={"Authorization": "Bearer the-real-token"},
        )

    assert response.status_code == 202
    assert captured["installation_id"] == 42
    assert captured["repo"] == "acme/widgets"
    assert captured["base_sha"] == "base123"
    assert captured["head_sha"] == "head456"
    assert captured["severity"] == "P1"


async def test_defaults_occurred_at_to_now_when_omitted(monkeypatch, override_dependencies):
    await override_dependencies.upsert(_installation())
    captured = {}
    monkeypatch.setattr(
        task_module.report_incident, "delay", lambda **kwargs: captured.update(kwargs)
    )

    async with await _client() as client:
        response = await client.post(
            "/api/v1/installations/42/incidents",
            json={"repo": "acme/widgets", "base_sha": "base123", "head_sha": "head456"},
            headers={"Authorization": "Bearer the-real-token"},
        )

    assert response.status_code == 202
    reported_at = datetime.fromisoformat(captured["occurred_at"])
    assert (datetime.now(timezone.utc) - reported_at).total_seconds() < 5


async def test_returns_404_for_an_unknown_installation(override_dependencies):
    async with await _client() as client:
        response = await client.post(
            "/api/v1/installations/999/incidents",
            json={"repo": "acme/widgets", "base_sha": "base123", "head_sha": "head456"},
            headers={"Authorization": "Bearer whatever"},
        )

    assert response.status_code == 404


async def test_returns_401_for_a_missing_token(override_dependencies):
    await override_dependencies.upsert(_installation())

    async with await _client() as client:
        response = await client.post(
            "/api/v1/installations/42/incidents",
            json={"repo": "acme/widgets", "base_sha": "base123", "head_sha": "head456"},
        )

    assert response.status_code == 401


async def test_returns_401_for_a_wrong_token(override_dependencies):
    await override_dependencies.upsert(_installation())

    async with await _client() as client:
        response = await client.post(
            "/api/v1/installations/42/incidents",
            json={"repo": "acme/widgets", "base_sha": "base123", "head_sha": "head456"},
            headers={"Authorization": "Bearer not-the-token"},
        )

    assert response.status_code == 401
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `docker compose run --rm app pytest tests/api/test_incidents.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'mergency.api.incidents'`

- [ ] **Step 3: Write the endpoint**

```python
# src/mergency/api/incidents.py
from dataclasses import dataclass
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Header, HTTPException

from mergency.api.auth import token_matches
from mergency.api.deps import get_tenant_repository
from mergency.domain.ports.tenant_repository import TenantRepository
from mergency.worker.report_incident import report_incident

router = APIRouter()


@dataclass
class IncidentReportRequest:
    repo: str
    base_sha: str
    head_sha: str
    severity: str | None = None
    occurred_at: datetime | None = None


@router.post("/api/v1/installations/{installation_id}/incidents", status_code=202)
async def report_incident_endpoint(
    installation_id: int,
    incident_report: IncidentReportRequest,
    authorization: str | None = Header(default=None),
    tenant_repository: TenantRepository = Depends(get_tenant_repository),
) -> dict:
    installation = await tenant_repository.get(installation_id)
    if installation is None:
        raise HTTPException(status_code=404, detail="installation not found")

    if not token_matches(installation, authorization):
        raise HTTPException(status_code=401, detail="invalid or missing token")

    occurred_at = incident_report.occurred_at or datetime.now(timezone.utc)
    report_incident.delay(
        installation_id=installation_id,
        repo=incident_report.repo,
        base_sha=incident_report.base_sha,
        head_sha=incident_report.head_sha,
        severity=incident_report.severity,
        occurred_at=occurred_at.isoformat(),
    )
    return {"accepted": True}
```

- [ ] **Step 4: Mount the router**

```python
# src/mergency/api/app.py
from fastapi import FastAPI

from mergency.api.budget_query import router as budget_query_router
from mergency.api.incidents import router as incidents_router
from mergency.api.internal import router as internal_router
from mergency.api.webhooks import router as webhooks_router


def create_app() -> FastAPI:
    app = FastAPI(title="mergency")
    app.include_router(webhooks_router)
    app.include_router(internal_router)
    app.include_router(budget_query_router)
    app.include_router(incidents_router)
    return app


app = create_app()
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `docker compose run --rm app pytest tests/api/test_incidents.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/mergency/api/incidents.py src/mergency/api/app.py tests/api/test_incidents.py
git commit -m "feat: add POST /api/v1/installations/{id}/incidents endpoint"
```

---

## Verification

Run the full suite in the container to confirm nothing regressed and the new pipeline works end to end:

```bash
docker compose up -d postgres
docker compose run --rm app pytest -v
docker compose run --rm app ruff check .
```

Expected: all tests pass, including every pre-existing test file plus the seven new/modified ones from this plan (`test_event.py`, `test_budget_calculator.py`, `test_incident_report.py`, `test_commit_range_provider.py`, `test_report_incident.py`, `test_deps.py`, `test_incidents.py`); `ruff` reports no issues.

Manual smoke test against the running compose stack, limited to the HTTP-facing half of the feature (needs a real installation with a minted `api_token` — same prerequisite as `docs/plan/0014-historical-query-api.md`'s manual smoke test):

```bash
docker compose up -d
```

```bash
curl -i -X POST "http://localhost:8000/api/v1/installations/<id>/incidents" \
  -H "Authorization: Bearer <the-minted-token>" \
  -H "Content-Type: application/json" \
  -d '{"repo": "<owner>/<repo>", "base_sha": "<sha-before-deploy>", "head_sha": "<sha-of-deploy>", "severity": "P1"}'
```

Expected: `202 {"accepted": true}` immediately; `401` when the `Authorization` header is omitted or wrong; `404` for an unknown `installation_id`.

**Known gap, not introduced by this plan:** `docker-compose.yml` currently defines only `app` and `postgres` — no `redis` broker and no separate worker process, so `report_incident.delay(...)` has nowhere to actually run in the local compose stack today. This is the same pre-existing gap every other Celery task in this codebase has (`classify_activity_event`, `evaluate_pr_budget` are equally untestable end-to-end via compose right now); wiring up Redis and a worker service is out of scope for this plan and should be its own `docs/plan/00XX-*.md` once it's needed. Until then, correctness of the correlation/attribution pipeline is verified by `tests/worker/test_report_incident.py`'s direct calls into `_correlate_resolve_and_persist`, not by an end-to-end compose smoke test.

Once all of the above passes, update the `## Status` line of `docs/adr/0011-deploy-to-incident-traceability-v2.md` from `proposed` to `accepted`, this plan's own `## Status` line (top of this file) from `proposed` to `implemented`, and check off "v2: deploy-to-incident traceability" in `README.md`'s Roadmap.
