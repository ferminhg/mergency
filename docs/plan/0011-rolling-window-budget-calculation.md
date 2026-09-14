# Rolling-window budget calculation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn owned `Event` rows into a per-owner rolling-window `BudgetStatus`, per ADR 0007 (`docs/adr/0007-rolling-window-budget-calculation.md`), and introduce the real Postgres/SQLAlchemy persistence layer this milestone is meant to bring in.

**Tracks:** [GitHub issue #14](https://github.com/ferminhg/mergency/issues/14).

---

## Status

proposed

## Context

This plan assumes `docs/plan/0010-codeowners-ownership-resolution.md` (issue #13) is implemented and merged first: `TenantConfig`, `TenantConfigRepository`, `ConfigResolver`, `OwnershipResolver`, and `EventRepository`'s fan-out methods (`list_unresolved`, `resolve_owners`) all already exist in code by the time this plan starts, and `Event.owner` is a real team handle instead of always `None`.

Nothing else needed for a budget number exists yet:

- No `BudgetStatus` model, no `BudgetCalculator` domain service.
- `EventRepository` has no windowed counting method.
- **No Postgres/SQLAlchemy/Alembic exists anywhere in the codebase.** `docker-compose.yml` has a single `app` service. Every repository so far (`InMemoryEventRepository`, `InMemoryTenantRepository`, and `InMemoryTenantConfigRepository` from plan 0010) is an in-process dict guarded by an `asyncio.Lock`, which does not survive a process restart. ADR 0007 is explicitly the milestone that introduces real persistence, so this plan does that from scratch.
- `mergency.yml`'s proposed shape has no `budget.warn_threshold_pct` field yet (README, `docs/plan/0010-*.md`'s `TenantConfig`/parser).

**Scoping decision this plan makes:** ADR 0007 says the in-memory adapter "is replaced here, not kept alongside it" — read as *deps.py's production wiring* switches to the new SQLAlchemy-backed adapters for `EventRepository` and `TenantConfigRepository`. The `InMemory*` classes themselves stay in the codebase: plan 0009's and plan 0010's existing unit tests construct them directly as fast, DB-free fakes, and deleting them would break tests that are unrelated to this plan's scope. Only `api/deps.py`'s factories change what they return.

**Out of scope:** the PR comment bot (ADR 0008) and historical query API (ADR 0009) that consume `BudgetStatus` — this plan only produces the type and the service that computes it.

## Design decisions

**1. `BudgetCalculator`'s dependencies stay exactly what ADR 0007 says.** `BudgetCalculator(event_repository: EventRepository, config_repository: TenantConfigRepository)` — no `ConfigResolver`, no GitHub adapter. If `TenantConfigRepository.get(installation_id)` returns `None` (config never resolved for this installation — shouldn't happen once an event has been through `OwnershipResolver`, but is possible for a direct/early call), `BudgetCalculator` falls back to the same hardcoded defaults `mergency_yml_parser.py` uses (`rolling_window_days=28`, `max_events_per_window=5`), duplicated here as local constants rather than importing `ConfigResolver`'s module, to keep the dependency shape ADR 0007 specifies.

**2. Allow-list, not deny-list.** `_COUNTED_EVENT_TYPES = [EventType.BUILD_FAILURE, EventType.REVERT]` is a module-level constant in `domain/budget_calculator.py`. `count_since` is always called with this explicit list, never "count everything for this owner" — so a future `EventType.FLAKY_TEST` (ADR 0010) added to the enum doesn't silently start consuming budget.

**3. `count_since` query shape.** `EventRepository.count_since(installation_id, owner, event_types, since) -> int` is the one new port method. The SQLAlchemy adapter backs it with a single indexed query; `(installation_id, owner, ts)` gets a composite index in the initial migration, matching ADR 0007's consequence list. The in-memory adapter also implements it (simple list comprehension) purely so `BudgetCalculator`'s own tests stay fast and DB-free — production wiring never uses the in-memory version once this plan's Task 10 lands.

