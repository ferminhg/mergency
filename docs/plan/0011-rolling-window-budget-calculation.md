# Rolling-window budget calculation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn owned `Event` rows into a per-owner rolling-window `BudgetStatus`, per ADR 0007 (`docs/adr/0007-rolling-window-budget-calculation.md`), and introduce the real Postgres/SQLAlchemy persistence layer this milestone is meant to bring in.

**Tracks:** [GitHub issue #14](https://github.com/ferminhg/mergency/issues/14).

---

## Status

implemented

**Implementation note (added after all 10 tasks landed):** three refinements surfaced during code review that this plan's original task text didn't anticipate, each fixed in its own commit rather than folded silently into the task that introduced the issue:
- `SqlAlchemyEventRepository.save_if_new` (Task 7) initially caught `IntegrityError` too broadly, which would have silently swallowed a NOT NULL violation (e.g. a stray `owner=None` `Event` reaching persistence) and misreported it as an ordinary duplicate. Narrowed to specifically match `asyncpg.exceptions.UniqueViolationError` on the `ux_events_dedupe_key` constraint, re-raising anything else — with a regression test proving a NOT NULL violation now propagates.
- `BudgetCalculator` (Task 9): `_COUNTED_EVENT_TYPES` was a mutable `list`, changed to a `tuple`; added a test for the `max_events_per_window <= 0` edge case, which the original formula already handled correctly but hadn't been exercised.
- **The engine returned by `get_db_engine()` (Task 10) is configured with `poolclass=NullPool`.** Without it, the Celery worker's existing per-task `asyncio.run()` pattern (unchanged since plan 0010) breaks on the second task processed by a long-lived worker process: asyncpg connections are bound to the event loop that created them, so a pooled connection from one `asyncio.run()` call fails when reused inside the next one. This was reproduced for real (not just theorized) before and after the fix. `NullPool` means every checkout opens a fresh connection tied to whatever loop is currently running, at the cost of not pooling connections across calls — an acceptable trade-off for this task-per-invocation worker shape; revisit only if per-task connection overhead becomes measurable.

## Context

`docs/plan/0010-codeowners-ownership-resolution.md` (issue #13) is implemented and merged. This plan is written against the **actual code that landed**, which deviates in a few places from ADR 0006's own sketch — verified by reading the real files, not by re-reading the ADR:

- `EventRepository` (`src/mergency/domain/ports/event_repository.py`) is just:
  ```python
  class EventRepository(Protocol):
      async def save_if_new(self, event: Event) -> bool: ...
      async def get(
          self, installation_id: int, repo: str, sha: str, event_type: EventType, owner: str
      ) -> Event | None: ...
  ```
  `owner` is a required 5th parameter on `get`, and it's part of `save_if_new`'s dedupe key too. There is **no "unresolved" state stored in `EventRepository` at all** — `EventClassifier.classify()` (`src/mergency/domain/event_classifier.py`) is pure and never persists; ownership fan-out happens entirely in `src/mergency/worker/classify_activity_event.py`, which calls `OwnershipResolver.resolve_owners(installation_id, repo, changed_files, default_team) -> list[str]` (a list of team-name strings, not `Event`s) and then does `event_repository.save_if_new(dataclasses.replace(event, owner=owner))` once per resolved owner. **By the time any `Event` reaches `EventRepository`, `owner` is always a real, non-`None` string.** This matters directly for this plan's schema: the `owner` column can be `NOT NULL`, and a plain composite unique constraint (no partial index, no NULL-handling subtlety) is enough to preserve `save_if_new`'s idempotency.
- `InMemoryEventRepository` stores a flat `dict[(installation_id, repo, sha, event_type, owner), Event]` — one `Event` per key, not a list. There's nothing to "replace" or "fan out" at the repository level; each owner just gets its own dict entry.
- `TenantConfig` (`src/mergency/domain/models/tenant_config.py`) has exactly `installation_id`, `rolling_window_days`, `default_team`, `max_events_per_window` — no `warn_threshold_pct` yet.
- There is no standalone `mergency_yml_parser.py`. Parsing is a private module-level `_parse(installation_id, text) -> TenantConfig` function inside `src/mergency/domain/config_resolver.py`, with `_DEFAULT_ROLLING_WINDOW_DAYS = 28`, `_DEFAULT_TEAM = "unassigned"`, `_DEFAULT_MAX_EVENTS_PER_WINDOW = 5`. This plan extends that same function in place rather than extracting a new module — no other consumer needs it standalone.
- `api/deps.py`'s real factories are `get_settings`, `get_tenant_repository`, `get_installation_service`, `get_installation_token_provider`, `get_event_repository`, `get_event_classifier`, `get_tenant_config_repository`, `get_repository_content_provider`, `get_codeowners_provider`, `get_changed_files_provider`, `get_config_resolver`, `get_ownership_resolver` — all `@lru_cache`, all cleared in `reset_dependency_caches()`.
- Nothing budget-related exists yet: no `BudgetStatus`, no `BudgetCalculator`, no windowed counting method on `EventRepository`.
- **No Postgres/SQLAlchemy/Alembic exists anywhere.** `docker-compose.yml` has one `app` service. `pyproject.toml` already has `pyyaml>=6.0` and `codeowners>=0.9` (from plan 0010) but nothing DB-related. ADR 0007 is explicitly the milestone that introduces real persistence, so this plan does that from scratch.

**Scoping decision this plan makes:** ADR 0007 says the in-memory adapter "is replaced here, not kept alongside it" — read as *`api/deps.py`'s production wiring* switches `get_event_repository`/`get_tenant_config_repository` to the new SQLAlchemy-backed adapters. `InMemoryEventRepository`/`InMemoryTenantConfigRepository` stay in the codebase — plans 0009/0010's existing unit tests construct them directly as fast, DB-free fakes, and deleting them would break unrelated tests.

**Out of scope:** the PR comment bot (ADR 0008) and historical query API (ADR 0009) that will consume `BudgetStatus` — this plan only produces the type and the service that computes it.

## Design decisions

**1. `BudgetCalculator`'s dependencies stay exactly what ADR 0007 says.** `BudgetCalculator(event_repository: EventRepository, config_repository: TenantConfigRepository)` — no `ConfigResolver`, no GitHub adapter. If `TenantConfigRepository.get(installation_id)` returns `None`, `BudgetCalculator` falls back to hardcoded defaults matching `config_resolver.py`'s own (`rolling_window_days=28`, `max_events_per_window=5`), duplicated as local constants rather than importing from `config_resolver.py`, to keep `BudgetCalculator`'s dependency shape exactly as ADR 0007 specifies (`EventRepository` + `TenantConfigRepository` only).

**2. Allow-list, not deny-list.** `_COUNTED_EVENT_TYPES = [EventType.BUILD_FAILURE, EventType.REVERT]`, a module-level constant in `domain/budget_calculator.py`. `count_since` is always called with this explicit list, never "count everything for this owner" — so a future `EventType.FLAKY_TEST` (ADR 0010, v2) doesn't silently start consuming budget.

**3. One new port method: `count_since`.** `EventRepository.count_since(installation_id, owner, event_types, since) -> int` is additive — `save_if_new`/`get` are untouched. The Postgres adapter backs it with one indexed query; `(installation_id, owner, ts)` gets a composite index in the initial migration, matching ADR 0007's own consequence list. The in-memory adapter also implements it (a generator expression over `self._events.values()`) purely so `BudgetCalculator`'s tests stay fast and DB-free — production wiring never uses the in-memory version once Task 9 lands.

**4. `owner` is `NOT NULL` in the `events` table, and the dedupe constraint is a plain composite unique index.** Because persistence in the real flow (`worker/classify_activity_event.py`) only ever happens after `OwnershipResolver.resolve_owners` returns, `owner` is never `NULL` on a stored `Event`. `UNIQUE (installation_id, repo, sha, event_type, owner)` is sufficient and needs no partial-index/NULL-handling trick — a straightforward mirror of `InMemoryEventRepository`'s dict key.

**5. SQLAlchemy Core, not the ORM.** Adapters use `sqlalchemy.Table` metadata + Core `select`/`insert` statements against an `AsyncEngine`, not declarative ORM classes with sessions. `Event`/`TenantConfig` are already the right shape to cross the port boundary — an ORM class per table would be pure duplication at this scale (2 tables, no relationships). Nothing outside `adapters/db/` imports `sqlalchemy`.

**6. Migrations run through Alembic in async mode**, since `asyncpg` (the only Postgres driver this plan adds) has no sync counterpart — `alembic/env.py` uses the standard `async_engine_from_config` + `run_sync` pattern from SQLAlchemy's own Alembic cookbook, not the sync template `alembic init` generates by default.

## Directory structure (new/changed files)

```
src/mergency/
├── domain/
│   ├── models/
│   │   ├── tenant_config.py           # modified: + warn_threshold_pct
│   │   └── budget_status.py           # BudgetStatus
│   ├── ports/
│   │   └── event_repository.py        # modified: + count_since
│   ├── config_resolver.py             # modified: _parse gains warn_threshold_pct
│   └── budget_calculator.py           # BudgetCalculator
├── adapters/
│   ├── memory/
│   │   └── event_repository.py        # modified: + count_since
│   └── db/
│       ├── tables.py                  # events_table, tenant_config_table
│       ├── engine.py                  # build_engine
│       ├── event_repository.py        # SqlAlchemyEventRepository
│       └── tenant_config_repository.py  # SqlAlchemyTenantConfigRepository
└── api/
    ├── settings.py                    # modified: + database_url
    └── deps.py                        # modified: swap to SQL adapters, + get_budget_calculator

alembic/
├── env.py
├── script.py.mako
└── versions/
    └── <rev>_create_events_and_tenant_config_tables.py
alembic.ini

docker-compose.yml                     # modified: + postgres service
.env / .env.example                    # modified: + MERGENCY_DATABASE_URL

tests/
├── domain/
│   ├── models/
│   │   ├── test_tenant_config.py      # modified: + warn_threshold_pct
│   │   └── test_budget_status.py
│   ├── test_config_resolver.py        # modified: + warn_threshold_pct cases
│   └── test_budget_calculator.py
├── adapters/
│   ├── memory/
│   │   ├── test_event_repository.py   # modified: + count_since tests
│   │   └── test_tenant_config_repository.py  # modified: + warn_threshold_pct
│   └── db/
│       ├── conftest.py                # db_engine fixture
│       ├── test_tenant_config_repository.py
│       └── test_event_repository.py
└── api/test_deps.py                   # modified
```

---

## Task 1: Add DB dependencies, Postgres service, and settings

**Files:** Modify `pyproject.toml`, `docker-compose.yml`, `src/mergency/api/settings.py`, `.env`, `.env.example`.

- [ ] **Step 1: Add dependencies** — modify `pyproject.toml`'s `dependencies` list (existing `pyyaml`/`codeowners` entries from plan 0010 stay as-is; append these three):

```toml
dependencies = [
    "fastapi>=0.115",
    "pydantic-settings>=2.5",
    "pygithub>=2.4",
    "celery>=5.4",
    "uvicorn[standard]>=0.32",
    "pyyaml>=6.0",
    "codeowners>=0.9",
    "sqlalchemy[asyncio]>=2.0",
    "asyncpg>=0.29",
    "alembic>=1.13",
]
```

- [ ] **Step 2: Add the `postgres` service** — modify `docker-compose.yml`:

```yaml
services:
  app:
    build: .
    env_file:
      - .env
    ports:
      - "8000:8000"
    volumes:
      - ./src:/app/src
      - ./tests:/app/tests
      - ./scripts:/app/scripts
      - ./alembic:/app/alembic
      - ./alembic.ini:/app/alembic.ini
    depends_on:
      postgres:
        condition: service_healthy

  postgres:
    image: postgres:16-alpine
    environment:
      POSTGRES_USER: mergency
      POSTGRES_PASSWORD: mergency
      POSTGRES_DB: mergency
    ports:
      - "5432:5432"
    volumes:
      - postgres_data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U mergency"]
      interval: 5s
      timeout: 5s
      retries: 5

volumes:
  postgres_data:
```

- [ ] **Step 3: Add `database_url` to `Settings`** — modify `src/mergency/api/settings.py`:

```python
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="MERGENCY_")

    github_app_id: str
    github_private_key: str
    github_webhook_secret: str
    database_url: str
```

- [ ] **Step 4: Add the connection string** — append to both `.env` and `.env.example`:

```
MERGENCY_DATABASE_URL=postgresql+asyncpg://mergency:mergency@postgres:5432/mergency
```

- [ ] **Step 5: Verify the stack builds and Postgres comes up healthy**

Run: `docker compose build app && docker compose up -d postgres && docker compose run --rm app python -c "import sqlalchemy, asyncpg, alembic; print('ok')"`
Expected: prints `ok`; `docker compose ps postgres` shows `healthy`.

- [ ] **Step 6:** commit: `chore: add Postgres service and SQLAlchemy/Alembic dependencies`.

---

## Task 2: `TenantConfig` gains `warn_threshold_pct`

**Files:** Modify `src/mergency/domain/models/tenant_config.py`, `src/mergency/domain/config_resolver.py`, `tests/domain/models/test_tenant_config.py`, `tests/domain/test_config_resolver.py`, `tests/adapters/memory/test_tenant_config_repository.py`, `README.md`.

- [ ] **Step 1: Update the tests**

`tests/domain/models/test_tenant_config.py`:

```python
import dataclasses

import pytest

from mergency.domain.models.tenant_config import TenantConfig


def test_tenant_config_is_immutable():
    config = TenantConfig(
        installation_id=1,
        rolling_window_days=28,
        default_team="platform-team",
        max_events_per_window=5,
        warn_threshold_pct=50,
    )

    with pytest.raises(dataclasses.FrozenInstanceError):
        config.default_team = "other-team"
```

`tests/domain/test_config_resolver.py` — update every existing assertion and add one new test:

```python
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
            "rolling_window_days: 14\ndefault_team: platform-team\n"
            "budget:\n  max_events_per_window: 3\n  warn_threshold_pct: 40\n"
        ),
        InMemoryTenantConfigRepository(),
    )

    config = await resolver.resolve(1, "acme/widgets")

    assert config.installation_id == 1
    assert config.rolling_window_days == 14
    assert config.default_team == "platform-team"
    assert config.max_events_per_window == 3
    assert config.warn_threshold_pct == 40


async def test_falls_back_to_defaults_when_file_is_absent():
    resolver = ConfigResolver(_StubContentProvider(None), InMemoryTenantConfigRepository())

    config = await resolver.resolve(1, "acme/widgets")

    assert config.rolling_window_days == 28
    assert config.default_team == "unassigned"
    assert config.max_events_per_window == 5
    assert config.warn_threshold_pct == 50


async def test_falls_back_to_defaults_when_yaml_is_invalid():
    resolver = ConfigResolver(
        _StubContentProvider("not: valid: yaml: ["), InMemoryTenantConfigRepository()
    )

    config = await resolver.resolve(1, "acme/widgets")

    assert config.default_team == "unassigned"
    assert config.warn_threshold_pct == 50


async def test_missing_budget_section_uses_default_max_events():
    resolver = ConfigResolver(
        _StubContentProvider("rolling_window_days: 10\ndefault_team: team-x\n"),
        InMemoryTenantConfigRepository(),
    )

    config = await resolver.resolve(1, "acme/widgets")

    assert config.max_events_per_window == 5
    assert config.warn_threshold_pct == 50


async def test_warn_threshold_pct_alone_overrides_only_itself():
    resolver = ConfigResolver(
        _StubContentProvider("budget:\n  warn_threshold_pct: 25\n"),
        InMemoryTenantConfigRepository(),
    )

    config = await resolver.resolve(1, "acme/widgets")

    assert config.warn_threshold_pct == 25
    assert config.max_events_per_window == 5


async def test_resolve_persists_config_into_repository():
    repository = InMemoryTenantConfigRepository()
    resolver = ConfigResolver(_StubContentProvider(None), repository)

    config = await resolver.resolve(1, "acme/widgets")

    assert await repository.get(1) == config
```

`tests/adapters/memory/test_tenant_config_repository.py` — update the `_config()` helper:

```python
from mergency.adapters.memory.tenant_config_repository import InMemoryTenantConfigRepository
from mergency.domain.models.tenant_config import TenantConfig


def _config(installation_id: int = 1, default_team: str = "team-a") -> TenantConfig:
    return TenantConfig(
        installation_id=installation_id,
        rolling_window_days=28,
        default_team=default_team,
        max_events_per_window=5,
        warn_threshold_pct=50,
    )
```

(The three test bodies below `_config()` in that file are unchanged — they only exercise `default_team`.)

Run: `docker compose run --rm app pytest tests/domain/models/test_tenant_config.py tests/domain/test_config_resolver.py tests/adapters/memory/test_tenant_config_repository.py -v`
Expected: fails — `TenantConfig.__init__()` doesn't accept `warn_threshold_pct` yet, and `_parse` doesn't set it.

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
    warn_threshold_pct: int
```

Modify `src/mergency/domain/config_resolver.py`:

```python
import yaml

from mergency.domain.models.tenant_config import TenantConfig
from mergency.domain.ports.repository_content_provider import RepositoryContentProvider
from mergency.domain.ports.tenant_config_repository import TenantConfigRepository

_CONFIG_PATH = "mergency.yml"
_DEFAULT_ROLLING_WINDOW_DAYS = 28
_DEFAULT_TEAM = "unassigned"
_DEFAULT_MAX_EVENTS_PER_WINDOW = 5
_DEFAULT_WARN_THRESHOLD_PCT = 50


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
        warn_threshold_pct=budget.get("warn_threshold_pct", _DEFAULT_WARN_THRESHOLD_PCT),
    )
```

- [ ] **Step 3: Update README's proposed config shape** — modify `README.md`'s "Configuration" section:

```yaml
# mergency.yml (proposed format, subject to change)
rolling_window_days: 28
default_team: platform-team
budget:
  max_events_per_window: 5
  warn_threshold_pct: 50
```

Run: `docker compose run --rm app pytest tests/domain/models/test_tenant_config.py tests/domain/test_config_resolver.py tests/adapters/memory/test_tenant_config_repository.py -v`
Expected: all passed.

- [ ] **Step 4:** commit: `feat: add warn_threshold_pct to TenantConfig and mergency.yml parsing`.

---

## Task 3: SQLAlchemy Core table definitions + engine factory

**Files:** Create `src/mergency/adapters/db/tables.py`, `src/mergency/adapters/db/engine.py`.

No red/green cycle — pure schema/factory declarations exercised by Task 5/7's integration tests.

- [ ] **Step 1: Implement**

```python
# src/mergency/adapters/db/tables.py
import sqlalchemy as sa

metadata = sa.MetaData()

events_table = sa.Table(
    "events",
    metadata,
    sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
    sa.Column("installation_id", sa.Integer, nullable=False),
    sa.Column("repo", sa.String, nullable=False),
    sa.Column("sha", sa.String, nullable=False),
    sa.Column("event_type", sa.String, nullable=False),
    sa.Column("owner", sa.String, nullable=False),
    sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
    sa.UniqueConstraint(
        "installation_id", "repo", "sha", "event_type", "owner", name="ux_events_dedupe_key"
    ),
    sa.Index("ix_events_budget_query", "installation_id", "owner", "ts"),
)

tenant_config_table = sa.Table(
    "tenant_config",
    metadata,
    sa.Column("installation_id", sa.Integer, primary_key=True),
    sa.Column("rolling_window_days", sa.Integer, nullable=False),
    sa.Column("default_team", sa.String, nullable=False),
    sa.Column("max_events_per_window", sa.Integer, nullable=False),
    sa.Column("warn_threshold_pct", sa.Integer, nullable=False),
)
```

```python
# src/mergency/adapters/db/engine.py
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine


def build_engine(database_url: str) -> AsyncEngine:
    return create_async_engine(database_url, pool_pre_ping=True)
```

Run: `docker compose run --rm app python -c "from mergency.adapters.db.tables import metadata; from mergency.adapters.db.engine import build_engine; print(len(metadata.tables))"`
Expected: prints `2`.

- [ ] **Step 2:** commit: `feat: add SQLAlchemy table definitions and engine factory`.

---

## Task 4: Alembic scaffolding + initial migration

**Files:** Create `alembic.ini`, `alembic/env.py`, `alembic/script.py.mako`, `alembic/versions/<rev>_create_events_and_tenant_config_tables.py`.

- [ ] **Step 1: Add `alembic.ini`**

```ini
[alembic]
script_location = alembic
sqlalchemy.url =

[loggers]
keys = root,sqlalchemy,alembic

[handlers]
keys = console

[formatters]
keys = generic

[logger_root]
level = WARN
handlers = console
qualname =

[logger_sqlalchemy]
level = WARN
handlers =
qualname = sqlalchemy.engine

[logger_alembic]
level = INFO
handlers =
qualname = alembic

[handler_console]
class = StreamHandler
args = (sys.stderr,)
level = NOTSET
formatter = generic

[formatter_generic]
format = %(levelname)-5.5s [%(name)s] %(message)s
datefmt = %H:%M:%S
```

- [ ] **Step 2: Add `alembic/script.py.mako`**

```mako
"""${message}

Revision ID: ${up_revision}
Revises: ${down_revision | comma,n}
Create Date: ${create_date}

"""
from alembic import op
import sqlalchemy as sa
${imports if imports else ""}

revision = ${repr(up_revision)}
down_revision = ${repr(down_revision)}
branch_labels = ${repr(branch_labels)}
depends_on = ${repr(depends_on)}


def upgrade() -> None:
    ${upgrades if upgrades else "pass"}


def downgrade() -> None:
    ${downgrades if downgrades else "pass"}
```

- [ ] **Step 3: Add `alembic/env.py`** (async-mode env — `asyncpg` has no sync driver to fall back to)

```python
# alembic/env.py
import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import async_engine_from_config

from mergency.adapters.db.tables import metadata
from mergency.api.settings import Settings

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

config.set_main_option("sqlalchemy.url", Settings().database_url)

target_metadata = metadata


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(url=url, target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def _do_run_migrations(connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(_do_run_migrations)
    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
```

- [ ] **Step 4: Generate and fill in the initial revision**

Run: `docker compose run --rm app alembic revision -m "create events and tenant_config tables"`
Expected: creates `alembic/versions/<random_rev_id>_create_events_and_tenant_config_tables.py` with empty `upgrade`/`downgrade` bodies.

Edit that generated file's `upgrade`/`downgrade` functions (leave the auto-generated `revision`/`down_revision`/header as-is):

```python
def upgrade() -> None:
    op.create_table(
        "events",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("installation_id", sa.Integer, nullable=False),
        sa.Column("repo", sa.String, nullable=False),
        sa.Column("sha", sa.String, nullable=False),
        sa.Column("event_type", sa.String, nullable=False),
        sa.Column("owner", sa.String, nullable=False),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "installation_id", "repo", "sha", "event_type", "owner", name="ux_events_dedupe_key"
        ),
    )
    op.create_index(
        "ix_events_budget_query",
        "events",
        ["installation_id", "owner", "ts"],
    )
    op.create_table(
        "tenant_config",
        sa.Column("installation_id", sa.Integer, primary_key=True),
        sa.Column("rolling_window_days", sa.Integer, nullable=False),
        sa.Column("default_team", sa.String, nullable=False),
        sa.Column("max_events_per_window", sa.Integer, nullable=False),
        sa.Column("warn_threshold_pct", sa.Integer, nullable=False),
    )


def downgrade() -> None:
    op.drop_table("tenant_config")
    op.drop_index("ix_events_budget_query", table_name="events")
    op.drop_table("events")
```

- [ ] **Step 5: Run the migration against the real Postgres service and verify**

Run: `docker compose run --rm app alembic upgrade head`
Expected: logs `Running upgrade  -> <rev>, create events and tenant_config tables`, exits 0.

Run:
```bash
docker compose run --rm app python -c "
import asyncio
from sqlalchemy import text
from mergency.adapters.db.engine import build_engine
from mergency.api.settings import Settings

async def main():
    engine = build_engine(Settings().database_url)
    async with engine.connect() as conn:
        result = await conn.execute(text(\"SELECT tablename FROM pg_tables WHERE schemaname='public'\"))
        print(sorted(r[0] for r in result))
    await engine.dispose()

asyncio.run(main())
"
```
Expected: prints `['alembic_version', 'events', 'tenant_config']`.

Run: `docker compose run --rm app alembic downgrade base && docker compose run --rm app alembic upgrade head` (round-trip check)
Expected: both commands exit 0, no errors.

- [ ] **Step 6:** commit: `feat: add Alembic migration for events and tenant_config tables`.

---

## Task 5: `SqlAlchemyTenantConfigRepository`

**Files:** Create `tests/adapters/db/conftest.py`, `tests/adapters/db/test_tenant_config_repository.py`, `src/mergency/adapters/db/tenant_config_repository.py`.

- [ ] **Step 1: Write the fixture and the test**

```python
# tests/adapters/db/conftest.py
import pytest

from mergency.adapters.db.engine import build_engine
from mergency.adapters.db.tables import metadata
from mergency.api.settings import Settings


@pytest.fixture
async def db_engine():
    engine = build_engine(Settings().database_url)
    async with engine.begin() as conn:
        await conn.run_sync(metadata.create_all)
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(metadata.drop_all)
    await engine.dispose()
```

```python
# tests/adapters/db/test_tenant_config_repository.py
from mergency.adapters.db.tenant_config_repository import SqlAlchemyTenantConfigRepository
from mergency.domain.models.tenant_config import TenantConfig


def _config(installation_id: int = 1) -> TenantConfig:
    return TenantConfig(
        installation_id=installation_id,
        rolling_window_days=28,
        default_team="platform-team",
        max_events_per_window=5,
        warn_threshold_pct=50,
    )


async def test_get_returns_none_when_absent(db_engine):
    repository = SqlAlchemyTenantConfigRepository(db_engine)

    assert await repository.get(1) is None


async def test_upsert_then_get_returns_stored_config(db_engine):
    repository = SqlAlchemyTenantConfigRepository(db_engine)

    await repository.upsert(_config())

    assert await repository.get(1) == _config()


async def test_upsert_overwrites_existing_config(db_engine):
    repository = SqlAlchemyTenantConfigRepository(db_engine)
    await repository.upsert(_config())

    await repository.upsert(TenantConfig(1, 14, "other-team", 10, 25))

    stored = await repository.get(1)
    assert stored.rolling_window_days == 14
    assert stored.default_team == "other-team"
    assert stored.warn_threshold_pct == 25
```

Run: `docker compose run --rm app pytest tests/adapters/db/test_tenant_config_repository.py -v`
Expected: fails with `ModuleNotFoundError`.

- [ ] **Step 2: Implement**

```python
# src/mergency/adapters/db/tenant_config_repository.py
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncEngine

from mergency.adapters.db.tables import tenant_config_table
from mergency.domain.models.tenant_config import TenantConfig


class SqlAlchemyTenantConfigRepository:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def upsert(self, config: TenantConfig) -> None:
        statement = pg_insert(tenant_config_table).values(
            installation_id=config.installation_id,
            rolling_window_days=config.rolling_window_days,
            default_team=config.default_team,
            max_events_per_window=config.max_events_per_window,
            warn_threshold_pct=config.warn_threshold_pct,
        )
        statement = statement.on_conflict_do_update(
            index_elements=[tenant_config_table.c.installation_id],
            set_={
                "rolling_window_days": statement.excluded.rolling_window_days,
                "default_team": statement.excluded.default_team,
                "max_events_per_window": statement.excluded.max_events_per_window,
                "warn_threshold_pct": statement.excluded.warn_threshold_pct,
            },
        )
        async with self._engine.begin() as conn:
            await conn.execute(statement)

    async def get(self, installation_id: int) -> TenantConfig | None:
        async with self._engine.connect() as conn:
            row = (
                await conn.execute(
                    sa.select(tenant_config_table).where(
                        tenant_config_table.c.installation_id == installation_id
                    )
                )
            ).first()
        if row is None:
            return None
        return TenantConfig(
            installation_id=row.installation_id,
            rolling_window_days=row.rolling_window_days,
            default_team=row.default_team,
            max_events_per_window=row.max_events_per_window,
            warn_threshold_pct=row.warn_threshold_pct,
        )
```

Run: `docker compose run --rm app pytest tests/adapters/db/test_tenant_config_repository.py -v`
Expected: 3 passed.

- [ ] **Step 3:** commit: `feat: add SqlAlchemyTenantConfigRepository`.

---

## Task 6: `count_since` on `EventRepository` (port + in-memory adapter)

**Files:** Modify `src/mergency/domain/ports/event_repository.py`, `src/mergency/adapters/memory/event_repository.py`, `tests/adapters/memory/test_event_repository.py`.

- [ ] **Step 1: Add the tests** (append to `tests/adapters/memory/test_event_repository.py`; add `from datetime import timedelta` to its imports)

```python
async def test_count_since_counts_matching_owner_and_type_within_window():
    repository = InMemoryEventRepository()
    await repository.save_if_new(_event(owner="@org/team-a"))

    count = await repository.count_since(
        1,
        "@org/team-a",
        [EventType.BUILD_FAILURE, EventType.REVERT],
        datetime.now(timezone.utc) - timedelta(days=1),
    )

    assert count == 1


async def test_count_since_excludes_events_outside_the_window():
    old_event = Event(
        installation_id=1,
        repo="acme/widgets",
        sha="old-sha",
        event_type=EventType.BUILD_FAILURE,
        owner="@org/team-a",
        ts=datetime.now(timezone.utc) - timedelta(days=100),
    )
    repository = InMemoryEventRepository()
    await repository.save_if_new(old_event)

    count = await repository.count_since(
        1, "@org/team-a", [EventType.BUILD_FAILURE], datetime.now(timezone.utc) - timedelta(days=28)
    )

    assert count == 0


async def test_count_since_excludes_event_types_not_in_the_allow_list():
    repository = InMemoryEventRepository()
    await repository.save_if_new(_event(owner="@org/team-a"))

    count = await repository.count_since(
        1, "@org/team-a", [EventType.REVERT], datetime.now(timezone.utc) - timedelta(days=1)
    )

    assert count == 0


async def test_count_since_excludes_other_owners():
    repository = InMemoryEventRepository()
    await repository.save_if_new(_event(owner="@org/team-a"))

    count = await repository.count_since(
        1, "@org/team-b", [EventType.BUILD_FAILURE], datetime.now(timezone.utc) - timedelta(days=1)
    )

    assert count == 0
```

Run: `docker compose run --rm app pytest tests/adapters/memory/test_event_repository.py -v`
Expected: 4 new tests fail with `AttributeError: 'InMemoryEventRepository' object has no attribute 'count_since'`; existing tests still pass.

- [ ] **Step 2: Implement** — modify `src/mergency/domain/ports/event_repository.py`:

```python
from datetime import datetime
from typing import Protocol

from mergency.domain.models.event import Event
from mergency.domain.models.event_type import EventType


class EventRepository(Protocol):
    async def save_if_new(self, event: Event) -> bool: ...

    async def get(
        self, installation_id: int, repo: str, sha: str, event_type: EventType, owner: str
    ) -> Event | None: ...

    async def count_since(
        self,
        installation_id: int,
        owner: str,
        event_types: list[EventType],
        since: datetime,
    ) -> int: ...
```

Modify `src/mergency/adapters/memory/event_repository.py`, add `from datetime import datetime` to imports and the new method:

```python
    async def count_since(
        self,
        installation_id: int,
        owner: str,
        event_types: list[EventType],
        since: datetime,
    ) -> int:
        allow_list = set(event_types)
        async with self._lock:
            return sum(
                1
                for event in self._events.values()
                if event.installation_id == installation_id
                and event.owner == owner
                and event.event_type in allow_list
                and event.ts >= since
            )
```

Run: `docker compose run --rm app pytest tests/adapters/memory/test_event_repository.py -v`
Expected: 10 passed (6 existing + 4 new).

- [ ] **Step 3:** commit: `feat: add count_since to EventRepository`.

---

## Task 7: `SqlAlchemyEventRepository`

**Files:** Create `tests/adapters/db/test_event_repository.py`, `src/mergency/adapters/db/event_repository.py`.

- [ ] **Step 1: Write the test**

```python
# tests/adapters/db/test_event_repository.py
from datetime import datetime, timedelta, timezone

from mergency.adapters.db.event_repository import SqlAlchemyEventRepository
from mergency.domain.models.event import Event
from mergency.domain.models.event_type import EventType


def _event(sha: str = "abc123", owner: str = "@org/team-a", ts: datetime | None = None) -> Event:
    return Event(
        installation_id=1,
        repo="acme/widgets",
        sha=sha,
        event_type=EventType.BUILD_FAILURE,
        owner=owner,
        ts=ts or datetime.now(timezone.utc),
    )


async def test_save_if_new_persists_and_reports_new(db_engine):
    repository = SqlAlchemyEventRepository(db_engine)

    saved = await repository.save_if_new(_event())

    assert saved is True
    stored = await repository.get(1, "acme/widgets", "abc123", EventType.BUILD_FAILURE, "@org/team-a")
    assert stored is not None
    assert stored.owner == "@org/team-a"


async def test_save_if_new_is_idempotent_on_dedupe_key(db_engine):
    repository = SqlAlchemyEventRepository(db_engine)
    await repository.save_if_new(_event())

    saved_again = await repository.save_if_new(_event())

    assert saved_again is False


async def test_same_raw_event_with_a_different_owner_is_a_distinct_row(db_engine):
    repository = SqlAlchemyEventRepository(db_engine)
    await repository.save_if_new(_event(owner="@org/team-a"))

    saved = await repository.save_if_new(_event(owner="@org/team-b"))

    assert saved is True


async def test_get_returns_none_when_absent(db_engine):
    repository = SqlAlchemyEventRepository(db_engine)

    assert (
        await repository.get(1, "acme/widgets", "missing", EventType.BUILD_FAILURE, "@org/team-a")
        is None
    )


async def test_count_since_counts_matching_owner_and_type_within_window(db_engine):
    repository = SqlAlchemyEventRepository(db_engine)
    await repository.save_if_new(_event())

    count = await repository.count_since(
        1,
        "@org/team-a",
        [EventType.BUILD_FAILURE, EventType.REVERT],
        datetime.now(timezone.utc) - timedelta(days=1),
    )

    assert count == 1


async def test_count_since_excludes_events_outside_the_window(db_engine):
    repository = SqlAlchemyEventRepository(db_engine)
    old_ts = datetime.now(timezone.utc) - timedelta(days=100)
    await repository.save_if_new(_event(sha="old-sha", ts=old_ts))

    count = await repository.count_since(
        1, "@org/team-a", [EventType.BUILD_FAILURE], datetime.now(timezone.utc) - timedelta(days=28)
    )

    assert count == 0
```

Run: `docker compose run --rm app pytest tests/adapters/db/test_event_repository.py -v`
Expected: fails with `ModuleNotFoundError`.

- [ ] **Step 2: Implement**

```python
# src/mergency/adapters/db/event_repository.py
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy import insert, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine

from mergency.adapters.db.tables import events_table
from mergency.domain.models.event import Event
from mergency.domain.models.event_type import EventType


class SqlAlchemyEventRepository:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def save_if_new(self, event: Event) -> bool:
        try:
            async with self._engine.begin() as conn:
                await conn.execute(
                    insert(events_table).values(
                        installation_id=event.installation_id,
                        repo=event.repo,
                        sha=event.sha,
                        event_type=event.event_type.value,
                        owner=event.owner,
                        ts=event.ts,
                    )
                )
        except IntegrityError:
            return False
        return True

    async def get(
        self, installation_id: int, repo: str, sha: str, event_type: EventType, owner: str
    ) -> Event | None:
        async with self._engine.connect() as conn:
            row = (
                await conn.execute(
                    select(events_table).where(
                        events_table.c.installation_id == installation_id,
                        events_table.c.repo == repo,
                        events_table.c.sha == sha,
                        events_table.c.event_type == event_type.value,
                        events_table.c.owner == owner,
                    )
                )
            ).first()
        return _row_to_event(row) if row else None

    async def count_since(
        self,
        installation_id: int,
        owner: str,
        event_types: list[EventType],
        since: datetime,
    ) -> int:
        async with self._engine.connect() as conn:
            result = await conn.execute(
                select(sa.func.count())
                .select_from(events_table)
                .where(
                    events_table.c.installation_id == installation_id,
                    events_table.c.owner == owner,
                    events_table.c.event_type.in_([t.value for t in event_types]),
                    events_table.c.ts >= since,
                )
            )
        return result.scalar_one()


def _row_to_event(row) -> Event:
    return Event(
        installation_id=row.installation_id,
        repo=row.repo,
        sha=row.sha,
        event_type=EventType(row.event_type),
        owner=row.owner,
        ts=row.ts,
    )
```

Run: `docker compose run --rm app pytest tests/adapters/db/test_event_repository.py -v`
Expected: 6 passed.

- [ ] **Step 3:** commit: `feat: add SqlAlchemyEventRepository`.

---

## Task 8: `BudgetStatus` model

**Files:** Create `tests/domain/models/test_budget_status.py`, `src/mergency/domain/models/budget_status.py`.

- [ ] **Step 1: Write the test**

```python
# tests/domain/models/test_budget_status.py
import dataclasses

import pytest

from mergency.domain.models.budget_status import BudgetStatus


def test_budget_status_is_immutable():
    status = BudgetStatus(
        owner="@org/backend-team", window_days=28, limit=5, consumed=2, remaining_pct=60.0
    )

    with pytest.raises(dataclasses.FrozenInstanceError):
        status.consumed = 3
```

Run: `docker compose run --rm app pytest tests/domain/models/test_budget_status.py -v`
Expected: fails with `ModuleNotFoundError`.

- [ ] **Step 2: Implement**

```python
# src/mergency/domain/models/budget_status.py
from dataclasses import dataclass


@dataclass(frozen=True)
class BudgetStatus:
    owner: str
    window_days: int
    limit: int
    consumed: int
    remaining_pct: float
```

Run: `docker compose run --rm app pytest tests/domain/models/test_budget_status.py -v`
Expected: 1 passed.

- [ ] **Step 3:** commit: `feat: add BudgetStatus domain model`.

---

## Task 9: `BudgetCalculator` domain service

**Files:** Create `tests/domain/test_budget_calculator.py`, `src/mergency/domain/budget_calculator.py`.

- [ ] **Step 1: Write the test**

```python
# tests/domain/test_budget_calculator.py
from datetime import datetime, timedelta, timezone

from mergency.adapters.memory.event_repository import InMemoryEventRepository
from mergency.adapters.memory.tenant_config_repository import InMemoryTenantConfigRepository
from mergency.domain.budget_calculator import BudgetCalculator
from mergency.domain.models.event import Event
from mergency.domain.models.event_type import EventType
from mergency.domain.models.tenant_config import TenantConfig


def _event(event_type: EventType, sha: str, owner: str, ts: datetime) -> Event:
    return Event(
        installation_id=1, repo="acme/widgets", sha=sha, event_type=event_type, owner=owner, ts=ts
    )


async def test_status_for_counts_allow_listed_events_within_the_window():
    event_repository = InMemoryEventRepository()
    config_repository = InMemoryTenantConfigRepository()
    await config_repository.upsert(
        TenantConfig(1, rolling_window_days=28, default_team="unassigned", max_events_per_window=5, warn_threshold_pct=50)
    )
    now = datetime.now(timezone.utc)
    await event_repository.save_if_new(_event(EventType.BUILD_FAILURE, "sha1", "@org/backend-team", now))
    await event_repository.save_if_new(_event(EventType.REVERT, "sha2", "@org/backend-team", now))
    calculator = BudgetCalculator(event_repository, config_repository)

    status = await calculator.status_for(1, "@org/backend-team")

    assert status.owner == "@org/backend-team"
    assert status.window_days == 28
    assert status.limit == 5
    assert status.consumed == 2
    assert status.remaining_pct == 60.0


async def test_status_for_excludes_events_outside_the_rolling_window():
    event_repository = InMemoryEventRepository()
    config_repository = InMemoryTenantConfigRepository()
    await config_repository.upsert(
        TenantConfig(1, rolling_window_days=28, default_team="unassigned", max_events_per_window=5, warn_threshold_pct=50)
    )
    stale_ts = datetime.now(timezone.utc) - timedelta(days=40)
    await event_repository.save_if_new(_event(EventType.BUILD_FAILURE, "sha1", "@org/backend-team", stale_ts))
    calculator = BudgetCalculator(event_repository, config_repository)

    status = await calculator.status_for(1, "@org/backend-team")

    assert status.consumed == 0
    assert status.remaining_pct == 100.0


async def test_status_for_never_goes_below_zero_percent_when_over_budget():
    event_repository = InMemoryEventRepository()
    config_repository = InMemoryTenantConfigRepository()
    await config_repository.upsert(
        TenantConfig(1, rolling_window_days=28, default_team="unassigned", max_events_per_window=1, warn_threshold_pct=50)
    )
    now = datetime.now(timezone.utc)
    await event_repository.save_if_new(_event(EventType.BUILD_FAILURE, "sha1", "@org/backend-team", now))
    await event_repository.save_if_new(_event(EventType.REVERT, "sha2", "@org/backend-team", now))
    calculator = BudgetCalculator(event_repository, config_repository)

    status = await calculator.status_for(1, "@org/backend-team")

    assert status.consumed == 2
    assert status.remaining_pct == 0.0


async def test_status_for_uses_hardcoded_defaults_when_no_config_exists():
    event_repository = InMemoryEventRepository()
    config_repository = InMemoryTenantConfigRepository()
    calculator = BudgetCalculator(event_repository, config_repository)

    status = await calculator.status_for(1, "@org/backend-team")

    assert status.window_days == 28
    assert status.limit == 5
    assert status.consumed == 0
    assert status.remaining_pct == 100.0
```

Run: `docker compose run --rm app pytest tests/domain/test_budget_calculator.py -v`
Expected: fails with `ModuleNotFoundError`.

- [ ] **Step 2: Implement**

```python
# src/mergency/domain/budget_calculator.py
from datetime import datetime, timedelta, timezone

from mergency.domain.models.budget_status import BudgetStatus
from mergency.domain.models.event_type import EventType
from mergency.domain.ports.event_repository import EventRepository
from mergency.domain.ports.tenant_config_repository import TenantConfigRepository

_COUNTED_EVENT_TYPES = [EventType.BUILD_FAILURE, EventType.REVERT]
_FALLBACK_ROLLING_WINDOW_DAYS = 28
_FALLBACK_MAX_EVENTS_PER_WINDOW = 5


class BudgetCalculator:
    def __init__(
        self, event_repository: EventRepository, config_repository: TenantConfigRepository
    ) -> None:
        self._event_repository = event_repository
        self._config_repository = config_repository

    async def status_for(self, installation_id: int, owner: str) -> BudgetStatus:
        config = await self._config_repository.get(installation_id)
        window_days = config.rolling_window_days if config else _FALLBACK_ROLLING_WINDOW_DAYS
        limit = config.max_events_per_window if config else _FALLBACK_MAX_EVENTS_PER_WINDOW

        since = datetime.now(timezone.utc) - timedelta(days=window_days)
        consumed = await self._event_repository.count_since(
            installation_id, owner, _COUNTED_EVENT_TYPES, since
        )

        remaining_pct = max(0.0, (limit - consumed) / limit * 100) if limit > 0 else 0.0

        return BudgetStatus(
            owner=owner,
            window_days=window_days,
            limit=limit,
            consumed=consumed,
            remaining_pct=remaining_pct,
        )
```

Run: `docker compose run --rm app pytest tests/domain/test_budget_calculator.py -v`
Expected: 4 passed.

- [ ] **Step 3:** commit: `feat: add BudgetCalculator domain service`.

---

## Task 10: Wire everything into `deps.py`

**Files:** Modify `src/mergency/api/deps.py`, `tests/api/test_deps.py`.

- [ ] **Step 1: Add the tests** (append to `tests/api/test_deps.py`)

```python
def test_get_budget_calculator_is_cached_and_resettable():
    from mergency.api import deps

    first = deps.get_budget_calculator()
    assert deps.get_budget_calculator() is first

    deps.reset_dependency_caches()

    assert deps.get_budget_calculator() is not first


def test_event_repository_is_sqlalchemy_backed():
    from mergency.adapters.db.event_repository import SqlAlchemyEventRepository
    from mergency.api import deps

    assert isinstance(deps.get_event_repository(), SqlAlchemyEventRepository)


def test_tenant_config_repository_is_sqlalchemy_backed():
    from mergency.adapters.db.tenant_config_repository import SqlAlchemyTenantConfigRepository
    from mergency.api import deps

    assert isinstance(deps.get_tenant_config_repository(), SqlAlchemyTenantConfigRepository)
```

Run: `docker compose run --rm app pytest tests/api/test_deps.py -v`
Expected: `test_get_budget_calculator_is_cached_and_resettable` fails with `AttributeError`; the two `is_sqlalchemy_backed` tests fail because `get_event_repository`/`get_tenant_config_repository` still return the in-memory adapters.

- [ ] **Step 2: Implement** — modify `src/mergency/api/deps.py`.

Remove the `InMemoryEventRepository`/`InMemoryTenantConfigRepository` imports and replace the two matching factory bodies; add these imports:

```python
from mergency.adapters.db.engine import build_engine
from mergency.adapters.db.event_repository import SqlAlchemyEventRepository
from mergency.adapters.db.tenant_config_repository import SqlAlchemyTenantConfigRepository
from mergency.domain.budget_calculator import BudgetCalculator
```

Replace:

```python
@lru_cache
def get_event_repository() -> EventRepository:
    return InMemoryEventRepository()
```

with:

```python
@lru_cache
def get_db_engine():
    return build_engine(get_settings().database_url)


@lru_cache
def get_event_repository() -> EventRepository:
    return SqlAlchemyEventRepository(get_db_engine())
```

Replace:

```python
@lru_cache
def get_tenant_config_repository() -> TenantConfigRepository:
    return InMemoryTenantConfigRepository()
```

with:

```python
@lru_cache
def get_tenant_config_repository() -> TenantConfigRepository:
    return SqlAlchemyTenantConfigRepository(get_db_engine())
```

Add alongside the other factories:

```python
@lru_cache
def get_budget_calculator() -> BudgetCalculator:
    return BudgetCalculator(get_event_repository(), get_tenant_config_repository())
```

Every other plan-0010 factory (`get_repository_content_provider`, `get_codeowners_provider`, `get_changed_files_provider`, `get_config_resolver`, `get_ownership_resolver`) stays unchanged — they depend on `get_event_repository()`/`get_tenant_config_repository()` only by calling the factory function, never by importing the concrete in-memory class.

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
```

Run: `docker compose run --rm app pytest tests/api/test_deps.py -v`
Expected: all passed. (This exercises a real DB connection through `get_db_engine()` — Postgres must be up, which `docker compose run` guarantees via the `depends_on: postgres` healthcheck from Task 1.)

- [ ] **Step 3: Full-suite check** — `worker/classify_activity_event.py` calls `get_event_repository()` by factory, and its own tests monkeypatch `get_event_classifier`/`get_config_resolver`/`get_ownership_resolver`/`get_changed_files_provider` directly rather than exercising the real `get_event_repository()`, so they're unaffected by the adapter swap. Confirm with a full run.

Run: `docker compose run --rm app pytest -v`
Expected: all tests pass.

- [ ] **Step 4:** commit: `feat: wire BudgetCalculator and switch EventRepository/TenantConfigRepository to SQLAlchemy`.

---

## Verification (full suite, after all tasks)

1. Full suite against real Postgres: `docker compose run --rm app pytest -v` — all tests pass, old and new.
2. Lint: `docker compose run --rm app ruff check src tests` — no errors.
3. Domain purity: `docker compose run --rm app grep -rniE "celery|fastapi|sqlalchemy|pygithub|^from github|^import github" src/mergency/domain/` — no matches (confirms `BudgetCalculator`, `budget_status.py`, and the modified `TenantConfig`/`config_resolver.py` stay framework-free).
4. Allow-list containment: `docker compose run --rm app grep -rn "_COUNTED_EVENT_TYPES" src/mergency/` — matches only its one definition and one use, both inside `domain/budget_calculator.py`.
5. Migration round-trip: `docker compose run --rm app alembic downgrade base && docker compose run --rm app alembic upgrade head` — both exit 0.
6. `git diff` on `tests/adapters/memory/test_event_repository.py`, `tests/adapters/memory/test_tenant_config_repository.py`, `tests/domain/models/test_tenant_config.py`, `tests/domain/test_config_resolver.py`, and `tests/api/test_deps.py` shows only additive tests or the documented `warn_threshold_pct`/adapter-swap edits — no unrelated behavior change.
7. Manual smoke (optional, not part of CI): `docker compose up -d`, run the full webhook → classify → resolve ownership flow from plan 0010 against a real installation, then in a REPL: `await get_budget_calculator().status_for(installation_id, "@org/backend-team")` and confirm a sane `BudgetStatus` comes back. Restart with `docker compose restart app` first to prove the data survives a process restart — the whole point of this milestone.
