# Historical Query API Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement ADR 0009 — a read-only `GET /api/v1/installations/{installation_id}/owners/{owner}/budget` endpoint that returns an owner's current `BudgetStatus` plus a daily-bucketed event count history over the rolling window, protected by an opaque per-installation API token minted at install time.

**Architecture:** A new domain service `BudgetHistoryQuery` composes the existing `BudgetCalculator` (ADR 0007) with a new `daily_counts_since` query added to the `EventRepository` port (and its in-memory + SQLAlchemy adapters). Access control reuses the existing `Installation`/`TenantRepository` machinery: `InstallationService` mints an opaque token on first install and stores it on the `Installation` record; a new `api/auth.py` pure function checks a presented bearer token against it. A new FastAPI router composes tenant lookup, token check, and the query, following the exact DI pattern already used by `api/internal.py`.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy (async, Postgres), pytest/pytest-asyncio/httpx, Docker Compose — no new dependencies.

---

## Status

proposed

## Context

`docs/adr/0009-historical-query-api.md` proposes this endpoint but no code exists yet. Since that ADR was written, `BudgetCalculator`, the SQLAlchemy `EventRepository`, and `TenantConfigRepository` have all landed (`docs/plan/0011-rolling-window-budget-calculation.md`), so this plan only adds what's missing: the history query, the token, and the route.

Two deviations from the ADR's literal wording, both intentional simplifications given the current codebase:
- The ADR names `InstallationService.handle_installation_created` and a separate `TenantApiTokenRepository`. The actual method is `InstallationService.handle` (pattern-matching on `CreateInstallation`/`TransitionInstallation`), and `TenantRepository` already has no SQL adapter yet — installations are still in-memory only (`api/deps.py::get_tenant_repository`). Rather than build a token table and a SQL-backed tenant store that doesn't otherwise exist yet, this plan adds `api_token: str | None` directly to the existing `Installation` dataclass and mints it inside `InstallationService.handle`'s `CreateInstallation` branch. This matches the tenant model's current persistence maturity (in-memory) rather than introducing a new one just for this feature.
- The ADR describes a pydantic response schema under `api/`. No such schema layer exists yet — every existing route (`api/internal.py`) returns a domain dataclass directly as its FastAPI response model. This plan follows that existing convention instead of introducing a new one, returning the new `BudgetHistory` dataclass directly.

**Known limitation, accepted for v1:** owner values contain slashes (e.g. `@org/backend-team`, per `CODEOWNERS` conventions used elsewhere in this codebase). The route uses `{owner:path}` so the slash is part of the path parameter; this is a greedy match against everything up to the final `/budget` segment, so an owner name that itself ends in a literal `/budget` substring would be parsed incorrectly. Not a realistic team name; not handled specially.

## Directory structure (additions only)

```
src/mergency/
├── api/
│   ├── auth.py                    # NEW — token_matches(installation, authorization_header) -> bool
│   └── budget_query.py            # NEW — GET /api/v1/installations/{id}/owners/{owner}/budget
├── domain/
│   ├── budget_history_query.py    # NEW — BudgetHistoryQuery service
│   └── models/
│       ├── budget_history.py      # NEW — BudgetHistory(status, daily_counts)
│       └── daily_event_count.py   # NEW — DailyEventCount(day, count)
tests/
├── api/
│   ├── test_auth.py                # NEW
│   └── test_budget_query.py        # NEW
├── domain/
│   ├── test_budget_history_query.py  # NEW
│   └── models/
│       ├── test_budget_history.py    # NEW
│       └── test_daily_event_count.py # NEW
└── adapters/
    ├── memory/test_event_repository.py   # MODIFY — add daily_counts_since tests
    └── db/test_event_repository.py       # MODIFY — add daily_counts_since tests
```

Modified (existing) files: `src/mergency/domain/models/installation.py`, `src/mergency/domain/installation_service.py`, `src/mergency/domain/ports/event_repository.py`, `src/mergency/adapters/memory/event_repository.py`, `src/mergency/adapters/db/event_repository.py`, `src/mergency/api/deps.py`, `src/mergency/api/app.py`, `tests/domain/test_installation_service.py`, `tests/api/test_deps.py`.

No new database migration: `events` already has `ix_events_budget_query` on `(installation_id, owner, ts)`, which covers the new daily-bucketed query, and `api_token` lives on the still-in-memory `Installation` record (see Context).