**4. `events` table's "unresolved row" invariant moves into the schema.** Plan 0010's in-memory adapter enforces "at most one `owner IS NULL` row per `(installation_id, repo, sha, event_type)`" in application code (a dict key). The Postgres schema enforces the same invariant with a **partial unique index**: `UNIQUE (installation_id, repo, sha, event_type) WHERE owner IS NULL`. Resolved rows (`owner` set) are unconstrained by it, since ADR 0006's fan-out means several rows legitimately share the same `(installation_id, repo, sha, event_type)` once resolved.

**5. SQLAlchemy Core, not the ORM.** Adapters use `sqlalchemy.Table` metadata + Core `select`/`insert`/`delete` statements against an `AsyncEngine`, not declarative ORM model classes with sessions. The domain's `Event`/`TenantConfig` dataclasses are already the right shape to hand data across the port boundary — adding a parallel ORM class per table would just be data-class duplication for no behavior gained at this scale (2 tables, no relationships). Keeps `adapters/db/` small and keeps the hexagonal boundary obvious: nothing outside `adapters/db/` imports `sqlalchemy`.

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
│   ├── mergency_yml_parser.py         # modified: + warn_threshold_pct parsing
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
│   ├── test_mergency_yml_parser.py    # modified: + warn_threshold_pct cases
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

- [ ] **Step 1: Add dependencies** — modify `pyproject.toml`:

```toml
dependencies = [
    "fastapi>=0.115",
    "pydantic-settings>=2.5",
    "pygithub>=2.4",
    "celery>=5.4",
    "uvicorn[standard]>=0.32",
    "pyyaml>=6.0",
    "codeowners>=0.6",
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

- [ ] **Step 4: Add the connection string to `.env` and `.env.example`**

```
MERGENCY_GITHUB_APP_ID=test-app-id
MERGENCY_GITHUB_PRIVATE_KEY=test-private-key
MERGENCY_GITHUB_WEBHOOK_SECRET=test-webhook-secret
MERGENCY_DATABASE_URL=postgresql+asyncpg://mergency:mergency@postgres:5432/mergency
```

(Same content for both files — `.env.example` keeps the non-secret placeholders as-is, `.env` already has dummy values for the GitHub fields per existing convention; just append the `MERGENCY_DATABASE_URL` line to both.)

- [ ] **Step 5: Verify the stack builds and Postgres comes up healthy**

Run: `docker compose build app && docker compose up -d postgres && docker compose run --rm app python -c "import sqlalchemy, asyncpg, alembic; print('ok')"`
Expected: prints `ok`; `docker compose ps postgres` shows `healthy`.

- [ ] **Step 6:** commit: `chore: add Postgres service and SQLAlchemy/Alembic dependencies`.

---

## Task 2: `TenantConfig` gains `warn_threshold_pct`

**Files:** Modify `src/mergency/domain/models/tenant_config.py`, `src/mergency/domain/mergency_yml_parser.py`, `tests/domain/models/test_tenant_config.py`, `tests/domain/test_mergency_yml_parser.py`, `tests/adapters/memory/test_tenant_config_repository.py`, `README.md`.

- [ ] **Step 1: Update the tests**

`tests/domain/models/test_tenant_config.py` — add the new field to the existing construction:

```python
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

`tests/domain/test_mergency_yml_parser.py` — extend each existing assertion and add one new test:

