# Flaky Test Detection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement ADR 0010 — detect that a `check_run` failure on the default branch was flaky (a same-sha, same-check re-run later succeeded) and reclassify it from `EventType.BUILD_FAILURE` to `EventType.FLAKY_TEST` so it stays visible in history but stops consuming budget.

**Architecture:** `EventClassifier` gains a second, narrower check — `is_flaky_candidate` — that recognizes a *successful* `check_run` completion on the default branch (today it only ever produces an `Event` for failing/timed-out completions). A new pure domain service, `FlakyTestDetector`, is injected with the existing `EventRepository` port and, on such a success signal, looks up any `BUILD_FAILURE` event(s) for the same `(installation_id, repo, sha, check_name)` recorded inside a fixed correlation window and retypes them in place to `FLAKY_TEST`. Because `BudgetCalculator`'s allow-list (`_COUNTED_EVENT_TYPES = (BUILD_FAILURE, REVERT)`, ADR 0007) already excludes anything not explicitly listed, no `BudgetCalculator` code changes are needed — adding `FLAKY_TEST` to the enum does not touch budget math, which is exactly the guarantee ADR 0010 asks for. Detection is wired into the existing `classify_activity_event` Celery task, the same seam that already turns raw signals into persisted events.

**Tech Stack:** Python 3.12, SQLAlchemy (async, Postgres) + Alembic, Celery, pytest/pytest-asyncio, Docker Compose — no new dependencies.

---

## Status

proposed

## Context

`docs/adr/0010-flaky-test-signal-v2.md` sketches this direction but leaves several parameters open, deferring them to "real v1 data" that doesn't exist yet. This plan makes those calls explicitly rather than waiting further, since the underlying v1 pieces (ADR 0005–0009) are now live:

- **Correlation key:** `(installation_id, repo, sha, check_name)` — exact match on GitHub's `check_run.name`. This requires a new `check_name` column; today's `events` table and `CheckRunSignal` don't carry it (the existing classifier only needs conclusion/branch/sha to produce a `BUILD_FAILURE`).
- **Correlation window:** 24 hours. Long enough to cover same-day re-runs and re-dispatch retries, short enough that an unrelated failure on the same commit days later (e.g. a rebase-and-recheck workflow) won't be misattributed as "fixed by rerun."
- **Confidence threshold:** a single later delivery with a differing conclusion (prior `failure`/`timed_out` → later `success`) is sufficient. This matches the ADR's own framing of the heuristic as "the simplest signal"; this plan does not implement a retry-count/majority-vote scheme.
- **Non-GitHub-native CI:** out of scope. All `check_run` deliveries are assumed to originate from GitHub Checks/Actions, same as the rest of the classifier.
- **Reclassification, not re-emission:** when the correlated success arrives, the *existing* owner-scoped `BUILD_FAILURE` row(s) are updated in place to `FLAKY_TEST` (original `ts` preserved). No new event is written for the successful rerun itself — a passing check has never produced an event in this codebase, and this plan doesn't change that.

These are treated as this feature's own design decisions (documented here, not silently assumed), not as amendments to the ADR's "left open" note.

## Directory structure (additions only)

```
src/mergency/
├── domain/
│   ├── event_classifier.py            # MODIFY — add is_flaky_candidate, set check_name on BUILD_FAILURE events
│   ├── flaky_test_detector.py         # NEW — FlakyTestDetector service
│   ├── models/
│   │   ├── event.py                   # MODIFY — add check_name: str | None = None
│   │   ├── event_type.py              # MODIFY — add FLAKY_TEST = "flaky_test"
│   │   └── check_run_signal.py        # MODIFY — add check_name: str
│   └── ports/
│       └── event_repository.py        # MODIFY — add find_recent, retype
├── adapters/
│   ├── db/
│   │   ├── tables.py                  # MODIFY — add events.check_name column
│   │   └── event_repository.py        # MODIFY — persist check_name, implement find_recent/retype
│   ├── memory/
│   │   └── event_repository.py        # MODIFY — implement find_recent/retype
│   └── github/
│       └── check_run_signal_parser.py # MODIFY — parse check_run.name
├── api/
│   └── deps.py                        # MODIFY — wire get_flaky_test_detector
└── worker/
    └── classify_activity_event.py     # MODIFY — call FlakyTestDetector on flaky-candidate signals
alembic/versions/
└── <generated>_add_check_name_to_events.py  # NEW — schema migration
tests/
├── domain/
│   ├── test_event_classifier.py       # MODIFY — is_flaky_candidate, check_name propagation
│   ├── test_budget_calculator.py      # MODIFY — regression test: FLAKY_TEST not counted
│   └── test_flaky_test_detector.py    # NEW
├── adapters/
│   ├── db/test_event_repository.py    # MODIFY — check_name persistence, find_recent, retype
│   ├── memory/test_event_repository.py# MODIFY — same, in-memory
│   └── github/test_check_run_signal_parser.py  # MODIFY — check_name parsing
└── worker/
    └── test_classify_activity_event.py # MODIFY — end-to-end rerun-reclassification scenarios
```

---

## Task 1: Reserve `EventType.FLAKY_TEST` and lock in the allow-list guarantee

**Files:**
- Modify: `src/mergency/domain/models/event_type.py`
- Test: `tests/domain/test_budget_calculator.py`

- [ ] **Step 1: Write the failing regression test**

Add to `tests/domain/test_budget_calculator.py`:

