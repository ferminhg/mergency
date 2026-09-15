# PR comment bot 💬

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Tracks:** [GitHub issue #15](https://github.com/ferminhg/mergency/issues/15). Design: `docs/adr/0008-pr-comment-bot.md`.

**Goal:** Post (and keep up to date) a single PR comment that lists which touched teams have a shrinking budget, per ADR 0008. This is the first user-visible output the whole system produces.

**Architecture:** A new `pull_request` webhook path, parallel to the existing `push`/`check_run` path: a signal parser, a Celery task, and a small domain service (`PrBudgetEvaluator`) that composes the already-existing `OwnershipResolver` (ADR 0006) and `BudgetCalculator` (ADR 0007) to decide which owners are shrinking. Two small adapters talk to GitHub: one to read the PR's changed files, one to find/create/update the bot's own marked comment.

**Tech Stack:** Same as the rest of the repo — Python, PyGithub, Celery, pytest. No new dependencies.

---

## Status

implemented

## Context

This plan depends on `docs/plan/0011-rolling-window-budget-calculation.md` (issue #14, "finishing" as of this writing) having landed on `main` first. This plan is written against the API that plan defines and does not re-derive it — verify these exist in `src/mergency/` before starting Task 5:

- `mergency.domain.models.budget_status.BudgetStatus(owner, window_days, limit, consumed, remaining_pct)`
- `mergency.domain.budget_calculator.BudgetCalculator(event_repository, config_repository)` with `async def status_for(installation_id: int, owner: str) -> BudgetStatus`
- `mergency.domain.models.tenant_config.TenantConfig` carrying `warn_threshold_pct: int`
- `mergency.api.deps.get_budget_calculator()`, cached and cleared by `reset_dependency_caches()`

If any of these are missing, finish plan 0011 first — this plan's Task 5 onward will fail to import.

Everything else this plan reuses already exists and is verified against the real code (not the ADR's sketch):

- `mergency.domain.ownership_resolver.OwnershipResolver(codeowners_provider)` with `async def resolve_owners(installation_id, repo, changed_files, default_team) -> list[str]` — already returns team names only, guardrail against individuals already in place (ADR 0006). Reused as-is; ADR 0008 only changes *which* changed-file list feeds it (a PR's full file list instead of one commit's).
- `mergency.domain.config_resolver.ConfigResolver(repository_content_provider, tenant_config_repository)` with `async def resolve(installation_id, repo) -> TenantConfig` — already resolves and persists `TenantConfig`, including `default_team` and (once plan 0011 lands) `warn_threshold_pct`.
- `mergency.domain.ports.installation_token_provider.InstallationTokenProvider` and its adapter `PyGithubInstallationTokenProvider` — the same cached-token pattern every GitHub adapter in this repo already uses (see `adapters/github/changed_files_provider.py`).
- `src/mergency/api/webhooks.py` currently dispatches `push`/`check_run` to `classify_activity_event.delay(...)` and acknowledges everything else (including `pull_request`) as a no-op. This plan adds a third branch.
- `src/mergency/worker/celery_app.py`'s `include` list currently has one module (`mergency.worker.classify_activity_event`) — this plan adds a second.

**Scoping decision:** the comment body format (a markdown table) is a first cut per the ADR — "wording/format is expected to be tuned after real usage, not treated as a frozen contract". This plan implements one reasonable format, not a configurable one.

## Design decisions

**1. `PullRequestSignal` is a new signal model, parsed the same way `CheckRunSignal`/`PushSignal` are.** Mirrors the existing pattern exactly: a frozen dataclass in `domain/models/`, a pure parser function in `adapters/github/`, raising on missing fields so the caller can catch and drop malformed payloads (same as `classify_activity_event.py` already does).

**2. Action filtering happens in `webhooks.py`, not in the task.** ADR 0008 triggers only on `opened`/`synchronize`/`reopened`. `webhooks.py` already filters `installation` events by branching on `action` inside `_handle_installation_event`; here the filter is simpler (a set membership check) and cheap enough to do before even enqueueing, so a `pull_request` webhook with an untracked action (`labeled`, `closed`, ...) is acknowledged as a no-op without ever touching the queue.

**3. `PrBudgetEvaluator`'s dependencies stay exactly what the ADR says.** `PrBudgetEvaluator(ownership_resolver: OwnershipResolver, budget_calculator: BudgetCalculator)` — no new domain concepts, just composition, matching the ADR's own consequence line. `warn_threshold_pct` and `default_team` are resolved once by the worker task (it already calls `ConfigResolver.resolve` for other reasons) and passed into `evaluate(...)` as plain arguments, rather than making `PrBudgetEvaluator` take a third `TenantConfigRepository` dependency.

**4. "Shrinking" means `remaining_pct <= warn_threshold_pct`.** Matches ADR 0007's own definition verbatim. `PrBudgetEvaluator.evaluate(...)` returns `list[BudgetStatus]` containing **only** the shrinking owners — callers never need to re-filter.

**5. Comment marker lives in one place: `domain/pr_comment_formatter.py`.** Both the formatter (writes the marker into new comment bodies) and the GitHub adapter (searches existing comment bodies for the marker) import the same `MARKER` constant from this domain module, so the exact string is never duplicated.

**6. Idempotent update vs. create, and the recovery case, are decided in the worker task — not in the comment client.** `PrCommentClient` is a dumb three-method port (`find_marked_comment`, `create_comment`, `update_comment`); all the "which one do I call" logic lives in `worker/evaluate_pr_budget.py`, matching this repo's existing convention that orchestration lives in the Celery task (see `classify_activity_event.py`'s own doc comment in plan 0010).

**7. Reusing `OwnershipResolver` against the PR's full file list, not a single commit.** The ADR is explicit about this: "against the PR's full changed-file list (via the Pull Request Files API) rather than a single commit's diff". A new `PullRequestFilesProvider` port covers this; `ChangedFilesProvider` (single-commit) stays untouched and unrelated.

## Directory structure (new/changed files)

```
src/mergency/
├── domain/
│   ├── models/
│   │   └── pull_request_signal.py       # NEW: PullRequestSignal
│   ├── ports/
│   │   ├── pull_request_files_provider.py  # NEW
│   │   └── pr_comment_client.py            # NEW
│   ├── pr_comment_formatter.py           # NEW: MARKER + pure formatting functions
│   └── pr_budget_evaluator.py            # NEW: PrBudgetEvaluator
├── adapters/
│   └── github/
│       ├── pull_request_signal_parser.py    # NEW
│       ├── pull_request_files_provider.py   # NEW: GithubPullRequestFilesProvider
│       └── pr_comment_client.py             # NEW: GithubPrCommentClient
├── worker/
│   └── evaluate_pr_budget.py             # NEW: Celery task, orchestration
├── worker/celery_app.py                  # MODIFIED: + include entry
└── api/
    ├── deps.py                           # MODIFIED: + 3 new factories
    └── webhooks.py                       # MODIFIED: + pull_request dispatch branch

tests/  (mirrors src/, one test file per new/changed module — see tasks below)
```

---

## Task 1: `PullRequestSignal` model + payload parser

**Files:** Create `tests/domain/models/test_pull_request_signal.py`, `tests/adapters/github/test_pull_request_signal_parser.py`, `src/mergency/domain/models/pull_request_signal.py`, `src/mergency/adapters/github/pull_request_signal_parser.py`.

- [ ] **Step 1: Write the tests**

```python
# tests/domain/models/test_pull_request_signal.py
import dataclasses

import pytest

from mergency.domain.models.pull_request_signal import PullRequestSignal


def test_pull_request_signal_is_immutable():
    signal = PullRequestSignal(installation_id=1, repo="acme/widgets", pr_number=42, action="opened")

    with pytest.raises(dataclasses.FrozenInstanceError):
        signal.action = "closed"
```

```python
# tests/adapters/github/test_pull_request_signal_parser.py
import pytest

from mergency.adapters.github.pull_request_signal_parser import parse_pull_request_signal


def _payload(**overrides) -> dict:
    payload = {
        "action": "opened",
        "number": 42,
        "repository": {"full_name": "acme/widgets"},
        "installation": {"id": 1},
    }
    payload.update(overrides)
    return payload


def test_parses_installation_repo_pr_number_and_action():
    signal = parse_pull_request_signal(_payload())

    assert signal.installation_id == 1
    assert signal.repo == "acme/widgets"
    assert signal.pr_number == 42
    assert signal.action == "opened"


def test_raises_key_error_when_repository_is_missing():
    payload = _payload()
    del payload["repository"]

    with pytest.raises(KeyError):
        parse_pull_request_signal(payload)
```

Run: `docker compose run --rm app pytest tests/domain/models/test_pull_request_signal.py tests/adapters/github/test_pull_request_signal_parser.py -v`
Expected: both files fail with `ModuleNotFoundError`.

- [ ] **Step 2: Implement**

```python
# src/mergency/domain/models/pull_request_signal.py
from dataclasses import dataclass


@dataclass(frozen=True)
class PullRequestSignal:
    installation_id: int
    repo: str
    pr_number: int
    action: str
```

```python
# src/mergency/adapters/github/pull_request_signal_parser.py
from mergency.domain.models.pull_request_signal import PullRequestSignal


def parse_pull_request_signal(payload: dict) -> PullRequestSignal:
    return PullRequestSignal(
        installation_id=payload["installation"]["id"],
        repo=payload["repository"]["full_name"],
        pr_number=payload["number"],
        action=payload["action"],
    )
```

Run: `docker compose run --rm app pytest tests/domain/models/test_pull_request_signal.py tests/adapters/github/test_pull_request_signal_parser.py -v`
Expected: 3 passed.

- [ ] **Step 3:** commit: `feat: add PullRequestSignal model and payload parser`.

---

## Task 2: `PullRequestFilesProvider` port + GitHub adapter

**Files:** Create `tests/adapters/github/test_pull_request_files_provider.py`, `src/mergency/domain/ports/pull_request_files_provider.py`, `src/mergency/adapters/github/pull_request_files_provider.py`.

- [ ] **Step 1: Write the test** (mirrors `tests/adapters/github/test_changed_files_provider.py` exactly, one call deeper — `get_pull(...).get_files()` instead of `get_commit(...).files`)

```python
# tests/adapters/github/test_pull_request_files_provider.py
from unittest.mock import MagicMock

from mergency.adapters.github.pull_request_files_provider import GithubPullRequestFilesProvider


class _StubTokenProvider:
    async def get_token(self, installation_id: int) -> str:
        return "test-token"


async def test_returns_filenames_from_the_pull_request(monkeypatch):
    provider = GithubPullRequestFilesProvider(_StubTokenProvider())
    file_a = MagicMock(filename="src/a.py")
    file_b = MagicMock(filename="src/b.py")
    client = MagicMock()
    client.get_repo.return_value.get_pull.return_value.get_files.return_value = [file_a, file_b]
    monkeypatch.setattr(
        "mergency.adapters.github.pull_request_files_provider.Github", lambda **kwargs: client
    )

    files = await provider.files_changed_in_pull_request(1, "acme/widgets", 42)

    assert files == ["src/a.py", "src/b.py"]
    client.get_repo.assert_called_once_with("acme/widgets")
    client.get_repo.return_value.get_pull.assert_called_once_with(42)
```

Run: `docker compose run --rm app pytest tests/adapters/github/test_pull_request_files_provider.py -v`
Expected: fails with `ModuleNotFoundError`.

- [ ] **Step 2: Implement**

```python
# src/mergency/domain/ports/pull_request_files_provider.py
from typing import Protocol


class PullRequestFilesProvider(Protocol):
    async def files_changed_in_pull_request(
        self, installation_id: int, repo: str, pr_number: int
    ) -> list[str]: ...
```

```python
# src/mergency/adapters/github/pull_request_files_provider.py
import asyncio

from github import Auth, Github

from mergency.domain.ports.installation_token_provider import InstallationTokenProvider


class GithubPullRequestFilesProvider:
    def __init__(self, token_provider: InstallationTokenProvider) -> None:
        self._token_provider = token_provider

    async def files_changed_in_pull_request(
        self, installation_id: int, repo: str, pr_number: int
    ) -> list[str]:
        token = await self._token_provider.get_token(installation_id)
        client = Github(auth=Auth.Token(token))

        def _fetch() -> list[str]:
            pull_request = client.get_repo(repo).get_pull(pr_number)
            return [file.filename for file in pull_request.get_files()]

        return await asyncio.to_thread(_fetch)
```

Run: `docker compose run --rm app pytest tests/adapters/github/test_pull_request_files_provider.py -v`
Expected: 1 passed.

- [ ] **Step 3:** commit: `feat: add PullRequestFilesProvider port and GitHub adapter`.

---

## Task 3: `PrCommentClient` port + GitHub adapter

**Files:** Create `tests/adapters/github/test_pr_comment_client.py`, `src/mergency/domain/ports/pr_comment_client.py`, `src/mergency/adapters/github/pr_comment_client.py`.

This task depends on Task 4's `MARKER` constant existing — do Task 4 first if working out of order, or inline the literal string `"<!-- mergency:budget-status -->"` here temporarily and switch the import once Task 4 lands. The steps below assume Task 4 is already done.

- [ ] **Step 1: Write the test**

```python
# tests/adapters/github/test_pr_comment_client.py
from unittest.mock import MagicMock

from mergency.adapters.github.pr_comment_client import GithubPrCommentClient
from mergency.domain.pr_comment_formatter import MARKER


class _StubTokenProvider:
    async def get_token(self, installation_id: int) -> str:
        return "test-token"


def _client() -> GithubPrCommentClient:
    return GithubPrCommentClient(_StubTokenProvider())


async def test_find_marked_comment_returns_the_id_of_the_matching_comment(monkeypatch):
    marked_comment = MagicMock(id=999, body=f"{MARKER}\nold status")
    other_comment = MagicMock(id=1, body="unrelated comment")
    client = MagicMock()
    client.get_repo.return_value.get_issue.return_value.get_comments.return_value = [
        other_comment,
        marked_comment,
    ]
    monkeypatch.setattr("mergency.adapters.github.pr_comment_client.Github", lambda **kwargs: client)

    comment_id = await _client().find_marked_comment(1, "acme/widgets", 42)

    assert comment_id == 999


async def test_find_marked_comment_returns_none_when_no_comment_carries_the_marker(monkeypatch):
    client = MagicMock()
    client.get_repo.return_value.get_issue.return_value.get_comments.return_value = [
        MagicMock(id=1, body="unrelated comment")
    ]
    monkeypatch.setattr("mergency.adapters.github.pr_comment_client.Github", lambda **kwargs: client)

    comment_id = await _client().find_marked_comment(1, "acme/widgets", 42)

    assert comment_id is None


async def test_create_comment_posts_the_body_on_the_pull_request_issue(monkeypatch):
    client = MagicMock()
    monkeypatch.setattr("mergency.adapters.github.pr_comment_client.Github", lambda **kwargs: client)

    await _client().create_comment(1, "acme/widgets", 42, "hello")

    client.get_repo.assert_called_once_with("acme/widgets")
    client.get_repo.return_value.get_issue.assert_called_once_with(42)
    client.get_repo.return_value.get_issue.return_value.create_comment.assert_called_once_with("hello")


async def test_update_comment_edits_the_comment_by_id(monkeypatch):
    client = MagicMock()
    monkeypatch.setattr("mergency.adapters.github.pr_comment_client.Github", lambda **kwargs: client)

    await _client().update_comment(1, "acme/widgets", 999, "updated body")

    client.get_repo.return_value.get_issue_comment.assert_called_once_with(999)
    client.get_repo.return_value.get_issue_comment.return_value.edit.assert_called_once_with(
        "updated body"
    )
```

Run: `docker compose run --rm app pytest tests/adapters/github/test_pr_comment_client.py -v`
Expected: fails with `ModuleNotFoundError`.

- [ ] **Step 2: Implement**

```python
# src/mergency/domain/ports/pr_comment_client.py
from typing import Protocol


class PrCommentClient(Protocol):
    async def find_marked_comment(
        self, installation_id: int, repo: str, pr_number: int
    ) -> int | None: ...

    async def create_comment(
        self, installation_id: int, repo: str, pr_number: int, body: str
    ) -> None: ...

    async def update_comment(
        self, installation_id: int, repo: str, comment_id: int, body: str
    ) -> None: ...
```

```python
# src/mergency/adapters/github/pr_comment_client.py
import asyncio

from github import Auth, Github

from mergency.domain.ports.installation_token_provider import InstallationTokenProvider
from mergency.domain.pr_comment_formatter import MARKER


class GithubPrCommentClient:
    def __init__(self, token_provider: InstallationTokenProvider) -> None:
        self._token_provider = token_provider

    async def find_marked_comment(
        self, installation_id: int, repo: str, pr_number: int
    ) -> int | None:
        client = await self._client(installation_id)

        def _find() -> int | None:
            issue = client.get_repo(repo).get_issue(pr_number)
            for comment in issue.get_comments():
                if MARKER in comment.body:
                    return comment.id
            return None

        return await asyncio.to_thread(_find)

    async def create_comment(
        self, installation_id: int, repo: str, pr_number: int, body: str
    ) -> None:
        client = await self._client(installation_id)

        def _create() -> None:
            client.get_repo(repo).get_issue(pr_number).create_comment(body)

        await asyncio.to_thread(_create)

    async def update_comment(
        self, installation_id: int, repo: str, comment_id: int, body: str
    ) -> None:
        client = await self._client(installation_id)

        def _update() -> None:
            client.get_repo(repo).get_issue_comment(comment_id).edit(body)

        await asyncio.to_thread(_update)

    async def _client(self, installation_id: int) -> Github:
        token = await self._token_provider.get_token(installation_id)
        return Github(auth=Auth.Token(token))
```

Run: `docker compose run --rm app pytest tests/adapters/github/test_pr_comment_client.py -v`
Expected: 4 passed.

- [ ] **Step 3:** commit: `feat: add PrCommentClient port and GitHub adapter`.

---

## Task 4: `pr_comment_formatter` — marker + pure body builders

**Files:** Create `tests/domain/test_pr_comment_formatter.py`, `src/mergency/domain/pr_comment_formatter.py`.

- [ ] **Step 1: Write the test**

```python
# tests/domain/test_pr_comment_formatter.py
from mergency.domain.models.budget_status import BudgetStatus
from mergency.domain.pr_comment_formatter import (
    MARKER,
    format_recovered_comment,
    format_shrinking_budget_comment,
)


def _status(owner: str) -> BudgetStatus:
    return BudgetStatus(owner=owner, window_days=28, limit=5, consumed=4, remaining_pct=20.0)


def test_shrinking_comment_starts_with_the_marker():
    body = format_shrinking_budget_comment([_status("@org/team-a")])

    assert body.startswith(MARKER)


def test_shrinking_comment_lists_every_shrinking_owner():
    body = format_shrinking_budget_comment([_status("@org/team-a"), _status("@org/team-b")])

    assert "@org/team-a" in body
    assert "@org/team-b" in body


def test_shrinking_comment_includes_consumed_limit_and_remaining_pct():
    body = format_shrinking_budget_comment([_status("@org/team-a")])

    assert "4/5" in body
    assert "20" in body


def test_recovered_comment_starts_with_the_marker_and_mentions_recovery():
    body = format_recovered_comment()

    assert body.startswith(MARKER)
    assert "recovered" in body.lower()
```

Run: `docker compose run --rm app pytest tests/domain/test_pr_comment_formatter.py -v`
Expected: fails with `ModuleNotFoundError`.

- [ ] **Step 2: Implement**

```python
# src/mergency/domain/pr_comment_formatter.py
from mergency.domain.models.budget_status import BudgetStatus

MARKER = "<!-- mergency:budget-status -->"


def format_shrinking_budget_comment(statuses: list[BudgetStatus]) -> str:
    header = "| Team | Window | Consumed/Limit | Remaining | Status |"
    separator = "| --- | --- | --- | --- | --- |"
    rows = [
        f"| {status.owner} | {status.window_days}d | {status.consumed}/{status.limit} "
        f"| {status.remaining_pct:.0f}% | ⚠️ |"
        for status in statuses
    ]
    table = "\n".join([header, separator, *rows])
    return f"{MARKER}\n### 🚨 Error budget warning\n\n{table}\n"


def format_recovered_comment() -> str:
    return f"{MARKER}\n### ✅ Budget recovered\n\nAll touched teams are back within budget.\n"
```

Run: `docker compose run --rm app pytest tests/domain/test_pr_comment_formatter.py -v`
Expected: 4 passed.

- [ ] **Step 3:** commit: `feat: add PR comment body formatting for shrinking and recovered budgets`.

---

## Task 5: `PrBudgetEvaluator` domain service

**Files:** Create `tests/domain/test_pr_budget_evaluator.py`, `src/mergency/domain/pr_budget_evaluator.py`.

**Prerequisite:** `mergency.domain.budget_calculator.BudgetCalculator` and `mergency.domain.models.budget_status.BudgetStatus` must exist (plan 0011). Confirm with:
`docker compose run --rm app python -c "from mergency.domain.budget_calculator import BudgetCalculator; from mergency.domain.models.budget_status import BudgetStatus; print('ok')"`

- [ ] **Step 1: Write the test**

```python
# tests/domain/test_pr_budget_evaluator.py
from mergency.domain.models.budget_status import BudgetStatus
from mergency.domain.pr_budget_evaluator import PrBudgetEvaluator


class _StubOwnershipResolver:
    def __init__(self, owners: list[str]) -> None:
        self._owners = owners

    async def resolve_owners(self, installation_id, repo, changed_files, default_team):
        return self._owners


class _StubBudgetCalculator:
    def __init__(self, statuses_by_owner: dict[str, BudgetStatus]) -> None:
        self._statuses_by_owner = statuses_by_owner

    async def status_for(self, installation_id, owner):
        return self._statuses_by_owner[owner]


def _status(owner: str, remaining_pct: float) -> BudgetStatus:
    return BudgetStatus(owner=owner, window_days=28, limit=5, consumed=2, remaining_pct=remaining_pct)


async def test_returns_only_owners_at_or_below_the_warn_threshold():
    evaluator = PrBudgetEvaluator(
        _StubOwnershipResolver(["@org/team-a", "@org/team-b"]),
        _StubBudgetCalculator(
            {
                "@org/team-a": _status("@org/team-a", remaining_pct=30.0),
                "@org/team-b": _status("@org/team-b", remaining_pct=80.0),
            }
        ),
    )

    shrinking = await evaluator.evaluate(
        1, "acme/widgets", ["src/a.py"], "unassigned", warn_threshold_pct=50
    )

    assert [status.owner for status in shrinking] == ["@org/team-a"]


async def test_returns_empty_list_when_every_touched_owner_is_healthy():
    evaluator = PrBudgetEvaluator(
        _StubOwnershipResolver(["@org/team-a"]),
        _StubBudgetCalculator({"@org/team-a": _status("@org/team-a", remaining_pct=80.0)}),
    )

    shrinking = await evaluator.evaluate(
        1, "acme/widgets", ["src/a.py"], "unassigned", warn_threshold_pct=50
    )

    assert shrinking == []


async def test_remaining_pct_exactly_at_the_threshold_counts_as_shrinking():
    evaluator = PrBudgetEvaluator(
        _StubOwnershipResolver(["@org/team-a"]),
        _StubBudgetCalculator({"@org/team-a": _status("@org/team-a", remaining_pct=50.0)}),
    )

    shrinking = await evaluator.evaluate(
        1, "acme/widgets", ["src/a.py"], "unassigned", warn_threshold_pct=50
    )

    assert [status.owner for status in shrinking] == ["@org/team-a"]
```

Run: `docker compose run --rm app pytest tests/domain/test_pr_budget_evaluator.py -v`
Expected: fails with `ModuleNotFoundError`.

- [ ] **Step 2: Implement**

```python
# src/mergency/domain/pr_budget_evaluator.py
from mergency.domain.budget_calculator import BudgetCalculator
from mergency.domain.models.budget_status import BudgetStatus
from mergency.domain.ownership_resolver import OwnershipResolver


class PrBudgetEvaluator:
    def __init__(
        self, ownership_resolver: OwnershipResolver, budget_calculator: BudgetCalculator
    ) -> None:
        self._ownership_resolver = ownership_resolver
        self._budget_calculator = budget_calculator

    async def evaluate(
        self,
        installation_id: int,
        repo: str,
        changed_files: list[str],
        default_team: str,
        warn_threshold_pct: int,
    ) -> list[BudgetStatus]:
        owners = await self._ownership_resolver.resolve_owners(
            installation_id, repo, changed_files, default_team
        )
        statuses = [
            await self._budget_calculator.status_for(installation_id, owner) for owner in owners
        ]
        return [status for status in statuses if status.remaining_pct <= warn_threshold_pct]
```

Run: `docker compose run --rm app pytest tests/domain/test_pr_budget_evaluator.py -v`
Expected: 3 passed.

- [ ] **Step 3:** commit: `feat: add PrBudgetEvaluator domain service`.

---

## Task 6: `evaluate_pr_budget` Celery task — orchestration

**Files:** Create `tests/worker/test_evaluate_pr_budget.py`, `src/mergency/worker/evaluate_pr_budget.py`.

- [ ] **Step 1: Write the tests**

```python
# tests/worker/test_evaluate_pr_budget.py
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


def _shrinking_status() -> BudgetStatus:
    return BudgetStatus(owner="@org/team-a", window_days=28, limit=5, consumed=4, remaining_pct=20.0)


def _wire(monkeypatch, *, shrinking: list[BudgetStatus], existing_comment_id: int | None):
    comment_client = _RecordingCommentClient(existing_comment_id)
    monkeypatch.setattr(task_module, "get_pull_request_files_provider", lambda: _StubFilesProvider())
    monkeypatch.setattr(task_module, "get_config_resolver", lambda: _StubConfigResolver())
    monkeypatch.setattr(task_module, "get_pr_budget_evaluator", lambda: _StubEvaluator(shrinking))
    monkeypatch.setattr(task_module, "get_pr_comment_client", lambda: comment_client)
    return comment_client


def test_creates_a_comment_when_an_owner_is_shrinking_and_none_exists_yet(monkeypatch):
    comment_client = _wire(monkeypatch, shrinking=[_shrinking_status()], existing_comment_id=None)

    task_module.evaluate_pr_budget(_payload())

    assert len(comment_client.created) == 1
    assert comment_client.updated == []
    installation_id, repo, pr_number, body = comment_client.created[0]
    assert (installation_id, repo, pr_number) == (1, "acme/widgets", 42)
    assert MARKER in body
    assert "@org/team-a" in body


def test_updates_the_existing_comment_when_still_shrinking(monkeypatch):
    comment_client = _wire(monkeypatch, shrinking=[_shrinking_status()], existing_comment_id=999)

    task_module.evaluate_pr_budget(_payload())

    assert comment_client.created == []
    assert len(comment_client.updated) == 1
    installation_id, repo, comment_id, body = comment_client.updated[0]
    assert (installation_id, repo, comment_id) == (1, "acme/widgets", 999)
    assert "@org/team-a" in body


def test_updates_the_existing_comment_to_recovered_when_no_longer_shrinking(monkeypatch):
    comment_client = _wire(monkeypatch, shrinking=[], existing_comment_id=999)

    task_module.evaluate_pr_budget(_payload())

    assert comment_client.created == []
    assert len(comment_client.updated) == 1
    _, _, comment_id, body = comment_client.updated[0]
    assert comment_id == 999
    assert "recovered" in body.lower()


def test_does_nothing_when_healthy_and_no_existing_comment(monkeypatch):
    comment_client = _wire(monkeypatch, shrinking=[], existing_comment_id=None)

    task_module.evaluate_pr_budget(_payload())

    assert comment_client.created == []
    assert comment_client.updated == []


def test_malformed_payload_is_dropped_without_error():
    task_module.evaluate_pr_budget({"action": "opened"})
```

Run: `docker compose run --rm app pytest tests/worker/test_evaluate_pr_budget.py -v`
Expected: fails with `ModuleNotFoundError`.

- [ ] **Step 2: Implement**

```python
# src/mergency/worker/evaluate_pr_budget.py
import asyncio
import logging

from mergency.adapters.github.pull_request_signal_parser import parse_pull_request_signal
from mergency.api.deps import (
    get_config_resolver,
    get_pr_budget_evaluator,
    get_pr_comment_client,
    get_pull_request_files_provider,
)
from mergency.domain.models.pull_request_signal import PullRequestSignal
from mergency.domain.pr_comment_formatter import format_recovered_comment, format_shrinking_budget_comment
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
        body = format_shrinking_budget_comment(shrinking)
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
Expected: 5 passed.

- [ ] **Step 3:** commit: `feat: add evaluate_pr_budget worker task`.

---

## Task 7: Wire new factories into `deps.py` and register the task

**Files:** Modify `src/mergency/api/deps.py`, `src/mergency/worker/celery_app.py`, `tests/api/test_deps.py`.

- [ ] **Step 1: Add the test** (append to `tests/api/test_deps.py`)

```python
def test_pr_comment_bot_dependencies_are_cached_and_resettable():
    factories = [
        deps.get_pull_request_files_provider,
        deps.get_pr_comment_client,
        deps.get_pr_budget_evaluator,
    ]
    first_instances = [factory() for factory in factories]

    assert [factory() for factory in factories] == first_instances

    deps.reset_dependency_caches()

    assert all(
        factory() is not first
        for factory, first in zip(factories, first_instances, strict=True)
    )
```

Run: `docker compose run --rm app pytest tests/api/test_deps.py -v`
Expected: the new test fails with `AttributeError: module 'mergency.api.deps' has no attribute 'get_pull_request_files_provider'`; existing tests still pass.

- [ ] **Step 2: Implement** — modify `src/mergency/api/deps.py`.

Add these imports alongside the existing ones:

```python
from mergency.adapters.github.pr_comment_client import GithubPrCommentClient
from mergency.adapters.github.pull_request_files_provider import GithubPullRequestFilesProvider
from mergency.domain.ports.pr_comment_client import PrCommentClient
from mergency.domain.ports.pull_request_files_provider import PullRequestFilesProvider
from mergency.domain.pr_budget_evaluator import PrBudgetEvaluator
```

Add these factories, alongside `get_ownership_resolver`:

```python
@lru_cache
def get_pull_request_files_provider() -> PullRequestFilesProvider:
    return GithubPullRequestFilesProvider(get_installation_token_provider())


@lru_cache
def get_pr_comment_client() -> PrCommentClient:
    return GithubPrCommentClient(get_installation_token_provider())


@lru_cache
def get_pr_budget_evaluator() -> PrBudgetEvaluator:
    return PrBudgetEvaluator(get_ownership_resolver(), get_budget_calculator())
```

Extend `reset_dependency_caches()`:

```python
def reset_dependency_caches() -> None:
    get_settings.cache_clear()
    get_tenant_repository.cache_clear()
    get_installation_service.cache_clear()
    get_installation_token_provider.cache_clear()
    get_event_repository.cache_clear()
    get_event_classifier.cache_clear()
    get_tenant_config_repository.cache_clear()
    get_repository_content_provider.cache_clear()
    get_codeowners_provider.cache_clear()
    get_changed_files_provider.cache_clear()
    get_config_resolver.cache_clear()
    get_ownership_resolver.cache_clear()
    get_db_engine.cache_clear()
    get_budget_calculator.cache_clear()
    get_pull_request_files_provider.cache_clear()
    get_pr_comment_client.cache_clear()
    get_pr_budget_evaluator.cache_clear()
```

(`get_db_engine`/`get_budget_calculator` lines above assume plan 0011 already added them — keep whatever the real, current body of `reset_dependency_caches()` is and just append the three new `.cache_clear()` calls.)

Modify `src/mergency/worker/celery_app.py`:

```python
from celery import Celery

celery_app = Celery(
    "mergency",
    broker="redis://localhost:6379/0",
    backend="redis://localhost:6379/0",
    include=[
        "mergency.worker.classify_activity_event",
        "mergency.worker.evaluate_pr_budget",
    ],
)
```

Run: `docker compose run --rm app pytest tests/api/test_deps.py -v`
Expected: all passed.

- [ ] **Step 3:** commit: `feat: wire PR comment bot dependencies and register evaluate_pr_budget task`.

---

## Task 8: Dispatch `pull_request` webhooks to `evaluate_pr_budget`

**Files:** Modify `src/mergency/api/webhooks.py`, `tests/api/test_webhooks.py`.

- [ ] **Step 1: Update the tests**

The existing `test_unhandled_event_type_is_acknowledged` test sends a `pull_request`/`opened` webhook expecting a no-op. Once this task lands, `opened` is a tracked action, so that test's premise is gone — replace it with a test using an untracked action, and add new tests mirroring the existing `test_check_run_event_enqueues_classify_activity_event` / `test_push_event_enqueues_classify_activity_event` pattern.

Replace this test in `tests/api/test_webhooks.py`:

```python
async def test_unhandled_event_type_is_acknowledged(override_dependencies):
    payload = json.dumps({"action": "opened"}).encode()
    headers = _signed_headers(payload, "pull_request")

    async with await _client() as client:
        response = await client.post("/webhooks/github", content=payload, headers=headers)

    assert response.status_code == 200
```

with:

```python
async def test_unhandled_event_type_is_acknowledged(override_dependencies):
    payload = json.dumps({"action": "some-future-event"}).encode()
    headers = _signed_headers(payload, "some_future_event_type")

    async with await _client() as client:
        response = await client.post("/webhooks/github", content=payload, headers=headers)

    assert response.status_code == 200


async def test_pull_request_with_untracked_action_is_acknowledged_without_enqueueing(
    override_dependencies, monkeypatch
):
    from mergency.api import webhooks

    calls = []
    monkeypatch.setattr(webhooks.evaluate_pr_budget, "delay", lambda *a: calls.append(a))

    payload = json.dumps({"action": "labeled"}).encode()
    headers = _signed_headers(payload, "pull_request")

    async with await _client() as client:
        response = await client.post("/webhooks/github", content=payload, headers=headers)

    assert response.status_code == 200
    assert calls == []
```

Append these tests (one per tracked action, mirroring the existing enqueue tests exactly):

```python
async def test_pull_request_opened_enqueues_evaluate_pr_budget(override_dependencies, monkeypatch):
    from mergency.api import webhooks

    calls = []
    monkeypatch.setattr(webhooks.evaluate_pr_budget, "delay", lambda *a: calls.append(a))

    payload = json.dumps({"action": "opened", "number": 42}).encode()
    headers = _signed_headers(payload, "pull_request")

    async with await _client() as client:
        response = await client.post("/webhooks/github", content=payload, headers=headers)

    assert response.status_code == 200
    assert calls == [({"action": "opened", "number": 42},)]


async def test_pull_request_synchronize_enqueues_evaluate_pr_budget(override_dependencies, monkeypatch):
    from mergency.api import webhooks

    calls = []
    monkeypatch.setattr(webhooks.evaluate_pr_budget, "delay", lambda *a: calls.append(a))

    payload = json.dumps({"action": "synchronize", "number": 42}).encode()
    headers = _signed_headers(payload, "pull_request")

    async with await _client() as client:
        response = await client.post("/webhooks/github", content=payload, headers=headers)

    assert response.status_code == 200
    assert len(calls) == 1


async def test_pull_request_reopened_enqueues_evaluate_pr_budget(override_dependencies, monkeypatch):
    from mergency.api import webhooks

    calls = []
    monkeypatch.setattr(webhooks.evaluate_pr_budget, "delay", lambda *a: calls.append(a))

    payload = json.dumps({"action": "reopened", "number": 42}).encode()
    headers = _signed_headers(payload, "pull_request")

    async with await _client() as client:
        response = await client.post("/webhooks/github", content=payload, headers=headers)

    assert response.status_code == 200
    assert len(calls) == 1
```

Run: `docker compose run --rm app pytest tests/api/test_webhooks.py -v`
Expected: fails — `webhooks.evaluate_pr_budget` doesn't exist yet, and `pull_request`/`opened` is still routed to the "unhandled" branch.

- [ ] **Step 2: Implement** — modify `src/mergency/api/webhooks.py`:

```python
import json
import logging

from fastapi import APIRouter, Depends, Header, HTTPException, Request

from mergency.adapters.github.installation_command_parser import parse_installation_command
from mergency.adapters.github.signature import verify_signature
from mergency.api.deps import get_installation_service, get_settings
from mergency.api.settings import Settings
from mergency.domain.installation_service import InstallationService
from mergency.worker.classify_activity_event import classify_activity_event
from mergency.worker.evaluate_pr_budget import evaluate_pr_budget

logger = logging.getLogger(__name__)

router = APIRouter()

_PR_TRIGGER_ACTIONS = {"opened", "synchronize", "reopened"}


@router.post("/webhooks/github")
async def receive_webhook(
    request: Request,
    x_hub_signature_256: str | None = Header(default=None),
    x_github_event: str | None = Header(default=None),
    settings: Settings = Depends(get_settings),
    installation_service: InstallationService = Depends(get_installation_service),
) -> dict[str, str]:
    body = await request.body()

    if not verify_signature(body, x_hub_signature_256, settings.github_webhook_secret):
        raise HTTPException(status_code=401, detail="invalid signature")

    payload = json.loads(body)

    if x_github_event == "installation":
        await _handle_installation_event(payload, installation_service)
    elif x_github_event == "installation_repositories":
        logger.info("installation_repositories event acknowledged, no-op for now")
    elif x_github_event in ("push", "check_run"):
        classify_activity_event.delay(x_github_event, payload)
    elif x_github_event == "pull_request" and payload.get("action") in _PR_TRIGGER_ACTIONS:
        evaluate_pr_budget.delay(payload)
    else:
        logger.info(
            "event acknowledged, processing not yet implemented",
            extra={"event": x_github_event},
        )

    return {"status": "ok"}


async def _handle_installation_event(
    payload: dict, installation_service: InstallationService
) -> None:
    action = payload.get("action")

    try:
        command = parse_installation_command(payload)
    except KeyError as error:
        logger.warning(
            "installation payload missing expected field, acknowledged without processing",
            extra={"action": action, "missing_field": str(error)},
        )
        return

    if command is None:
        logger.info("unhandled installation action acknowledged", extra={"action": action})
        return

    await installation_service.handle(command)
```

Run: `docker compose run --rm app pytest tests/api/test_webhooks.py -v`
Expected: all passed.

- [ ] **Step 3: Full-suite check**

Run: `docker compose run --rm app pytest -v`
Expected: all tests pass.

- [ ] **Step 4:** commit: `feat: dispatch pull_request webhooks to evaluate_pr_budget`.

---

## Verification (full suite, after all tasks)

1. Full suite: `docker compose run --rm app pytest -v` — all tests pass, old and new.
2. Lint: `docker compose run --rm app ruff check src tests` — no errors.
3. Domain purity: `docker compose run --rm app grep -rniE "celery|fastapi|sqlalchemy|pygithub|^from github|^import github" src/mergency/domain/` — no matches (confirms `PrBudgetEvaluator` and `pr_comment_formatter.py` stay framework-free; `PullRequestSignal` too).
4. Marker single-source check: `docker compose run --rm app grep -rn "mergency:budget-status" src/mergency/` — matches only the one definition in `domain/pr_comment_formatter.py`, plus its one import site in `adapters/github/pr_comment_client.py`.
5. `git diff tests/api/test_webhooks.py` shows the one replaced test (`test_unhandled_event_type_is_acknowledged`, now using an untracked event type) plus new, additive tests — no unrelated behavior change to the `installation`/`installation_repositories` paths.
6. Manual smoke (optional, not part of CI): with a real installation and a `mergency.yml` setting a low `budget.max_events_per_window`, open a PR touching a file owned by a team that already has build-failure/revert events in its rolling window. Confirm a comment appears carrying `<!-- mergency:budget-status -->`. Push a new commit (`synchronize`) after fixing the underlying issue (or waiting out the window) and confirm the **same** comment is edited to the "recovered" message rather than a second comment being posted.