---

## Task 1: `DailyEventCount` domain model

**Files:**
- Create: `src/mergency/domain/models/daily_event_count.py`
- Test: `tests/domain/models/test_daily_event_count.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/domain/models/test_daily_event_count.py
from datetime import date

from mergency.domain.models.daily_event_count import DailyEventCount


def test_daily_event_count_is_a_frozen_day_count_pair():
    bucket = DailyEventCount(day=date(2026, 9, 1), count=3)

    assert bucket.day == date(2026, 9, 1)
    assert bucket.count == 3
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker compose run --rm app pytest tests/domain/models/test_daily_event_count.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'mergency.domain.models.daily_event_count'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/mergency/domain/models/daily_event_count.py
from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class DailyEventCount:
    day: date
    count: int
```

- [ ] **Step 4: Run test to verify it passes**

Run: `docker compose run --rm app pytest tests/domain/models/test_daily_event_count.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/mergency/domain/models/daily_event_count.py tests/domain/models/test_daily_event_count.py
git commit -m "feat: add DailyEventCount domain model"
```

---

## Task 2: `EventRepository.daily_counts_since` — port + in-memory adapter

**Files:**
- Modify: `src/mergency/domain/ports/event_repository.py`
- Modify: `src/mergency/adapters/memory/event_repository.py`
- Modify: `tests/adapters/memory/test_event_repository.py`

- [ ] **Step 1: Write the failing tests**

The existing file's `_event` helper only takes `sha` and `owner` (both defaulted, `installation_id` hardcoded to `1`, `ts` hardcoded to "now", `event_type` hardcoded to `EventType.BUILD_FAILURE`). Widen it in place — add `event_type` and `ts` keyword params with defaults that preserve every existing call site — then append the new tests below it. Change the top of the file to:

```python
from datetime import date, datetime, timedelta, timezone

from mergency.adapters.memory.event_repository import InMemoryEventRepository
from mergency.domain.models.daily_event_count import DailyEventCount
from mergency.domain.models.event import Event
from mergency.domain.models.event_type import EventType


def _event(
    sha: str = "abc123",
    owner: str = "@org/team-a",
    event_type: EventType = EventType.BUILD_FAILURE,
    ts: datetime | None = None,
) -> Event:
    return Event(
        installation_id=1,
        repo="acme/widgets",
        sha=sha,
        event_type=event_type,
        owner=owner,
        ts=ts or datetime.now(timezone.utc),
    )
```

Leave every existing test in the file untouched — the new keyword-only-by-default params don't change any existing `_event(...)` call. Then append:

```python
async def test_daily_counts_since_buckets_by_day_for_matching_owner_and_type():
    repository = InMemoryEventRepository()
    day1 = datetime(2026, 9, 1, 10, 0, tzinfo=timezone.utc)
    day2 = datetime(2026, 9, 2, 10, 0, tzinfo=timezone.utc)
    await repository.save_if_new(_event(sha="sha1", ts=day1))
    await repository.save_if_new(_event(sha="sha2", event_type=EventType.REVERT, ts=day1))
    await repository.save_if_new(_event(sha="sha3", ts=day2))

    buckets = await repository.daily_counts_since(
        1, "@org/team-a", [EventType.BUILD_FAILURE, EventType.REVERT], day1 - timedelta(days=1)
    )

    assert buckets == [
        DailyEventCount(day=date(2026, 9, 1), count=2),
        DailyEventCount(day=date(2026, 9, 2), count=1),
    ]


async def test_daily_counts_since_excludes_other_owners_types_installations_and_stale_events():
    repository = InMemoryEventRepository()
    now = datetime.now(timezone.utc)
    await repository.save_if_new(_event(sha="sha1", ts=now))
    await repository.save_if_new(
        Event(installation_id=2, repo="acme/widgets", sha="sha2", event_type=EventType.BUILD_FAILURE, owner="@org/team-a", ts=now)
    )
    await repository.save_if_new(_event(sha="sha3", owner="@org/team-b", ts=now))
    old = now - timedelta(days=100)
    await repository.save_if_new(_event(sha="sha4", ts=old))

    buckets = await repository.daily_counts_since(
        1, "@org/team-a", [EventType.BUILD_FAILURE], now - timedelta(days=1)
    )

    assert buckets == [DailyEventCount(day=now.date(), count=1)]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `docker compose run --rm app pytest tests/adapters/memory/test_event_repository.py -v`
Expected: FAIL with `AttributeError: 'InMemoryEventRepository' object has no attribute 'daily_counts_since'`

- [ ] **Step 3: Add the port method**

Edit `src/mergency/domain/ports/event_repository.py`:

```python
from datetime import datetime
from typing import Protocol

