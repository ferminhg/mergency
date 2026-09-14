# CODEOWNERS-based ownership resolution — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Tracks:** [GitHub issue #13](https://github.com/ferminhg/mergency/issues/13). Design: `docs/adr/0006-codeowners-ownership-resolution.md`.

**Goal:** Turn a classified, unowned `Event` (`owner=None`, from ADR 0005) into one or more persisted `Event` rows carrying a real team owner, using the repo's `CODEOWNERS` file with a tenant-configured default-team fallback, per ADR 0006 — while enforcing the non-negotiable rule that an individual can never become a stored owner.

**Architecture:** Five new pieces slot into the existing hexagonal layout: `TenantConfig`/`ConfigResolver` (reads `mergency.yml`), `CodeownersProvider` (fetches+parses+caches `CODEOWNERS`), `ChangedFilesProvider` (Commits API, build_failure only), and `OwnershipResolver` (pure domain logic: guardrail + fan-out). `EventClassifier` stops persisting (becomes pure); the Celery task orchestrates classify → resolve changed files → resolve config → resolve owners → persist N owned rows.

**Tech Stack:** Same as the rest of the repo — Python, PyGithub, pydantic-settings, Celery/pytest — plus two new runtime dependencies: `pyyaml` (parse `mergency.yml`) and `codeowners` (gitignore-style CODEOWNERS matching, last-match-wins).

**IMPORTANT — final destination of this plan:** per `CLAUDE.md`'s "Plans as code" convention, once this plan is approved it must be committed to the repo at `docs/plan/0010-codeowners-ownership-resolution.md` (next number after `docs/plan/0009-event-classification.md`) with `## Status: proposed`, updated to `implemented` once all tasks land.

---

## Status

proposed

## Context

