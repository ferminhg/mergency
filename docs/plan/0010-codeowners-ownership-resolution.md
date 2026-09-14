# CODEOWNERS-based ownership resolution

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn a classified `Event` (`owner=None`) into one or more `Event` rows with a real team owner, per ADR 0006 (`docs/adr/0006-codeowners-ownership-resolution.md`), reading `mergency.yml` for tenant config and `CODEOWNERS` for ownership, while keeping the hexagonal domain/adapters/api boundary intact.

**Tracks:** [GitHub issue #13](https://github.com/ferminhg/mergency/issues/13).

---

## Status

proposed

## Context

`EventClassifier` (`src/mergency/domain/event_classifier.py`, implemented by `docs/plan/0009-event-classification.md`) persists `Event`s with `owner` always `None`. Nothing in the codebase resolves ownership yet: `TenantConfig`, `TenantConfigRepository`, `ConfigResolver`, `CodeownersProvider`, and `OwnershipResolver` all exist only as design in ADR 0006, not as code.

This plan is deliberately scoped to ownership resolution + in-memory persistence only, matching ADR 0006's own scope. It reuses `mergency.yml`'s already-proposed shape (`rolling_window_days`, `default_team`, `budget.max_events_per_window` — see README's "Configuration" section) as-is; ADR 0007's `budget.warn_threshold_pct` addition and the move to real Postgres persistence are out of scope here and land in the follow-up plan for issue #14.

**Two scoping decisions this plan makes that ADR 0006 leaves open:**

1. **When `TenantConfig` gets resolved.** ADR 0006's diagram shows `ConfigResolver` running at install time (`InstallHandler --> ConfigResolver`). Modifying the already-implemented installation flow (`InstallationService`, `docs/plan/0001-github-app-scaffolding.md`) to call it is out of scope for this plan — instead, `ConfigResolver.resolve(installation_id, repo)` is **cache-first**: it returns the stored `TenantConfig` if one already exists, and only fetches+parses `mergency.yml` on a cache miss. `OwnershipResolver` calls it lazily the first time it needs a default-team fallback for a given installation. Revisit (call it eagerly from `InstallationService`) in a later plan if lazy resolution proves to be the wrong trigger point.
2. **Fan-out storage mechanics.** ADR 0006 says ownership resolution "fans out one classified `Event` into N stored rows" but doesn't say how that interacts with `EventRepository`'s existing `save_if_new` dedupe key (`installation_id, repo, sha, event_type`) that `EventClassifier` already uses to store the initial `owner=None` row. This plan keeps that row as the single source of truth per dedupe key until resolution happens, then **replaces** it in place with N owner-tagged rows via a new `EventRepository.resolve_owners(...)` method (see Task 7). This means `OwnershipResolver.resolve()` is naturally idempotent — running it again against the same event recomputes and overwrites the same final rows — without changing `EventClassifier`'s already-implemented, already-shipped `save_if_new` contract at all.

**CODEOWNERS caching.** ADR 0006 specifies a Redis-backed cache with a short TTL. Redis is not wired into `docker-compose.yml` yet (only the `app` service exists — this repo is still greenfield on that front). This plan uses a simple in-process TTL cache (a `dict` guarded by `asyncio.Lock`, same pattern as `PyGithubInstallationTokenProvider`'s token cache) as an explicit, documented simplification. Revisit once Redis is actually provisioned for the token cache or Celery broker.

## Design decisions

**1. Individual-vs-team guardrail uses the `codeowners` library's own classification.** The `codeowners` PyPI package's `CodeOwners.of(path)` returns `list[tuple[str, str]]` of `(kind, handle)` pairs, where `kind` is one of `"TEAM"`, `"USERNAME"`, `"EMAIL"`. `OwnershipResolver` keeps `kind == "TEAM"` filtering in exactly one place (itself), per ADR 0006's "this check happens in one place" requirement — `CodeownersProvider` stays a thin fetch-and-parse adapter that returns the raw `(kind, handle)` pairs without judging them.

**2. Which files determine ownership.** A `CommitFilesProvider` port wraps the GitHub Commits API (`GET /repos/{owner}/{repo}/commits/{sha}`, via PyGithub's `Repository.get_commit(sha).files`) to get the changed-file list for any event's `sha`, regardless of whether it originated from a `check_run` or a `push` — this matches ADR 0006's "the resolver looks up the commit's changed files via the Commits API" for both event types, and keeps `OwnershipResolver` from needing to know which webhook produced the event it's resolving.

**3. Team owner string format.** CODEOWNERS team handles come back as `@org/team-name`; `mergency.yml`'s `default_team` is a bare string like `platform-team`. `OwnershipResolver` strips a leading `@` from CODEOWNERS handles before storing, but does not otherwise normalize — `owner` stays an opaque string key for every downstream consumer (ADR 0007's budget calculator, ADR 0008's comment bot), consistent with `Event.owner: str | None`'s existing type.

**4. Hardcoded fallback default team.** `mergency.yml`'s proposed shape makes `default_team` optional-with-a-default from a product standpoint, but the field has no natural hardcoded value the way `rolling_window_days: 28` or `max_events_per_window: 5` do. Chosen: `"unowned"` as the literal fallback string when `mergency.yml` is absent, invalid, or doesn't set `default_team` — a value that will never collide with a real CODEOWNERS team handle (those always contain `/`) and reads clearly in a PR comment or query result later. This lives once, in `mergency_yml_parser.py`.

## Directory structure (new/changed files)

```
src/mergency/
├── domain/
│   ├── models/
│   │   └── tenant_config.py           # TenantConfig
│   ├── ports/
│   │   ├── event_repository.py        # modified: + list_unresolved, resolve_owners
│   │   ├── tenant_config_repository.py
│   │   ├── repo_config_fetcher.py
│   │   ├── codeowners_provider.py
│   │   └── commit_files_provider.py
│   ├── mergency_yml_parser.py         # parse_tenant_config
│   ├── config_resolver.py             # ConfigResolver
│   └── ownership_resolver.py          # OwnershipResolver
├── adapters/
│   ├── memory/
│   │   ├── event_repository.py        # modified: fan-out storage
│   │   └── tenant_config_repository.py
│   └── github/
│       ├── repo_config_fetcher.py     # GithubRepoConfigFetcher
│       ├── codeowners_provider.py     # GithubCodeownersProvider
│       └── commit_files_provider.py   # GithubCommitFilesProvider
├── api/
│   └── deps.py                        # modified: new factories
└── worker/
    └── classify_activity_event.py     # modified: resolve ownership after classify

tests/
├── domain/
│   ├── models/test_tenant_config.py
│   ├── test_mergency_yml_parser.py
│   ├── test_config_resolver.py
│   └── test_ownership_resolver.py
├── adapters/
│   ├── memory/
│   │   ├── test_event_repository.py   # modified: + fan-out tests
│   │   └── test_tenant_config_repository.py
│   └── github/
│       ├── test_repo_config_fetcher.py
│       ├── test_codeowners_provider.py
│       └── test_commit_files_provider.py
├── api/test_deps.py                   # modified
└── worker/test_classify_activity_event.py  # modified
```

---

## Task 1: Add new dependencies

**Files:** Modify `pyproject.toml`.

- [ ] **Step 1: Add `pyyaml` and `codeowners` to `dependencies`**

```toml
dependencies = [
    "fastapi>=0.115",
    "pydantic-settings>=2.5",
    "pygithub>=2.4",
    "celery>=5.4",
    "uvicorn[standard]>=0.32",
    "pyyaml>=6.0",
    "codeowners>=0.6",
]
```

- [ ] **Step 2: Rebuild the image and verify both import cleanly**

Run: `docker compose build app && docker compose run --rm app python -c "import yaml, codeowners; print('ok')"`
Expected: prints `ok`, no `ModuleNotFoundError`.

- [ ] **Step 3:** commit: `chore: add pyyaml and codeowners dependencies`.

---

## Task 2: `TenantConfig` model

**Files:** Create `tests/domain/models/test_tenant_config.py`, `src/mergency/domain/models/tenant_config.py`.

- [ ] **Step 1: Write the test**

```python
# tests/domain/models/test_tenant_config.py
import dataclasses

import pytest

from mergency.domain.models.tenant_config import TenantConfig


def test_tenant_config_is_immutable():
    config = TenantConfig(
        installation_id=1,
        rolling_window_days=28,
        default_team="platform-team",
        max_events_per_window=5,
    )

    with pytest.raises(dataclasses.FrozenInstanceError):
        config.default_team = "other-team"
```

Run: `docker compose run --rm app pytest tests/domain/models/test_tenant_config.py -v`
Expected: fails with `ModuleNotFoundError`.

- [ ] **Step 2: Implement**

```python
# src/mergency/domain/models/tenant_config.py
from dataclasses import dataclass


@dataclass(frozen=True)
class TenantConfig:
    installation_id: int
    rolling_window_days: int
    default_team: str
    max_events_per_window: int
```

Run: `docker compose run --rm app pytest tests/domain/models/test_tenant_config.py -v`
Expected: 1 passed.

- [ ] **Step 3:** commit: `feat: add TenantConfig domain model`.

---

## Task 3: `TenantConfigRepository` port + in-memory adapter

**Files:** Create `tests/adapters/memory/test_tenant_config_repository.py`, `src/mergency/domain/ports/tenant_config_repository.py`, `src/mergency/adapters/memory/tenant_config_repository.py`.

- [ ] **Step 1: Write the test**

```python
# tests/adapters/memory/test_tenant_config_repository.py
from mergency.adapters.memory.tenant_config_repository import InMemoryTenantConfigRepository
from mergency.domain.models.tenant_config import TenantConfig


def _config(installation_id: int = 1) -> TenantConfig:
    return TenantConfig(
        installation_id=installation_id,
        rolling_window_days=28,
        default_team="platform-team",
        max_events_per_window=5,
    )


async def test_get_returns_none_when_absent():
    repository = InMemoryTenantConfigRepository()

    assert await repository.get(1) is None


async def test_upsert_then_get_returns_stored_config():
    repository = InMemoryTenantConfigRepository()

    await repository.upsert(_config())

    stored = await repository.get(1)
    assert stored is not None
    assert stored.default_team == "platform-team"


async def test_upsert_overwrites_existing_config():
    repository = InMemoryTenantConfigRepository()
    await repository.upsert(_config())

    await repository.upsert(_config().__class__(1, 14, "other-team", 10))

    stored = await repository.get(1)
    assert stored.rolling_window_days == 14
    assert stored.default_team == "other-team"
```

Run: `docker compose run --rm app pytest tests/adapters/memory/test_tenant_config_repository.py -v`
Expected: fails with `ModuleNotFoundError`.

- [ ] **Step 2: Implement**

```python
# src/mergency/domain/ports/tenant_config_repository.py
from typing import Protocol

from mergency.domain.models.tenant_config import TenantConfig


class TenantConfigRepository(Protocol):
    async def upsert(self, config: TenantConfig) -> None: ...

    async def get(self, installation_id: int) -> TenantConfig | None: ...
```

```python
# src/mergency/adapters/memory/tenant_config_repository.py
import asyncio

from mergency.domain.models.tenant_config import TenantConfig


class InMemoryTenantConfigRepository:
    def __init__(self) -> None:
        self._configs: dict[int, TenantConfig] = {}
        self._lock = asyncio.Lock()

    async def upsert(self, config: TenantConfig) -> None:
        async with self._lock:
            self._configs[config.installation_id] = config

    async def get(self, installation_id: int) -> TenantConfig | None:
        async with self._lock:
            return self._configs.get(installation_id)
```

Run: `docker compose run --rm app pytest tests/adapters/memory/test_tenant_config_repository.py -v`
Expected: 3 passed.

- [ ] **Step 3:** commit: `feat: add TenantConfigRepository port and in-memory adapter`.

---

## Task 4: `mergency.yml` parser

**Files:** Create `tests/domain/test_mergency_yml_parser.py`, `src/mergency/domain/mergency_yml_parser.py`.

- [ ] **Step 1: Write the test**

```python
# tests/domain/test_mergency_yml_parser.py
from mergency.domain.mergency_yml_parser import parse_tenant_config


def test_parses_full_yaml():
    yaml_text = """
    rolling_window_days: 14
    default_team: platform-team
    budget:
      max_events_per_window: 10
    """

    config = parse_tenant_config(1, yaml_text)

    assert config.installation_id == 1
    assert config.rolling_window_days == 14
    assert config.default_team == "platform-team"
    assert config.max_events_per_window == 10


def test_missing_fields_fall_back_to_defaults():
    config = parse_tenant_config(1, "default_team: only-this-team\n")

    assert config.rolling_window_days == 28
    assert config.default_team == "only-this-team"
    assert config.max_events_per_window == 5


def test_none_text_falls_back_to_all_defaults():
    config = parse_tenant_config(1, None)

    assert config.rolling_window_days == 28
    assert config.default_team == "unowned"
    assert config.max_events_per_window == 5


def test_invalid_yaml_falls_back_to_all_defaults():
    config = parse_tenant_config(1, "not: valid: yaml: [")

    assert config.rolling_window_days == 28
    assert config.default_team == "unowned"


def test_empty_yaml_document_falls_back_to_all_defaults():
    config = parse_tenant_config(1, "")

    assert config.default_team == "unowned"
```

Run: `docker compose run --rm app pytest tests/domain/test_mergency_yml_parser.py -v`
Expected: fails with `ModuleNotFoundError`.

- [ ] **Step 2: Implement**

```python
# src/mergency/domain/mergency_yml_parser.py
import yaml

from mergency.domain.models.tenant_config import TenantConfig

_DEFAULT_ROLLING_WINDOW_DAYS = 28
_DEFAULT_DEFAULT_TEAM = "unowned"
_DEFAULT_MAX_EVENTS_PER_WINDOW = 5


def parse_tenant_config(installation_id: int, yaml_text: str | None) -> TenantConfig:
    raw: dict = {}
    if yaml_text is not None:
        try:
            raw = yaml.safe_load(yaml_text) or {}
        except yaml.YAMLError:
            raw = {}

    budget = raw.get("budget") or {}
    return TenantConfig(
        installation_id=installation_id,
        rolling_window_days=raw.get("rolling_window_days", _DEFAULT_ROLLING_WINDOW_DAYS),
        default_team=raw.get("default_team", _DEFAULT_DEFAULT_TEAM),
        max_events_per_window=budget.get("max_events_per_window", _DEFAULT_MAX_EVENTS_PER_WINDOW),
    )
```

Run: `docker compose run --rm app pytest tests/domain/test_mergency_yml_parser.py -v`
Expected: 5 passed.

- [ ] **Step 3:** commit: `feat: add mergency.yml parser`.

---

## Task 5: `RepoConfigFetcher` port + GitHub adapter

**Files:** Create `tests/adapters/github/test_repo_config_fetcher.py`, `src/mergency/domain/ports/repo_config_fetcher.py`, `src/mergency/adapters/github/repo_config_fetcher.py`.

- [ ] **Step 1: Write the test**

```python
# tests/adapters/github/test_repo_config_fetcher.py
from unittest.mock import AsyncMock, MagicMock

from github import GithubException

from mergency.adapters.github.repo_config_fetcher import GithubRepoConfigFetcher


def _token_provider(token: str = "tok") -> AsyncMock:
    provider = AsyncMock()
    provider.get_token.return_value = token
    return provider


def _content_file(text: str) -> MagicMock:
    content = MagicMock()
    content.decoded_content = text.encode("utf-8")
    return content


async def test_returns_file_contents_when_present(monkeypatch):
    client = MagicMock()
    client.get_repo.return_value.get_contents.return_value = _content_file("rolling_window_days: 14")
    monkeypatch.setattr(
        "mergency.adapters.github.repo_config_fetcher.Github", MagicMock(return_value=client)
    )
    fetcher = GithubRepoConfigFetcher(_token_provider())

    text = await fetcher.fetch_mergency_yml(1, "acme/widgets")

    assert text == "rolling_window_days: 14"
    client.get_repo.return_value.get_contents.assert_called_once_with("mergency.yml")


async def test_returns_none_when_file_is_missing(monkeypatch):
    client = MagicMock()
    not_found = GithubException(404, {"message": "Not Found"}, {})
    client.get_repo.return_value.get_contents.side_effect = not_found
    monkeypatch.setattr(
        "mergency.adapters.github.repo_config_fetcher.Github", MagicMock(return_value=client)
    )
    fetcher = GithubRepoConfigFetcher(_token_provider())

    assert await fetcher.fetch_mergency_yml(1, "acme/widgets") is None


async def test_reraises_non_404_errors(monkeypatch):
    client = MagicMock()
    server_error = GithubException(500, {"message": "boom"}, {})
    client.get_repo.return_value.get_contents.side_effect = server_error
    monkeypatch.setattr(
        "mergency.adapters.github.repo_config_fetcher.Github", MagicMock(return_value=client)
    )
    fetcher = GithubRepoConfigFetcher(_token_provider())

    try:
        await fetcher.fetch_mergency_yml(1, "acme/widgets")
        assert False, "expected GithubException to propagate"
    except GithubException as error:
        assert error.status == 500
```

Run: `docker compose run --rm app pytest tests/adapters/github/test_repo_config_fetcher.py -v`
Expected: fails with `ModuleNotFoundError`.

- [ ] **Step 2: Implement**

```python
# src/mergency/domain/ports/repo_config_fetcher.py
from typing import Protocol


class RepoConfigFetcher(Protocol):
    async def fetch_mergency_yml(self, installation_id: int, repo: str) -> str | None: ...
```

```python
# src/mergency/adapters/github/repo_config_fetcher.py
import asyncio

from github import Github, GithubException

from mergency.domain.ports.installation_token_provider import InstallationTokenProvider

_CONFIG_PATH = "mergency.yml"


class GithubRepoConfigFetcher:
    def __init__(self, token_provider: InstallationTokenProvider) -> None:
        self._token_provider = token_provider

    async def fetch_mergency_yml(self, installation_id: int, repo: str) -> str | None:
        token = await self._token_provider.get_token(installation_id)
        client = Github(token)
        repository = await asyncio.to_thread(client.get_repo, repo)
        try:
            content = await asyncio.to_thread(repository.get_contents, _CONFIG_PATH)
        except GithubException as error:
            if error.status == 404:
                return None
            raise
        return content.decoded_content.decode("utf-8")
```

Run: `docker compose run --rm app pytest tests/adapters/github/test_repo_config_fetcher.py -v`
Expected: 3 passed.

- [ ] **Step 3:** commit: `feat: add RepoConfigFetcher port and GitHub adapter`.

---

## Task 6: `ConfigResolver` domain service

**Files:** Create `tests/domain/test_config_resolver.py`, `src/mergency/domain/config_resolver.py`.

- [ ] **Step 1: Write the test**

```python
# tests/domain/test_config_resolver.py
from mergency.adapters.memory.tenant_config_repository import InMemoryTenantConfigRepository
from mergency.domain.config_resolver import ConfigResolver


class _FakeConfigFetcher:
    def __init__(self, text: str | None) -> None:
        self.text = text
        self.calls = 0

    async def fetch_mergency_yml(self, installation_id: int, repo: str) -> str | None:
        self.calls += 1
        return self.text


async def test_resolve_fetches_parses_and_persists_on_first_call():
    fetcher = _FakeConfigFetcher("default_team: platform-team\n")
    repository = InMemoryTenantConfigRepository()
    resolver = ConfigResolver(fetcher, repository)

    config = await resolver.resolve(1, "acme/widgets")

    assert config.default_team == "platform-team"
    assert fetcher.calls == 1
    assert (await repository.get(1)).default_team == "platform-team"


async def test_resolve_is_cache_first_on_subsequent_calls():
    fetcher = _FakeConfigFetcher("default_team: platform-team\n")
    repository = InMemoryTenantConfigRepository()
    resolver = ConfigResolver(fetcher, repository)
    await resolver.resolve(1, "acme/widgets")

    await resolver.resolve(1, "acme/widgets")

    assert fetcher.calls == 1


async def test_resolve_falls_back_to_defaults_when_file_absent():
    fetcher = _FakeConfigFetcher(None)
    repository = InMemoryTenantConfigRepository()
    resolver = ConfigResolver(fetcher, repository)

    config = await resolver.resolve(1, "acme/widgets")

    assert config.default_team == "unowned"
```

Run: `docker compose run --rm app pytest tests/domain/test_config_resolver.py -v`
Expected: fails with `ModuleNotFoundError`.

- [ ] **Step 2: Implement**

```python
# src/mergency/domain/config_resolver.py
from mergency.domain.mergency_yml_parser import parse_tenant_config
from mergency.domain.models.tenant_config import TenantConfig
from mergency.domain.ports.repo_config_fetcher import RepoConfigFetcher
from mergency.domain.ports.tenant_config_repository import TenantConfigRepository


class ConfigResolver:
    def __init__(
        self, config_fetcher: RepoConfigFetcher, config_repository: TenantConfigRepository
    ) -> None:
        self._config_fetcher = config_fetcher
        self._config_repository = config_repository

    async def resolve(self, installation_id: int, repo: str) -> TenantConfig:
        existing = await self._config_repository.get(installation_id)
        if existing is not None:
            return existing

        yaml_text = await self._config_fetcher.fetch_mergency_yml(installation_id, repo)
        config = parse_tenant_config(installation_id, yaml_text)
        await self._config_repository.upsert(config)
        return config
```

Run: `docker compose run --rm app pytest tests/domain/test_config_resolver.py -v`
Expected: 3 passed.

- [ ] **Step 3:** commit: `feat: add ConfigResolver domain service`.

---

## Task 7: `EventRepository` fan-out support

**Files:** Modify `src/mergency/domain/ports/event_repository.py`, `src/mergency/adapters/memory/event_repository.py`, `tests/adapters/memory/test_event_repository.py`.

- [ ] **Step 1: Add the tests** (append to `tests/adapters/memory/test_event_repository.py`, keep existing tests untouched)

```python
async def test_list_unresolved_returns_only_owner_none_events():
    repository = InMemoryEventRepository()
    await repository.save_if_new(_event(sha="abc123"))

    unresolved = await repository.list_unresolved(1)

    assert len(unresolved) == 1
    assert unresolved[0].sha == "abc123"


async def test_list_unresolved_excludes_other_installations():
    repository = InMemoryEventRepository()
    await repository.save_if_new(_event(sha="abc123"))

    assert await repository.list_unresolved(999) == []


async def test_resolve_owners_replaces_the_unresolved_row_with_one_row_per_owner():
    repository = InMemoryEventRepository()
    await repository.save_if_new(_event(sha="abc123"))

    resolved = await repository.resolve_owners(1, "acme/widgets", "abc123", EventType.BUILD_FAILURE, ["team-a", "team-b"])

    assert {event.owner for event in resolved} == {"team-a", "team-b"}
    assert await repository.list_unresolved(1) == []


async def test_resolve_owners_on_unknown_event_returns_empty_list():
    repository = InMemoryEventRepository()

    resolved = await repository.resolve_owners(1, "acme/widgets", "missing", EventType.BUILD_FAILURE, ["team-a"])

    assert resolved == []
```

Run: `docker compose run --rm app pytest tests/adapters/memory/test_event_repository.py -v`
Expected: 4 new tests fail with `AttributeError` (`list_unresolved`/`resolve_owners` don't exist yet); existing tests still pass.

- [ ] **Step 2: Implement** — modify `src/mergency/domain/ports/event_repository.py`:

```python
# src/mergency/domain/ports/event_repository.py
from typing import Protocol

from mergency.domain.models.event import Event
from mergency.domain.models.event_type import EventType


class EventRepository(Protocol):
    async def save_if_new(self, event: Event) -> bool: ...

    async def get(
        self, installation_id: int, repo: str, sha: str, event_type: EventType
    ) -> Event | None: ...

    async def list_unresolved(self, installation_id: int) -> list[Event]: ...

    async def resolve_owners(
        self,
        installation_id: int,
        repo: str,
        sha: str,
        event_type: EventType,
        owners: list[str],
    ) -> list[Event]: ...
```

Modify `src/mergency/adapters/memory/event_repository.py` — internal storage moves from `dict[key, Event]` to `dict[key, list[Event]]`, so a resolved event can occupy more than one row under the same dedupe key:

```python
# src/mergency/adapters/memory/event_repository.py
import asyncio
import dataclasses

from mergency.domain.models.event import Event
from mergency.domain.models.event_type import EventType


class InMemoryEventRepository:
    def __init__(self) -> None:
        self._events: dict[tuple[int, str, str, EventType], list[Event]] = {}
        self._lock = asyncio.Lock()

    async def save_if_new(self, event: Event) -> bool:
        key = (event.installation_id, event.repo, event.sha, event.event_type)
        async with self._lock:
            if key in self._events:
                return False
            self._events[key] = [event]
            return True

    async def get(
        self, installation_id: int, repo: str, sha: str, event_type: EventType
    ) -> Event | None:
        async with self._lock:
            stored = self._events.get((installation_id, repo, sha, event_type))
            return stored[0] if stored else None

    async def list_unresolved(self, installation_id: int) -> list[Event]:
        async with self._lock:
            return [
                events[0]
                for (inst_id, _, _, _), events in self._events.items()
                if inst_id == installation_id and len(events) == 1 and events[0].owner is None
            ]

    async def resolve_owners(
        self,
        installation_id: int,
        repo: str,
        sha: str,
        event_type: EventType,
        owners: list[str],
    ) -> list[Event]:
        key = (installation_id, repo, sha, event_type)
        async with self._lock:
            existing = self._events.get(key)
            if not existing:
                return []
            base = existing[0]
            resolved = [dataclasses.replace(base, owner=owner) for owner in owners]
            self._events[key] = resolved
            return resolved
```

Run: `docker compose run --rm app pytest tests/adapters/memory/test_event_repository.py -v`
Expected: 8 passed (4 original + 4 new).

- [ ] **Step 3:** commit: `feat: add ownership fan-out to EventRepository`.

---

## Task 8: `CodeownersProvider` port + GitHub adapter

**Files:** Create `tests/adapters/github/test_codeowners_provider.py`, `src/mergency/domain/ports/codeowners_provider.py`, `src/mergency/adapters/github/codeowners_provider.py`.

- [ ] **Step 1: Write the test**

```python
# tests/adapters/github/test_codeowners_provider.py
from unittest.mock import AsyncMock, MagicMock

from github import GithubException

from mergency.adapters.github.codeowners_provider import GithubCodeownersProvider

_CODEOWNERS = "*.py @acme/backend-team\n/docs/ @someone-individual\n"


def _token_provider() -> AsyncMock:
    provider = AsyncMock()
    provider.get_token.return_value = "tok"
    return provider


def _content_file(text: str) -> MagicMock:
    content = MagicMock()
    content.decoded_content = text.encode("utf-8")
    return content


def _client_with_codeowners_at(path: str, text: str) -> MagicMock:
    client = MagicMock()

    def get_contents(requested_path: str):
        if requested_path == path:
            return _content_file(text)
        raise GithubException(404, {"message": "Not Found"}, {})

    client.get_repo.return_value.get_contents.side_effect = get_contents
    return client


async def test_resolves_owners_for_matching_path(monkeypatch):
    client = _client_with_codeowners_at("CODEOWNERS", _CODEOWNERS)
    monkeypatch.setattr(
        "mergency.adapters.github.codeowners_provider.Github", MagicMock(return_value=client)
    )
    provider = GithubCodeownersProvider(_token_provider())

    owners = await provider.get_owners_for_paths(1, "acme/widgets", ["src/app.py"])

    assert ("TEAM", "@acme/backend-team") in owners


async def test_falls_back_to_nested_codeowners_locations(monkeypatch):
    client = _client_with_codeowners_at(".github/CODEOWNERS", _CODEOWNERS)
    monkeypatch.setattr(
        "mergency.adapters.github.codeowners_provider.Github", MagicMock(return_value=client)
    )
    provider = GithubCodeownersProvider(_token_provider())

    owners = await provider.get_owners_for_paths(1, "acme/widgets", ["src/app.py"])

    assert ("TEAM", "@acme/backend-team") in owners


async def test_returns_empty_list_when_no_codeowners_file_exists(monkeypatch):
    client = MagicMock()
    client.get_repo.return_value.get_contents.side_effect = GithubException(
        404, {"message": "Not Found"}, {}
    )
    monkeypatch.setattr(
        "mergency.adapters.github.codeowners_provider.Github", MagicMock(return_value=client)
    )
    provider = GithubCodeownersProvider(_token_provider())

    assert await provider.get_owners_for_paths(1, "acme/widgets", ["src/app.py"]) == []


async def test_caches_the_parsed_ruleset_across_calls(monkeypatch):
    client = _client_with_codeowners_at("CODEOWNERS", _CODEOWNERS)
    monkeypatch.setattr(
        "mergency.adapters.github.codeowners_provider.Github", MagicMock(return_value=client)
    )
    token_provider = _token_provider()
    provider = GithubCodeownersProvider(token_provider)

    await provider.get_owners_for_paths(1, "acme/widgets", ["src/app.py"])
    await provider.get_owners_for_paths(1, "acme/widgets", ["src/app.py"])

    assert token_provider.get_token.call_count == 1
```

Run: `docker compose run --rm app pytest tests/adapters/github/test_codeowners_provider.py -v`
Expected: fails with `ModuleNotFoundError`.

- [ ] **Step 2: Implement**

```python
# src/mergency/domain/ports/codeowners_provider.py
from typing import Protocol


class CodeownersProvider(Protocol):
    async def get_owners_for_paths(
        self, installation_id: int, repo: str, paths: list[str]
    ) -> list[tuple[str, str]]: ...
```

```python
# src/mergency/adapters/github/codeowners_provider.py
import asyncio
import time

from codeowners import CodeOwners
from github import Github, GithubException

from mergency.domain.ports.installation_token_provider import InstallationTokenProvider

_CODEOWNERS_PATHS = ("CODEOWNERS", ".github/CODEOWNERS", "docs/CODEOWNERS")
_CACHE_TTL_SECONDS = 300


class GithubCodeownersProvider:
    def __init__(self, token_provider: InstallationTokenProvider) -> None:
        self._token_provider = token_provider
        self._cache: dict[tuple[int, str], tuple[CodeOwners, float]] = {}
        self._lock = asyncio.Lock()

    async def get_owners_for_paths(
        self, installation_id: int, repo: str, paths: list[str]
    ) -> list[tuple[str, str]]:
        ruleset = await self._get_ruleset(installation_id, repo)
        if ruleset is None:
            return []

        matches: set[tuple[str, str]] = set()
        for path in paths:
            matches.update(ruleset.of(path))
        return sorted(matches)

    async def _get_ruleset(self, installation_id: int, repo: str) -> CodeOwners | None:
        key = (installation_id, repo)
        async with self._lock:
            cached = self._cache.get(key)
            if cached is not None and cached[1] > time.monotonic():
                return cached[0]

        text = await self._fetch_codeowners_text(installation_id, repo)
        if text is None:
            return None

        ruleset = CodeOwners(text)
        async with self._lock:
            self._cache[key] = (ruleset, time.monotonic() + _CACHE_TTL_SECONDS)
        return ruleset

    async def _fetch_codeowners_text(self, installation_id: int, repo: str) -> str | None:
        token = await self._token_provider.get_token(installation_id)
        client = Github(token)
        repository = await asyncio.to_thread(client.get_repo, repo)
        for path in _CODEOWNERS_PATHS:
            try:
                content = await asyncio.to_thread(repository.get_contents, path)
            except GithubException as error:
                if error.status == 404:
                    continue
                raise
            return content.decoded_content.decode("utf-8")
        return None
```

Run: `docker compose run --rm app pytest tests/adapters/github/test_codeowners_provider.py -v`
Expected: 4 passed.

- [ ] **Step 3:** commit: `feat: add CodeownersProvider port and GitHub adapter`.

---

## Task 9: `CommitFilesProvider` port + GitHub adapter

**Files:** Create `tests/adapters/github/test_commit_files_provider.py`, `src/mergency/domain/ports/commit_files_provider.py`, `src/mergency/adapters/github/commit_files_provider.py`.

- [ ] **Step 1: Write the test**

```python
# tests/adapters/github/test_commit_files_provider.py
from unittest.mock import AsyncMock, MagicMock

from mergency.adapters.github.commit_files_provider import GithubCommitFilesProvider


def _token_provider() -> AsyncMock:
    provider = AsyncMock()
    provider.get_token.return_value = "tok"
    return provider


async def test_returns_changed_file_paths(monkeypatch):
    file_a = MagicMock()
    file_a.filename = "src/app.py"
    file_b = MagicMock()
    file_b.filename = "docs/readme.md"
    client = MagicMock()
    client.get_repo.return_value.get_commit.return_value.files = [file_a, file_b]
    monkeypatch.setattr(
        "mergency.adapters.github.commit_files_provider.Github", MagicMock(return_value=client)
    )
    provider = GithubCommitFilesProvider(_token_provider())

    files = await provider.get_changed_files(1, "acme/widgets", "abc123")

    assert files == ["src/app.py", "docs/readme.md"]
    client.get_repo.return_value.get_commit.assert_called_once_with("abc123")


async def test_returns_empty_list_when_commit_has_no_files(monkeypatch):
    client = MagicMock()
    client.get_repo.return_value.get_commit.return_value.files = []
    monkeypatch.setattr(
        "mergency.adapters.github.commit_files_provider.Github", MagicMock(return_value=client)
    )
    provider = GithubCommitFilesProvider(_token_provider())

    assert await provider.get_changed_files(1, "acme/widgets", "abc123") == []
```

Run: `docker compose run --rm app pytest tests/adapters/github/test_commit_files_provider.py -v`
Expected: fails with `ModuleNotFoundError`.

- [ ] **Step 2: Implement**

```python
# src/mergency/domain/ports/commit_files_provider.py
from typing import Protocol


class CommitFilesProvider(Protocol):
    async def get_changed_files(self, installation_id: int, repo: str, sha: str) -> list[str]: ...
```

```python
# src/mergency/adapters/github/commit_files_provider.py
import asyncio

from github import Github

from mergency.domain.ports.installation_token_provider import InstallationTokenProvider


class GithubCommitFilesProvider:
    def __init__(self, token_provider: InstallationTokenProvider) -> None:
        self._token_provider = token_provider

    async def get_changed_files(self, installation_id: int, repo: str, sha: str) -> list[str]:
        token = await self._token_provider.get_token(installation_id)
        client = Github(token)
        repository = await asyncio.to_thread(client.get_repo, repo)
        commit = await asyncio.to_thread(repository.get_commit, sha)
        return [changed_file.filename for changed_file in commit.files]
```

Run: `docker compose run --rm app pytest tests/adapters/github/test_commit_files_provider.py -v`
Expected: 2 passed.

- [ ] **Step 3:** commit: `feat: add CommitFilesProvider port and GitHub adapter`.

---

## Task 10: `OwnershipResolver` domain service

**Files:** Create `tests/domain/test_ownership_resolver.py`, `src/mergency/domain/ownership_resolver.py`.

- [ ] **Step 1: Write the test**

```python
# tests/domain/test_ownership_resolver.py
from datetime import datetime, timezone

from mergency.adapters.memory.event_repository import InMemoryEventRepository
from mergency.adapters.memory.tenant_config_repository import InMemoryTenantConfigRepository
from mergency.domain.config_resolver import ConfigResolver
from mergency.domain.models.event import Event
from mergency.domain.models.event_type import EventType
from mergency.domain.ownership_resolver import OwnershipResolver


class _FakeCodeownersProvider:
    def __init__(self, owners: list[tuple[str, str]]) -> None:
        self._owners = owners

    async def get_owners_for_paths(self, installation_id, repo, paths) -> list[tuple[str, str]]:
        return self._owners


class _FakeCommitFilesProvider:
    def __init__(self, files: list[str]) -> None:
        self._files = files

    async def get_changed_files(self, installation_id, repo, sha) -> list[str]:
        return self._files


class _FakeConfigFetcher:
    async def fetch_mergency_yml(self, installation_id, repo) -> str | None:
        return None


async def _seed_unresolved_event(repository: InMemoryEventRepository) -> Event:
    event = Event(
        installation_id=1,
        repo="acme/widgets",
        sha="abc123",
        event_type=EventType.BUILD_FAILURE,
        owner=None,
        ts=datetime.now(timezone.utc),
    )
    await repository.save_if_new(event)
    return event


def _build_resolver(
    event_repository: InMemoryEventRepository, codeowners: list[tuple[str, str]]
) -> OwnershipResolver:
    config_resolver = ConfigResolver(_FakeConfigFetcher(), InMemoryTenantConfigRepository())
    return OwnershipResolver(
        _FakeCodeownersProvider(codeowners),
        _FakeCommitFilesProvider(["src/app.py"]),
        config_resolver,
        event_repository,
    )


async def test_resolves_to_matching_team_owners():
    event_repository = InMemoryEventRepository()
    event = await _seed_unresolved_event(event_repository)
    resolver = _build_resolver(event_repository, [("TEAM", "@acme/backend-team")])

    resolved = await resolver.resolve(event)

    assert [e.owner for e in resolved] == ["acme/backend-team"]


async def test_fans_out_to_multiple_team_owners():
    event_repository = InMemoryEventRepository()
    event = await _seed_unresolved_event(event_repository)
    resolver = _build_resolver(
        event_repository, [("TEAM", "@acme/backend-team"), ("TEAM", "@acme/infra-team")]
    )

    resolved = await resolver.resolve(event)

    assert {e.owner for e in resolved} == {"acme/backend-team", "acme/infra-team"}


async def test_individual_handles_never_surface_falls_back_to_default_team():
    event_repository = InMemoryEventRepository()
    event = await _seed_unresolved_event(event_repository)
    resolver = _build_resolver(event_repository, [("USERNAME", "@some-individual")])

    resolved = await resolver.resolve(event)

    assert [e.owner for e in resolved] == ["unowned"]


async def test_no_codeowners_match_falls_back_to_default_team():
    event_repository = InMemoryEventRepository()
    event = await _seed_unresolved_event(event_repository)
    resolver = _build_resolver(event_repository, [])

    resolved = await resolver.resolve(event)

    assert [e.owner for e in resolved] == ["unowned"]
```

Run: `docker compose run --rm app pytest tests/domain/test_ownership_resolver.py -v`
Expected: fails with `ModuleNotFoundError`.

- [ ] **Step 2: Implement**

```python
# src/mergency/domain/ownership_resolver.py
from mergency.domain.config_resolver import ConfigResolver
from mergency.domain.models.event import Event
from mergency.domain.ports.codeowners_provider import CodeownersProvider
from mergency.domain.ports.commit_files_provider import CommitFilesProvider
from mergency.domain.ports.event_repository import EventRepository


class OwnershipResolver:
    def __init__(
        self,
        codeowners_provider: CodeownersProvider,
        commit_files_provider: CommitFilesProvider,
        config_resolver: ConfigResolver,
        event_repository: EventRepository,
    ) -> None:
        self._codeowners_provider = codeowners_provider
        self._commit_files_provider = commit_files_provider
        self._config_resolver = config_resolver
        self._event_repository = event_repository

    async def resolve(self, event: Event) -> list[Event]:
        changed_files = await self._commit_files_provider.get_changed_files(
            event.installation_id, event.repo, event.sha
        )
        raw_owners = await self._codeowners_provider.get_owners_for_paths(
            event.installation_id, event.repo, changed_files
        )
        team_owners = {handle.lstrip("@") for kind, handle in raw_owners if kind == "TEAM"}

        if not team_owners:
            config = await self._config_resolver.resolve(event.installation_id, event.repo)
            team_owners = {config.default_team}

        return await self._event_repository.resolve_owners(
            event.installation_id,
            event.repo,
            event.sha,
            event.event_type,
            sorted(team_owners),
        )
```

Run: `docker compose run --rm app pytest tests/domain/test_ownership_resolver.py -v`
Expected: 4 passed.

- [ ] **Step 3:** commit: `feat: add OwnershipResolver domain service`.

---

## Task 11: Wire everything into `deps.py`

**Files:** Modify `src/mergency/api/deps.py`, `tests/api/test_deps.py`.

- [ ] **Step 1: Add the test** (append to `tests/api/test_deps.py`, keep existing tests untouched)

```python
def test_get_ownership_resolver_is_cached_and_resettable():
    from mergency.api import deps

    first = deps.get_ownership_resolver()
    assert deps.get_ownership_resolver() is first

    deps.reset_dependency_caches()

    assert deps.get_ownership_resolver() is not first
```

Run: `docker compose run --rm app pytest tests/api/test_deps.py -v`
Expected: fails with `AttributeError: module 'mergency.api.deps' has no attribute 'get_ownership_resolver'`.

- [ ] **Step 2: Implement** — modify `src/mergency/api/deps.py`, add imports:

```python
from mergency.adapters.github.codeowners_provider import GithubCodeownersProvider
from mergency.adapters.github.commit_files_provider import GithubCommitFilesProvider
from mergency.adapters.github.repo_config_fetcher import GithubRepoConfigFetcher
from mergency.adapters.memory.tenant_config_repository import InMemoryTenantConfigRepository
from mergency.domain.config_resolver import ConfigResolver
from mergency.domain.ownership_resolver import OwnershipResolver
from mergency.domain.ports.codeowners_provider import CodeownersProvider
from mergency.domain.ports.commit_files_provider import CommitFilesProvider
from mergency.domain.ports.repo_config_fetcher import RepoConfigFetcher
from mergency.domain.ports.tenant_config_repository import TenantConfigRepository
```

Add alongside the other factories:

```python
@lru_cache
def get_tenant_config_repository() -> TenantConfigRepository:
    return InMemoryTenantConfigRepository()


@lru_cache
def get_repo_config_fetcher() -> RepoConfigFetcher:
    return GithubRepoConfigFetcher(get_installation_token_provider())


@lru_cache
def get_config_resolver() -> ConfigResolver:
    return ConfigResolver(get_repo_config_fetcher(), get_tenant_config_repository())


@lru_cache
def get_codeowners_provider() -> CodeownersProvider:
    return GithubCodeownersProvider(get_installation_token_provider())


@lru_cache
def get_commit_files_provider() -> CommitFilesProvider:
    return GithubCommitFilesProvider(get_installation_token_provider())


@lru_cache
def get_ownership_resolver() -> OwnershipResolver:
    return OwnershipResolver(
        get_codeowners_provider(),
        get_commit_files_provider(),
        get_config_resolver(),
        get_event_repository(),
    )
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
    get_repo_config_fetcher.cache_clear()
    get_config_resolver.cache_clear()
    get_codeowners_provider.cache_clear()
    get_commit_files_provider.cache_clear()
    get_ownership_resolver.cache_clear()
```

Run: `docker compose run --rm app pytest tests/api/test_deps.py -v`
Expected: all passed.

- [ ] **Step 3:** commit: `feat: wire ownership resolution dependencies into deps`.

---

## Task 12: Resolve ownership after classification in the worker task

**Files:** Modify `src/mergency/worker/classify_activity_event.py`, `tests/worker/test_classify_activity_event.py`.

- [ ] **Step 1: Add the tests** (append to `tests/worker/test_classify_activity_event.py`)

```python
def test_classify_activity_event_resolves_ownership_for_a_new_event(monkeypatch):
    repository = InMemoryEventRepository()
    monkeypatch.setattr(task_module, "get_event_classifier", lambda: EventClassifier(repository))

    resolved_events = []

    class _FakeOwnershipResolver:
        async def resolve(self, event):
            resolved_events.append(event)
            return []

    monkeypatch.setattr(task_module, "get_ownership_resolver", lambda: _FakeOwnershipResolver())

    task_module.classify_activity_event("check_run", _check_run_payload())

    assert len(resolved_events) == 1
    assert resolved_events[0].sha == "abc123"


def test_classify_activity_event_skips_ownership_resolution_when_nothing_classified(monkeypatch):
    repository = InMemoryEventRepository()
    monkeypatch.setattr(task_module, "get_event_classifier", lambda: EventClassifier(repository))

    def _fail():
        raise AssertionError("ownership resolver should not be constructed when nothing classified")

    monkeypatch.setattr(task_module, "get_ownership_resolver", _fail)

    payload = _check_run_payload()
    payload["check_run"]["conclusion"] = "success"
    task_module.classify_activity_event("check_run", payload)
```

Run: `docker compose run --rm app pytest tests/worker/test_classify_activity_event.py -v`
Expected: 2 new tests fail with `AttributeError: module 'mergency.worker.classify_activity_event' has no attribute 'get_ownership_resolver'`; existing tests still pass.

- [ ] **Step 2: Implement** — modify `src/mergency/worker/classify_activity_event.py`:

```python
# src/mergency/worker/classify_activity_event.py
import asyncio
import logging

from mergency.adapters.github.check_run_signal_parser import parse_check_run_signal
from mergency.adapters.github.push_signal_parser import parse_push_signal
from mergency.api.deps import get_event_classifier, get_ownership_resolver
from mergency.worker.celery_app import celery_app

logger = logging.getLogger(__name__)

_PARSERS = {
    "check_run": parse_check_run_signal,
    "push": parse_push_signal,
}


@celery_app.task(name="classify_activity_event")
def classify_activity_event(event_type: str, payload: dict) -> None:
    parser = _PARSERS.get(event_type)
    if parser is None:
        logger.warning("no signal parser registered", extra={"event_type": event_type})
        return

    try:
        signal = parser(payload)
    except KeyError as error:
        logger.warning(
            "activity payload missing expected field, dropped",
            extra={"event_type": event_type, "missing_field": str(error)},
        )
        return

    asyncio.run(_classify_and_resolve_ownership(signal))


async def _classify_and_resolve_ownership(signal) -> None:
    event = await get_event_classifier().classify(signal)
    if event is not None:
        await get_ownership_resolver().resolve(event)
```

Run: `docker compose run --rm app pytest tests/worker/test_classify_activity_event.py -v`
Expected: 6 passed (4 original + 2 new).

- [ ] **Step 3:** commit: `feat: resolve ownership after classifying an activity event`.

---

## Verification (full suite, after all tasks)

1. Full suite: `docker compose run --rm app pytest -v` — all tests pass, old and new.
2. Lint: `docker compose run --rm app ruff check src tests` — no errors.
3. Domain purity: `docker compose run --rm app grep -rniE "celery|fastapi|sqlalchemy" src/mergency/domain/` — no matches. (`pygithub`/`github` is intentionally *not* in this grep — `domain/ports/*.py` are pure `Protocol`s with no `github` import; verify separately with `grep -rn "^from github\|^import github" src/mergency/domain/` — no matches.)
4. Individual-vs-team guardrail containment: `docker compose run --rm app grep -rn '"TEAM"' src/mergency/domain/` — matches only `ownership_resolver.py` (confirms the guardrail lives in exactly one place, per ADR 0006).
5. `git diff` on `tests/adapters/memory/test_event_repository.py`, `tests/api/test_deps.py`, and `tests/worker/test_classify_activity_event.py` shows only additive test functions — no existing test bodies changed.
6. Manual smoke (optional, not part of CI): `docker compose up -d`, send a signed `check_run` webhook (`conclusion: failure`, default branch) for a real installation/repo with a `CODEOWNERS` file, confirm the worker logs no errors and the resulting event (inspectable via a REPL against `InMemoryEventRepository`, or a temporary debug endpoint) carries a real team owner instead of `None`.