from mergency.domain.models.daily_event_count import DailyEventCount
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

    async def daily_counts_since(
        self,
        installation_id: int,
        owner: str,
        event_types: list[EventType],
        since: datetime,
    ) -> list[DailyEventCount]: ...
```

- [ ] **Step 4: Implement in the in-memory adapter**

Edit `src/mergency/adapters/memory/event_repository.py`:

```python
import asyncio
from datetime import date, datetime, timezone

from mergency.domain.models.daily_event_count import DailyEventCount
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

    async def daily_counts_since(
        self,
        installation_id: int,
        owner: str,
        event_types: list[EventType],
        since: datetime,
    ) -> list[DailyEventCount]:
        allow_list = set(event_types)
        counts: dict[date, int] = {}
        async with self._lock:
            for event in self._events.values():
                if not (
                    event.installation_id == installation_id
                    and event.owner == owner
                    and event.event_type in allow_list
                    and event.ts >= since
                ):
                    continue
                day = event.ts.astimezone(timezone.utc).date()
                counts[day] = counts.get(day, 0) + 1
        return [DailyEventCount(day=day, count=count) for day, count in sorted(counts.items())]
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `docker compose run --rm app pytest tests/adapters/memory/test_event_repository.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/mergency/domain/ports/event_repository.py src/mergency/adapters/memory/event_repository.py tests/adapters/memory/test_event_repository.py
git commit -m "feat: add daily_counts_since to EventRepository port and in-memory adapter"
```

---

## Task 3: `EventRepository.daily_counts_since` — SQLAlchemy adapter

**Files:**
- Modify: `src/mergency/adapters/db/event_repository.py`
- Modify: `tests/adapters/db/test_event_repository.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/adapters/db/test_event_repository.py` (add `date` to the existing `datetime` import, and add `DailyEventCount` to imports):

```python
from datetime import date

from mergency.domain.models.daily_event_count import DailyEventCount


async def test_daily_counts_since_buckets_events_by_day(db_engine):
    repository = SqlAlchemyEventRepository(db_engine)
    day1 = datetime(2026, 9, 1, 10, 0, tzinfo=timezone.utc)
    day2 = datetime(2026, 9, 2, 10, 0, tzinfo=timezone.utc)
    await repository.save_if_new(_event(sha="sha1", ts=day1))
    await repository.save_if_new(_event(sha="sha2", ts=day2))

    buckets = await repository.daily_counts_since(
        1, "@org/team-a", [EventType.BUILD_FAILURE], day1 - timedelta(days=1)
    )

    assert buckets == [
        DailyEventCount(day=date(2026, 9, 1), count=1),
        DailyEventCount(day=date(2026, 9, 2), count=1),
    ]


async def test_daily_counts_since_excludes_events_outside_the_window(db_engine):
    repository = SqlAlchemyEventRepository(db_engine)
    old_ts = datetime.now(timezone.utc) - timedelta(days=100)
    await repository.save_if_new(_event(sha="old-sha", ts=old_ts))

    buckets = await repository.daily_counts_since(
        1, "@org/team-a", [EventType.BUILD_FAILURE], datetime.now(timezone.utc) - timedelta(days=28)
    )

    assert buckets == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `docker compose run --rm app pytest tests/adapters/db/test_event_repository.py -v`
Expected: FAIL with `AttributeError: 'SqlAlchemyEventRepository' object has no attribute 'daily_counts_since'`

- [ ] **Step 3: Implement in the SQLAlchemy adapter**

Edit `src/mergency/adapters/db/event_repository.py` (add `DailyEventCount` to imports, add the method):

```python
from datetime import datetime

import asyncpg
import sqlalchemy as sa
from sqlalchemy import insert, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine

from mergency.adapters.db.tables import events_table
from mergency.domain.models.daily_event_count import DailyEventCount
from mergency.domain.models.event import Event
from mergency.domain.models.event_type import EventType