```python
async def test_status_for_excludes_flaky_test_events_from_consumption():
    event_repository = InMemoryEventRepository()
    config_repository = InMemoryTenantConfigRepository()
    await config_repository.upsert(
        TenantConfig(1, rolling_window_days=28, default_team="unassigned", max_events_per_window=5, warn_threshold_pct=50)
    )
    now = datetime.now(timezone.utc)
    await event_repository.save_if_new(_event(EventType.FLAKY_TEST, "sha1", "@org/backend-team", now))
    calculator = BudgetCalculator(event_repository, config_repository)

    status = await calculator.status_for(1, "@org/backend-team")

    assert status.consumed == 0
    assert status.remaining_pct == 100.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker compose run --rm app pytest tests/domain/test_budget_calculator.py::test_status_for_excludes_flaky_test_events_from_consumption -v`
Expected: FAIL with `AttributeError: FLAKY_TEST` (the enum member doesn't exist yet).

- [ ] **Step 3: Add the enum member**

In `src/mergency/domain/models/event_type.py`:

```python
from enum import Enum


class EventType(str, Enum):
    BUILD_FAILURE = "build_failure"
    REVERT = "revert"
    FLAKY_TEST = "flaky_test"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `docker compose run --rm app pytest tests/domain/test_budget_calculator.py -v`
Expected: PASS (all tests, including the new one — `BudgetCalculator._COUNTED_EVENT_TYPES` is unchanged, so `FLAKY_TEST` is excluded by default, exactly as ADR 0010 requires).

- [ ] **Step 5: Commit**

```bash
git add src/mergency/domain/models/event_type.py tests/domain/test_budget_calculator.py
git commit -m "feat: reserve EventType.FLAKY_TEST, excluded from budget by default"
```

---

## Task 2: Carry `check_name` on `CheckRunSignal`

**Files:**
- Modify: `src/mergency/domain/models/check_run_signal.py`
- Modify: `src/mergency/adapters/github/check_run_signal_parser.py`
- Test: `tests/adapters/github/test_check_run_signal_parser.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/adapters/github/test_check_run_signal_parser.py`:

```python
def test_parses_check_name():
    signal = parse_check_run_signal(_payload())

    assert signal.check_name == "ci/build"
```

Update the module's `_payload` helper to include a `name` key on `check_run` (required from now on, not optional):

```python
def _payload(action="completed", conclusion="failure", head_branch="main", default_branch="main"):
    return {
        "action": action,
        "check_run": {
            "name": "ci/build",
            "head_sha": "abc123",
            "conclusion": conclusion,
            "completed_at": "2026-09-14T10:00:00Z",
            "check_suite": {"head_branch": head_branch},
        },
        "repository": {"full_name": "acme/widgets", "default_branch": default_branch},
        "installation": {"id": 1},
    }
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker compose run --rm app pytest tests/adapters/github/test_check_run_signal_parser.py::test_parses_check_name -v`
Expected: FAIL with `AttributeError: 'CheckRunSignal' object has no attribute 'check_name'`.

- [ ] **Step 3: Add the field and parse it**

`src/mergency/domain/models/check_run_signal.py`:

```python
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class CheckRunSignal:
    installation_id: int
    repo: str
    sha: str
    check_name: str
    action: str
    conclusion: str | None
    head_branch: str
    default_branch: str
    completed_at: datetime | None
```

`src/mergency/adapters/github/check_run_signal_parser.py`:

```python
from datetime import datetime

from mergency.domain.models.check_run_signal import CheckRunSignal


def parse_check_run_signal(payload: dict) -> CheckRunSignal:
    check_run = payload["check_run"]
    repository = payload["repository"]
    completed_at = check_run["completed_at"]

    return CheckRunSignal(
        installation_id=payload["installation"]["id"],
        repo=repository["full_name"],
        sha=check_run["head_sha"],
        check_name=check_run["name"],
        action=payload["action"],
        conclusion=check_run["conclusion"],
        head_branch=check_run["check_suite"]["head_branch"],
        default_branch=repository["default_branch"],
        completed_at=datetime.fromisoformat(completed_at) if completed_at else None,
    )
```

- [ ] **Step 4: Fix the now-broken `CheckRunSignal(...)` call sites**

`check_name` is a required positional-by-keyword field with no default, so every existing test that constructs `CheckRunSignal(...)` directly needs a `check_name` kwarg. Update `tests/domain/test_event_classifier.py`'s `_check_run_signal` helper:

```python
def _check_run_signal(**overrides) -> CheckRunSignal:
    defaults = dict(
        installation_id=1,
        repo="acme/widgets",
        sha="abc123",
        check_name="ci/build",
        action="completed",
        conclusion="failure",
        head_branch="main",
        default_branch="main",
        completed_at=datetime.now(timezone.utc),
    )
    defaults.update(overrides)
    return CheckRunSignal(**defaults)
```

Also update `tests/worker/test_classify_activity_event.py`'s `_check_run_payload` fixture (used indirectly via the parser) to include `"name": "ci/build"` in its `check_run` dict — same change as Step 1 above, applied to that file's payload builder.

- [ ] **Step 5: Run full test suite to verify nothing else broke**

Run: `docker compose run --rm app pytest -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/mergency/domain/models/check_run_signal.py src/mergency/adapters/github/check_run_signal_parser.py tests/adapters/github/test_check_run_signal_parser.py tests/domain/test_event_classifier.py tests/worker/test_classify_activity_event.py
git commit -m "feat: parse check_run.name into CheckRunSignal.check_name"
```

---

## Task 3: Persist `check_name` on events

**Files:**
- Modify: `src/mergency/domain/models/event.py`
- Modify: `src/mergency/domain/event_classifier.py`
- Modify: `src/mergency/adapters/db/tables.py`
- Modify: `src/mergency/adapters/db/event_repository.py`
- Create: `alembic/versions/<generated>_add_check_name_to_events.py`
- Test: `tests/domain/test_event_classifier.py`
- Test: `tests/adapters/db/test_event_repository.py`

- [ ] **Step 1: Write the failing domain test**

Add to `tests/domain/test_event_classifier.py`:

```python
async def test_build_failure_event_carries_the_check_name(classifier):
    event = await classifier.classify(_check_run_signal(check_name="ci/integration"))

    assert event.check_name == "ci/integration"


async def test_revert_event_has_no_check_name(classifier):
    event = await classifier.classify(_push_signal())

    assert event.check_name is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker compose run --rm app pytest tests/domain/test_event_classifier.py -v`
Expected: FAIL with `AttributeError: 'Event' object has no attribute 'check_name'`.

- [ ] **Step 3: Add `check_name` to the `Event` model**

`src/mergency/domain/models/event.py`:

```python
from dataclasses import dataclass
from datetime import datetime

from mergency.domain.models.event_type import EventType


@dataclass(frozen=True)
class Event:
    installation_id: int
    repo: str
    sha: str
    event_type: EventType
    owner: str | None
    ts: datetime
    check_name: str | None = None
```

- [ ] **Step 4: Populate it from `EventClassifier._classify_check_run`**

In `src/mergency/domain/event_classifier.py`, update the `Event(...)` construction inside `_classify_check_run`:

```python
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
            check_name=signal.check_name,
        )