```python
def test_parses_full_yaml():
    yaml_text = """
    rolling_window_days: 14
    default_team: platform-team
    budget:
      max_events_per_window: 10
      warn_threshold_pct: 40
    """

    config = parse_tenant_config(1, yaml_text)

    assert config.installation_id == 1
    assert config.rolling_window_days == 14
    assert config.default_team == "platform-team"
    assert config.max_events_per_window == 10
    assert config.warn_threshold_pct == 40


def test_missing_fields_fall_back_to_defaults():
    config = parse_tenant_config(1, "default_team: only-this-team\n")

    assert config.rolling_window_days == 28
    assert config.default_team == "only-this-team"
    assert config.max_events_per_window == 5
    assert config.warn_threshold_pct == 50


def test_none_text_falls_back_to_all_defaults():
    config = parse_tenant_config(1, None)

    assert config.rolling_window_days == 28
    assert config.default_team == "unowned"
    assert config.warn_threshold_pct == 50


def test_warn_threshold_pct_alone_overrides_only_itself():
    config = parse_tenant_config(1, "budget:\n  warn_threshold_pct: 25\n")

    assert config.warn_threshold_pct == 25
    assert config.max_events_per_window == 5
```

(Keep `test_invalid_yaml_falls_back_to_all_defaults` and `test_empty_yaml_document_falls_back_to_all_defaults` as-is — they only assert on `default_team`.)

`tests/adapters/memory/test_tenant_config_repository.py` — the one positional-args construction needs the new field:

```python
async def test_upsert_overwrites_existing_config():
    repository = InMemoryTenantConfigRepository()
    await repository.upsert(_config())

    await repository.upsert(TenantConfig(1, 14, "other-team", 10, 25))

    stored = await repository.get(1)
    assert stored.rolling_window_days == 14
    assert stored.default_team == "other-team"
    assert stored.warn_threshold_pct == 25
```

Also update the `_config()` helper at the top of that file:

```python
def _config(installation_id: int = 1) -> TenantConfig:
    return TenantConfig(
        installation_id=installation_id,
        rolling_window_days=28,
        default_team="platform-team",
        max_events_per_window=5,
        warn_threshold_pct=50,
    )
```

Run: `docker compose run --rm app pytest tests/domain/models/test_tenant_config.py tests/domain/test_mergency_yml_parser.py tests/adapters/memory/test_tenant_config_repository.py -v`
Expected: fails — `TenantConfig.__init__()` doesn't accept `warn_threshold_pct` yet.

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

```python
# src/mergency/domain/mergency_yml_parser.py
import yaml

from mergency.domain.models.tenant_config import TenantConfig

_DEFAULT_ROLLING_WINDOW_DAYS = 28
_DEFAULT_DEFAULT_TEAM = "unowned"
_DEFAULT_MAX_EVENTS_PER_WINDOW = 5
_DEFAULT_WARN_THRESHOLD_PCT = 50


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

Run: `docker compose run --rm app pytest tests/domain/models/test_tenant_config.py tests/domain/test_mergency_yml_parser.py tests/adapters/memory/test_tenant_config_repository.py -v`
Expected: all passed.

- [ ] **Step 4:** commit: `feat: add warn_threshold_pct to TenantConfig and mergency.yml parsing`.

---

## Task 3: SQLAlchemy Core table definitions + engine factory

**Files:** Create `src/mergency/adapters/db/tables.py`, `src/mergency/adapters/db/engine.py`.

No red/green cycle — these are pure schema/factory declarations exercised by Task 5/7's integration tests. Verified by import.

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
    sa.Column("owner", sa.String, nullable=True),
    sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
    sa.Index(
        "ux_events_unresolved",
        "installation_id",
        "repo",
        "sha",
        "event_type",
        unique=True,
        postgresql_where=sa.text("owner IS NULL"),
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
# alembic.ini
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

- [ ] **Step 3: Add `alembic/env.py`** (async-mode env, per SQLAlchemy's own Alembic cookbook — `asyncpg` has no sync driver to fall back to)

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
        sa.Column("owner", sa.String, nullable=True),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ux_events_unresolved",
        "events",
        ["installation_id", "repo", "sha", "event_type"],
        unique=True,
        postgresql_where=sa.text("owner IS NULL"),
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
    op.drop_index("ux_events_unresolved", table_name="events")
    op.drop_table("events")
```

- [ ] **Step 5: Run the migration against the real Postgres service and verify**

