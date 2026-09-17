# Rename `Event`/`EventType` to `ActivityEvent`/`ActivityEventType` Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Execute the rename decided in [ADR 0013](../adr/0013-activity-event-model-naming.md) (tracked by [issue #25](https://github.com/ferminhg/mergency/issues/25)): `Event` → `ActivityEvent`, `EventType` → `ActivityEventType`, and every dependent port/adapter/factory, without changing behavior or the Postgres `events` table.

**Architecture:** This is a pure rename — no new behavior, no new tests. Each task renames one file group and updates every reference to it (imports, type annotations, constructor calls) using precise, word-boundary-safe find/replace so that lookalike identifiers (`EventClassifier`, `DailyEventCount`, `events_table`, `classify_activity_event`, the lowercase `event_type`/`event_repository` local names) are left untouched. Each task follows a red/green shape suited to a rename: update the *test* file's imports/usages to the new names first (this fails, because the source still exports the old names — genuine red), then rename the source and confirm the test passes (green).

**Tech Stack:** Python 3.12, pytest/pytest-asyncio, SQLAlchemy (async) + asyncpg, ruff (import sorting via the `I` rule set). All commands run through Docker Compose per `CLAUDE.md` — never bare `pytest`/`python`/`ruff` on the host.

---

## Context

[ADR 0013](../adr/0013-activity-event-model-naming.md) decided the rename; [issue #25](https://github.com/ferminhg/mergency/issues/25) asks for the implementation plan and code, TDD-first, ideally landing before PR #24 (which introduced the original `Event`/`EventType` names) merges.

Since ADR 0013 was written, the codebase grew beyond what it anticipated — the ADR only called out `EventClassifier`, `api/deps.py`'s factories, and "every test file referencing these symbols." A full repo scan (see below) shows the actual footprint is larger:

- `src/mergency/domain/budget_calculator.py`, `budget_history_query.py`, `flaky_test_detector.py`, `worker/report_incident.py` all depend on `EventType`/`EventRepository` and were not mentioned in the ADR (written before those modules existed).
- A **Postgres adapter** (`src/mergency/adapters/db/event_repository.py`, `SqlAlchemyEventRepository`) exists alongside the in-memory one the ADR's consequences section calls out (`adapters/memory/event_repository.py`) — both need the same rename.
- `domain/models/daily_event_count.py` (`DailyEventCount`) is an unrelated model that happens to contain the substring "Event" — it must **not** be touched.
- The `events` table (`adapters/db/tables.py`, referenced via `events_table`) and the Celery task `classify_activity_event.py` are correctly named already, per the ADR, and are also left untouched.

**Naming decisions this plan makes that the ADR left open:**

- `EventClassifier` is **not** renamed (ADR only lists it as needing "updated" references, not a new name — `EventClassifier` already reads fine: it classifies signals into activity events).
- `api/deps.py`'s `get_event_repository()` **is** renamed to `get_activity_event_repository()`, to match the renamed return type (`ActivityEventRepository`) and the renamed concrete class it wires (`SqlAlchemyActivityEventRepository`). `get_event_classifier()` is left as-is (matches the unrenamed `EventClassifier`).
- Local variable/parameter names (`event`, `event_repository`, `event_type`) are **not** renamed. The ADR's stated problem is bare `Event`/`EventType` *imports* being ambiguous — a local variable's meaning is already clear from its constructor/type at the point of use, so renaming every occurrence of `event_repository` to `activity_event_repository` throughout the codebase would add large diff noise for no disambiguation benefit. Only type/class names and file names change.

**Full footprint found in the repo** (source files; each has a matching test file):

| Layer | Old file | New file | Old class(es) | New class(es) |
|---|---|---|---|---|
| Model | `domain/models/event_type.py` | `domain/models/activity_event_type.py` | `EventType` | `ActivityEventType` |
| Model | `domain/models/event.py` | `domain/models/activity_event.py` | `Event` | `ActivityEvent` |
| Port | `domain/ports/event_repository.py` | `domain/ports/activity_event_repository.py` | `EventRepository` | `ActivityEventRepository` |
| Adapter (memory) | `adapters/memory/event_repository.py` | `adapters/memory/activity_event_repository.py` | `InMemoryEventRepository` | `InMemoryActivityEventRepository` |
| Adapter (db) | `adapters/db/event_repository.py` | `adapters/db/activity_event_repository.py` | `SqlAlchemyEventRepository` | `SqlAlchemyActivityEventRepository` |

Consumers updated in place (no file rename): `domain/event_classifier.py`, `domain/budget_calculator.py`, `domain/budget_history_query.py`, `domain/flaky_test_detector.py`, `worker/classify_activity_event.py`, `worker/report_incident.py`, `api/deps.py`, and their test files.

**Substitution rules used throughout** (applied with `perl -pi -e`, in this order, so nothing double-substitutes — verified by a dry run against real files before writing this plan):

```
1. s/mergency\.domain\.models\.event_type/mergency.domain.models.activity_event_type/g
2. s/mergency\.domain\.models\.event\b/mergency.domain.models.activity_event/g
3. s/mergency\.domain\.ports\.event_repository/mergency.domain.ports.activity_event_repository/g
4. s/mergency\.adapters\.memory\.event_repository/mergency.adapters.memory.activity_event_repository/g
5. s/mergency\.adapters\.db\.event_repository/mergency.adapters.db.activity_event_repository/g
6. s/EventRepository/ActivityEventRepository/g      # also fixes InMemoryEventRepository, SqlAlchemyEventRepository
7. s/EventType/ActivityEventType/g
8. s/\bEvent\b/ActivityEvent/g                       # word-boundary: does NOT touch EventType/EventRepository/
                                                      # EventClassifier/DailyEventCount (they're single tokens,
                                                      # no boundary mid-identifier)
9. s/get_event_repository/get_activity_event_repository/g
```

Rules 6-8 are order-independent (word boundaries make them safe to run in any order against each other); rules 1-5 must run before their corresponding bare-name rule would otherwise be fine either way since they target dotted module paths, not bare identifiers. Nothing in this list touches `EventClassifier`, `DailyEventCount`, `events_table`, `classify_activity_event`, or the lowercase local names `event`, `event_type`, `event_repository`.

After each source-file edit, `ruff check --fix` reorders the now-renamed import (`activity_event_repository` sorts differently than `event_repository`) — verified during dry-run: `mergency.domain.ports.activity_event_repository` needs to move from its old alphabetical slot in `api/deps.py`.

---

## Implementation steps

### Task 1: Rename `EventType` → `ActivityEventType` and `Event` → `ActivityEvent` (domain models)

**Files:**
- Modify: `src/mergency/domain/models/event_type.py` → renamed to `src/mergency/domain/models/activity_event_type.py`
- Modify: `src/mergency/domain/models/event.py` → renamed to `src/mergency/domain/models/activity_event.py`
- Test: `tests/domain/models/test_event.py` → renamed to `tests/domain/models/test_activity_event.py`

- [ ] **Step 1: Rename the test file and update it to the new names**

```bash
git mv tests/domain/models/test_event.py tests/domain/models/test_activity_event.py
perl -pi -e 's/mergency\.domain\.models\.event_type/mergency.domain.models.activity_event_type/g' tests/domain/models/test_activity_event.py
perl -pi -e 's/mergency\.domain\.models\.event\b/mergency.domain.models.activity_event/g' tests/domain/models/test_activity_event.py
perl -pi -e 's/EventType/ActivityEventType/g' tests/domain/models/test_activity_event.py
perl -pi -e 's/\bEvent\b/ActivityEvent/g' tests/domain/models/test_activity_event.py
```

Resulting file:

```python
import dataclasses
from datetime import datetime, timezone

import pytest

from mergency.domain.models.activity_event import ActivityEvent
from mergency.domain.models.activity_event_type import ActivityEventType


def test_event_type_values_match_adr():
    assert ActivityEventType.BUILD_FAILURE == "build_failure"
    assert ActivityEventType.REVERT == "revert"
    assert ActivityEventType.INCIDENT == "incident"


def test_event_is_immutable():
    event = ActivityEvent(
        installation_id=1,
        repo="acme/widgets",
        sha="abc123",
        event_type=ActivityEventType.BUILD_FAILURE,
        owner=None,
        ts=datetime.now(timezone.utc),
    )

    with pytest.raises(dataclasses.FrozenInstanceError):
        event.owner = "team-x"
```

- [ ] **Step 2: Run the test to verify it fails (source not renamed yet)**

Run: `docker compose run --rm app pytest tests/domain/models/test_activity_event.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'mergency.domain.models.activity_event_type'`

- [ ] **Step 3: Rename the source files**

```bash
git mv src/mergency/domain/models/event_type.py src/mergency/domain/models/activity_event_type.py
git mv src/mergency/domain/models/event.py src/mergency/domain/models/activity_event.py
perl -pi -e 's/EventType/ActivityEventType/g' src/mergency/domain/models/activity_event_type.py
perl -pi -e 's/mergency\.domain\.models\.event_type/mergency.domain.models.activity_event_type/g' src/mergency/domain/models/activity_event.py
perl -pi -e 's/EventType/ActivityEventType/g' src/mergency/domain/models/activity_event.py
perl -pi -e 's/\bEvent\b/ActivityEvent/g' src/mergency/domain/models/activity_event.py
```

Resulting `src/mergency/domain/models/activity_event_type.py`:

```python
from enum import Enum


class ActivityEventType(str, Enum):
    BUILD_FAILURE = "build_failure"
    REVERT = "revert"
    FLAKY_TEST = "flaky_test"
    INCIDENT = "incident"
```

Resulting `src/mergency/domain/models/activity_event.py`:

```python
from dataclasses import dataclass
from datetime import datetime

from mergency.domain.models.activity_event_type import ActivityEventType


@dataclass(frozen=True)
class ActivityEvent:
    installation_id: int
    repo: str
    sha: str
    event_type: ActivityEventType
    owner: str | None
    ts: datetime
    check_name: str | None = None
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `docker compose run --rm app pytest tests/domain/models/test_activity_event.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add src/mergency/domain/models/activity_event.py src/mergency/domain/models/activity_event_type.py tests/domain/models/test_activity_event.py
git status
git add -u src/mergency/domain/models tests/domain/models
git commit -m "refactor: rename Event/EventType to ActivityEvent/ActivityEventType"
```

---

### Task 2: Rename `EventRepository` port → `ActivityEventRepository`

**Files:**
- Modify: `src/mergency/domain/ports/event_repository.py` → renamed to `src/mergency/domain/ports/activity_event_repository.py`

There is no dedicated test file for this `Protocol` (it has no behavior of its own — verified: no `tests/domain/ports/test_event_repository.py` exists). This task has no test step; it renames the port and its internal imports so Task 3 (the memory adapter) and Task 4 (the db adapter) can depend on it.

- [ ] **Step 1: Rename the port file and update its contents**

```bash
git mv src/mergency/domain/ports/event_repository.py src/mergency/domain/ports/activity_event_repository.py
perl -pi -e 's/mergency\.domain\.models\.event_type/mergency.domain.models.activity_event_type/g' src/mergency/domain/ports/activity_event_repository.py
perl -pi -e 's/mergency\.domain\.models\.event\b/mergency.domain.models.activity_event/g' src/mergency/domain/ports/activity_event_repository.py
perl -pi -e 's/EventRepository/ActivityEventRepository/g' src/mergency/domain/ports/activity_event_repository.py
perl -pi -e 's/EventType/ActivityEventType/g' src/mergency/domain/ports/activity_event_repository.py
perl -pi -e 's/\bEvent\b/ActivityEvent/g' src/mergency/domain/ports/activity_event_repository.py
```

Resulting `src/mergency/domain/ports/activity_event_repository.py`:

```python
from datetime import datetime
from typing import Protocol

from mergency.domain.models.daily_event_count import DailyEventCount
from mergency.domain.models.activity_event import ActivityEvent
from mergency.domain.models.activity_event_type import ActivityEventType


class ActivityEventRepository(Protocol):
    async def save_if_new(self, event: ActivityEvent) -> bool: ...

    async def get(
        self, installation_id: int, repo: str, sha: str, event_type: ActivityEventType, owner: str
    ) -> ActivityEvent | None: ...

    async def count_since(
        self,
        installation_id: int,
        owner: str,
        event_types: list[ActivityEventType],
        since: datetime,
    ) -> int: ...

    async def daily_counts_since(
        self,
        installation_id: int,
        owner: str,
        event_types: list[ActivityEventType],
        since: datetime,
    ) -> list[DailyEventCount]: ...

    async def find_recent(
        self,
        installation_id: int,
        repo: str,
        sha: str,
        check_name: str,
        event_type: ActivityEventType,
        since: datetime,
    ) -> list[ActivityEvent]: ...

    async def retype(self, event: ActivityEvent, new_type: ActivityEventType) -> bool: ...
```

- [ ] **Step 2: Fix import order and verify the file imports cleanly**

```bash
docker compose run --rm app ruff check --fix src/mergency/domain/ports/activity_event_repository.py
docker compose run --rm app python -c "from mergency.domain.ports.activity_event_repository import ActivityEventRepository"
```

Expected: both commands succeed with no error output.

- [ ] **Step 3: Commit**

```bash
git add src/mergency/domain/ports/activity_event_repository.py
git commit -m "refactor: rename EventRepository port to ActivityEventRepository"
```

---

### Task 3: Rename the in-memory adapter — `InMemoryEventRepository` → `InMemoryActivityEventRepository`

**Files:**
- Modify: `src/mergency/adapters/memory/event_repository.py` → renamed to `src/mergency/adapters/memory/activity_event_repository.py`
- Test: `tests/adapters/memory/test_event_repository.py` → renamed to `tests/adapters/memory/test_activity_event_repository.py`

- [ ] **Step 1: Rename the test file and update it to the new names**

```bash
git mv tests/adapters/memory/test_event_repository.py tests/adapters/memory/test_activity_event_repository.py
perl -pi -e 's/mergency\.adapters\.memory\.event_repository/mergency.adapters.memory.activity_event_repository/g' tests/adapters/memory/test_activity_event_repository.py
perl -pi -e 's/mergency\.domain\.models\.event_type/mergency.domain.models.activity_event_type/g' tests/adapters/memory/test_activity_event_repository.py
perl -pi -e 's/mergency\.domain\.models\.event\b/mergency.domain.models.activity_event/g' tests/adapters/memory/test_activity_event_repository.py
perl -pi -e 's/EventRepository/ActivityEventRepository/g' tests/adapters/memory/test_activity_event_repository.py
perl -pi -e 's/EventType/ActivityEventType/g' tests/adapters/memory/test_activity_event_repository.py
perl -pi -e 's/\bEvent\b/ActivityEvent/g' tests/adapters/memory/test_activity_event_repository.py
docker compose run --rm app ruff check --fix tests/adapters/memory/test_activity_event_repository.py
```

This mechanically transforms all 262 lines (same structure as today — every `Event(` / `EventType.X` / `InMemoryEventRepository()` call site renamed, nothing else). The full expected result of `git diff tests/adapters/memory/test_activity_event_repository.py` after this step is: `InMemoryEventRepository` → `InMemoryActivityEventRepository` (16 occurrences), `Event(` / `Event]` → `ActivityEvent(` / `ActivityEvent]` (10 occurrences), `EventType.` → `ActivityEventType.` (34 occurrences), and the two `from mergency...` import lines updated — no other lines change.

- [ ] **Step 2: Run the test to verify it fails (source not renamed yet)**

Run: `docker compose run --rm app pytest tests/adapters/memory/test_activity_event_repository.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'mergency.adapters.memory.activity_event_repository'`

- [ ] **Step 3: Rename the source file**

```bash
git mv src/mergency/adapters/memory/event_repository.py src/mergency/adapters/memory/activity_event_repository.py
perl -pi -e 's/mergency\.domain\.models\.event_type/mergency.domain.models.activity_event_type/g' src/mergency/adapters/memory/activity_event_repository.py
perl -pi -e 's/mergency\.domain\.models\.event\b/mergency.domain.models.activity_event/g' src/mergency/adapters/memory/activity_event_repository.py
perl -pi -e 's/EventRepository/ActivityEventRepository/g' src/mergency/adapters/memory/activity_event_repository.py
perl -pi -e 's/EventType/ActivityEventType/g' src/mergency/adapters/memory/activity_event_repository.py
perl -pi -e 's/\bEvent\b/ActivityEvent/g' src/mergency/adapters/memory/activity_event_repository.py
docker compose run --rm app ruff check --fix src/mergency/adapters/memory/activity_event_repository.py
```

Resulting `src/mergency/adapters/memory/activity_event_repository.py`:

```python
import asyncio
import dataclasses
from datetime import date, datetime, timezone

from mergency.domain.models.daily_event_count import DailyEventCount
from mergency.domain.models.activity_event import ActivityEvent
from mergency.domain.models.activity_event_type import ActivityEventType


class InMemoryActivityEventRepository:
    def __init__(self) -> None:
        self._events: dict[tuple[int, str, str, ActivityEventType, str | None], ActivityEvent] = {}
        self._lock = asyncio.Lock()

    async def save_if_new(self, event: ActivityEvent) -> bool:
        key = (event.installation_id, event.repo, event.sha, event.event_type, event.owner)
        async with self._lock:
            if key in self._events:
                return False
            self._events[key] = event
            return True

    async def get(
        self, installation_id: int, repo: str, sha: str, event_type: ActivityEventType, owner: str
    ) -> ActivityEvent | None:
        async with self._lock:
            return self._events.get((installation_id, repo, sha, event_type, owner))

    async def count_since(
        self,
        installation_id: int,
        owner: str,
        event_types: list[ActivityEventType],
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
        event_types: list[ActivityEventType],
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

    async def find_recent(
        self,
        installation_id: int,
        repo: str,
        sha: str,
        check_name: str,
        event_type: ActivityEventType,
        since: datetime,
    ) -> list[ActivityEvent]:
        async with self._lock:
            return [
                event
                for event in self._events.values()
                if event.installation_id == installation_id
                and event.repo == repo
                and event.sha == sha
                and event.check_name == check_name
                and event.event_type == event_type
                and event.ts >= since
            ]

    async def retype(self, event: ActivityEvent, new_type: ActivityEventType) -> bool:
        old_key = (event.installation_id, event.repo, event.sha, event.event_type, event.owner)
        new_key = (event.installation_id, event.repo, event.sha, new_type, event.owner)
        async with self._lock:
            if old_key not in self._events:
                return False
            if new_key in self._events:
                return False
            retyped = dataclasses.replace(self._events.pop(old_key), event_type=new_type)
            self._events[new_key] = retyped
            return True
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `docker compose run --rm app pytest tests/adapters/memory/test_activity_event_repository.py -v`
Expected: PASS (17 tests)

- [ ] **Step 5: Commit**

```bash
git add src/mergency/adapters/memory/activity_event_repository.py tests/adapters/memory/test_activity_event_repository.py
git commit -m "refactor: rename InMemoryEventRepository to InMemoryActivityEventRepository"
```

---

### Task 4: Rename the Postgres adapter — `SqlAlchemyEventRepository` → `SqlAlchemyActivityEventRepository`

**Files:**
- Modify: `src/mergency/adapters/db/event_repository.py` → renamed to `src/mergency/adapters/db/activity_event_repository.py`
- Test: `tests/adapters/db/test_event_repository.py` → renamed to `tests/adapters/db/test_activity_event_repository.py`

This adapter is not mentioned by ADR 0013 (it postdates the ADR) but needs the identical rename for the same reason as the memory adapter. Its tests require a running Postgres (`db_engine` fixture in `tests/adapters/db/conftest.py`, unaffected by this rename) via `docker compose up -d postgres`.

- [ ] **Step 1: Rename the test file and update it to the new names**

```bash
git mv tests/adapters/db/test_event_repository.py tests/adapters/db/test_activity_event_repository.py
perl -pi -e 's/mergency\.adapters\.db\.event_repository/mergency.adapters.db.activity_event_repository/g' tests/adapters/db/test_activity_event_repository.py
perl -pi -e 's/mergency\.domain\.models\.event_type/mergency.domain.models.activity_event_type/g' tests/adapters/db/test_activity_event_repository.py
perl -pi -e 's/mergency\.domain\.models\.event\b/mergency.domain.models.activity_event/g' tests/adapters/db/test_activity_event_repository.py
perl -pi -e 's/EventRepository/ActivityEventRepository/g' tests/adapters/db/test_activity_event_repository.py
perl -pi -e 's/EventType/ActivityEventType/g' tests/adapters/db/test_activity_event_repository.py
perl -pi -e 's/\bEvent\b/ActivityEvent/g' tests/adapters/db/test_activity_event_repository.py
docker compose run --rm app ruff check --fix tests/adapters/db/test_activity_event_repository.py
```

- [ ] **Step 2: Start Postgres and run the test to verify it fails (source not renamed yet)**

```bash
docker compose up -d postgres
```

Run: `docker compose run --rm app pytest tests/adapters/db/test_activity_event_repository.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'mergency.adapters.db.activity_event_repository'`

- [ ] **Step 3: Rename the source file**

```bash
git mv src/mergency/adapters/db/event_repository.py src/mergency/adapters/db/activity_event_repository.py
perl -pi -e 's/mergency\.domain\.models\.event_type/mergency.domain.models.activity_event_type/g' src/mergency/adapters/db/activity_event_repository.py
perl -pi -e 's/mergency\.domain\.models\.event\b/mergency.domain.models.activity_event/g' src/mergency/adapters/db/activity_event_repository.py
perl -pi -e 's/EventRepository/ActivityEventRepository/g' src/mergency/adapters/db/activity_event_repository.py
perl -pi -e 's/EventType/ActivityEventType/g' src/mergency/adapters/db/activity_event_repository.py
perl -pi -e 's/\bEvent\b/ActivityEvent/g' src/mergency/adapters/db/activity_event_repository.py
docker compose run --rm app ruff check --fix src/mergency/adapters/db/activity_event_repository.py
```

Resulting `src/mergency/adapters/db/activity_event_repository.py`:

```python
from datetime import datetime

import asyncpg
import sqlalchemy as sa
from sqlalchemy import insert, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine

from mergency.adapters.db.tables import events_table
from mergency.domain.models.daily_event_count import DailyEventCount
from mergency.domain.models.activity_event import ActivityEvent
from mergency.domain.models.activity_event_type import ActivityEventType


class SqlAlchemyActivityEventRepository:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def save_if_new(self, event: ActivityEvent) -> bool:
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
                        check_name=event.check_name,
                    )
                )
        except IntegrityError as error:
            if isinstance(error.orig.__cause__, asyncpg.exceptions.UniqueViolationError):
                return False
            raise
        return True

    async def get(
        self, installation_id: int, repo: str, sha: str, event_type: ActivityEventType, owner: str
    ) -> ActivityEvent | None:
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
        event_types: list[ActivityEventType],
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

    async def daily_counts_since(
        self,
        installation_id: int,
        owner: str,
        event_types: list[ActivityEventType],
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

    async def find_recent(
        self,
        installation_id: int,
        repo: str,
        sha: str,
        check_name: str,
        event_type: ActivityEventType,
        since: datetime,
    ) -> list[ActivityEvent]:
        async with self._engine.connect() as conn:
            rows = (
                await conn.execute(
                    select(events_table).where(
                        events_table.c.installation_id == installation_id,
                        events_table.c.repo == repo,
                        events_table.c.sha == sha,
                        events_table.c.check_name == check_name,
                        events_table.c.event_type == event_type.value,
                        events_table.c.ts >= since,
                    )
                )
            ).all()
        return [_row_to_event(row) for row in rows]

    async def retype(self, event: ActivityEvent, new_type: ActivityEventType) -> bool:
        try:
            async with self._engine.begin() as conn:
                result = await conn.execute(
                    update(events_table)
                    .where(
                        events_table.c.installation_id == event.installation_id,
                        events_table.c.repo == event.repo,
                        events_table.c.sha == event.sha,
                        events_table.c.event_type == event.event_type.value,
                        events_table.c.owner == event.owner,
                    )
                    .values(event_type=new_type.value)
                )
        except IntegrityError as error:
            if isinstance(error.orig.__cause__, asyncpg.exceptions.UniqueViolationError):
                return False
            raise
        return result.rowcount > 0


def _row_to_event(row) -> ActivityEvent:
    return ActivityEvent(
        installation_id=row.installation_id,
        repo=row.repo,
        sha=row.sha,
        event_type=ActivityEventType(row.event_type),
        owner=row.owner,
        ts=row.ts,
        check_name=row.check_name,
    )
```

Note: `events_table` (imported from `adapters/db/tables.py`) is untouched — the Postgres table keeps its `events` name per ADR 0013's consequences (storage vocabulary and code vocabulary are allowed to diverge).

- [ ] **Step 4: Run the test to verify it passes**

Run: `docker compose run --rm app pytest tests/adapters/db/test_activity_event_repository.py -v`
Expected: PASS (16 tests)

- [ ] **Step 5: Commit**

```bash
git add src/mergency/adapters/db/activity_event_repository.py tests/adapters/db/test_activity_event_repository.py
git commit -m "refactor: rename SqlAlchemyEventRepository to SqlAlchemyActivityEventRepository"
```

---

### Task 5: Update `EventClassifier` to produce `ActivityEvent`/`ActivityEventType`

**Files:**
- Modify: `src/mergency/domain/event_classifier.py` (class name unchanged, per the naming decision in Context)
- Test: `tests/domain/test_event_classifier.py` (unchanged filename, imports updated)

- [ ] **Step 1: Update the test file's imports and usages**

```bash
perl -pi -e 's/mergency\.domain\.models\.event_type/mergency.domain.models.activity_event_type/g' tests/domain/test_event_classifier.py
perl -pi -e 's/EventType/ActivityEventType/g' tests/domain/test_event_classifier.py
docker compose run --rm app ruff check --fix tests/domain/test_event_classifier.py
```

`EventClassifier` itself is untouched by these rules (no `\bEvent\b` rule is applied here since the class name stays); only the `EventType` import and its three usages (`EventType.BUILD_FAILURE`, `EventType.REVERT` × 2) change to `ActivityEventType`.

- [ ] **Step 2: Run the test to verify it fails (source not updated yet)**

Run: `docker compose run --rm app pytest tests/domain/test_event_classifier.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'mergency.domain.models.activity_event_type'`

- [ ] **Step 3: Update the source file**

```bash
perl -pi -e 's/mergency\.domain\.models\.event_type/mergency.domain.models.activity_event_type/g' src/mergency/domain/event_classifier.py
perl -pi -e 's/mergency\.domain\.models\.event\b/mergency.domain.models.activity_event/g' src/mergency/domain/event_classifier.py
perl -pi -e 's/EventType/ActivityEventType/g' src/mergency/domain/event_classifier.py
perl -pi -e 's/\bEvent\b/ActivityEvent/g' src/mergency/domain/event_classifier.py
docker compose run --rm app ruff check --fix src/mergency/domain/event_classifier.py
```

Resulting `src/mergency/domain/event_classifier.py`:

```python
import re

from mergency.domain.models.check_run_signal import CheckRunSignal
from mergency.domain.models.activity_event import ActivityEvent
from mergency.domain.models.activity_event_type import ActivityEventType
from mergency.domain.models.push_signal import PushSignal

_QUALIFYING_CONCLUSIONS = {"failure", "timed_out"}
_REVERT_SUBJECT_PATTERN = re.compile(r'^Revert "')
_REVERT_MENTION = "this reverts commit"


class EventClassifier:
    async def classify(self, signal: CheckRunSignal | PushSignal) -> ActivityEvent | None:
        match signal:
            case CheckRunSignal():
                return self._classify_check_run(signal)
            case PushSignal():
                return self._classify_push(signal)
            case _:
                raise TypeError(f"unsupported signal type: {type(signal)!r}")

    def is_flaky_candidate(self, signal: CheckRunSignal) -> bool:
        if signal.action != "completed":
            return False
        if signal.conclusion != "success":
            return False
        if signal.head_branch != signal.default_branch:
            return False
        if signal.completed_at is None:
            return False
        return True

    def _classify_check_run(self, signal: CheckRunSignal) -> ActivityEvent | None:
        if signal.action != "completed":
            return None
        if signal.conclusion not in _QUALIFYING_CONCLUSIONS:
            return None
        if signal.head_branch != signal.default_branch:
            return None
        if signal.completed_at is None:
            return None
        return ActivityEvent(
            installation_id=signal.installation_id,
            repo=signal.repo,
            sha=signal.sha,
            event_type=ActivityEventType.BUILD_FAILURE,
            owner=None,
            ts=signal.completed_at,
            check_name=signal.check_name,
        )

    def _classify_push(self, signal: PushSignal) -> ActivityEvent | None:
        if signal.ref != f"refs/heads/{signal.default_branch}":
            return None
        for commit in signal.commits:
            if _looks_like_revert(commit.message):
                return ActivityEvent(
                    installation_id=signal.installation_id,
                    repo=signal.repo,
                    sha=commit.sha,
                    event_type=ActivityEventType.REVERT,
                    owner=None,
                    ts=commit.timestamp,
                )
        return None


def _looks_like_revert(message: str) -> bool:
    first_line = message.splitlines()[0] if message else ""
    return bool(_REVERT_SUBJECT_PATTERN.match(first_line)) or _REVERT_MENTION in message.lower()
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `docker compose run --rm app pytest tests/domain/test_event_classifier.py -v`
Expected: PASS (17 tests)

- [ ] **Step 5: Commit**

```bash
git add src/mergency/domain/event_classifier.py tests/domain/test_event_classifier.py
git commit -m "refactor: EventClassifier produces ActivityEvent/ActivityEventType"
```

---

### Task 6: Update `budget_calculator.py`, `budget_history_query.py`, `flaky_test_detector.py`

**Files:**
- Modify: `src/mergency/domain/budget_calculator.py`
- Modify: `src/mergency/domain/budget_history_query.py`
- Modify: `src/mergency/domain/flaky_test_detector.py`
- Test: `tests/domain/test_budget_calculator.py`
- Test: `tests/domain/test_budget_history_query.py`
- Test: `tests/worker/test_report_incident.py` (indirectly — imports `EventType`; its own module gets updated in Task 8, but note it also imports `InMemoryEventRepository`, which is already renamed by Task 3)

None of these three modules mention `Event` (the bare model) directly — only `EventType` and `EventRepository`. `flaky_test_detector.py`'s and `budget_history_query.py`'s tests import `InMemoryEventRepository`, already renamed in Task 3, so this task's test-file updates only touch `EventType`/`Event`/`EventRepository` symbols still pointing at old names.

- [ ] **Step 1: Update the two source-adjacent test files**

```bash
perl -pi -e 's/mergency\.adapters\.memory\.event_repository/mergency.adapters.memory.activity_event_repository/g' tests/domain/test_budget_calculator.py tests/domain/test_budget_history_query.py
perl -pi -e 's/mergency\.domain\.models\.event_type/mergency.domain.models.activity_event_type/g' tests/domain/test_budget_calculator.py tests/domain/test_budget_history_query.py
perl -pi -e 's/mergency\.domain\.models\.event\b/mergency.domain.models.activity_event/g' tests/domain/test_budget_calculator.py tests/domain/test_budget_history_query.py
perl -pi -e 's/EventRepository/ActivityEventRepository/g' tests/domain/test_budget_calculator.py tests/domain/test_budget_history_query.py
perl -pi -e 's/EventType/ActivityEventType/g' tests/domain/test_budget_calculator.py tests/domain/test_budget_history_query.py
perl -pi -e 's/\bEvent\b/ActivityEvent/g' tests/domain/test_budget_calculator.py tests/domain/test_budget_history_query.py
docker compose run --rm app ruff check --fix tests/domain/test_budget_calculator.py tests/domain/test_budget_history_query.py
```

- [ ] **Step 2: Run both tests to verify they fail (source not updated yet)**

Run: `docker compose run --rm app pytest tests/domain/test_budget_calculator.py tests/domain/test_budget_history_query.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'mergency.adapters.memory.activity_event_repository'`

- [ ] **Step 3: Update the three source files**

```bash
perl -pi -e 's/mergency\.domain\.models\.event_type/mergency.domain.models.activity_event_type/g' src/mergency/domain/budget_calculator.py src/mergency/domain/budget_history_query.py src/mergency/domain/flaky_test_detector.py
perl -pi -e 's/mergency\.domain\.ports\.event_repository/mergency.domain.ports.activity_event_repository/g' src/mergency/domain/budget_calculator.py src/mergency/domain/budget_history_query.py src/mergency/domain/flaky_test_detector.py
perl -pi -e 's/EventRepository/ActivityEventRepository/g' src/mergency/domain/budget_calculator.py src/mergency/domain/budget_history_query.py src/mergency/domain/flaky_test_detector.py
perl -pi -e 's/EventType/ActivityEventType/g' src/mergency/domain/budget_calculator.py src/mergency/domain/budget_history_query.py src/mergency/domain/flaky_test_detector.py
docker compose run --rm app ruff check --fix src/mergency/domain/budget_calculator.py src/mergency/domain/budget_history_query.py src/mergency/domain/flaky_test_detector.py
```

Resulting `src/mergency/domain/budget_calculator.py`:

```python
from datetime import datetime, timedelta, timezone

from mergency.domain.models.budget_status import BudgetStatus
from mergency.domain.models.activity_event_type import ActivityEventType
from mergency.domain.ports.activity_event_repository import ActivityEventRepository
from mergency.domain.ports.tenant_config_repository import TenantConfigRepository

_COUNTED_EVENT_TYPES = (ActivityEventType.BUILD_FAILURE, ActivityEventType.REVERT, ActivityEventType.INCIDENT)
_FALLBACK_ROLLING_WINDOW_DAYS = 28
_FALLBACK_MAX_EVENTS_PER_WINDOW = 5


class BudgetCalculator:
    def __init__(
        self, event_repository: ActivityEventRepository, config_repository: TenantConfigRepository
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

Resulting `src/mergency/domain/budget_history_query.py`:

```python
from datetime import datetime, timedelta, timezone

from mergency.domain.budget_calculator import BudgetCalculator
from mergency.domain.models.budget_history import BudgetHistory
from mergency.domain.models.activity_event_type import ActivityEventType
from mergency.domain.ports.activity_event_repository import ActivityEventRepository

_COUNTED_EVENT_TYPES = (ActivityEventType.BUILD_FAILURE, ActivityEventType.REVERT)


class BudgetHistoryQuery:
    def __init__(
        self, budget_calculator: BudgetCalculator, event_repository: ActivityEventRepository
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

Resulting `src/mergency/domain/flaky_test_detector.py`:

```python
from datetime import datetime, timedelta

from mergency.domain.models.activity_event_type import ActivityEventType
from mergency.domain.ports.activity_event_repository import ActivityEventRepository

_CORRELATION_WINDOW = timedelta(hours=24)


class FlakyTestDetector:
    def __init__(self, event_repository: ActivityEventRepository) -> None:
        self._event_repository = event_repository

    async def detect_and_reclassify(
        self,
        installation_id: int,
        repo: str,
        sha: str,
        check_name: str,
        observed_at: datetime,
    ) -> int:
        since = observed_at - _CORRELATION_WINDOW
        prior_failures = await self._event_repository.find_recent(
            installation_id, repo, sha, check_name, ActivityEventType.BUILD_FAILURE, since
        )

        reclassified = 0
        for failure in prior_failures:
            if await self._event_repository.retype(failure, ActivityEventType.FLAKY_TEST):
                reclassified += 1
        return reclassified
```

- [ ] **Step 4: Run both tests to verify they pass**

Run: `docker compose run --rm app pytest tests/domain/test_budget_calculator.py tests/domain/test_budget_history_query.py -v`
Expected: PASS (9 + 2 tests)

`flaky_test_detector.py` has no dedicated test module (verified: no `tests/domain/test_flaky_test_detector.py` — the earlier repo-wide grep found it referenced only in `src/mergency/domain/flaky_test_detector.py` itself and `tests/worker/test_classify_activity_event.py`, which Task 8 covers). Run a quick import check for it here:

Run: `docker compose run --rm app python -c "from mergency.domain.flaky_test_detector import FlakyTestDetector"`
Expected: no error output

- [ ] **Step 5: Commit**

```bash
git add src/mergency/domain/budget_calculator.py src/mergency/domain/budget_history_query.py src/mergency/domain/flaky_test_detector.py tests/domain/test_budget_calculator.py tests/domain/test_budget_history_query.py
git commit -m "refactor: budget calculator/history/flaky-test-detector use ActivityEvent types"
```

---

### Task 7: Rename `api/deps.py`'s `get_event_repository` → `get_activity_event_repository`

**Files:**
- Modify: `src/mergency/api/deps.py`
- Test: `tests/api/test_deps.py`

This is the factory wiring — `get_activity_event_repository()` (renamed) constructs `SqlAlchemyActivityEventRepository`, and every other factory that depends on it (`get_flaky_test_detector`, `get_budget_calculator`, `get_budget_history_query`) calls the renamed accessor instead. `get_event_classifier()` is untouched (see Context).

- [ ] **Step 1: Update the test file**

```bash
perl -pi -e 's/mergency\.adapters\.db\.event_repository/mergency.adapters.db.activity_event_repository/g' tests/api/test_deps.py
perl -pi -e 's/EventRepository/ActivityEventRepository/g' tests/api/test_deps.py
perl -pi -e 's/get_event_repository/get_activity_event_repository/g' tests/api/test_deps.py
perl -pi -e 's/test_event_repository_is_sqlalchemy_backed/test_activity_event_repository_is_sqlalchemy_backed/' tests/api/test_deps.py
docker compose run --rm app ruff check --fix tests/api/test_deps.py
```

This changes lines 84-88 only:

```python
def test_activity_event_repository_is_sqlalchemy_backed():
    from mergency.adapters.db.activity_event_repository import SqlAlchemyActivityEventRepository
    from mergency.api import deps

    assert isinstance(deps.get_activity_event_repository(), SqlAlchemyActivityEventRepository)
```

(`test_get_event_classifier_is_cached_and_resettable`, `test_get_budget_calculator_is_cached_and_resettable`, and `test_get_budget_history_query_is_cached_and_resettable` are untouched — none of these three rules match their contents: they call `deps.get_event_classifier()`, `deps.get_budget_calculator()`, `deps.get_budget_history_query()`, none of which is `get_event_repository`.)

- [ ] **Step 2: Run the test to verify it fails (source not updated yet)**

Run: `docker compose run --rm app pytest tests/api/test_deps.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'mergency.adapters.db.activity_event_repository'`

- [ ] **Step 3: Update the source file**

```bash
perl -pi -e 's/mergency\.adapters\.db\.event_repository/mergency.adapters.db.activity_event_repository/g' src/mergency/api/deps.py
perl -pi -e 's/mergency\.domain\.ports\.event_repository/mergency.domain.ports.activity_event_repository/g' src/mergency/api/deps.py
perl -pi -e 's/EventRepository/ActivityEventRepository/g' src/mergency/api/deps.py
perl -pi -e 's/get_event_repository/get_activity_event_repository/g' src/mergency/api/deps.py
docker compose run --rm app ruff check --fix src/mergency/api/deps.py
```

Resulting `src/mergency/api/deps.py` (only the changed lines shown — everything else is untouched):

```python
from mergency.adapters.db.activity_event_repository import SqlAlchemyActivityEventRepository
...
from mergency.domain.ports.activity_event_repository import ActivityEventRepository
...


@lru_cache
def get_activity_event_repository() -> ActivityEventRepository:
    return SqlAlchemyActivityEventRepository(get_db_engine())


@lru_cache
def get_event_classifier() -> EventClassifier:
    return EventClassifier()


@lru_cache
def get_flaky_test_detector() -> FlakyTestDetector:
    return FlakyTestDetector(get_activity_event_repository())
...


@lru_cache
def get_budget_calculator() -> BudgetCalculator:
    return BudgetCalculator(get_activity_event_repository(), get_tenant_config_repository())


@lru_cache
def get_budget_history_query() -> BudgetHistoryQuery:
    return BudgetHistoryQuery(get_budget_calculator(), get_activity_event_repository())
...


def reset_dependency_caches() -> None:
    get_settings.cache_clear()
    get_tenant_repository.cache_clear()
    get_installation_service.cache_clear()
    get_installation_token_provider.cache_clear()
    get_activity_event_repository.cache_clear()
    get_event_classifier.cache_clear()
    get_flaky_test_detector.cache_clear()
    get_tenant_config_repository.cache_clear()
    get_repository_content_provider.cache_clear()
    get_codeowners_provider.cache_clear()
    get_changed_files_provider.cache_clear()
    get_commit_range_provider.cache_clear()
    get_config_resolver.cache_clear()
    get_ownership_resolver.cache_clear()
    get_db_engine.cache_clear()
    get_budget_calculator.cache_clear()
    get_budget_history_query.cache_clear()
    get_pull_request_files_provider.cache_clear()
    get_pr_comment_client.cache_clear()
    get_pr_budget_evaluator.cache_clear()
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `docker compose run --rm app pytest tests/api/test_deps.py -v`
Expected: PASS (11 tests)

- [ ] **Step 5: Commit**

```bash
git add src/mergency/api/deps.py tests/api/test_deps.py
git commit -m "refactor: rename get_event_repository to get_activity_event_repository"
```

---

### Task 8: Update the worker tasks — `classify_activity_event.py` and `report_incident.py`

**Files:**
- Modify: `src/mergency/worker/classify_activity_event.py` (module/task name unchanged — already correctly scoped per ADR 0013)
- Modify: `src/mergency/worker/report_incident.py`
- Test: `tests/worker/test_classify_activity_event.py`
- Test: `tests/worker/test_report_incident.py`

Both test files monkeypatch `task_module.get_event_repository` — since Task 7 renamed that factory, the monkeypatch targets must be renamed too, or they'd silently monkeypatch a name that no longer exists on the module and each test would hit the real (unmocked) dependency.

- [ ] **Step 1: Update both test files**

```bash
perl -pi -e 's/mergency\.adapters\.memory\.event_repository/mergency.adapters.memory.activity_event_repository/g' tests/worker/test_classify_activity_event.py tests/worker/test_report_incident.py
perl -pi -e 's/mergency\.domain\.models\.event_type/mergency.domain.models.activity_event_type/g' tests/worker/test_classify_activity_event.py tests/worker/test_report_incident.py
perl -pi -e 's/EventRepository/ActivityEventRepository/g' tests/worker/test_classify_activity_event.py tests/worker/test_report_incident.py
perl -pi -e 's/EventType/ActivityEventType/g' tests/worker/test_classify_activity_event.py tests/worker/test_report_incident.py
perl -pi -e 's/get_event_repository/get_activity_event_repository/g' tests/worker/test_classify_activity_event.py tests/worker/test_report_incident.py
docker compose run --rm app ruff check --fix tests/worker/test_classify_activity_event.py tests/worker/test_report_incident.py
```

This renames, among others, the two `monkeypatch.setattr(task_module, "get_event_repository", ...)` lines to `monkeypatch.setattr(task_module, "get_activity_event_repository", ...)` in each file, plus every `InMemoryEventRepository` and `EventType.X` reference.

- [ ] **Step 2: Run both tests to verify they fail (source not updated yet)**

Run: `docker compose run --rm app pytest tests/worker/test_classify_activity_event.py tests/worker/test_report_incident.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'mergency.adapters.memory.activity_event_repository'`

- [ ] **Step 3: Update both source files**

```bash
perl -pi -e 's/mergency\.domain\.models\.event\b/mergency.domain.models.activity_event/g' src/mergency/worker/classify_activity_event.py src/mergency/worker/report_incident.py
perl -pi -e 's/mergency\.domain\.models\.event_type/mergency.domain.models.activity_event_type/g' src/mergency/worker/classify_activity_event.py src/mergency/worker/report_incident.py
perl -pi -e 's/\bEvent\b/ActivityEvent/g' src/mergency/worker/classify_activity_event.py src/mergency/worker/report_incident.py
perl -pi -e 's/EventType/ActivityEventType/g' src/mergency/worker/classify_activity_event.py src/mergency/worker/report_incident.py
perl -pi -e 's/get_event_repository/get_activity_event_repository/g' src/mergency/worker/classify_activity_event.py src/mergency/worker/report_incident.py
docker compose run --rm app ruff check --fix src/mergency/worker/classify_activity_event.py src/mergency/worker/report_incident.py
```

Resulting `src/mergency/worker/classify_activity_event.py`:

```python
import asyncio
import dataclasses
import logging

from mergency.adapters.github.check_run_signal_parser import parse_check_run_signal
from mergency.adapters.github.push_signal_parser import parse_push_signal
from mergency.api.deps import (
    get_changed_files_provider,
    get_config_resolver,
    get_event_classifier,
    get_activity_event_repository,
    get_flaky_test_detector,
    get_ownership_resolver,
)
from mergency.domain.models.check_run_signal import CheckRunSignal
from mergency.domain.models.activity_event import ActivityEvent
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
    event_classifier = get_event_classifier()
    event = await event_classifier.classify(signal)
    if event is not None:
        changed_files = await _changed_files_for(signal, event)
        config = await get_config_resolver().resolve(event.installation_id, event.repo)
        owners = await get_ownership_resolver().resolve_owners(
            event.installation_id, event.repo, changed_files, config.default_team
        )

        event_repository = get_activity_event_repository()
        for owner in owners:
            await event_repository.save_if_new(dataclasses.replace(event, owner=owner))
        return

    if isinstance(signal, CheckRunSignal) and event_classifier.is_flaky_candidate(signal):
        await get_flaky_test_detector().detect_and_reclassify(
            signal.installation_id, signal.repo, signal.sha, signal.check_name, signal.completed_at
        )


async def _changed_files_for(signal: CheckRunSignal | PushSignal, event: ActivityEvent) -> list[str]:
    if isinstance(signal, PushSignal):
        commit = next(commit for commit in signal.commits if commit.sha == event.sha)
        return commit.files
    return await get_changed_files_provider().files_changed_in_commit(
        event.installation_id, event.repo, event.sha
    )
```

Resulting `src/mergency/worker/report_incident.py`:

```python
import asyncio
from datetime import datetime

from mergency.api.deps import (
    get_changed_files_provider,
    get_commit_range_provider,
    get_config_resolver,
    get_activity_event_repository,
    get_ownership_resolver,
)
from mergency.domain.models.activity_event import ActivityEvent
from mergency.domain.models.activity_event_type import ActivityEventType
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
    event_repository = get_activity_event_repository()

    for sha in shas:
        changed_files = await get_changed_files_provider().files_changed_in_commit(
            installation_id, repo, sha
        )
        owners = await get_ownership_resolver().resolve_owners(
            installation_id, repo, changed_files, config.default_team
        )
        for owner in owners:
            await event_repository.save_if_new(
                ActivityEvent(
                    installation_id=installation_id,
                    repo=repo,
                    sha=sha,
                    event_type=ActivityEventType.INCIDENT,
                    owner=owner,
                    ts=occurred_at,
                )
            )
```

`ruff check --fix`'s isort pass (Step 3, already run above) reorders the `mergency.api.deps` import block alphabetically — `get_activity_event_repository` sorts before `get_changed_files_provider` in `classify_activity_event.py`'s import list and before `get_commit_range_provider` in `report_incident.py`'s; confirm this with the ruff run rather than hand-ordering it.

- [ ] **Step 4: Run both tests to verify they pass**

Run: `docker compose run --rm app pytest tests/worker/test_classify_activity_event.py tests/worker/test_report_incident.py -v`
Expected: PASS (13 + 3 tests)

- [ ] **Step 5: Commit**

```bash
git add src/mergency/worker/classify_activity_event.py src/mergency/worker/report_incident.py tests/worker/test_classify_activity_event.py tests/worker/test_report_incident.py
git commit -m "refactor: worker tasks use ActivityEvent/ActivityEventType and get_activity_event_repository"
```

---

### Task 9: Update `tests/api/test_budget_query.py` and run the full suite

**Files:**
- Test: `tests/api/test_budget_query.py`

This is the last remaining consumer (the historical-query HTTP endpoint's integration test) — it imports `InMemoryEventRepository`, `Event`, `EventType` directly and constructs an `Event(...)` inline. No source change is needed for this task; everything it depends on (`InMemoryActivityEventRepository`, `ActivityEvent`, `ActivityEventType`, `BudgetHistoryQuery`, `get_budget_history_query`) already exists after Tasks 1-7.

- [ ] **Step 1: Update the test file**

```bash
perl -pi -e 's/mergency\.adapters\.memory\.event_repository/mergency.adapters.memory.activity_event_repository/g' tests/api/test_budget_query.py
perl -pi -e 's/mergency\.domain\.models\.event_type/mergency.domain.models.activity_event_type/g' tests/api/test_budget_query.py
perl -pi -e 's/mergency\.domain\.models\.event\b/mergency.domain.models.activity_event/g' tests/api/test_budget_query.py
perl -pi -e 's/EventRepository/ActivityEventRepository/g' tests/api/test_budget_query.py
perl -pi -e 's/EventType/ActivityEventType/g' tests/api/test_budget_query.py
perl -pi -e 's/\bEvent\b/ActivityEvent/g' tests/api/test_budget_query.py
docker compose run --rm app ruff check --fix tests/api/test_budget_query.py
```

- [ ] **Step 2: Run the test to verify it passes** (nothing on the source side was left unrenamed by Tasks 1-7, so this should go straight to green — no red step needed here)

Run: `docker compose run --rm app pytest tests/api/test_budget_query.py -v`
Expected: PASS (6 tests)

- [ ] **Step 3: Run the entire test suite and static checks**

```bash
docker compose up -d postgres
docker compose run --rm app pytest -v
docker compose run --rm app ruff check .
docker compose run --rm app python -c "
from mergency.domain.models.activity_event import ActivityEvent
from mergency.domain.models.activity_event_type import ActivityEventType
from mergency.domain.ports.activity_event_repository import ActivityEventRepository
from mergency.adapters.memory.activity_event_repository import InMemoryActivityEventRepository
from mergency.adapters.db.activity_event_repository import SqlAlchemyActivityEventRepository
from mergency.api import deps
assert not hasattr(deps, 'get_event_repository')
print('OK: renamed symbols import cleanly, old accessor is gone')
"
grep -rn "class Event\b\|class EventType\b\|class EventRepository\b\|InMemoryEventRepository\|SqlAlchemyEventRepository\|get_event_repository\b" src tests || echo "OK: no old names remain"
```

Expected: full suite passes, `ruff check .` reports no issues, the Python import check prints `OK`, and the final `grep` finds nothing (prints `OK: no old names remain`).

- [ ] **Step 4: Commit**

```bash
git add tests/api/test_budget_query.py
git commit -m "refactor: budget query integration test uses ActivityEvent/ActivityEventType"
```

---

### Task 10: Close out ADR 0013 and this plan

**Files:**
- Modify: `docs/adr/0013-activity-event-model-naming.md`
- Modify: `docs/plan/0017-rename-event-to-activity-event.md` (this file)

- [ ] **Step 1: Mark ADR 0013 accepted**

In `docs/adr/0013-activity-event-model-naming.md`, change:

```markdown
## Status

📋 proposed
```

to:

```markdown
## Status

✅ accepted (implemented — see `docs/plan/0017-rename-event-to-activity-event.md`)
```

- [ ] **Step 2: Mark this plan implemented**

In this file's header, change `> **For agentic workers:** ...` block's preceding status — add a `## Status` section right after the title if one does not already exist (per `CLAUDE.md`'s plan-file convention, mirroring `docs/plan/0016-deploy-to-incident-traceability.md`):

```markdown
## Status

✅ implemented
```

Insert it directly under the title, before the `> **For agentic workers:**` callout.

- [ ] **Step 3: Commit**

```bash
git add docs/adr/0013-activity-event-model-naming.md docs/plan/0017-rename-event-to-activity-event.md
git commit -m "docs: mark ADR 0013 and its implementation plan accepted/implemented"
```

---

## Verification

End-to-end confirmation that the rename is complete and nothing regressed:

```bash
docker compose up -d postgres
docker compose run --rm app pytest -v
docker compose run --rm app ruff check .
grep -rn "class Event\b\|class EventType\b\|class EventRepository\b\|InMemoryEventRepository\|SqlAlchemyEventRepository\|get_event_repository\b\|domain\.models\.event\b\|domain\.models\.event_type\b\|domain\.ports\.event_repository\b\|adapters\.memory\.event_repository\b\|adapters\.db\.event_repository\b" src tests
```

Expected:
- The full pytest suite passes (all layers: domain models, ports have no direct tests, memory adapter, db adapter, `EventClassifier`, `BudgetCalculator`, `BudgetHistoryQuery`, `FlakyTestDetector` (import-only check), both worker tasks, `api/deps.py`, and the budget-query HTTP integration test).
- `ruff check .` reports no lint or import-order issues.
- The `grep` for every old name/module-path pattern returns **no matches** anywhere in `src/` or `tests/`.
- `git log --oneline -10` shows one commit per task, each independently reviewable.
- `docs/adr/0013-activity-event-model-naming.md`'s Status line reads `✅ accepted (implemented — ...)`.
- No change to `alembic/versions/*.py` or `adapters/db/tables.py` — the Postgres `events` table and its columns are untouched, confirming the rename stayed a Python-identifier-only change per ADR 0013's consequences.