```

`_classify_push` is unchanged — `check_name` defaults to `None` for `REVERT` events, which is correct (reverts aren't check-run-scoped).

- [ ] **Step 5: Run test to verify it passes**

Run: `docker compose run --rm app pytest tests/domain/test_event_classifier.py -v`
Expected: PASS.

- [ ] **Step 6: Write the failing persistence test**

Add to `tests/adapters/db/test_event_repository.py`:

```python
async def test_save_if_new_persists_check_name(db_engine):
    repository = SqlAlchemyEventRepository(db_engine)
    event = Event(
        installation_id=1,
        repo="acme/widgets",
        sha="abc123",
        event_type=EventType.BUILD_FAILURE,
        owner="@org/team-a",
        ts=datetime.now(timezone.utc),
        check_name="ci/build",
    )

    await repository.save_if_new(event)

    stored = await repository.get(1, "acme/widgets", "abc123", EventType.BUILD_FAILURE, "@org/team-a")
    assert stored.check_name == "ci/build"


async def test_save_if_new_persists_null_check_name_for_revert_events(db_engine):
    repository = SqlAlchemyEventRepository(db_engine)
    event = Event(
        installation_id=1,
        repo="acme/widgets",
        sha="sha1",
        event_type=EventType.REVERT,
        owner="@org/team-a",
        ts=datetime.now(timezone.utc),
    )

    await repository.save_if_new(event)

    stored = await repository.get(1, "acme/widgets", "sha1", EventType.REVERT, "@org/team-a")
    assert stored.check_name is None
```

- [ ] **Step 7: Run test to verify it fails**

Run: `docker compose run --rm app pytest tests/adapters/db/test_event_repository.py -v`
Expected: FAIL — `sa.exc.CompileError` or similar, since `events_table` has no `check_name` column yet.

- [ ] **Step 8: Add the column and update the adapter**

`src/mergency/adapters/db/tables.py` — add one column to `events_table` (after `owner`, before `ts` is fine, but keep it simple and append at the end to avoid reshuffling the existing positional column list):

```python
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
    sa.Column("check_name", sa.String, nullable=True),
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

`src/mergency/adapters/db/event_repository.py` — persist and read it back. Update `save_if_new`'s `insert(...).values(...)` call to add `check_name=event.check_name`, and update `_row_to_event`:

```python
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
                        check_name=event.check_name,
                    )
                )
        except IntegrityError as error:
            if isinstance(error.orig.__cause__, asyncpg.exceptions.UniqueViolationError):
                return False
            raise
        return True
```

```python
def _row_to_event(row) -> Event:
    return Event(
        installation_id=row.installation_id,
        repo=row.repo,
        sha=row.sha,
        event_type=EventType(row.event_type),
        owner=row.owner,
        ts=row.ts,
        check_name=row.check_name,
    )
```

- [ ] **Step 9: Run test to verify it passes**

Run: `docker compose run --rm app pytest tests/adapters/db/test_event_repository.py -v`
Expected: PASS.

- [ ] **Step 10: Generate and fill in the Alembic migration**

Run: `docker compose run --rm app alembic revision -m "add_check_name_to_events"`

This creates `alembic/versions/<generated_id>_add_check_name_to_events.py` with `down_revision = 'f254790a5d55'` (the current head) already filled in by Alembic. Edit its `upgrade`/`downgrade` bodies:

```python
def upgrade() -> None:
    op.add_column("events", sa.Column("check_name", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("events", "check_name")
```

- [ ] **Step 11: Apply the migration locally and verify**

Run: `docker compose run --rm app alembic upgrade head`
Expected: migration applies cleanly with no errors.

- [ ] **Step 12: Run the full suite**

Run: `docker compose run --rm app pytest -v`
Expected: PASS.

- [ ] **Step 13: Commit**