Run: `docker compose run --rm app alembic upgrade head`
Expected: logs `Running upgrade  -> <rev>, create events and tenant_config tables`, exits 0.

Run: `docker compose run --rm app python -c "
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
"`
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

    stored = await repository.get(1)
    assert stored == _config()


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

- [ ] **Step 1: Add the tests** (append to `tests/adapters/memory/test_event_repository.py`)

```python
from datetime import timedelta


async def test_count_since_counts_matching_owner_and_type_within_window():
    repository = InMemoryEventRepository()
    await repository.save_if_new(_event(sha="abc123"))
    await repository.resolve_owners(1, "acme/widgets", "abc123", EventType.BUILD_FAILURE, ["team-a"])

    count = await repository.count_since(
        1, "team-a", [EventType.BUILD_FAILURE, EventType.REVERT], datetime.now(timezone.utc) - timedelta(days=1)
    )

    assert count == 1


async def test_count_since_excludes_events_outside_the_window():
    repository = InMemoryEventRepository()
    old_event = Event(
        installation_id=1,
        repo="acme/widgets",
        sha="old-sha",
        event_type=EventType.BUILD_FAILURE,
        owner=None,
        ts=datetime.now(timezone.utc) - timedelta(days=100),
    )
    await repository.save_if_new(old_event)
    await repository.resolve_owners(1, "acme/widgets", "old-sha", EventType.BUILD_FAILURE, ["team-a"])

    count = await repository.count_since(
        1, "team-a", [EventType.BUILD_FAILURE], datetime.now(timezone.utc) - timedelta(days=28)
    )

    assert count == 0


async def test_count_since_excludes_event_types_not_in_the_allow_list():
    repository = InMemoryEventRepository()
    await repository.save_if_new(_event(sha="abc123"))
    await repository.resolve_owners(1, "acme/widgets", "abc123", EventType.BUILD_FAILURE, ["team-a"])

    count = await repository.count_since(
        1, "team-a", [EventType.REVERT], datetime.now(timezone.utc) - timedelta(days=1)
    )

    assert count == 0
```

(Add `from datetime import datetime, timedelta, timezone` and `from mergency.domain.models.event import Event` to the top of the file if not already imported.)

Run: `docker compose run --rm app pytest tests/adapters/memory/test_event_repository.py -v`
Expected: 3 new tests fail with `AttributeError: 'InMemoryEventRepository' object has no attribute 'count_since'`; existing tests still pass.

- [ ] **Step 2: Implement** — modify `src/mergency/domain/ports/event_repository.py`, add to the `Protocol`:

```python
    async def count_since(
        self,
        installation_id: int,
        owner: str,
        event_types: list[EventType],
        since: "datetime",
    ) -> int: ...
```

(Add `from datetime import datetime` to that file's imports.)

Modify `src/mergency/adapters/memory/event_repository.py`, add:

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
                for events in self._events.values()
                for event in events
                if event.installation_id == installation_id
                and event.owner == owner
                and event.event_type in allow_list
                and event.ts >= since
            )