class SqlAlchemyEventRepository:
    # ... save_if_new, get, count_since unchanged ...

    async def daily_counts_since(
        self,
        installation_id: int,
        owner: str,
        event_types: list[EventType],
        since: datetime,
    ) -> list[DailyEventCount]:
        day = sa.cast(events_table.c.ts, sa.Date).label("day")
        async with self._engine.connect() as conn:
            result = await conn.execute(
                select(day, sa.func.count().label("count"))
                .where(
                    events_table.c.installation_id == installation_id,
                    events_table.c.owner == owner,
                    events_table.c.event_type.in_([t.value for t in event_types]),
                    events_table.c.ts >= since,
                )
                .group_by(day)
                .order_by(day)
            )
            rows = result.all()
        return [DailyEventCount(day=row.day, count=row.count) for row in rows]
```

(Keep the existing `save_if_new`, `get`, `count_since` methods and the module-level `_row_to_event` helper exactly as they are — only add the import and the new method.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `docker compose run --rm app pytest tests/adapters/db/test_event_repository.py -v`
Expected: PASS (requires the `db` service — run via `docker compose run --rm app pytest ...`, which shares the compose network with Postgres)

- [ ] **Step 5: Commit**

```bash
git add src/mergency/adapters/db/event_repository.py tests/adapters/db/test_event_repository.py
git commit -m "feat: add daily_counts_since to SqlAlchemyEventRepository"
```

---

## Task 4: `BudgetHistory` domain model

**Files:**
- Create: `src/mergency/domain/models/budget_history.py`
- Test: `tests/domain/models/test_budget_history.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/domain/models/test_budget_history.py
from datetime import date

from mergency.domain.models.budget_history import BudgetHistory
from mergency.domain.models.budget_status import BudgetStatus
from mergency.domain.models.daily_event_count import DailyEventCount


def test_budget_history_pairs_a_status_with_its_daily_counts():
    status = BudgetStatus(
        owner="@org/team-a", window_days=28, limit=5, consumed=2, remaining_pct=60.0
    )
    daily_counts = [DailyEventCount(day=date(2026, 9, 1), count=2)]

    history = BudgetHistory(status=status, daily_counts=daily_counts)

    assert history.status is status
    assert history.daily_counts == daily_counts
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker compose run --rm app pytest tests/domain/models/test_budget_history.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'mergency.domain.models.budget_history'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/mergency/domain/models/budget_history.py
from dataclasses import dataclass

from mergency.domain.models.budget_status import BudgetStatus
from mergency.domain.models.daily_event_count import DailyEventCount


@dataclass(frozen=True)
class BudgetHistory:
    status: BudgetStatus
    daily_counts: list[DailyEventCount]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `docker compose run --rm app pytest tests/domain/models/test_budget_history.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/mergency/domain/models/budget_history.py tests/domain/models/test_budget_history.py
git commit -m "feat: add BudgetHistory domain model"
```

---

## Task 5: `BudgetHistoryQuery` domain service