```bash
git add src/mergency/domain/models/event.py src/mergency/domain/event_classifier.py src/mergency/adapters/db/tables.py src/mergency/adapters/db/event_repository.py alembic/versions/*_add_check_name_to_events.py tests/domain/test_event_classifier.py tests/adapters/db/test_event_repository.py
git commit -m "feat: persist check_name on events"
```

---

## Task 4: `EventRepository.find_recent` — look up prior failures for a check

**Files:**
- Modify: `src/mergency/domain/ports/event_repository.py`
- Modify: `src/mergency/adapters/memory/event_repository.py`
- Modify: `src/mergency/adapters/db/event_repository.py`
- Test: `tests/adapters/memory/test_event_repository.py`
- Test: `tests/adapters/db/test_event_repository.py`

- [ ] **Step 1: Write the failing in-memory test**

Add to `tests/adapters/memory/test_event_repository.py`:

```python
async def test_find_recent_returns_matching_events_within_window():
    repository = InMemoryEventRepository()
    now = datetime.now(timezone.utc)
    matching = Event(
        installation_id=1, repo="acme/widgets", sha="abc123",
        event_type=EventType.BUILD_FAILURE, owner="@org/team-a", ts=now, check_name="ci/build",
    )
    await repository.save_if_new(matching)

    found = await repository.find_recent(
        1, "acme/widgets", "abc123", "ci/build", EventType.BUILD_FAILURE, now - timedelta(hours=1)
    )

    assert found == [matching]


async def test_find_recent_excludes_events_outside_the_window():
    repository = InMemoryEventRepository()
    stale_ts = datetime.now(timezone.utc) - timedelta(hours=48)
    await repository.save_if_new(Event(
        installation_id=1, repo="acme/widgets", sha="abc123",
        event_type=EventType.BUILD_FAILURE, owner="@org/team-a", ts=stale_ts, check_name="ci/build",
    ))

    found = await repository.find_recent(
        1, "acme/widgets", "abc123", "ci/build", EventType.BUILD_FAILURE,
        datetime.now(timezone.utc) - timedelta(hours=24),
    )

    assert found == []


async def test_find_recent_excludes_a_different_check_name():
    repository = InMemoryEventRepository()
    now = datetime.now(timezone.utc)
    await repository.save_if_new(Event(
        installation_id=1, repo="acme/widgets", sha="abc123",
        event_type=EventType.BUILD_FAILURE, owner="@org/team-a", ts=now, check_name="ci/lint",
    ))

    found = await repository.find_recent(
        1, "acme/widgets", "abc123", "ci/build", EventType.BUILD_FAILURE, now - timedelta(hours=1)
    )

    assert found == []
```

Check that this test file already imports `timedelta`; if not, add it to the existing `from datetime import ...` line.

- [ ] **Step 2: Run test to verify it fails**

Run: `docker compose run --rm app pytest tests/adapters/memory/test_event_repository.py -v`
Expected: FAIL with `AttributeError: 'InMemoryEventRepository' object has no attribute 'find_recent'`.

- [ ] **Step 3: Add the port method**

`src/mergency/domain/ports/event_repository.py` — add to the `EventRepository` Protocol:

```python
    async def find_recent(
        self,
        installation_id: int,
        repo: str,
        sha: str,
        check_name: str,
        event_type: EventType,
        since: datetime,
    ) -> list[Event]: ...
```

- [ ] **Step 4: Implement it in `InMemoryEventRepository`**

`src/mergency/adapters/memory/event_repository.py` — add the method:

```python
    async def find_recent(
        self,
        installation_id: int,
        repo: str,
        sha: str,
        check_name: str,
        event_type: EventType,
        since: datetime,
    ) -> list[Event]:
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
```

- [ ] **Step 5: Run test to verify it passes**

Run: `docker compose run --rm app pytest tests/adapters/memory/test_event_repository.py -v`
Expected: PASS.

- [ ] **Step 6: Write the failing DB test**

Add to `tests/adapters/db/test_event_repository.py`:

```python
async def test_find_recent_returns_matching_events_within_window(db_engine):
    repository = SqlAlchemyEventRepository(db_engine)
    now = datetime.now(timezone.utc)
    await repository.save_if_new(Event(
        installation_id=1, repo="acme/widgets", sha="abc123",
        event_type=EventType.BUILD_FAILURE, owner="@org/team-a", ts=now, check_name="ci/build",
    ))

    found = await repository.find_recent(
        1, "acme/widgets", "abc123", "ci/build", EventType.BUILD_FAILURE,
        now - timedelta(hours=1),
    )

    assert len(found) == 1
    assert found[0].check_name == "ci/build"


async def test_find_recent_excludes_events_outside_the_window(db_engine):
    repository = SqlAlchemyEventRepository(db_engine)
    stale_ts = datetime.now(timezone.utc) - timedelta(hours=48)
    await repository.save_if_new(Event(
        installation_id=1, repo="acme/widgets", sha="abc123",
        event_type=EventType.BUILD_FAILURE, owner="@org/team-a", ts=stale_ts, check_name="ci/build",
    ))

    found = await repository.find_recent(
        1, "acme/widgets", "abc123", "ci/build", EventType.BUILD_FAILURE,
        datetime.now(timezone.utc) - timedelta(hours=24),
    )

    assert found == []
```

- [ ] **Step 7: Run test to verify it fails**

Run: `docker compose run --rm app pytest tests/adapters/db/test_event_repository.py -v`
Expected: FAIL with `AttributeError: 'SqlAlchemyEventRepository' object has no attribute 'find_recent'`.