```

(Add `from datetime import datetime` to that file's imports.)

Run: `docker compose run --rm app pytest tests/adapters/memory/test_event_repository.py -v`
Expected: 11 passed (8 existing + 3 new).

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


def _event(sha: str = "abc123", ts: datetime | None = None) -> Event:
    return Event(
        installation_id=1,
        repo="acme/widgets",
        sha=sha,
        event_type=EventType.BUILD_FAILURE,
        owner=None,
        ts=ts or datetime.now(timezone.utc),
    )


async def test_save_if_new_persists_and_reports_new(db_engine):
    repository = SqlAlchemyEventRepository(db_engine)

    saved = await repository.save_if_new(_event())

    assert saved is True
    stored = await repository.get(1, "acme/widgets", "abc123", EventType.BUILD_FAILURE)
    assert stored is not None
    assert stored.sha == "abc123"


async def test_save_if_new_is_idempotent_on_the_unresolved_partial_index(db_engine):
    repository = SqlAlchemyEventRepository(db_engine)
    await repository.save_if_new(_event())

    saved_again = await repository.save_if_new(_event())

    assert saved_again is False


async def test_get_returns_none_when_absent(db_engine):
    repository = SqlAlchemyEventRepository(db_engine)

    assert await repository.get(1, "acme/widgets", "missing", EventType.BUILD_FAILURE) is None


async def test_list_unresolved_returns_only_owner_none_events(db_engine):
    repository = SqlAlchemyEventRepository(db_engine)
    await repository.save_if_new(_event())

    unresolved = await repository.list_unresolved(1)

    assert len(unresolved) == 1
    assert unresolved[0].owner is None


async def test_resolve_owners_replaces_the_unresolved_row_with_one_row_per_owner(db_engine):
    repository = SqlAlchemyEventRepository(db_engine)
    await repository.save_if_new(_event())

    resolved = await repository.resolve_owners(
        1, "acme/widgets", "abc123", EventType.BUILD_FAILURE, ["team-a", "team-b"]
    )

    assert {event.owner for event in resolved} == {"team-a", "team-b"}
    assert await repository.list_unresolved(1) == []


async def test_resolve_owners_on_unknown_event_returns_empty_list(db_engine):
    repository = SqlAlchemyEventRepository(db_engine)

    resolved = await repository.resolve_owners(
        1, "acme/widgets", "missing", EventType.BUILD_FAILURE, ["team-a"]
    )

    assert resolved == []


async def test_count_since_counts_matching_owner_and_type_within_window(db_engine):
    repository = SqlAlchemyEventRepository(db_engine)
    await repository.save_if_new(_event())
    await repository.resolve_owners(1, "acme/widgets", "abc123", EventType.BUILD_FAILURE, ["team-a"])

    count = await repository.count_since(
        1,
        "team-a",
        [EventType.BUILD_FAILURE, EventType.REVERT],
        datetime.now(timezone.utc) - timedelta(days=1),
    )

    assert count == 1


async def test_count_since_excludes_events_outside_the_window(db_engine):
    repository = SqlAlchemyEventRepository(db_engine)
    old_ts = datetime.now(timezone.utc) - timedelta(days=100)
    await repository.save_if_new(_event(sha="old-sha", ts=old_ts))
    await repository.resolve_owners(1, "acme/widgets", "old-sha", EventType.BUILD_FAILURE, ["team-a"])

    count = await repository.count_since(
        1, "team-a", [EventType.BUILD_FAILURE], datetime.now(timezone.utc) - timedelta(days=28)
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
from sqlalchemy import delete, insert, select
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
        self, installation_id: int, repo: str, sha: str, event_type: EventType
    ) -> Event | None:
        async with self._engine.connect() as conn:
            row = (
                await conn.execute(
                    select(events_table)
                    .where(
                        events_table.c.installation_id == installation_id,
                        events_table.c.repo == repo,
                        events_table.c.sha == sha,
                        events_table.c.event_type == event_type.value,
                    )
                    .order_by(events_table.c.id.asc())
                    .limit(1)
                )
            ).first()
        return _row_to_event(row) if row else None

    async def list_unresolved(self, installation_id: int) -> list[Event]:
        async with self._engine.connect() as conn:
            rows = (
                await conn.execute(
                    select(events_table).where(
                        events_table.c.installation_id == installation_id,
                        events_table.c.owner.is_(None),
                    )
                )
            ).all()
        return [_row_to_event(row) for row in rows]

    async def resolve_owners(
        self,
        installation_id: int,
        repo: str,
        sha: str,
        event_type: EventType,
        owners: list[str],
    ) -> list[Event]:
        async with self._engine.begin() as conn:
            base = (
                await conn.execute(
                    select(events_table).where(
                        events_table.c.installation_id == installation_id,
                        events_table.c.repo == repo,
                        events_table.c.sha == sha,
                        events_table.c.event_type == event_type.value,
                        events_table.c.owner.is_(None),
                    )
                )
            ).first()
            if base is None:
                return []

            await conn.execute(delete(events_table).where(events_table.c.id == base.id))
            await conn.execute(
                insert(events_table),
                [
                    {
                        "installation_id": installation_id,
                        "repo": repo,
                        "sha": sha,
                        "event_type": event_type.value,
                        "owner": owner,
                        "ts": base.ts,
                    }
                    for owner in owners
                ],
            )
        return [Event(installation_id, repo, sha, event_type, owner, base.ts) for owner in owners]

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
Expected: 8 passed.

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
    status = BudgetStatus(owner="acme/backend-team", window_days=28, limit=5, consumed=2, remaining_pct=60.0)

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


async def _seed_resolved_event(
    repository: InMemoryEventRepository, owner: str, event_type: EventType, sha: str, ts: datetime
) -> None:
    await repository.save_if_new(
        Event(installation_id=1, repo="acme/widgets", sha=sha, event_type=event_type, owner=None, ts=ts)
    )
    await repository.resolve_owners(1, "acme/widgets", sha, event_type, [owner])


async def test_status_for_counts_allow_listed_events_within_the_window():
    event_repository = InMemoryEventRepository()
    config_repository = InMemoryTenantConfigRepository()
    await config_repository.upsert(
        TenantConfig(1, rolling_window_days=28, default_team="unowned", max_events_per_window=5, warn_threshold_pct=50)
    )
    now = datetime.now(timezone.utc)
    await _seed_resolved_event(event_repository, "acme/backend-team", EventType.BUILD_FAILURE, "sha1", now)
    await _seed_resolved_event(event_repository, "acme/backend-team", EventType.REVERT, "sha2", now)
    calculator = BudgetCalculator(event_repository, config_repository)

    status = await calculator.status_for(1, "acme/backend-team")

    assert status.owner == "acme/backend-team"
    assert status.window_days == 28
    assert status.limit == 5
    assert status.consumed == 2
    assert status.remaining_pct == 60.0


async def test_status_for_excludes_events_outside_the_rolling_window():
    event_repository = InMemoryEventRepository()
    config_repository = InMemoryTenantConfigRepository()
    await config_repository.upsert(
        TenantConfig(1, rolling_window_days=28, default_team="unowned", max_events_per_window=5, warn_threshold_pct=50)
    )
    stale_ts = datetime.now(timezone.utc) - timedelta(days=40)
    await _seed_resolved_event(event_repository, "acme/backend-team", EventType.BUILD_FAILURE, "sha1", stale_ts)
    calculator = BudgetCalculator(event_repository, config_repository)

    status = await calculator.status_for(1, "acme/backend-team")

    assert status.consumed == 0
    assert status.remaining_pct == 100.0


async def test_status_for_never_goes_below_zero_percent_when_over_budget():
    event_repository = InMemoryEventRepository()
    config_repository = InMemoryTenantConfigRepository()
    await config_repository.upsert(
        TenantConfig(1, rolling_window_days=28, default_team="unowned", max_events_per_window=1, warn_threshold_pct=50)
    )
    now = datetime.now(timezone.utc)
    await _seed_resolved_event(event_repository, "acme/backend-team", EventType.BUILD_FAILURE, "sha1", now)
    await _seed_resolved_event(event_repository, "acme/backend-team", EventType.REVERT, "sha2", now)
    calculator = BudgetCalculator(event_repository, config_repository)

    status = await calculator.status_for(1, "acme/backend-team")

    assert status.consumed == 2
    assert status.remaining_pct == 0.0


async def test_status_for_uses_hardcoded_defaults_when_no_config_exists():
    event_repository = InMemoryEventRepository()
    config_repository = InMemoryTenantConfigRepository()
    calculator = BudgetCalculator(event_repository, config_repository)

    status = await calculator.status_for(1, "acme/backend-team")

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

- [ ] **Step 1: Add the test** (append to `tests/api/test_deps.py`)

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

Replace the in-memory `EventRepository`/`TenantConfigRepository` factories and add the new ones:

```python
from mergency.adapters.db.engine import build_engine
from mergency.adapters.db.event_repository import SqlAlchemyEventRepository
from mergency.adapters.db.tenant_config_repository import SqlAlchemyTenantConfigRepository
from mergency.domain.budget_calculator import BudgetCalculator
```

```python
@lru_cache
def get_db_engine():
    return build_engine(get_settings().database_url)