ADR 0005 classified raw webhooks into `Event` records but deliberately left `owner` as `None` — ownership resolution was explicitly out of scope, tracked as ADR 0006. That ADR is now ready to implement (issue #13). It introduces the "Ownership resolver" stage from `ARQUITECTURE.md`'s pipeline: `CODEOWNERS` + a tenant-configured default team, with one hard product constraint carried through every design choice — **budgets are team-scoped only; an individual (`@user`) can never become a stored owner.**

Two decisions were made with the user before finalizing this plan (both affect scope directly):

1. **CODEOWNERS cache: in-memory TTL, not Redis.** The ADR says the parsed CODEOWNERS ruleset should live "in Redis, next to the installation-token cache" — but the installation-token cache is actually an in-process dict (an accepted ADR 0004 simplification), no Redis client exists anywhere in the codebase yet, and `docker-compose.yml` doesn't even have a `redis` service. `TenantConfigRepository`, introduced by this same ADR, is itself "in-memory for now". Introducing a real Redis client is meaningful new infra work that (per `CLAUDE.md`) deserves its own plan, not a rider on this one. This plan implements the cache as an in-process `dict` + TTL, matching the codebase's existing precedent everywhere else, and defers a real Redis-backed cache to a future plan when it's actually needed.
2. **`EventClassifier` becomes pure; persistence moves after ownership resolution.** Today `EventClassifier.classify()` persists an `Event` immediately with `owner=None` (`EventRepository.save_if_new`, deduped on `(installation_id, repo, sha, event_type)`). Fanning one classified event into N owned rows requires the dedupe key to include `owner` — otherwise the second/third owned row is rejected as a "duplicate" of the first. Rather than bolt an owner-reconciliation method onto the repository and leave permanent `owner=None` rows behind, `EventClassifier.classify()` becomes a pure function (no repository dependency, returns `Event | None`), and the Celery task persists only the final, fully-owned `Event` rows. This changes `EventClassifier`'s existing (ADR 0005/plan 0009) contract and touches its already-passing test suite — that's expected and is the correct fix, not scope creep.

A few implementation details the ADR leaves open, decided here directly (straightforward engineering calls, not user-facing tradeoffs):

- **No CODEOWNERS match at all** (empty file, or file present but no pattern matches the path) is treated the same as "matched entry is an individual" — both fall back to `default_team`. The ADR only names the individual-vs-team case explicitly, but the same non-negotiable "never leave an event unowned" reasoning applies to the unmatched case.
- **Hardcoded config defaults** (used when `mergency.yml` is absent or invalid): `rolling_window_days=28`, `max_events_per_window=5` (matching README's example values), `default_team="unassigned"` (no universal sensible default team name exists).
- **Changed files, per event type:** for `revert` (push), the files come straight off the push webhook's own commit payload (`added`/`removed`/`modified` — no extra API call needed); for `build_failure` (check_run), there's no file list on the webhook, so a new `ChangedFilesProvider` port calls the Commits API (`GET /repos/{owner}/{repo}/commits/{sha}`) — this part isn't cached (the ADR doesn't call for it, and it isn't yet a measured bottleneck).
- **Token-fetch failures** (`TokenFetchError`, still open per ADR 0004's gap #2 — "the first real caller of `get_token()` must decide") — this ADR's adapters (`CodeownersProvider`'s backing `RepositoryContentProvider`, `ChangedFilesProvider`) are that first real caller. Decision: let `TokenFetchError` propagate uncaught out of the Celery task. This matches the existing task's style (only specific parse errors are caught; everything else propagates as a visible Celery task failure) — simplest correct choice, no silent data loss.

## Design decisions

**1. Two shared "fetch a file from a repo" concerns, one port.** Both `mergency.yml` (for `ConfigResolver`) and `CODEOWNERS` (for the `CodeownersProvider` adapter, which checks 3 well-known locations) need "get this file's raw text from a repo via GitHub's Contents API, or `None` if it doesn't exist". One new port, `RepositoryContentProvider` (`domain/ports/repository_content_provider.py`), with one adapter (`adapters/github/repository_content_provider.py`) backing both. Keeps PyGithub and 404-handling (`UnknownObjectException`) in exactly one place.

**2. Where CODEOWNERS parsing/caching lives vs. where the guardrail lives.** Per the ADR: parsing (via the `codeowners` PyPI package, which already implements gitignore-style last-match-wins semantics — confirmed by reading its source, `CodeOwners(text).of(path) -> list[tuple[Literal["TEAM","USERNAME","EMAIL"], str]]`) and the in-memory TTL cache live in the **adapter** (`adapters/github/codeowners_provider.py`). The individual-vs-team guardrail and the "fan out to N rows" decision live in the **domain** (`domain/ownership_resolver.py`) — this is where the ADR explicitly says the check must live ("this check happens in one place... so no downstream component needs to re-implement or even be aware of this rule"). The port (`domain/ports/codeowners_provider.py`) is the seam: it returns raw `(type, name)` tuples, not pre-filtered team names, so the guardrail logic stays testable in the domain without any GitHub/adapter involvement.

**3. `OwnershipResolver` shape.** One entry point, pure (only depends on the `CodeownersProvider` port):
```python
class OwnershipResolver:
    def __init__(self, codeowners_provider: CodeownersProvider) -> None: ...
    async def resolve_owners(
        self, installation_id: int, repo: str, changed_files: list[str], default_team: str
    ) -> list[str]: ...
```
Iterates `changed_files`, collects every `TEAM`-typed owner across all of them into a set (dedup — the same team owning two changed files must not produce two rows), discards `USERNAME`/`EMAIL` matches (logging that the fallback happened, for operator visibility per the ADR). Returns `[default_team]` if the resulting set is empty (covers both "matched but individual" and "no match at all"), otherwise the sorted team list. Always returns at least one owner — callers never need to handle "no owner at all".

**4. `ConfigResolver` shape and where it fits.** `TenantConfigRepository` (`get`/`upsert`, mirroring the existing `TenantRepository`/`InMemoryTenantRepository` shape exactly) is the source of truth other future components (ADR 0007's budget calculator) will read from directly. `ConfigResolver` is the thing that *populates* it: fetches `mergency.yml` via `RepositoryContentProvider`, parses with `pyyaml` (parsing itself is domain logic per the ADR — "no framework imports beyond what's needed to read repo content through the existing GitHub adapter boundary" — so `import yaml` in `domain/config_resolver.py` is fine, it's just not FastAPI/Celery/SQLAlchemy/PyGithub), falls back field-by-field to hardcoded defaults on a missing file, invalid YAML, or a missing key, and `upsert`s the resolved `TenantConfig` before returning it. Every classified event re-resolves config fresh (no caching here — simplest correct thing per the ADR, revisit only if it becomes a measured bottleneck, same reasoning ADR 0007 already applies elsewhere in this codebase).

**5. Fan-out requires the `EventRepository` dedupe key to include `owner`.** `save_if_new(event)`'s internal key becomes `(installation_id, repo, sha, event_type, owner)` — no signature change, since `owner` is already a field on the `Event` passed in. `get(...)` does gain a required 5th parameter (`owner: str`), because under the new pure-classifier design **no event with `owner=None` is ever stored** — every persisted row has a real, resolved team name, so "get the event for this raw `(installation_id, repo, sha, event_type)`" is inherently ambiguous once fan-out can produce multiple rows for it; the caller must say which owner's row it wants. This is a breaking change to an already-tested port/adapter — expected, tests are updated in the same task.

**6. Orchestration lives in the existing Celery task, not a new domain "service" wrapper.** `worker/classify_activity_event.py` already is "the driving adapter that does parse → classify → persist" (plan 0009's words). It grows to parse → classify (now pure) → determine changed files (from the push commit directly, or via `ChangedFilesProvider` for build_failure) → resolve config → resolve owners → persist each owned `Event` via `save_if_new`. No new "OwnershipService" abstraction — the task function is the composition root, exactly like today, just doing one more step. Redelivered webhooks redo the CODEOWNERS/config/changed-files work (not free, but cheap and cached where it matters), but `save_if_new`'s owner-aware key still prevents duplicate storage — accepted, matches this codebase's existing "revisit only if it's a measured bottleneck" philosophy.

## Directory structure (new/changed files)

```
src/mergency/
├── domain/
│   ├── models/
│   │   ├── tenant_config.py             # NEW: TenantConfig
│   │   └── push_commit.py               # MODIFIED: + files: list[str]
│   ├── ports/
│   │   ├── tenant_config_repository.py  # NEW
│   │   ├── repository_content_provider.py  # NEW
│   │   ├── codeowners_provider.py       # NEW
│   │   ├── changed_files_provider.py    # NEW
│   │   └── event_repository.py          # MODIFIED: get() gains owner param
│   ├── config_resolver.py               # NEW: ConfigResolver
│   ├── ownership_resolver.py            # NEW: OwnershipResolver
│   └── event_classifier.py              # MODIFIED: no longer persists, pure
├── adapters/
│   ├── memory/
│   │   ├── tenant_config_repository.py  # NEW: InMemoryTenantConfigRepository
│   │   └── event_repository.py          # MODIFIED: owner-aware dedupe key
│   └── github/
│       ├── repository_content_provider.py  # NEW: GithubRepositoryContentProvider
│       ├── codeowners_provider.py          # NEW: GithubCodeownersProvider (+ TTL cache)
│       ├── changed_files_provider.py       # NEW: GithubChangedFilesProvider
│       └── push_signal_parser.py           # MODIFIED: populate commit.files
├── worker/
│   └── classify_activity_event.py       # MODIFIED: orchestrate resolve + persist
└── api/
    └── deps.py                          # MODIFIED: new factories

tests/  (mirrors src/, one test file per new/changed module — see tasks below)
pyproject.toml                           # MODIFIED: + pyyaml, + codeowners
```

---

## Task 1: Add `pyyaml` and `codeowners` dependencies

**Files:** Modify `pyproject.toml`.

- [ ] **Step 1:** Add to `[project].dependencies` in `pyproject.toml`:

```toml
    "pyyaml>=6.0",
    "codeowners>=0.9",
```

(alongside the existing `fastapi`, `pydantic-settings`, `pygithub`, `celery`, `uvicorn[standard]` entries)

- [ ] **Step 2: Regenerate the lock file and rebuild the image** — dependency changes need a `uv.lock` update and an image rebuild, done through Docker per `CLAUDE.md` (no bare `uv`/`pip` on the host):

```bash
docker compose run --rm -v "$(pwd):/app" app uv lock
docker compose build app
```

Expected: `uv.lock` on the host now lists `pyyaml` and `codeowners`; the image build succeeds.

- [ ] **Step 3: Verify the packages are importable inside the container:**

```bash
docker compose run --rm app python -c "import yaml, codeowners; print(codeowners.CodeOwners)"
```

Expected: prints `<class 'codeowners.CodeOwners'>` with no import error.

- [ ] **Step 4:** commit: `chore: add pyyaml and codeowners dependencies`.

---

## Task 2: `TenantConfig` domain model

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


def _config(installation_id: int = 1, default_team: str = "team-a") -> TenantConfig:
    return TenantConfig(
        installation_id=installation_id,
        rolling_window_days=28,
        default_team=default_team,
        max_events_per_window=5,
    )


async def test_upsert_then_get_returns_the_stored_config():
    repository = InMemoryTenantConfigRepository()

    await repository.upsert(_config())

    assert await repository.get(1) == _config()


async def test_upsert_overwrites_the_previous_config():
    repository = InMemoryTenantConfigRepository()
    await repository.upsert(_config(default_team="team-a"))

    await repository.upsert(_config(default_team="team-b"))

    stored = await repository.get(1)
    assert stored is not None
    assert stored.default_team == "team-b"


async def test_get_returns_none_when_absent():
    repository = InMemoryTenantConfigRepository()

    assert await repository.get(999) is None
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

## Task 4: `RepositoryContentProvider` port + GitHub adapter

**Files:** Create `tests/adapters/github/test_repository_content_provider.py`, `src/mergency/domain/ports/repository_content_provider.py`, `src/mergency/adapters/github/repository_content_provider.py`.

- [ ] **Step 1: Write the test**

```python
# tests/adapters/github/test_repository_content_provider.py
from unittest.mock import MagicMock

from github.GithubException import UnknownObjectException

from mergency.adapters.github.repository_content_provider import GithubRepositoryContentProvider


class _StubTokenProvider:
    async def get_token(self, installation_id: int) -> str:
        return "test-token"


def _provider() -> GithubRepositoryContentProvider:
    return GithubRepositoryContentProvider(_StubTokenProvider())


async def test_get_file_returns_decoded_content(monkeypatch):
    provider = _provider()
    content_file = MagicMock()
    content_file.decoded_content = b"rolling_window_days: 14\n"
    client = MagicMock()
    client.get_repo.return_value.get_contents.return_value = content_file
    monkeypatch.setattr(
        "mergency.adapters.github.repository_content_provider.Github", lambda **kwargs: client
    )

    text = await provider.get_file(1, "acme/widgets", "mergency.yml")

    assert text == "rolling_window_days: 14\n"
    client.get_repo.assert_called_once_with("acme/widgets")
    client.get_repo.return_value.get_contents.assert_called_once_with("mergency.yml")


async def test_get_file_returns_none_when_missing(monkeypatch):
    provider = _provider()
    client = MagicMock()
    client.get_repo.return_value.get_contents.side_effect = UnknownObjectException(
        404, data="Not Found"
    )
    monkeypatch.setattr(
        "mergency.adapters.github.repository_content_provider.Github", lambda **kwargs: client
    )

    text = await provider.get_file(1, "acme/widgets", "mergency.yml")

    assert text is None
```

Run: `docker compose run --rm app pytest tests/adapters/github/test_repository_content_provider.py -v`
Expected: fails with `ModuleNotFoundError`.

- [ ] **Step 2: Implement**

```python
# src/mergency/domain/ports/repository_content_provider.py
from typing import Protocol


class RepositoryContentProvider(Protocol):
    async def get_file(self, installation_id: int, repo: str, path: str) -> str | None: ...
```

```python
# src/mergency/adapters/github/repository_content_provider.py
import asyncio

from github import Auth, Github
from github.GithubException import UnknownObjectException

from mergency.domain.ports.installation_token_provider import InstallationTokenProvider


class GithubRepositoryContentProvider:
    def __init__(self, token_provider: InstallationTokenProvider) -> None:
        self._token_provider = token_provider

    async def get_file(self, installation_id: int, repo: str, path: str) -> str | None:
        token = await self._token_provider.get_token(installation_id)
        client = Github(auth=Auth.Token(token))

        def _fetch():
            return client.get_repo(repo).get_contents(path)

        try:
            content_file = await asyncio.to_thread(_fetch)
        except UnknownObjectException:
            return None
        return content_file.decoded_content.decode("utf-8")
```

Run: `docker compose run --rm app pytest tests/adapters/github/test_repository_content_provider.py -v`
Expected: 2 passed.

- [ ] **Step 3:** commit: `feat: add RepositoryContentProvider port and GitHub adapter`.

---

## Task 5: `ConfigResolver` domain service

**Files:** Create `tests/domain/test_config_resolver.py`, `src/mergency/domain/config_resolver.py`.

- [ ] **Step 1: Write the test**

```python
# tests/domain/test_config_resolver.py
from mergency.adapters.memory.tenant_config_repository import InMemoryTenantConfigRepository
from mergency.domain.config_resolver import ConfigResolver


class _StubContentProvider:
    def __init__(self, content: str | None) -> None:
        self._content = content

    async def get_file(self, installation_id, repo, path):
        return self._content


async def test_resolves_config_from_valid_yaml():
    resolver = ConfigResolver(
        _StubContentProvider(
            "rolling_window_days: 14\ndefault_team: platform-team\nbudget:\n  max_events_per_window: 3\n"
        ),
        InMemoryTenantConfigRepository(),
    )

    config = await resolver.resolve(1, "acme/widgets")

    assert config.installation_id == 1
    assert config.rolling_window_days == 14
    assert config.default_team == "platform-team"
    assert config.max_events_per_window == 3


async def test_falls_back_to_defaults_when_file_is_absent():
    resolver = ConfigResolver(_StubContentProvider(None), InMemoryTenantConfigRepository())

    config = await resolver.resolve(1, "acme/widgets")

    assert config.rolling_window_days == 28
    assert config.default_team == "unassigned"
    assert config.max_events_per_window == 5


async def test_falls_back_to_defaults_when_yaml_is_invalid():
    resolver = ConfigResolver(
        _StubContentProvider("not: valid: yaml: ["), InMemoryTenantConfigRepository()
    )

    config = await resolver.resolve(1, "acme/widgets")

    assert config.default_team == "unassigned"


async def test_missing_budget_section_uses_default_max_events():
    resolver = ConfigResolver(
        _StubContentProvider("rolling_window_days: 10\ndefault_team: team-x\n"),
        InMemoryTenantConfigRepository(),
    )

    config = await resolver.resolve(1, "acme/widgets")

    assert config.max_events_per_window == 5


async def test_resolve_persists_config_into_repository():
    repository = InMemoryTenantConfigRepository()
    resolver = ConfigResolver(_StubContentProvider(None), repository)

    config = await resolver.resolve(1, "acme/widgets")

    assert await repository.get(1) == config
```

Run: `docker compose run --rm app pytest tests/domain/test_config_resolver.py -v`
Expected: fails with `ModuleNotFoundError`.

- [ ] **Step 2: Implement**

```python
# src/mergency/domain/config_resolver.py
import yaml

from mergency.domain.models.tenant_config import TenantConfig
from mergency.domain.ports.repository_content_provider import RepositoryContentProvider
from mergency.domain.ports.tenant_config_repository import TenantConfigRepository

_CONFIG_PATH = "mergency.yml"
_DEFAULT_ROLLING_WINDOW_DAYS = 28
_DEFAULT_TEAM = "unassigned"
_DEFAULT_MAX_EVENTS_PER_WINDOW = 5


class ConfigResolver:
    def __init__(
        self,
        repository_content_provider: RepositoryContentProvider,
        tenant_config_repository: TenantConfigRepository,
    ) -> None:
        self._repository_content_provider = repository_content_provider
        self._tenant_config_repository = tenant_config_repository

    async def resolve(self, installation_id: int, repo: str) -> TenantConfig:
        text = await self._repository_content_provider.get_file(
            installation_id, repo, _CONFIG_PATH
        )
        config = _parse(installation_id, text)
        await self._tenant_config_repository.upsert(config)
        return config


def _parse(installation_id: int, text: str | None) -> TenantConfig:
    data: dict = {}
    if text is not None:
        try:
            loaded = yaml.safe_load(text)
            if isinstance(loaded, dict):
                data = loaded
        except yaml.YAMLError:
            data = {}

    budget = data.get("budget")
    budget = budget if isinstance(budget, dict) else {}

    return TenantConfig(
        installation_id=installation_id,
        rolling_window_days=data.get("rolling_window_days", _DEFAULT_ROLLING_WINDOW_DAYS),
        default_team=data.get("default_team", _DEFAULT_TEAM),
        max_events_per_window=budget.get("max_events_per_window", _DEFAULT_MAX_EVENTS_PER_WINDOW),
    )
```

Run: `docker compose run --rm app pytest tests/domain/test_config_resolver.py -v`
Expected: 5 passed.

- [ ] **Step 3:** commit: `feat: add ConfigResolver domain service`.

---

## Task 6: `CodeownersProvider` port + GitHub adapter (with in-memory TTL cache)

**Files:** Create `tests/adapters/github/test_codeowners_provider.py`, `src/mergency/domain/ports/codeowners_provider.py`, `src/mergency/adapters/github/codeowners_provider.py`.

- [ ] **Step 1: Write the test**

```python
# tests/adapters/github/test_codeowners_provider.py
from mergency.adapters.github.codeowners_provider import GithubCodeownersProvider


class _StubContentProvider:
    def __init__(self, files: dict[str, str]) -> None:
        self._files = files
        self.requested_paths: list[str] = []

    async def get_file(self, installation_id, repo, path):
        self.requested_paths.append(path)
        return self._files.get(path)


async def test_parses_codeowners_from_root_location():
    content_provider = _StubContentProvider({"CODEOWNERS": "*.py @org/team-a\n"})
    provider = GithubCodeownersProvider(content_provider)

    owners = await provider.owners_for(1, "acme/widgets", "src/a.py")

    assert owners == [("TEAM", "@org/team-a")]


async def test_falls_back_to_github_directory_location():
    content_provider = _StubContentProvider({".github/CODEOWNERS": "*.py @org/team-b\n"})
    provider = GithubCodeownersProvider(content_provider)

    owners = await provider.owners_for(1, "acme/widgets", "src/a.py")

    assert owners == [("TEAM", "@org/team-b")]
    assert content_provider.requested_paths == ["CODEOWNERS", ".github/CODEOWNERS"]


async def test_falls_back_to_docs_directory_location():
    content_provider = _StubContentProvider({"docs/CODEOWNERS": "*.py @org/team-c\n"})
    provider = GithubCodeownersProvider(content_provider)

    owners = await provider.owners_for(1, "acme/widgets", "src/a.py")

    assert owners == [("TEAM", "@org/team-c")]


async def test_returns_empty_list_when_no_codeowners_file_exists():
    provider = GithubCodeownersProvider(_StubContentProvider({}))

    owners = await provider.owners_for(1, "acme/widgets", "src/a.py")

    assert owners == []


async def test_caches_parsed_rules_across_calls_for_the_same_repo():
    content_provider = _StubContentProvider({"CODEOWNERS": "*.py @org/team-a\n"})
    provider = GithubCodeownersProvider(content_provider)

    await provider.owners_for(1, "acme/widgets", "src/a.py")
    await provider.owners_for(1, "acme/widgets", "src/b.py")

    assert content_provider.requested_paths == ["CODEOWNERS"]


async def test_different_repos_are_cached_independently():
    content_provider = _StubContentProvider({"CODEOWNERS": "*.py @org/team-a\n"})
    provider = GithubCodeownersProvider(content_provider)

    await provider.owners_for(1, "acme/widgets", "src/a.py")
    await provider.owners_for(1, "acme/other", "src/a.py")

    assert content_provider.requested_paths == ["CODEOWNERS", "CODEOWNERS"]


async def test_refetches_after_the_ttl_expires(monkeypatch):
    content_provider = _StubContentProvider({"CODEOWNERS": "*.py @org/team-a\n"})
    provider = GithubCodeownersProvider(content_provider)
    current_time = [1000.0]
    monkeypatch.setattr(
        "mergency.adapters.github.codeowners_provider.time.monotonic", lambda: current_time[0]
    )

    await provider.owners_for(1, "acme/widgets", "src/a.py")
    current_time[0] += 301
    await provider.owners_for(1, "acme/widgets", "src/a.py")

    assert content_provider.requested_paths == ["CODEOWNERS", "CODEOWNERS"]
```

Run: `docker compose run --rm app pytest tests/adapters/github/test_codeowners_provider.py -v`
Expected: fails with `ModuleNotFoundError`.

- [ ] **Step 2: Implement**

```python
# src/mergency/domain/ports/codeowners_provider.py
from typing import Protocol


class CodeownersProvider(Protocol):
    async def owners_for(
        self, installation_id: int, repo: str, path: str
    ) -> list[tuple[str, str]]: ...
```

```python
# src/mergency/adapters/github/codeowners_provider.py
import time

from codeowners import CodeOwners

from mergency.domain.ports.repository_content_provider import RepositoryContentProvider

_CODEOWNERS_PATHS = ("CODEOWNERS", ".github/CODEOWNERS", "docs/CODEOWNERS")
_CACHE_TTL_SECONDS = 300.0


class GithubCodeownersProvider:
    def __init__(self, repository_content_provider: RepositoryContentProvider) -> None:
        self._repository_content_provider = repository_content_provider
        self._cache: dict[tuple[int, str], tuple[CodeOwners, float]] = {}

    async def owners_for(
        self, installation_id: int, repo: str, path: str
    ) -> list[tuple[str, str]]:
        rules = await self._rules_for(installation_id, repo)
        return rules.of(path)

    async def _rules_for(self, installation_id: int, repo: str) -> CodeOwners:
        key = (installation_id, repo)
        cached = self._cache.get(key)
        now = time.monotonic()
        if cached is not None and cached[1] > now:
            return cached[0]

        text = await self._fetch_codeowners_text(installation_id, repo)
        rules = CodeOwners(text or "")
        self._cache[key] = (rules, now + _CACHE_TTL_SECONDS)
        return rules

    async def _fetch_codeowners_text(self, installation_id: int, repo: str) -> str | None:
        for path in _CODEOWNERS_PATHS:
            content = await self._repository_content_provider.get_file(
                installation_id, repo, path
            )
            if content is not None:
                return content
        return None
```

Run: `docker compose run --rm app pytest tests/adapters/github/test_codeowners_provider.py -v`
Expected: 7 passed.

- [ ] **Step 3:** commit: `feat: add CodeownersProvider port and GitHub adapter with TTL cache`.

---

## Task 7: `ChangedFilesProvider` port + GitHub adapter

**Files:** Create `tests/adapters/github/test_changed_files_provider.py`, `src/mergency/domain/ports/changed_files_provider.py`, `src/mergency/adapters/github/changed_files_provider.py`.

- [ ] **Step 1: Write the test**

```python
# tests/adapters/github/test_changed_files_provider.py
from unittest.mock import MagicMock

from mergency.adapters.github.changed_files_provider import GithubChangedFilesProvider


class _StubTokenProvider:
    async def get_token(self, installation_id: int) -> str:
        return "test-token"


async def test_returns_filenames_from_the_commit(monkeypatch):
    provider = GithubChangedFilesProvider(_StubTokenProvider())
    file_a = MagicMock(filename="src/a.py")
    file_b = MagicMock(filename="src/b.py")
    client = MagicMock()
    client.get_repo.return_value.get_commit.return_value.files = [file_a, file_b]
    monkeypatch.setattr(
        "mergency.adapters.github.changed_files_provider.Github", lambda **kwargs: client
    )

    files = await provider.files_changed_in_commit(1, "acme/widgets", "abc123")

    assert files == ["src/a.py", "src/b.py"]
    client.get_repo.assert_called_once_with("acme/widgets")
    client.get_repo.return_value.get_commit.assert_called_once_with("abc123")
```

Run: `docker compose run --rm app pytest tests/adapters/github/test_changed_files_provider.py -v`
Expected: fails with `ModuleNotFoundError`.

- [ ] **Step 2: Implement**

```python
# src/mergency/domain/ports/changed_files_provider.py
from typing import Protocol


class ChangedFilesProvider(Protocol):
    async def files_changed_in_commit(
        self, installation_id: int, repo: str, sha: str
    ) -> list[str]: ...
```

```python
# src/mergency/adapters/github/changed_files_provider.py
import asyncio

from github import Auth, Github

from mergency.domain.ports.installation_token_provider import InstallationTokenProvider


class GithubChangedFilesProvider:
    def __init__(self, token_provider: InstallationTokenProvider) -> None:
        self._token_provider = token_provider

    async def files_changed_in_commit(
        self, installation_id: int, repo: str, sha: str
    ) -> list[str]:
        token = await self._token_provider.get_token(installation_id)
        client = Github(auth=Auth.Token(token))

        def _fetch() -> list[str]:
            commit = client.get_repo(repo).get_commit(sha)
            return [f.filename for f in commit.files]

        return await asyncio.to_thread(_fetch)
```

Run: `docker compose run --rm app pytest tests/adapters/github/test_changed_files_provider.py -v`
Expected: 1 passed.

- [ ] **Step 3:** commit: `feat: add ChangedFilesProvider port and GitHub adapter`.

---

## Task 8: `OwnershipResolver` domain service

**Files:** Create `tests/domain/test_ownership_resolver.py`, `src/mergency/domain/ownership_resolver.py`.

- [ ] **Step 1: Write the test**

```python
# tests/domain/test_ownership_resolver.py
from mergency.domain.ownership_resolver import OwnershipResolver


class _StubCodeownersProvider:
    def __init__(self, owners_by_path: dict[str, list[tuple[str, str]]]) -> None:
        self._owners_by_path = owners_by_path

    async def owners_for(self, installation_id, repo, path):
        return self._owners_by_path.get(path, [])


async def test_resolves_a_single_team_owner():
    resolver = OwnershipResolver(
        _StubCodeownersProvider({"src/a.py": [("TEAM", "@org/team-a")]})
    )

    owners = await resolver.resolve_owners(1, "acme/widgets", ["src/a.py"], "unassigned")

    assert owners == ["@org/team-a"]


async def test_fans_out_to_multiple_distinct_team_owners():
    resolver = OwnershipResolver(
        _StubCodeownersProvider(
            {
                "src/a.py": [("TEAM", "@org/team-a")],
                "src/b.py": [("TEAM", "@org/team-b")],
            }
        )
    )

    owners = await resolver.resolve_owners(
        1, "acme/widgets", ["src/a.py", "src/b.py"], "unassigned"
    )

    assert owners == ["@org/team-a", "@org/team-b"]


async def test_deduplicates_the_same_team_matched_by_multiple_files():
    resolver = OwnershipResolver(
        _StubCodeownersProvider(
            {
                "src/a.py": [("TEAM", "@org/team-a")],
                "src/b.py": [("TEAM", "@org/team-a")],
            }
        )
    )

    owners = await resolver.resolve_owners(
        1, "acme/widgets", ["src/a.py", "src/b.py"], "unassigned"
    )

    assert owners == ["@org/team-a"]


async def test_individual_match_falls_back_to_default_team():
    resolver = OwnershipResolver(
        _StubCodeownersProvider({"src/a.py": [("USERNAME", "@someuser")]})
    )

    owners = await resolver.resolve_owners(1, "acme/widgets", ["src/a.py"], "unassigned")

    assert owners == ["unassigned"]


async def test_email_match_also_falls_back_to_default_team():
    resolver = OwnershipResolver(
        _StubCodeownersProvider({"src/a.py": [("EMAIL", "docs@example.com")]})
    )

    owners = await resolver.resolve_owners(1, "acme/widgets", ["src/a.py"], "unassigned")

    assert owners == ["unassigned"]


async def test_no_match_falls_back_to_default_team():
    resolver = OwnershipResolver(_StubCodeownersProvider({}))

    owners = await resolver.resolve_owners(1, "acme/widgets", ["src/unmatched.py"], "unassigned")

    assert owners == ["unassigned"]


async def test_mixed_team_and_individual_matches_keep_only_the_team():
    resolver = OwnershipResolver(
        _StubCodeownersProvider(
            {"src/a.py": [("TEAM", "@org/team-a"), ("USERNAME", "@someuser")]}
        )
    )

    owners = await resolver.resolve_owners(1, "acme/widgets", ["src/a.py"], "unassigned")

    assert owners == ["@org/team-a"]
```

Run: `docker compose run --rm app pytest tests/domain/test_ownership_resolver.py -v`
Expected: fails with `ModuleNotFoundError`.

- [ ] **Step 2: Implement**

```python
# src/mergency/domain/ownership_resolver.py
import logging

from mergency.domain.ports.codeowners_provider import CodeownersProvider

logger = logging.getLogger(__name__)


class OwnershipResolver:
    def __init__(self, codeowners_provider: CodeownersProvider) -> None:
        self._codeowners_provider = codeowners_provider

    async def resolve_owners(
        self, installation_id: int, repo: str, changed_files: list[str], default_team: str
    ) -> list[str]:
        teams: set[str] = set()
        for path in changed_files:
            for owner_type, owner_name in await self._codeowners_provider.owners_for(
                installation_id, repo, path
            ):
                if owner_type == "TEAM":
                    teams.add(owner_name)
                else:
                    logger.info(
                        "non-team CODEOWNERS entry discarded, falling back to default team",
                        extra={
                            "installation_id": installation_id,
                            "repo": repo,
                            "path": path,
                            "owner": owner_name,
                        },
                    )

        if not teams:
            return [default_team]
        return sorted(teams)
```

Run: `docker compose run --rm app pytest tests/domain/test_ownership_resolver.py -v`
Expected: 7 passed.

- [ ] **Step 3:** commit: `feat: add OwnershipResolver domain service`.

---

## Task 9: `PushCommit` gains `files`; `push_signal_parser` populates it

**Files:** Modify `src/mergency/domain/models/push_commit.py`, `src/mergency/adapters/github/push_signal_parser.py`, `tests/adapters/github/test_push_signal_parser.py`.

- [ ] **Step 1: Update the test** (append to `tests/adapters/github/test_push_signal_parser.py`, alongside the existing tests):

```python
def test_parses_commit_added_removed_and_modified_files():
    payload = {
        "ref": "refs/heads/main",
        "repository": {"full_name": "acme/widgets", "default_branch": "main"},
        "installation": {"id": 1},
        "commits": [
            {
                "id": "sha1",
                "message": "fix bug",
                "timestamp": "2026-09-14T10:00:00Z",
                "added": ["src/new.py"],
                "removed": ["src/old.py"],
                "modified": ["src/changed.py"],
            }
        ],
    }

    signal = parse_push_signal(payload)

    assert signal.commits[0].files == ["src/new.py", "src/old.py", "src/changed.py"]
```

Run: `docker compose run --rm app pytest tests/adapters/github/test_push_signal_parser.py -v`
Expected: the existing tests still pass; the new test fails with `AttributeError: 'PushCommit' object has no attribute 'files'` or a `KeyError` inside the parser (whichever the current implementation hits first).

- [ ] **Step 2: Implement** — modify `src/mergency/domain/models/push_commit.py`:

```python
# src/mergency/domain/models/push_commit.py
from dataclasses import dataclass, field
from datetime import datetime


@dataclass(frozen=True)
class PushCommit:
    sha: str
    message: str
    timestamp: datetime
    files: list[str] = field(default_factory=list)
```

Modify `src/mergency/adapters/github/push_signal_parser.py`:

```python
# src/mergency/adapters/github/push_signal_parser.py
from datetime import datetime

from mergency.domain.models.push_commit import PushCommit
from mergency.domain.models.push_signal import PushSignal


def parse_push_signal(payload: dict) -> PushSignal:
    repository = payload["repository"]
    commits = [
        PushCommit(
            sha=commit["id"],
            message=commit["message"],
            timestamp=datetime.fromisoformat(commit["timestamp"]),
            files=[
                *commit.get("added", []),
                *commit.get("removed", []),
                *commit.get("modified", []),
            ],
        )
        for commit in payload["commits"]
    ]

    return PushSignal(
        installation_id=payload["installation"]["id"],
        repo=repository["full_name"],
        ref=payload["ref"],
        default_branch=repository["default_branch"],
        commits=commits,
    )
```

Run: `docker compose run --rm app pytest tests/adapters/github/test_push_signal_parser.py tests/domain/models/test_activity_signal.py -v`
Expected: all passed (the existing `PushCommit(sha=..., message=..., timestamp=...)` construction in `test_activity_signal.py` still works — `files` defaults to `[]`).

- [ ] **Step 3:** commit: `feat: capture changed files on PushCommit for ownership resolution`.

---

## Task 10: `EventRepository` dedupe key includes `owner`

**Files:** Modify `src/mergency/domain/ports/event_repository.py`, `src/mergency/adapters/memory/event_repository.py`, `tests/adapters/memory/test_event_repository.py`.

- [ ] **Step 1: Rewrite the test file**

```python
# tests/adapters/memory/test_event_repository.py
from datetime import datetime, timezone

from mergency.adapters.memory.event_repository import InMemoryEventRepository
from mergency.domain.models.event import Event
from mergency.domain.models.event_type import EventType


def _event(sha: str = "abc123", owner: str = "@org/team-a") -> Event:
    return Event(
        installation_id=1,
        repo="acme/widgets",
        sha=sha,
        event_type=EventType.BUILD_FAILURE,
        owner=owner,
        ts=datetime.now(timezone.utc),
    )


async def test_save_if_new_persists_and_reports_new():
    repository = InMemoryEventRepository()

    saved = await repository.save_if_new(_event())

    assert saved is True
    stored = await repository.get(
        1, "acme/widgets", "abc123", EventType.BUILD_FAILURE, "@org/team-a"
    )
    assert stored is not None


async def test_save_if_new_is_idempotent_on_dedupe_key():
    repository = InMemoryEventRepository()
    await repository.save_if_new(_event())

    saved_again = await repository.save_if_new(_event())

    assert saved_again is False


async def test_different_sha_is_a_distinct_event():
    repository = InMemoryEventRepository()
    await repository.save_if_new(_event(sha="abc123"))

    saved = await repository.save_if_new(_event(sha="def456"))

    assert saved is True


async def test_same_raw_event_with_a_different_owner_is_a_distinct_row():
    repository = InMemoryEventRepository()
    await repository.save_if_new(_event(owner="@org/team-a"))

    saved = await repository.save_if_new(_event(owner="@org/team-b"))

    assert saved is True
    assert (
        await repository.get(1, "acme/widgets", "abc123", EventType.BUILD_FAILURE, "@org/team-a")
        is not None
    )
    assert (
        await repository.get(1, "acme/widgets", "abc123", EventType.BUILD_FAILURE, "@org/team-b")
        is not None
    )


async def test_get_returns_none_when_absent():
    repository = InMemoryEventRepository()

    assert (
        await repository.get(1, "acme/widgets", "missing", EventType.BUILD_FAILURE, "@org/team-a")
        is None
    )
```

Run: `docker compose run --rm app pytest tests/adapters/memory/test_event_repository.py -v`
Expected: fails — `get()` doesn't accept a 5th positional argument yet.

- [ ] **Step 2: Implement**

```python
# src/mergency/domain/ports/event_repository.py
from typing import Protocol

from mergency.domain.models.event import Event
from mergency.domain.models.event_type import EventType


class EventRepository(Protocol):
    async def save_if_new(self, event: Event) -> bool: ...

    async def get(
        self, installation_id: int, repo: str, sha: str, event_type: EventType, owner: str
    ) -> Event | None: ...
```

```python
# src/mergency/adapters/memory/event_repository.py
import asyncio

from mergency.domain.models.event import Event
from mergency.domain.models.event_type import EventType


class InMemoryEventRepository:
    def __init__(self) -> None:
        self._events: dict[tuple[int, str, str, EventType, str | None], Event] = {}
        self._lock = asyncio.Lock()

    async def save_if_new(self, event: Event) -> bool:
        key = (event.installation_id, event.repo, event.sha, event.event_type, event.owner)
        async with self._lock:
            if key in self._events:
                return False
            self._events[key] = event
            return True

    async def get(
        self, installation_id: int, repo: str, sha: str, event_type: EventType, owner: str
    ) -> Event | None:
        async with self._lock:
            return self._events.get((installation_id, repo, sha, event_type, owner))
```

Run: `docker compose run --rm app pytest tests/adapters/memory/test_event_repository.py -v`
Expected: 5 passed. (Note: `tests/worker/test_classify_activity_event.py` will now fail to import/run correctly against the old signature — that's expected and gets fixed in Task 13, per this plan's "full suite only needs to be green at the end" convention, same as plan 0009.)

- [ ] **Step 3:** commit: `feat: make EventRepository dedupe key owner-aware for ownership fan-out`.

---

## Task 11: `EventClassifier` becomes pure (no more persistence)

**Files:** Modify `src/mergency/domain/event_classifier.py`, `tests/domain/test_event_classifier.py`.

- [ ] **Step 1: Rewrite the test file**

```python
# tests/domain/test_event_classifier.py
from datetime import datetime, timezone

import pytest

from mergency.domain.event_classifier import EventClassifier
from mergency.domain.models.check_run_signal import CheckRunSignal
from mergency.domain.models.event_type import EventType
from mergency.domain.models.push_commit import PushCommit
from mergency.domain.models.push_signal import PushSignal


@pytest.fixture
def classifier() -> EventClassifier:
    return EventClassifier()


def _check_run_signal(**overrides) -> CheckRunSignal:
    defaults = dict(
        installation_id=1,
        repo="acme/widgets",
        sha="abc123",
        action="completed",
        conclusion="failure",
        head_branch="main",
        default_branch="main",
        completed_at=datetime.now(timezone.utc),
    )
    defaults.update(overrides)
    return CheckRunSignal(**defaults)


def _push_signal(message: str = 'Revert "x"') -> PushSignal:
    return PushSignal(
        installation_id=1,
        repo="acme/widgets",
        ref="refs/heads/main",
        default_branch="main",
        commits=[PushCommit(sha="sha1", message=message, timestamp=datetime.now(timezone.utc))],
    )


async def test_classifies_completed_failure_on_default_branch_as_build_failure(classifier):
    event = await classifier.classify(_check_run_signal())

    assert event is not None
    assert event.event_type == EventType.BUILD_FAILURE
    assert event.owner is None


async def test_ignores_non_completed_check_run(classifier):
    assert await classifier.classify(_check_run_signal(action="in_progress")) is None


async def test_ignores_success_conclusion(classifier):
    assert await classifier.classify(_check_run_signal(conclusion="success")) is None


async def test_ignores_check_run_on_feature_branch(classifier):
    assert await classifier.classify(_check_run_signal(head_branch="feature-x")) is None


async def test_classifies_revert_push_on_default_branch(classifier):
    event = await classifier.classify(_push_signal())

    assert event is not None
    assert event.event_type == EventType.REVERT
    assert event.sha == "sha1"


async def test_ignores_push_without_revert_commit(classifier):
    assert await classifier.classify(_push_signal(message="fix typo")) is None


async def test_ignores_push_to_non_default_branch(classifier):
    signal = PushSignal(
        installation_id=1,
        repo="acme/widgets",
        ref="refs/heads/feature-x",
        default_branch="main",
        commits=[PushCommit(sha="sha1", message='Revert "x"', timestamp=datetime.now(timezone.utc))],
    )
    assert await classifier.classify(signal) is None


async def test_recognizes_explicit_revert_mention(classifier):
    event = await classifier.classify(
        _push_signal(message="Undo bad change\n\nThis reverts commit abc123.")
    )

    assert event is not None
    assert event.event_type == EventType.REVERT
```

(The old `test_duplicate_check_run_delivery_is_not_reclassified` test is removed — `EventClassifier` no longer persists or dedupes; that responsibility moves to `EventRepository.save_if_new` at the worker-orchestration level, covered by a new test in Task 13.)

Run: `docker compose run --rm app pytest tests/domain/test_event_classifier.py -v`
Expected: fails — `EventClassifier()` currently requires an `event_repository` argument.

- [ ] **Step 2: Implement**

```python
# src/mergency/domain/event_classifier.py
import re

from mergency.domain.models.check_run_signal import CheckRunSignal
from mergency.domain.models.event import Event
from mergency.domain.models.event_type import EventType
from mergency.domain.models.push_signal import PushSignal

_QUALIFYING_CONCLUSIONS = {"failure", "timed_out"}
_REVERT_SUBJECT_PATTERN = re.compile(r'^Revert "')
_REVERT_MENTION = "this reverts commit"


class EventClassifier:
    async def classify(self, signal: CheckRunSignal | PushSignal) -> Event | None:
        match signal:
            case CheckRunSignal():
                return self._classify_check_run(signal)
            case PushSignal():
                return self._classify_push(signal)
            case _:
                raise TypeError(f"unsupported signal type: {type(signal)!r}")

    def _classify_check_run(self, signal: CheckRunSignal) -> Event | None:
        if signal.action != "completed":
            return None
        if signal.conclusion not in _QUALIFYING_CONCLUSIONS:
            return None
        if signal.head_branch != signal.default_branch:
            return None
        if signal.completed_at is None:
            return None
        return Event(
            installation_id=signal.installation_id,
            repo=signal.repo,
            sha=signal.sha,
            event_type=EventType.BUILD_FAILURE,
            owner=None,
            ts=signal.completed_at,
        )

    def _classify_push(self, signal: PushSignal) -> Event | None:
        if signal.ref != f"refs/heads/{signal.default_branch}":
            return None
        for commit in signal.commits:
            if _looks_like_revert(commit.message):
                return Event(
                    installation_id=signal.installation_id,
                    repo=signal.repo,
                    sha=commit.sha,
                    event_type=EventType.REVERT,
                    owner=None,
                    ts=commit.timestamp,
                )
        return None


def _looks_like_revert(message: str) -> bool:
    first_line = message.splitlines()[0] if message else ""
    return bool(_REVERT_SUBJECT_PATTERN.match(first_line)) or _REVERT_MENTION in message.lower()
```

Run: `docker compose run --rm app pytest tests/domain/test_event_classifier.py -v`
Expected: 8 passed.

- [ ] **Step 3:** commit: `refactor: make EventClassifier pure, persistence moves to the worker task`.

---

## Task 12: Wire everything into `deps.py`

**Files:** Modify `src/mergency/api/deps.py`, `tests/api/test_deps.py`.

- [ ] **Step 1: Add the test** (append to `tests/api/test_deps.py`, keep existing tests untouched)

```python
def test_ownership_resolution_dependencies_are_cached_and_resettable():
    factories = [
        deps.get_tenant_config_repository,
        deps.get_repository_content_provider,
        deps.get_codeowners_provider,
        deps.get_changed_files_provider,
        deps.get_config_resolver,
        deps.get_ownership_resolver,
    ]
    first_instances = [factory() for factory in factories]

    assert [factory() for factory in factories] == first_instances

    deps.reset_dependency_caches()

    assert all(
        factory() is not first for factory, first in zip(factories, first_instances)
    )
```

Run: `docker compose run --rm app pytest tests/api/test_deps.py -v`
Expected: the new test fails with `AttributeError: module 'mergency.api.deps' has no attribute 'get_tenant_config_repository'`; existing tests still pass.

- [ ] **Step 2: Implement** — modify `src/mergency/api/deps.py`:

```python
from functools import lru_cache

from mergency.adapters.github.changed_files_provider import GithubChangedFilesProvider
from mergency.adapters.github.codeowners_provider import GithubCodeownersProvider
from mergency.adapters.github.repository_content_provider import GithubRepositoryContentProvider
from mergency.adapters.github.token_manager import PyGithubInstallationTokenProvider
from mergency.adapters.memory.event_repository import InMemoryEventRepository
from mergency.adapters.memory.tenant_config_repository import InMemoryTenantConfigRepository
from mergency.adapters.memory.tenant_repository import InMemoryTenantRepository
from mergency.api.settings import Settings
from mergency.domain.config_resolver import ConfigResolver
from mergency.domain.event_classifier import EventClassifier
from mergency.domain.installation_service import InstallationService
from mergency.domain.ownership_resolver import OwnershipResolver
from mergency.domain.ports.changed_files_provider import ChangedFilesProvider
from mergency.domain.ports.codeowners_provider import CodeownersProvider
from mergency.domain.ports.event_repository import EventRepository
from mergency.domain.ports.installation_token_provider import InstallationTokenProvider
from mergency.domain.ports.repository_content_provider import RepositoryContentProvider
from mergency.domain.ports.tenant_config_repository import TenantConfigRepository
from mergency.domain.ports.tenant_repository import TenantRepository


@lru_cache
def get_settings() -> Settings:
    return Settings()


@lru_cache
def get_tenant_repository() -> TenantRepository:
    return InMemoryTenantRepository()


@lru_cache
def get_installation_service() -> InstallationService:
    return InstallationService(get_tenant_repository())


@lru_cache
def get_installation_token_provider() -> InstallationTokenProvider:
    settings = get_settings()
    return PyGithubInstallationTokenProvider(
        app_id=settings.github_app_id,
        private_key=settings.github_private_key,
    )


@lru_cache
def get_event_repository() -> EventRepository:
    return InMemoryEventRepository()


@lru_cache
def get_event_classifier() -> EventClassifier:
    return EventClassifier()


@lru_cache
def get_tenant_config_repository() -> TenantConfigRepository:
    return InMemoryTenantConfigRepository()


@lru_cache
def get_repository_content_provider() -> RepositoryContentProvider:
    return GithubRepositoryContentProvider(get_installation_token_provider())


@lru_cache
def get_codeowners_provider() -> CodeownersProvider:
    return GithubCodeownersProvider(get_repository_content_provider())


@lru_cache
def get_changed_files_provider() -> ChangedFilesProvider:
    return GithubChangedFilesProvider(get_installation_token_provider())


@lru_cache
def get_config_resolver() -> ConfigResolver:
    return ConfigResolver(get_repository_content_provider(), get_tenant_config_repository())


@lru_cache
def get_ownership_resolver() -> OwnershipResolver:
    return OwnershipResolver(get_codeowners_provider())


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
```

Run: `docker compose run --rm app pytest tests/api/test_deps.py -v`
Expected: all passed.

- [ ] **Step 3:** commit: `feat: wire ownership resolution dependencies into deps`.

---

## Task 13: Orchestrate ownership resolution in the `classify_activity_event` Celery task

**Files:** Modify `src/mergency/worker/classify_activity_event.py`, `tests/worker/test_classify_activity_event.py`.

- [ ] **Step 1: Rewrite the test file**

```python
# tests/worker/test_classify_activity_event.py
import asyncio

from mergency.adapters.memory.event_repository import InMemoryEventRepository
from mergency.adapters.memory.tenant_config_repository import InMemoryTenantConfigRepository
from mergency.domain.config_resolver import ConfigResolver
from mergency.domain.event_classifier import EventClassifier
from mergency.domain.models.event_type import EventType
from mergency.domain.ownership_resolver import OwnershipResolver
from mergency.worker import classify_activity_event as task_module


class _StubContentProvider:
    def __init__(self, content: str | None = None) -> None:
        self._content = content

    async def get_file(self, installation_id, repo, path):
        return self._content


class _StubCodeownersProvider:
    def __init__(self, owners_by_path: dict[str, list[tuple[str, str]]]) -> None:
        self._owners_by_path = owners_by_path

    async def owners_for(self, installation_id, repo, path):
        return self._owners_by_path.get(path, [])


class _StubChangedFilesProvider:
    def __init__(self, files: list[str]) -> None:
        self._files = files

    async def files_changed_in_commit(self, installation_id, repo, sha):
        return self._files


def _wire(monkeypatch, *, codeowners_by_path=None, changed_files=None):
    event_repository = InMemoryEventRepository()
    monkeypatch.setattr(task_module, "get_event_classifier", lambda: EventClassifier())
    monkeypatch.setattr(task_module, "get_event_repository", lambda: event_repository)
    monkeypatch.setattr(
        task_module,
        "get_config_resolver",
        lambda: ConfigResolver(_StubContentProvider(None), InMemoryTenantConfigRepository()),
    )
    monkeypatch.setattr(
        task_module,
        "get_ownership_resolver",
        lambda: OwnershipResolver(_StubCodeownersProvider(codeowners_by_path or {})),
    )
    monkeypatch.setattr(
        task_module,
        "get_changed_files_provider",
        lambda: _StubChangedFilesProvider(changed_files or []),
    )
    return event_repository


def _check_run_payload():
    return {
        "action": "completed",
        "check_run": {
            "head_sha": "abc123",
            "conclusion": "failure",
            "completed_at": "2026-09-14T10:00:00Z",
            "check_suite": {"head_branch": "main"},
        },
        "repository": {"full_name": "acme/widgets", "default_branch": "main"},
        "installation": {"id": 1},
    }


def _push_payload():
    return {
        "ref": "refs/heads/main",
        "repository": {"full_name": "acme/widgets", "default_branch": "main"},
        "installation": {"id": 1},
        "commits": [
            {
                "id": "sha1",
                "message": 'Revert "add flaky feature"',
                "timestamp": "2026-09-14T10:00:00Z",
                "added": [],
                "removed": [],
                "modified": ["src/a.py"],
            }
        ],
    }


def test_build_failure_is_persisted_with_owner_from_commits_api(monkeypatch):
    event_repository = _wire(
        monkeypatch,
        codeowners_by_path={"src/build.py": [("TEAM", "@org/team-a")]},
        changed_files=["src/build.py"],
    )

    task_module.classify_activity_event("check_run", _check_run_payload())

    stored = asyncio.run(
        event_repository.get(1, "acme/widgets", "abc123", EventType.BUILD_FAILURE, "@org/team-a")
    )
    assert stored is not None


def test_revert_is_persisted_with_owner_from_push_commit_files(monkeypatch):
    event_repository = _wire(
        monkeypatch, codeowners_by_path={"src/a.py": [("TEAM", "@org/team-b")]}
    )

    task_module.classify_activity_event("push", _push_payload())

    stored = asyncio.run(
        event_repository.get(1, "acme/widgets", "sha1", EventType.REVERT, "@org/team-b")
    )
    assert stored is not None


def test_fans_out_into_one_row_per_distinct_owning_team(monkeypatch):
    event_repository = _wire(
        monkeypatch,
        codeowners_by_path={
            "src/build.py": [("TEAM", "@org/team-a"), ("TEAM", "@org/team-b")]
        },
        changed_files=["src/build.py"],
    )

    task_module.classify_activity_event("check_run", _check_run_payload())

    stored_a = asyncio.run(
        event_repository.get(1, "acme/widgets", "abc123", EventType.BUILD_FAILURE, "@org/team-a")
    )
    stored_b = asyncio.run(
        event_repository.get(1, "acme/widgets", "abc123", EventType.BUILD_FAILURE, "@org/team-b")
    )
    assert stored_a is not None
    assert stored_b is not None


def test_falls_back_to_default_team_when_no_codeowners_match(monkeypatch):
    event_repository = _wire(monkeypatch, codeowners_by_path={}, changed_files=["src/build.py"])

    task_module.classify_activity_event("check_run", _check_run_payload())

    stored = asyncio.run(
        event_repository.get(1, "acme/widgets", "abc123", EventType.BUILD_FAILURE, "unassigned")
    )
    assert stored is not None


def test_classify_activity_event_is_idempotent_across_redelivery(monkeypatch):
    event_repository = _wire(
        monkeypatch,
        codeowners_by_path={"src/build.py": [("TEAM", "@org/team-a")]},
        changed_files=["src/build.py"],
    )

    task_module.classify_activity_event("check_run", _check_run_payload())
    task_module.classify_activity_event("check_run", _check_run_payload())

    stored = asyncio.run(
        event_repository.get(1, "acme/widgets", "abc123", EventType.BUILD_FAILURE, "@org/team-a")
    )
    assert stored is not None


def test_unknown_event_type_is_dropped_without_error(monkeypatch):
    def _fail():
        raise AssertionError("classifier should not be constructed for an unknown event type")

    monkeypatch.setattr(task_module, "get_event_classifier", _fail)

    task_module.classify_activity_event("pull_request", {})


def test_malformed_payload_is_dropped_without_error():
    task_module.classify_activity_event("check_run", {"action": "completed"})
```

Run: `docker compose run --rm app pytest tests/worker/test_classify_activity_event.py -v`
Expected: fails — `task_module` doesn't expose `get_config_resolver`/`get_ownership_resolver`/`get_changed_files_provider` yet.

- [ ] **Step 2: Implement**

```python
# src/mergency/worker/classify_activity_event.py
import asyncio
import dataclasses
import logging

from mergency.adapters.github.check_run_signal_parser import parse_check_run_signal
from mergency.adapters.github.push_signal_parser import parse_push_signal
from mergency.api.deps import (
    get_changed_files_provider,
    get_config_resolver,
    get_event_classifier,
    get_event_repository,
    get_ownership_resolver,
)
from mergency.domain.models.check_run_signal import CheckRunSignal
from mergency.domain.models.event import Event
from mergency.domain.models.push_signal import PushSignal
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
    except (KeyError, ValueError, TypeError) as error:
        logger.warning(
            "activity payload could not be parsed, dropped",
            extra={"event_type": event_type, "error": str(error)},
        )
        return

    asyncio.run(_classify_resolve_and_persist(signal))


async def _classify_resolve_and_persist(signal: CheckRunSignal | PushSignal) -> None:
    event = await get_event_classifier().classify(signal)
    if event is None:
        return

    changed_files = await _changed_files_for(signal, event)
    config = await get_config_resolver().resolve(event.installation_id, event.repo)
    owners = await get_ownership_resolver().resolve_owners(
        event.installation_id, event.repo, changed_files, config.default_team
    )

    event_repository = get_event_repository()
    for owner in owners:
        await event_repository.save_if_new(dataclasses.replace(event, owner=owner))


async def _changed_files_for(signal: CheckRunSignal | PushSignal, event: Event) -> list[str]:
    if isinstance(signal, PushSignal):
        commit = next(commit for commit in signal.commits if commit.sha == event.sha)
        return commit.files
    return await get_changed_files_provider().files_changed_in_commit(
        event.installation_id, event.repo, event.sha
    )
```

Run: `docker compose run --rm app pytest tests/worker/test_classify_activity_event.py -v`
Expected: 8 passed.

- [ ] **Step 3:** commit: `feat: resolve and persist owned events in classify_activity_event`.

---

## Verification (full suite, after all tasks)

1. Full suite: `docker compose run --rm app pytest -v` — all tests pass, old and new.
2. Lint: `docker compose run --rm app ruff check src tests` — no errors.
3. Domain purity: `docker compose run --rm app grep -rniE "celery|fastapi|pygithub|sqlalchemy" src/mergency/domain/` — no matches (confirms `ConfigResolver`, `OwnershipResolver`, `EventClassifier`, and `domain/models/*` stay framework-free; `pyyaml` is fine to import here, it isn't in the forbidden list).
4. Guardrail containment: `docker compose run --rm app grep -rn "USERNAME\|EMAIL" src/mergency/adapters/` — no matches (confirms the individual-vs-team filtering logic lives only in `domain/ownership_resolver.py`, not duplicated into any adapter).
5. Fan-out sanity check (manual, via a one-off script or REPL inside the container): construct an `OwnershipResolver` with a stub `CodeownersProvider` returning two distinct `TEAM` owners for two different changed files, call `resolve_owners`, confirm both team names come back and `EventRepository.save_if_new` accepts both owned copies of the same `(installation_id, repo, sha, event_type)`.
6. `git diff` on `tests/domain/test_event_classifier.py` and `tests/adapters/memory/test_event_repository.py` shows the expected breaking-change updates only (no unrelated behavior change).
7. Manual smoke (optional, not part of CI): with a real installation token configured, trigger a `check_run` webhook with `conclusion: failure` against a repo that has a `CODEOWNERS` file, confirm the resulting `Event` row(s) carry a real team name and never an `@individual` handle.

After all tasks land, update this plan's `## Status` line (once committed to `docs/plan/0010-codeowners-ownership-resolution.md`) from `proposed` to `implemented`.