- [ ] **Step 8: Implement it in `SqlAlchemyEventRepository`**

`src/mergency/adapters/db/event_repository.py` — add the method:

```python
    async def find_recent(
        self,
        installation_id: int,
        repo: str,
        sha: str,
        check_name: str,
        event_type: EventType,
        since: datetime,
    ) -> list[Event]:
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
```

- [ ] **Step 9: Run test to verify it passes**

Run: `docker compose run --rm app pytest tests/adapters/db/test_event_repository.py -v`
Expected: PASS.

- [ ] **Step 10: Commit**

```bash
git add src/mergency/domain/ports/event_repository.py src/mergency/adapters/memory/event_repository.py src/mergency/adapters/db/event_repository.py tests/adapters/memory/test_event_repository.py tests/adapters/db/test_event_repository.py
git commit -m "feat: add EventRepository.find_recent for check-run correlation lookups"
```

---

## Task 5: `EventRepository.retype` — reclassify an event's type in place

**Files:**
- Modify: `src/mergency/domain/ports/event_repository.py`
- Modify: `src/mergency/adapters/memory/event_repository.py`
- Modify: `src/mergency/adapters/db/event_repository.py`
- Test: `tests/adapters/memory/test_event_repository.py`
- Test: `tests/adapters/db/test_event_repository.py`

- [ ] **Step 1: Write the failing in-memory test**

Add to `tests/adapters/memory/test_event_repository.py`:

```python
async def test_retype_changes_the_event_type_in_place():
    repository = InMemoryEventRepository()
    now = datetime.now(timezone.utc)
    original = Event(
        installation_id=1, repo="acme/widgets", sha="abc123",
        event_type=EventType.BUILD_FAILURE, owner="@org/team-a", ts=now, check_name="ci/build",
    )
    await repository.save_if_new(original)

    retyped = await repository.retype(original, EventType.FLAKY_TEST)

    assert retyped is True
    assert await repository.get(1, "acme/widgets", "abc123", EventType.BUILD_FAILURE, "@org/team-a") is None
    stored = await repository.get(1, "acme/widgets", "abc123", EventType.FLAKY_TEST, "@org/team-a")
    assert stored is not None
    assert stored.ts == now
    assert stored.check_name == "ci/build"


async def test_retype_is_a_noop_when_the_source_event_is_missing():
    repository = InMemoryEventRepository()
    missing = Event(
        installation_id=1, repo="acme/widgets", sha="abc123",
        event_type=EventType.BUILD_FAILURE, owner="@org/team-a", ts=datetime.now(timezone.utc),
    )

    assert await repository.retype(missing, EventType.FLAKY_TEST) is False


async def test_retype_is_a_noop_when_the_target_already_exists():
    repository = InMemoryEventRepository()
    now = datetime.now(timezone.utc)
    original = Event(
        installation_id=1, repo="acme/widgets", sha="abc123",
        event_type=EventType.BUILD_FAILURE, owner="@org/team-a", ts=now, check_name="ci/build",
    )
    already_flaky = Event(
        installation_id=1, repo="acme/widgets", sha="abc123",
        event_type=EventType.FLAKY_TEST, owner="@org/team-a", ts=now, check_name="ci/build",
    )
    await repository.save_if_new(original)
    await repository.save_if_new(already_flaky)

    assert await repository.retype(original, EventType.FLAKY_TEST) is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker compose run --rm app pytest tests/adapters/memory/test_event_repository.py -v`
Expected: FAIL with `AttributeError: 'InMemoryEventRepository' object has no attribute 'retype'`.

- [ ] **Step 3: Add the port method**

`src/mergency/domain/ports/event_repository.py` — add:

```python
    async def retype(self, event: Event, new_type: EventType) -> bool: ...
```

- [ ] **Step 4: Implement it in `InMemoryEventRepository`**

`src/mergency/adapters/memory/event_repository.py` — add `import dataclasses` at the top, and the method:

```python
    async def retype(self, event: Event, new_type: EventType) -> bool:
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

- [ ] **Step 5: Run test to verify it passes**

Run: `docker compose run --rm app pytest tests/adapters/memory/test_event_repository.py -v`
Expected: PASS.

- [ ] **Step 6: Write the failing DB test**

Add to `tests/adapters/db/test_event_repository.py`:

```python
async def test_retype_changes_the_event_type_in_place(db_engine):
    repository = SqlAlchemyEventRepository(db_engine)
    now = datetime.now(timezone.utc)
    original = Event(
        installation_id=1, repo="acme/widgets", sha="abc123",
        event_type=EventType.BUILD_FAILURE, owner="@org/team-a", ts=now, check_name="ci/build",
    )
    await repository.save_if_new(original)

    retyped = await repository.retype(original, EventType.FLAKY_TEST)

    assert retyped is True
    assert await repository.get(1, "acme/widgets", "abc123", EventType.BUILD_FAILURE, "@org/team-a") is None
    stored = await repository.get(1, "acme/widgets", "abc123", EventType.FLAKY_TEST, "@org/team-a")
    assert stored is not None
    assert stored.check_name == "ci/build"