@lru_cache
def get_event_repository() -> EventRepository:
    return SqlAlchemyEventRepository(get_db_engine())


@lru_cache
def get_tenant_config_repository() -> TenantConfigRepository:
    return SqlAlchemyTenantConfigRepository(get_db_engine())


@lru_cache
def get_budget_calculator() -> BudgetCalculator:
    return BudgetCalculator(get_event_repository(), get_tenant_config_repository())
```

(Remove the old `InMemoryEventRepository`/`InMemoryTenantConfigRepository` imports and factory bodies for these two — everything else from plan 0010 (`get_repo_config_fetcher`, `get_config_resolver`, `get_codeowners_provider`, `get_commit_files_provider`, `get_ownership_resolver`) stays unchanged, since they depend on `get_event_repository()`/`get_tenant_config_repository()` by factory call, not by concrete type.)

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
    get_db_engine.cache_clear()
    get_budget_calculator.cache_clear()
```

Run: `docker compose run --rm app pytest tests/api/test_deps.py -v`
Expected: all passed. (This now exercises a real DB connection through `get_db_engine()` — Postgres must be up, which `docker compose run` guarantees via the `depends_on: postgres` healthcheck added in Task 1.)

- [ ] **Step 3: Full-suite check** — the worker/webhook tests from plans 0009/0010 monkeypatch `get_event_classifier`/`get_ownership_resolver` directly rather than exercising `get_event_repository()`, so they're unaffected by the adapter swap; confirm with a full run.