**Files:**
- Create: `src/mergency/domain/budget_history_query.py`
- Test: `tests/domain/test_budget_history_query.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/domain/test_budget_history_query.py
from datetime import datetime, timedelta, timezone

from mergency.adapters.memory.event_repository import InMemoryEventRepository
from mergency.adapters.memory.tenant_config_repository import InMemoryTenantConfigRepository
from mergency.domain.budget_calculator import BudgetCalculator
from mergency.domain.budget_history_query import BudgetHistoryQuery
from mergency.domain.models.daily_event_count import DailyEventCount
from mergency.domain.models.event import Event
from mergency.domain.models.event_type import EventType
from mergency.domain.models.tenant_config import TenantConfig


def _event(event_type: EventType, sha: str, owner: str, ts: datetime) -> Event:
    return Event(
        installation_id=1, repo="acme/widgets", sha=sha, event_type=event_type, owner=owner, ts=ts
    )


async def test_for_owner_returns_current_status_and_daily_history_within_the_window():
    event_repository = InMemoryEventRepository()
    config_repository = InMemoryTenantConfigRepository()
    await config_repository.upsert(
        TenantConfig(1, rolling_window_days=28, default_team="unassigned", max_events_per_window=5, warn_threshold_pct=50)
    )
    now = datetime.now(timezone.utc)
    await event_repository.save_if_new(_event(EventType.BUILD_FAILURE, "sha1", "@org/team-a", now))
    query = BudgetHistoryQuery(BudgetCalculator(event_repository, config_repository), event_repository)

    history = await query.for_owner(1, "@org/team-a")

    assert history.status.owner == "@org/team-a"
    assert history.status.consumed == 1
    assert history.daily_counts == [DailyEventCount(day=now.date(), count=1)]


async def test_for_owner_excludes_history_outside_the_configured_window():
    event_repository = InMemoryEventRepository()
    config_repository = InMemoryTenantConfigRepository()
    await config_repository.upsert(
        TenantConfig(1, rolling_window_days=28, default_team="unassigned", max_events_per_window=5, warn_threshold_pct=50)
    )
    stale_ts = datetime.now(timezone.utc) - timedelta(days=40)
    await event_repository.save_if_new(_event(EventType.BUILD_FAILURE, "sha1", "@org/team-a", stale_ts))
    query = BudgetHistoryQuery(BudgetCalculator(event_repository, config_repository), event_repository)

    history = await query.for_owner(1, "@org/team-a")

    assert history.status.consumed == 0
    assert history.daily_counts == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `docker compose run --rm app pytest tests/domain/test_budget_history_query.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'mergency.domain.budget_history_query'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/mergency/domain/budget_history_query.py
from datetime import datetime, timedelta, timezone

from mergency.domain.budget_calculator import BudgetCalculator
from mergency.domain.models.budget_history import BudgetHistory
from mergency.domain.models.event_type import EventType
from mergency.domain.ports.event_repository import EventRepository

_COUNTED_EVENT_TYPES = (EventType.BUILD_FAILURE, EventType.REVERT)


class BudgetHistoryQuery:
    def __init__(
        self, budget_calculator: BudgetCalculator, event_repository: EventRepository
    ) -> None:
        self._budget_calculator = budget_calculator
        self._event_repository = event_repository

    async def for_owner(self, installation_id: int, owner: str) -> BudgetHistory:
        status = await self._budget_calculator.status_for(installation_id, owner)
        since = datetime.now(timezone.utc) - timedelta(days=status.window_days)
        daily_counts = await self._event_repository.daily_counts_since(
            installation_id, owner, _COUNTED_EVENT_TYPES, since
        )
        return BudgetHistory(status=status, daily_counts=daily_counts)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `docker compose run --rm app pytest tests/domain/test_budget_history_query.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/mergency/domain/budget_history_query.py tests/domain/test_budget_history_query.py
git commit -m "feat: add BudgetHistoryQuery domain service"
```

---

## Task 6: Per-installation API token — model field + minting

**Files:**
- Modify: `src/mergency/domain/models/installation.py`
- Modify: `src/mergency/domain/installation_service.py`
- Modify: `tests/domain/test_installation_service.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/domain/test_installation_service.py`:

```python
async def test_handle_create_installation_mints_an_api_token(service, repository):
    await service.handle(CreateInstallation(installation=_installation()))

    stored = await repository.get(42)
    assert stored is not None
    assert stored.api_token is not None
    assert len(stored.api_token) > 20


async def test_recreating_an_existing_installation_preserves_its_api_token(service, repository):
    await service.handle(CreateInstallation(installation=_installation()))
    first = await repository.get(42)

    await service.handle(CreateInstallation(installation=_installation()))
    second = await repository.get(42)

    assert second is not None
    assert second.api_token == first.api_token
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `docker compose run --rm app pytest tests/domain/test_installation_service.py -v`
Expected: FAIL with `AttributeError: 'Installation' object has no attribute 'api_token'`

- [ ] **Step 3: Add the field to `Installation`**

Edit `src/mergency/domain/models/installation.py`:

```python
from dataclasses import dataclass

from mergency.domain.models.tenant_status import TenantStatus


@dataclass(frozen=True)
class Installation:
    installation_id: int
    account_login: str
    account_type: str
    status: TenantStatus
    repository_selection: str
    api_token: str | None = None
```

The new field is appended last with a default so every existing call site (webhook parser, tests, fixtures) that builds `Installation(...)` positionally or by keyword without `api_token` keeps working unchanged.

- [ ] **Step 4: Mint (or preserve) the token in `InstallationService`**

Edit `src/mergency/domain/installation_service.py`:

```python
import dataclasses
import logging
import secrets