async def test_retype_is_a_noop_when_the_target_already_exists(db_engine):
    repository = SqlAlchemyEventRepository(db_engine)
    now = datetime.now(timezone.utc)
    original = Event(
        installation_id=1, repo="acme/widgets", sha="abc123",
        event_type=EventType.BUILD_FAILURE, owner="@org/team-a", ts=now, check_name="ci/build",
    )
    already_flaky = Event(
        installation_id=1, repo="acme/widgets", sha="abc123",
        event_type=EventType.FLAKY_TEST, owner="@org/team-a", ts=now, check_name="ci/build",
    )
    await repository.save_if_new(original)
    await repository.save_if_new(already_flaky)

    assert await repository.retype(original, EventType.FLAKY_TEST) is False
```

- [ ] **Step 7: Run test to verify it fails**

Run: `docker compose run --rm app pytest tests/adapters/db/test_event_repository.py -v`
Expected: FAIL with `AttributeError: 'SqlAlchemyEventRepository' object has no attribute 'retype'`.

- [ ] **Step 8: Implement it in `SqlAlchemyEventRepository`**

`src/mergency/adapters/db/event_repository.py` — add `update` to the `sqlalchemy` import (`from sqlalchemy import insert, select, update`), and the method:

```python
    async def retype(self, event: Event, new_type: EventType) -> bool:
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
```

This relies on `ux_events_dedupe_key` to turn a collision with an already-`FLAKY_TEST` row into an `IntegrityError` — same pattern `save_if_new` already uses.

- [ ] **Step 9: Run test to verify it passes**

Run: `docker compose run --rm app pytest tests/adapters/db/test_event_repository.py -v`
Expected: PASS.

- [ ] **Step 10: Commit**

```bash
git add src/mergency/domain/ports/event_repository.py src/mergency/adapters/memory/event_repository.py src/mergency/adapters/db/event_repository.py tests/adapters/memory/test_event_repository.py tests/adapters/db/test_event_repository.py
git commit -m "feat: add EventRepository.retype for in-place event reclassification"
```

---

## Task 6: `EventClassifier.is_flaky_candidate`

**Files:**
- Modify: `src/mergency/domain/event_classifier.py`
- Test: `tests/domain/test_event_classifier.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/domain/test_event_classifier.py`:

```python
async def test_is_flaky_candidate_for_a_successful_completion_on_default_branch(classifier):
    signal = _check_run_signal(conclusion="success")

    assert classifier.is_flaky_candidate(signal) is True


async def test_is_not_a_flaky_candidate_when_not_completed(classifier):
    signal = _check_run_signal(conclusion="success", action="in_progress")

    assert classifier.is_flaky_candidate(signal) is False


async def test_is_not_a_flaky_candidate_for_a_failure_conclusion(classifier):
    signal = _check_run_signal(conclusion="failure")

    assert classifier.is_flaky_candidate(signal) is False


async def test_is_not_a_flaky_candidate_off_the_default_branch(classifier):
    signal = _check_run_signal(conclusion="success", head_branch="feature-x")

    assert classifier.is_flaky_candidate(signal) is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker compose run --rm app pytest tests/domain/test_event_classifier.py -v`
Expected: FAIL with `AttributeError: 'EventClassifier' object has no attribute 'is_flaky_candidate'`.

- [ ] **Step 3: Implement the method**

`src/mergency/domain/event_classifier.py` — add a method to `EventClassifier` (the `classify` method and `_classify_check_run`/`_classify_push` are unchanged):

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `docker compose run --rm app pytest tests/domain/test_event_classifier.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/mergency/domain/event_classifier.py tests/domain/test_event_classifier.py
git commit -m "feat: recognize a successful check_run completion as a flaky-rerun candidate"
```

---

## Task 7: `FlakyTestDetector` domain service

**Files:**
- Create: `src/mergency/domain/flaky_test_detector.py`
- Test: `tests/domain/test_flaky_test_detector.py`

- [ ] **Step 1: Write the failing test**

Create `tests/domain/test_flaky_test_detector.py`:

```python
from datetime import datetime, timedelta, timezone

from mergency.adapters.memory.event_repository import InMemoryEventRepository
from mergency.domain.flaky_test_detector import FlakyTestDetector
from mergency.domain.models.event import Event
from mergency.domain.models.event_type import EventType


async def test_reclassifies_a_prior_failure_on_the_same_sha_and_check_within_the_window():
    event_repository = InMemoryEventRepository()
    now = datetime.now(timezone.utc)
    await event_repository.save_if_new(Event(
        installation_id=1, repo="acme/widgets", sha="abc123",
        event_type=EventType.BUILD_FAILURE, owner="@org/team-a", ts=now, check_name="ci/build",
    ))
    detector = FlakyTestDetector(event_repository)

    reclassified = await detector.detect_and_reclassify(
        1, "acme/widgets", "abc123", "ci/build", now + timedelta(hours=1)
    )

    assert reclassified == 1
    assert await event_repository.get(1, "acme/widgets", "abc123", EventType.BUILD_FAILURE, "@org/team-a") is None
    assert await event_repository.get(1, "acme/widgets", "abc123", EventType.FLAKY_TEST, "@org/team-a") is not None


async def test_reclassifies_every_owner_fanned_out_row_for_the_same_check():
    event_repository = InMemoryEventRepository()
    now = datetime.now(timezone.utc)
    await event_repository.save_if_new(Event(
        installation_id=1, repo="acme/widgets", sha="abc123",
        event_type=EventType.BUILD_FAILURE, owner="@org/team-a", ts=now, check_name="ci/build",
    ))
    await event_repository.save_if_new(Event(
        installation_id=1, repo="acme/widgets", sha="abc123",
        event_type=EventType.BUILD_FAILURE, owner="@org/team-b", ts=now, check_name="ci/build",
    ))
    detector = FlakyTestDetector(event_repository)

    reclassified = await detector.detect_and_reclassify(
        1, "acme/widgets", "abc123", "ci/build", now + timedelta(hours=1)
    )

    assert reclassified == 2