Run: `docker compose run --rm app pytest -v`
Expected: all tests pass.

- [ ] **Step 4:** commit: `feat: wire BudgetCalculator and switch EventRepository/TenantConfigRepository to SQLAlchemy`.

---

## Verification (full suite, after all tasks)

1. Full suite against real Postgres: `docker compose run --rm app pytest -v` — all tests pass, old and new.
2. Lint: `docker compose run --rm app ruff check src tests` — no errors.
3. Domain purity: `docker compose run --rm app grep -rniE "celery|fastapi|sqlalchemy|pygithub|^from github|^import github" src/mergency/domain/` — no matches (confirms `BudgetCalculator`, `budget_status.py`, and the modified `TenantConfig`/`mergency_yml_parser.py` stay framework-free).
4. Allow-list containment: `docker compose run --rm app grep -rn "_COUNTED_EVENT_TYPES" src/mergency/` — matches only its one definition and one use, both inside `domain/budget_calculator.py` (confirms nothing else hand-rolls its own "which events count" logic).
5. Migration round-trip: `docker compose run --rm app alembic downgrade base && docker compose run --rm app alembic upgrade head` — both exit 0.
6. `git diff` on `tests/adapters/memory/test_event_repository.py`, `tests/adapters/memory/test_tenant_config_repository.py`, `tests/domain/models/test_tenant_config.py`, `tests/domain/test_mergency_yml_parser.py`, and `tests/api/test_deps.py` shows only additive tests or the documented `warn_threshold_pct`/adapter-swap edits — no unrelated behavior change.
7. Manual smoke (optional, not part of CI): `docker compose up -d`, run the full webhook → classify → resolve ownership flow from plan 0010 against a real installation, then in a REPL: `await get_budget_calculator().status_for(installation_id, "acme/backend-team")` and confirm a sane `BudgetStatus` comes back reflecting the events just persisted in Postgres (restart `docker compose restart app` first to prove it survives a process restart — the whole point of this milestone).