from mergency.domain.models.create_installation_command import CreateInstallation
from mergency.domain.models.installation import Installation
from mergency.domain.models.installation_command import InstallationCommand
from mergency.domain.models.transition_installation_command import TransitionInstallation
from mergency.domain.ports.tenant_repository import TenantRepository

logger = logging.getLogger(__name__)


class InstallationService:
    def __init__(self, tenant_repository: TenantRepository) -> None:
        self._tenant_repository = tenant_repository

    async def handle(self, command: InstallationCommand) -> None:
        match command:
            case CreateInstallation(installation=installation):
                await self._create_or_update(installation)
            case TransitionInstallation(installation_id=installation_id, status=status):
                updated = await self._tenant_repository.transition(installation_id, status)
                if updated is None:
                    logger.warning(
                        "transition targeted unknown installation, acknowledged as no-op",
                        extra={"installation_id": installation_id, "status": status.value},
                    )

    async def _create_or_update(self, installation: Installation) -> None:
        existing = await self._tenant_repository.get(installation.installation_id)
        api_token = existing.api_token if existing and existing.api_token else secrets.token_urlsafe(32)
        await self._tenant_repository.upsert(dataclasses.replace(installation, api_token=api_token))
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `docker compose run --rm app pytest tests/domain/test_installation_service.py -v`
Expected: PASS (all tests, including the pre-existing ones — the earlier tests don't assert on `api_token`, so they still pass unchanged)

- [ ] **Step 6: Commit**

```bash
git add src/mergency/domain/models/installation.py src/mergency/domain/installation_service.py tests/domain/test_installation_service.py
git commit -m "feat: mint and preserve a per-installation API token on install"
```

---

## Task 7: `api/auth.py` — bearer token check

**Files:**
- Create: `src/mergency/api/auth.py`
- Test: `tests/api/test_auth.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/api/test_auth.py
from mergency.api.auth import token_matches
from mergency.domain.models.installation import Installation
from mergency.domain.models.tenant_status import TenantStatus


def _installation(api_token: str | None = "the-real-token") -> Installation:
    return Installation(
        installation_id=42,
        account_login="acme",
        account_type="Organization",
        status=TenantStatus.ACTIVE,
        repository_selection="all",
        api_token=api_token,
    )


def test_token_matches_accepts_the_correct_bearer_token():
    assert token_matches(_installation(), "Bearer the-real-token") is True


def test_token_matches_rejects_a_wrong_token():
    assert token_matches(_installation(), "Bearer wrong-token") is False


def test_token_matches_rejects_a_missing_header():
    assert token_matches(_installation(), None) is False


def test_token_matches_rejects_a_header_without_the_bearer_prefix():
    assert token_matches(_installation(), "the-real-token") is False


def test_token_matches_rejects_when_installation_has_no_token_minted():
    assert token_matches(_installation(api_token=None), "Bearer anything") is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `docker compose run --rm app pytest tests/api/test_auth.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'mergency.api.auth'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/mergency/api/auth.py
import secrets

from mergency.domain.models.installation import Installation

_BEARER_PREFIX = "Bearer "


def token_matches(installation: Installation, authorization_header: str | None) -> bool:
    if installation.api_token is None:
        return False
    if authorization_header is None or not authorization_header.startswith(_BEARER_PREFIX):
        return False
    presented_token = authorization_header[len(_BEARER_PREFIX) :]
    return secrets.compare_digest(presented_token, installation.api_token)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `docker compose run --rm app pytest tests/api/test_auth.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/mergency/api/auth.py tests/api/test_auth.py
git commit -m "feat: add bearer token check for installation-scoped API access"
```

---

## Task 8: Wire `BudgetHistoryQuery` into dependency injection

**Files:**
- Modify: `src/mergency/api/deps.py`
- Modify: `tests/api/test_deps.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/api/test_deps.py`:

```python
def test_get_budget_history_query_is_cached_and_resettable():
    from mergency.api import deps

    first = deps.get_budget_history_query()
    assert deps.get_budget_history_query() is first

    deps.reset_dependency_caches()

    assert deps.get_budget_history_query() is not first
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker compose run --rm app pytest tests/api/test_deps.py -v`
Expected: FAIL with `AttributeError: module 'mergency.api.deps' has no attribute 'get_budget_history_query'`

- [ ] **Step 3: Add the dependency factory**

Edit `src/mergency/api/deps.py` — add the import and the factory function (placed after `get_budget_calculator`), and add the cache-clear call to `reset_dependency_caches`:

```python
from mergency.domain.budget_history_query import BudgetHistoryQuery
```

```python
@lru_cache
def get_budget_history_query() -> BudgetHistoryQuery:
    return BudgetHistoryQuery(get_budget_calculator(), get_event_repository())
```

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
    get_budget_history_query.cache_clear()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `docker compose run --rm app pytest tests/api/test_deps.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/mergency/api/deps.py tests/api/test_deps.py
git commit -m "feat: wire BudgetHistoryQuery into dependency injection"
```

---

## Task 9: `GET /api/v1/installations/{installation_id}/owners/{owner}/budget` router

**Files:**
- Create: `src/mergency/api/budget_query.py`
- Modify: `src/mergency/api/app.py`
- Test: `tests/api/test_budget_query.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/api/test_budget_query.py
from datetime import datetime, timezone

import pytest
from httpx import ASGITransport, AsyncClient

from mergency.adapters.memory.event_repository import InMemoryEventRepository
from mergency.adapters.memory.tenant_config_repository import InMemoryTenantConfigRepository
from mergency.adapters.memory.tenant_repository import InMemoryTenantRepository
from mergency.api.app import app
from mergency.api.deps import get_budget_history_query, get_tenant_repository
from mergency.domain.budget_calculator import BudgetCalculator
from mergency.domain.budget_history_query import BudgetHistoryQuery
from mergency.domain.models.event import Event
from mergency.domain.models.event_type import EventType
from mergency.domain.models.installation import Installation
from mergency.domain.models.tenant_config import TenantConfig
from mergency.domain.models.tenant_status import TenantStatus


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
    event_repository = InMemoryEventRepository()
    config_repository = InMemoryTenantConfigRepository()
    budget_history_query = BudgetHistoryQuery(
        BudgetCalculator(event_repository, config_repository), event_repository
    )

    app.dependency_overrides[get_tenant_repository] = lambda: tenant_repository
    app.dependency_overrides[get_budget_history_query] = lambda: budget_history_query

    yield tenant_repository, event_repository, config_repository

    app.dependency_overrides.clear()


async def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def test_returns_status_and_daily_history_for_a_valid_token(override_dependencies):
    tenant_repository, event_repository, config_repository = override_dependencies
    await tenant_repository.upsert(_installation())
    await config_repository.upsert(
        TenantConfig(42, rolling_window_days=28, default_team="unassigned", max_events_per_window=5, warn_threshold_pct=50)
    )
    now = datetime.now(timezone.utc)
    await event_repository.save_if_new(
        Event(installation_id=42, repo="acme/widgets", sha="sha1", event_type=EventType.BUILD_FAILURE, owner="@org/team-a", ts=now)
    )

    async with await _client() as client:
        response = await client.get(
            "/api/v1/installations/42/owners/@org/team-a/budget",
            headers={"Authorization": "Bearer the-real-token"},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["status"]["owner"] == "@org/team-a"
    assert body["status"]["consumed"] == 1
    assert body["daily_counts"] == [{"day": now.date().isoformat(), "count": 1}]


async def test_returns_404_for_an_unknown_installation(override_dependencies):
    async with await _client() as client:
        response = await client.get(
            "/api/v1/installations/999/owners/@org/team-a/budget",
            headers={"Authorization": "Bearer whatever"},
        )

    assert response.status_code == 404


async def test_returns_401_for_a_missing_token(override_dependencies):
    tenant_repository, _, _ = override_dependencies
    await tenant_repository.upsert(_installation())

    async with await _client() as client:
        response = await client.get("/api/v1/installations/42/owners/@org/team-a/budget")

    assert response.status_code == 401


async def test_returns_401_for_a_wrong_token(override_dependencies):
    tenant_repository, _, _ = override_dependencies
    await tenant_repository.upsert(_installation())

    async with await _client() as client:
        response = await client.get(
            "/api/v1/installations/42/owners/@org/team-a/budget",
            headers={"Authorization": "Bearer not-the-token"},
        )

    assert response.status_code == 401


async def test_a_different_installations_token_cannot_read_this_installations_data(override_dependencies):
    tenant_repository, _, _ = override_dependencies
    await tenant_repository.upsert(_installation(api_token="token-for-42"))
    await tenant_repository.upsert(
        Installation(
            installation_id=7,
            account_login="other",
            account_type="Organization",
            status=TenantStatus.ACTIVE,
            repository_selection="all",
            api_token="token-for-7",
        )
    )

    async with await _client() as client:
        response = await client.get(
            "/api/v1/installations/42/owners/@org/team-a/budget",
            headers={"Authorization": "Bearer token-for-7"},
        )

    assert response.status_code == 401
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `docker compose run --rm app pytest tests/api/test_budget_query.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'mergency.api.budget_query'` (or a 404 from the route not existing yet, once the module import is fixed)

- [ ] **Step 3: Write the router**

```python
# src/mergency/api/budget_query.py
from fastapi import APIRouter, Depends, Header, HTTPException

from mergency.api.auth import token_matches
from mergency.api.deps import get_budget_history_query, get_tenant_repository
from mergency.domain.budget_history_query import BudgetHistoryQuery
from mergency.domain.models.budget_history import BudgetHistory
from mergency.domain.ports.tenant_repository import TenantRepository

router = APIRouter()


@router.get("/api/v1/installations/{installation_id}/owners/{owner:path}/budget")
async def get_owner_budget_history(
    installation_id: int,
    owner: str,
    authorization: str | None = Header(default=None),
    tenant_repository: TenantRepository = Depends(get_tenant_repository),
    budget_history_query: BudgetHistoryQuery = Depends(get_budget_history_query),
) -> BudgetHistory:
    installation = await tenant_repository.get(installation_id)
    if installation is None:
        raise HTTPException(status_code=404, detail="installation not found")

    if not token_matches(installation, authorization):
        raise HTTPException(status_code=401, detail="invalid or missing token")

    return await budget_history_query.for_owner(installation_id, owner)
```

- [ ] **Step 4: Wire the router into the app**

Edit `src/mergency/api/app.py`:

```python
from fastapi import FastAPI

from mergency.api.budget_query import router as budget_query_router
from mergency.api.internal import router as internal_router
from mergency.api.webhooks import router as webhooks_router


def create_app() -> FastAPI:
    app = FastAPI(title="mergency")
    app.include_router(webhooks_router)
    app.include_router(internal_router)
    app.include_router(budget_query_router)
    return app


app = create_app()
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `docker compose run --rm app pytest tests/api/test_budget_query.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/mergency/api/budget_query.py src/mergency/api/app.py tests/api/test_budget_query.py
git commit -m "feat: add historical query API endpoint for owner budget history"
```

---

## Verification

Run the full suite in the container to confirm nothing regressed and the new endpoint works end to end:

```bash
docker compose up -d db redis
docker compose run --rm app pytest -v
```

Expected: all tests pass, including every pre-existing test file plus the ten new/modified ones from this plan (`test_daily_event_count.py`, `test_budget_history.py`, `test_budget_history_query.py`, `test_auth.py`, `test_budget_query.py`, and the extended `test_event_repository.py` (both memory and db), `test_installation_service.py`, `test_deps.py`).

Manual smoke test against the running compose stack:

```bash
docker compose up -d
```

```bash
curl -i http://localhost:8000/internal/installations/1
```

(Use whatever installation ID exists in your local dev setup, or trigger a fresh `installation` webhook first — e.g. via the manifest-flow script from `docs/plan/0001-github-app-scaffolding.md` — to get a real installation with a minted `api_token`, then read that token from wherever `InstallationService` stored it and call:)

```bash
curl -i -H "Authorization: Bearer <the-minted-token>" \
  "http://localhost:8000/api/v1/installations/<id>/owners/@org/team-a/budget"
```

Expected: `200` with a JSON body shaped `{"status": {"owner": ..., "window_days": ..., "limit": ..., "consumed": ..., "remaining_pct": ...}, "daily_counts": [{"day": "YYYY-MM-DD", "count": N}, ...]}`, and `401` when the `Authorization` header is omitted or wrong.

Once all of the above passes, update the `## Status` line of `docs/adr/0009-historical-query-api.md` from `proposed` to `accepted`, and this plan's own `## Status` line (top of this file) from `proposed` to `implemented`.