async def test_does_not_reclassify_a_failure_outside_the_correlation_window():
    event_repository = InMemoryEventRepository()
    now = datetime.now(timezone.utc)
    await event_repository.save_if_new(Event(
        installation_id=1, repo="acme/widgets", sha="abc123",
        event_type=EventType.BUILD_FAILURE, owner="@org/team-a", ts=now, check_name="ci/build",
    ))
    detector = FlakyTestDetector(event_repository)

    reclassified = await detector.detect_and_reclassify(
        1, "acme/widgets", "abc123", "ci/build", now + timedelta(hours=25)
    )

    assert reclassified == 0
    assert await event_repository.get(1, "acme/widgets", "abc123", EventType.BUILD_FAILURE, "@org/team-a") is not None


async def test_does_not_reclassify_a_failure_for_a_different_check_name():
    event_repository = InMemoryEventRepository()
    now = datetime.now(timezone.utc)
    await event_repository.save_if_new(Event(
        installation_id=1, repo="acme/widgets", sha="abc123",
        event_type=EventType.BUILD_FAILURE, owner="@org/team-a", ts=now, check_name="ci/lint",
    ))
    detector = FlakyTestDetector(event_repository)

    reclassified = await detector.detect_and_reclassify(
        1, "acme/widgets", "abc123", "ci/build", now + timedelta(hours=1)
    )

    assert reclassified == 0


async def test_is_a_noop_when_there_is_no_prior_failure():
    event_repository = InMemoryEventRepository()
    detector = FlakyTestDetector(event_repository)

    reclassified = await detector.detect_and_reclassify(
        1, "acme/widgets", "abc123", "ci/build", datetime.now(timezone.utc)
    )

    assert reclassified == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker compose run --rm app pytest tests/domain/test_flaky_test_detector.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'mergency.domain.flaky_test_detector'`.

- [ ] **Step 3: Implement `FlakyTestDetector`**

Create `src/mergency/domain/flaky_test_detector.py`:

```python
from datetime import datetime, timedelta

from mergency.domain.models.event_type import EventType
from mergency.domain.ports.event_repository import EventRepository

_CORRELATION_WINDOW = timedelta(hours=24)


class FlakyTestDetector:
    def __init__(self, event_repository: EventRepository) -> None:
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
            installation_id, repo, sha, check_name, EventType.BUILD_FAILURE, since
        )

        reclassified = 0
        for failure in prior_failures:
            if await self._event_repository.retype(failure, EventType.FLAKY_TEST):
                reclassified += 1
        return reclassified
```

- [ ] **Step 4: Run test to verify it passes**

Run: `docker compose run --rm app pytest tests/domain/test_flaky_test_detector.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/mergency/domain/flaky_test_detector.py tests/domain/test_flaky_test_detector.py
git commit -m "feat: add FlakyTestDetector domain service"
```

---

## Task 8: Wire detection into `classify_activity_event`

**Files:**
- Modify: `src/mergency/api/deps.py`
- Modify: `src/mergency/worker/classify_activity_event.py`
- Test: `tests/worker/test_classify_activity_event.py`

- [ ] **Step 1: Add DI wiring**

`src/mergency/api/deps.py` — add the import and a cached factory, and register it in `reset_dependency_caches`:

```python
from mergency.domain.flaky_test_detector import FlakyTestDetector
```

```python
@lru_cache
def get_flaky_test_detector() -> FlakyTestDetector:
    return FlakyTestDetector(get_event_repository())
```

In `reset_dependency_caches()`, add:

```python
    get_flaky_test_detector.cache_clear()
```

- [ ] **Step 2: Write the failing end-to-end test**

Add to `tests/worker/test_classify_activity_event.py`. First, extend `_check_run_payload` to accept overrides so success/rerun payloads can be built without duplicating the whole dict:

```python
def _check_run_payload(**overrides):
    payload = {
        "action": "completed",
        "check_run": {
            "name": "ci/build",
            "head_sha": "abc123",
            "conclusion": "failure",
            "completed_at": "2026-09-14T10:00:00Z",
            "check_suite": {"head_branch": "main"},
        },
        "repository": {"full_name": "acme/widgets", "default_branch": "main"},
        "installation": {"id": 1},
    }
    for key, value in overrides.items():
        if key in payload["check_run"]:
            payload["check_run"][key] = value
        else:
            payload[key] = value
    return payload
```

Existing call sites `_check_run_payload()` with no args keep working unchanged.

Then add the wiring to `_wire` so `get_flaky_test_detector` is monkeypatched consistently with `get_event_repository`:

```python
    monkeypatch.setattr(
        task_module, "get_flaky_test_detector", lambda: FlakyTestDetector(event_repository)
    )
```

(add `from mergency.domain.flaky_test_detector import FlakyTestDetector` to the test file's imports)

New test functions:

```python
def test_a_successful_rerun_reclassifies_the_prior_failure_as_flaky(monkeypatch):
    event_repository = _wire(
        monkeypatch,
        codeowners_by_path={"src/build.py": [("TEAM", "@org/team-a")]},
        changed_files=["src/build.py"],
    )
    task_module.classify_activity_event("check_run", _check_run_payload())

    task_module.classify_activity_event(
        "check_run",
        _check_run_payload(conclusion="success", completed_at="2026-09-14T11:00:00Z"),
    )

    assert asyncio.run(
        event_repository.get(1, "acme/widgets", "abc123", EventType.BUILD_FAILURE, "@org/team-a")
    ) is None
    assert asyncio.run(
        event_repository.get(1, "acme/widgets", "abc123", EventType.FLAKY_TEST, "@org/team-a")
    ) is not None


def test_a_successful_rerun_outside_the_correlation_window_does_not_reclassify(monkeypatch):
    event_repository = _wire(
        monkeypatch,
        codeowners_by_path={"src/build.py": [("TEAM", "@org/team-a")]},
        changed_files=["src/build.py"],
    )
    task_module.classify_activity_event("check_run", _check_run_payload())

    task_module.classify_activity_event(
        "check_run",
        _check_run_payload(conclusion="success", completed_at="2026-09-16T10:00:00Z"),
    )

    assert asyncio.run(
        event_repository.get(1, "acme/widgets", "abc123", EventType.BUILD_FAILURE, "@org/team-a")
    ) is not None


def test_a_successful_rerun_for_a_different_check_name_does_not_reclassify(monkeypatch):
    event_repository = _wire(
        monkeypatch,
        codeowners_by_path={"src/build.py": [("TEAM", "@org/team-a")]},
        changed_files=["src/build.py"],
    )
    task_module.classify_activity_event("check_run", _check_run_payload())

    task_module.classify_activity_event(
        "check_run",
        _check_run_payload(name="ci/lint", conclusion="success", completed_at="2026-09-14T11:00:00Z"),
    )

    assert asyncio.run(
        event_repository.get(1, "acme/widgets", "abc123", EventType.BUILD_FAILURE, "@org/team-a")
    ) is not None
```

- [ ] **Step 3: Run test to verify it fails**

Run: `docker compose run --rm app pytest tests/worker/test_classify_activity_event.py -v`
Expected: FAIL — the success payload currently classifies to `None` and is silently dropped, so the `FLAKY_TEST` assertions fail (`BUILD_FAILURE` row still present, `FLAKY_TEST` row absent).

- [ ] **Step 4: Wire `FlakyTestDetector` into the worker task**

`src/mergency/worker/classify_activity_event.py` — import the classifier's new capability is already available via `get_event_classifier()`; add the DI import and branch:

```python
from mergency.api.deps import (
    get_changed_files_provider,
    get_config_resolver,
    get_event_classifier,
    get_event_repository,
    get_flaky_test_detector,
    get_ownership_resolver,
)
```

```python
async def _classify_resolve_and_persist(signal: CheckRunSignal | PushSignal) -> None:
    event_classifier = get_event_classifier()
    event = await event_classifier.classify(signal)
    if event is not None:
        changed_files = await _changed_files_for(signal, event)
        config = await get_config_resolver().resolve(event.installation_id, event.repo)
        owners = await get_ownership_resolver().resolve_owners(
            event.installation_id, event.repo, changed_files, config.default_team
        )

        event_repository = get_event_repository()
        for owner in owners:
            await event_repository.save_if_new(dataclasses.replace(event, owner=owner))
        return

    if isinstance(signal, CheckRunSignal) and event_classifier.is_flaky_candidate(signal):
        await get_flaky_test_detector().detect_and_reclassify(
            signal.installation_id, signal.repo, signal.sha, signal.check_name, signal.completed_at
        )
```

`_changed_files_for` is unchanged.

- [ ] **Step 5: Run test to verify it passes**

Run: `docker compose run --rm app pytest tests/worker/test_classify_activity_event.py -v`
Expected: PASS.

- [ ] **Step 6: Run the full suite and lint**

Run: `docker compose run --rm app pytest -v`
Run: `docker compose run --rm app ruff check .`
Expected: both PASS.

- [ ] **Step 7: Commit**

```bash
git add src/mergency/api/deps.py src/mergency/worker/classify_activity_event.py tests/worker/test_classify_activity_event.py
git commit -m "feat: reclassify build failures as flaky when a same-check rerun succeeds"
```

---

## Verification

End-to-end, after all tasks land:

1. `docker compose up -d postgres` then `docker compose run --rm app alembic upgrade head` — schema includes `events.check_name`.
2. `docker compose run --rm app pytest -v` — full suite green, including the new `tests/domain/test_flaky_test_detector.py` and the rerun scenarios in `tests/worker/test_classify_activity_event.py`.
3. `docker compose run --rm app ruff check .` — clean.
4. Manual smoke test against the running stack (`docker compose up`):
   a. POST a `check_run` webhook payload with `action=completed`, `conclusion=failure`, `head_sha=abc123`, `check_run.name=ci/build`, on the default branch. Confirm via `SELECT * FROM events WHERE sha='abc123'` that a `build_failure` row exists with `check_name='ci/build'`.
   b. POST a second `check_run` webhook for the same `head_sha`/`check_run.name`, `conclusion=success`, timestamped within 24h of the first. Confirm the row's `event_type` is now `flaky_test` (same row, same `ts`, no new row inserted).
   c. Call the owner's budget endpoint (`GET /api/v1/installations/{id}/owners/{owner}/budget`, ADR 0009) and confirm `consumed` does **not** include the reclassified event — the flaky failure is excluded from budget while still visible via the `events` table / any future history view.
   d. POST a third `check_run` webhook for a *different* `head_sha`, `conclusion=failure`, then a same-check success more than 24h later. Confirm the failure row is **not** reclassified (stays `build_failure`), demonstrating the correlation window boundary.
