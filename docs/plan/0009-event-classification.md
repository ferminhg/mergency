# Event classification: build failures and reverts

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn raw `push` and `check_run` GitHub webhooks into classified domain `Event`s (`build_failure`, `revert`), per ADR 0005 (`docs/adr/0005-event-classification-build-failures-and-reverts.md`), while keeping the hexagonal domain/adapters/api boundary intact.

**Tracks:** [GitHub issue #12](https://github.com/ferminhg/mergency/issues/12).

---

## Status

implemented

## Context

The webhook receiver (`src/mergency/api/webhooks.py`) currently only handles the `installation` and `installation_repositories` events; every other event type — including `push` and `check_run` — falls into a catch-all `else` branch that just logs `"event acknowledged, processing not yet implemented"` and returns 200. ADR 0005 is the next roadmap item: classify those two event types into the `build_failure`/`revert` domain events that `ARQUITECTURE.md`'s "Event classifier" pipeline stage and README's "What counts as an error (v1)" section describe:

- **`build_failure`**: a `check_run` webhook, `action: completed`, `check_run.conclusion` in `{failure, timed_out}`, on the repository's default branch (not a feature-branch PR check).
- **`revert`**: a `push` webhook to the default branch containing a commit whose message matches the standard revert pattern (`Revert "<original subject>"`) or explicitly names the commit/PR it reverts.

This plan is deliberately scoped to classification + in-memory persistence only. Ownership resolution (`owner` field, ADR 0006) and budget calculation (ADR 0007, which is also where real Postgres persistence gets introduced) are out of scope — `Event.owner` stays `None`.

**Plan numbering note:** `docs/plan/0008-installation-webhook-command-translator.md` (the `InstallationCommand`/`parse_installation_command` refactor of the installation webhook flow) merged to `main` while this plan was being written, so this is `docs/plan/0009`, not `0008`. That merge changed `webhooks.py`'s `_handle_installation_event` internals but not its `if x_github_event == ...` dispatch shape, and did not touch `tests/api/test_webhooks.py` — both were re-verified against the current `main` before finalizing this plan, so Task 9 below applies cleanly on top of it.

## Design decisions

**1. Adapter parsing vs. domain classification split.** Two pure translator functions in `adapters/github/` — `parse_check_run_signal(payload: dict) -> CheckRunSignal` and `parse_push_signal(payload: dict) -> PushSignal` — do nothing but reshape GitHub's JSON into small frozen-dataclass "signal" value objects (raise a bare `KeyError` on a missing field, no business logic, no branching). This mirrors the shape `adapters/github/installation_command_parser.py` already established for installation webhooks. All qualifying/disqualifying decisions (action must be `completed`, conclusion must be in the qualifying set, branch must equal the default branch, the revert-message heuristic) live in a new domain `EventClassifier` service. This keeps 100% of ADR 0005's business rules testable without HTTP or GitHub's JSON shape in view, and keeps `adapters/` a thin, swappable translation layer.

**2. `EventClassifier` shape.** One public entry point, mirroring the single-entry-point shape `InstallationService.handle(command)` already uses:

```python
class EventClassifier:
    def __init__(self, event_repository: EventRepository) -> None: ...
    async def classify(self, signal: CheckRunSignal | PushSignal) -> Event | None: ...
```

`classify` returns the `Event` only when it both qualifies **and** was newly persisted (not a duplicate); `None` covers "doesn't qualify" and "duplicate redelivery" alike — the caller doesn't need to tell them apart, it just does nothing further either way.

**3. Idempotency / `EventRepository` shape.** A single atomic `save_if_new(event) -> bool`, keyed on the ADR's exact dedupe tuple `(installation_id, repo, sha, event_type)`, plus a `get(...)` read for adapter tests — avoids a separate `exists` + `save` TOCTOU race. The in-memory adapter mirrors `InMemoryTenantRepository`'s `asyncio.Lock`-guarded dict.

**4. Webhook → Celery → domain wiring.** `webhooks.py` stays a thin dispatcher — no parsing happens there. `push` and `check_run` enqueue the new job with the raw, already-HMAC-verified payload dict plus the event-type string:

```python
elif x_github_event in ("push", "check_run"):
    classify_activity_event.delay(x_github_event, payload)
```

`worker/classify_activity_event.py` is the **first `@celery_app.task` in the codebase** (today's `celery_app.py` is a bare `Celery(...)` stub with no tasks). It's the driving adapter that does parse → classify → persist, reusing `mergency.api.deps`'s plain `@lru_cache` factories (`get_event_classifier`) as the single composition root shared by both the FastAPI and worker entry points — `api/deps.py` has no FastAPI import today, so this is a safe, no-new-infra reuse. `celery_app.py` gains `include=["mergency.worker.classify_activity_event"]` so the task registers without a manual import cycle.

Domain purity holds: `domain/event_classifier.py` and `domain/models/*` import nothing from `celery`, `fastapi`, `github`, or `sqlalchemy`.

**5. Revert heuristic (v1, ADR-accepted).** First line of the commit message matches `^Revert "` **or** the full message contains `this reverts commit` (case-insensitive) — covers both cases README/ADR 0005 name. One small pure helper inside `EventClassifier`, unit-tested directly.

**6. `check_run` filtering stays in the domain.** `action == "completed"` is checked inside `EventClassifier`, not in the adapter parser or `webhooks.py` — keeps every classification rule in one place, fully unit-testable without HTTP.

## Directory structure (new/changed files)

```
src/mergency/
├── domain/
│   ├── models/
│   │   ├── event_type.py            # EventType(str, Enum): BUILD_FAILURE, REVERT
│   │   ├── event.py                 # Event — installation_id, repo, sha, event_type, owner, ts
│   │   ├── check_run_signal.py      # CheckRunSignal
│   │   ├── push_commit.py           # PushCommit
│   │   └── push_signal.py           # PushSignal
│   ├── ports/
│   │   └── event_repository.py      # EventRepository (Protocol)
│   └── event_classifier.py          # EventClassifier
├── adapters/
│   ├── memory/
│   │   └── event_repository.py      # InMemoryEventRepository
│   └── github/
│       ├── check_run_signal_parser.py
│       └── push_signal_parser.py
├── worker/
│   ├── celery_app.py                # modified: include=[...]
│   └── classify_activity_event.py   # first @celery_app.task
└── api/
    ├── deps.py                      # modified: get_event_repository, get_event_classifier
    └── webhooks.py                  # modified: dispatch push/check_run

tests/
├── domain/
│   ├── models/
│   │   └── test_event.py
│   └── test_event_classifier.py
├── adapters/
│   ├── memory/test_event_repository.py
│   └── github/
│       ├── test_check_run_signal_parser.py
│       └── test_push_signal_parser.py
├── worker/
│   ├── __init__.py
│   └── test_classify_activity_event.py
└── api/test_webhooks.py             # modified (retarget one existing test, add two)
```

---

## Task 1: `EventType` enum + `Event` model

**Files:** Create `tests/domain/models/test_event.py`, `src/mergency/domain/models/event_type.py`, `src/mergency/domain/models/event.py`.

- [ ] **Step 1: Write the test**

```python
# tests/domain/models/test_event.py
import dataclasses
from datetime import datetime, timezone

import pytest

from mergency.domain.models.event import Event
from mergency.domain.models.event_type import EventType


def test_event_type_values_match_adr():
    assert EventType.BUILD_FAILURE == "build_failure"
    assert EventType.REVERT == "revert"


def test_event_is_immutable():
    event = Event(
        installation_id=1,
        repo="acme/widgets",
        sha="abc123",
        event_type=EventType.BUILD_FAILURE,
        owner=None,
        ts=datetime.now(timezone.utc),
    )

    with pytest.raises(dataclasses.FrozenInstanceError):
        event.owner = "team-x"
```

Run: `docker compose run --rm app pytest tests/domain/models/test_event.py -v`
Expected: fails with `ModuleNotFoundError` (files don't exist yet).

- [ ] **Step 2: Implement**

```python
# src/mergency/domain/models/event_type.py
from enum import Enum


class EventType(str, Enum):
    BUILD_FAILURE = "build_failure"
    REVERT = "revert"
```

```python
# src/mergency/domain/models/event.py
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
```

Run: `docker compose run --rm app pytest tests/domain/models/test_event.py -v`
Expected: 2 passed.

- [ ] **Step 3:** `git add` the three files and commit: `feat: add Event domain model and EventType enum`.

---

## Task 2: `EventRepository` port + in-memory adapter

**Files:** Create `tests/adapters/memory/test_event_repository.py`, `src/mergency/domain/ports/event_repository.py`, `src/mergency/adapters/memory/event_repository.py`.

- [ ] **Step 1: Write the test**

```python
# tests/adapters/memory/test_event_repository.py
from datetime import datetime, timezone

from mergency.adapters.memory.event_repository import InMemoryEventRepository
from mergency.domain.models.event import Event
from mergency.domain.models.event_type import EventType


def _event(sha: str = "abc123") -> Event:
    return Event(
        installation_id=1,
        repo="acme/widgets",
        sha=sha,
        event_type=EventType.BUILD_FAILURE,
        owner=None,
        ts=datetime.now(timezone.utc),
    )


async def test_save_if_new_persists_and_reports_new():
    repository = InMemoryEventRepository()

    saved = await repository.save_if_new(_event())

    assert saved is True
    stored = await repository.get(1, "acme/widgets", "abc123", EventType.BUILD_FAILURE)
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


async def test_get_returns_none_when_absent():
    repository = InMemoryEventRepository()

    assert await repository.get(1, "acme/widgets", "missing", EventType.BUILD_FAILURE) is None
```

Run: `docker compose run --rm app pytest tests/adapters/memory/test_event_repository.py -v`
Expected: fails with `ModuleNotFoundError`.

- [ ] **Step 2: Implement**

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
```

```python
# src/mergency/adapters/memory/event_repository.py
import asyncio

from mergency.domain.models.event import Event
from mergency.domain.models.event_type import EventType


class InMemoryEventRepository:
    def __init__(self) -> None:
        self._events: dict[tuple[int, str, str, EventType], Event] = {}
        self._lock = asyncio.Lock()

    async def save_if_new(self, event: Event) -> bool:
        key = (event.installation_id, event.repo, event.sha, event.event_type)
        async with self._lock:
            if key in self._events:
                return False
            self._events[key] = event
            return True

    async def get(
        self, installation_id: int, repo: str, sha: str, event_type: EventType
    ) -> Event | None:
        async with self._lock:
            return self._events.get((installation_id, repo, sha, event_type))
```

Run: `docker compose run --rm app pytest tests/adapters/memory/test_event_repository.py -v`
Expected: 4 passed.

- [ ] **Step 3:** commit: `feat: add EventRepository port and in-memory adapter`.

---

## Task 3: Activity signal value objects

**Files:** Create `tests/domain/models/test_activity_signal.py`, `src/mergency/domain/models/check_run_signal.py`, `src/mergency/domain/models/push_commit.py`, `src/mergency/domain/models/push_signal.py`.

- [ ] **Step 1: Write the test**

```python
# tests/domain/models/test_activity_signal.py
import dataclasses
from datetime import datetime, timezone

import pytest

from mergency.domain.models.check_run_signal import CheckRunSignal
from mergency.domain.models.push_commit import PushCommit
from mergency.domain.models.push_signal import PushSignal


def test_check_run_signal_is_immutable():
    signal = CheckRunSignal(
        installation_id=1,
        repo="acme/widgets",
        sha="abc123",
        action="completed",
        conclusion="failure",
        head_branch="main",
        default_branch="main",
        completed_at=datetime.now(timezone.utc),
    )

    with pytest.raises(dataclasses.FrozenInstanceError):
        signal.conclusion = "success"


def test_push_signal_is_immutable():
    commit = PushCommit(sha="abc123", message='Revert "x"', timestamp=datetime.now(timezone.utc))
    signal = PushSignal(
        installation_id=1,
        repo="acme/widgets",
        ref="refs/heads/main",
        default_branch="main",
        commits=[commit],
    )

    with pytest.raises(dataclasses.FrozenInstanceError):
        signal.ref = "refs/heads/other"
```

Run: `docker compose run --rm app pytest tests/domain/models/test_activity_signal.py -v`
Expected: fails with `ModuleNotFoundError`.

- [ ] **Step 2: Implement**

```python
# src/mergency/domain/models/check_run_signal.py
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class CheckRunSignal:
    installation_id: int
    repo: str
    sha: str
    action: str
    conclusion: str | None
    head_branch: str
    default_branch: str
    completed_at: datetime | None
```

```python
# src/mergency/domain/models/push_commit.py
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class PushCommit:
    sha: str
    message: str
    timestamp: datetime
```

```python
# src/mergency/domain/models/push_signal.py
from dataclasses import dataclass

from mergency.domain.models.push_commit import PushCommit


@dataclass(frozen=True)
class PushSignal:
    installation_id: int
    repo: str
    ref: str
    default_branch: str
    commits: list[PushCommit]
```

Run: `docker compose run --rm app pytest tests/domain/models/test_activity_signal.py -v`
Expected: 2 passed.

- [ ] **Step 3:** commit: `feat: add CheckRunSignal/PushSignal activity value objects`.

---

## Task 4: `check_run` payload parser

**Files:** Create `tests/adapters/github/test_check_run_signal_parser.py`, `src/mergency/adapters/github/check_run_signal_parser.py`.

- [ ] **Step 1: Write the test**

```python
# tests/adapters/github/test_check_run_signal_parser.py
import pytest

from mergency.adapters.github.check_run_signal_parser import parse_check_run_signal


def _payload(action="completed", conclusion="failure", head_branch="main", default_branch="main"):
    return {
        "action": action,
        "check_run": {
            "head_sha": "abc123",
            "conclusion": conclusion,
            "completed_at": "2026-09-14T10:00:00Z",
            "check_suite": {"head_branch": head_branch},
        },
        "repository": {"full_name": "acme/widgets", "default_branch": default_branch},
        "installation": {"id": 1},
    }


def test_parses_completed_failure_on_default_branch():
    signal = parse_check_run_signal(_payload())

    assert signal.installation_id == 1
    assert signal.repo == "acme/widgets"
    assert signal.sha == "abc123"
    assert signal.action == "completed"
    assert signal.conclusion == "failure"
    assert signal.head_branch == "main"
    assert signal.default_branch == "main"
    assert signal.completed_at.isoformat() == "2026-09-14T10:00:00+00:00"


def test_parses_non_completed_action_with_null_conclusion():
    payload = _payload(action="in_progress", conclusion=None)
    payload["check_run"]["completed_at"] = None

    signal = parse_check_run_signal(payload)

    assert signal.action == "in_progress"
    assert signal.conclusion is None
    assert signal.completed_at is None


def test_missing_check_run_field_raises_key_error():
    with pytest.raises(KeyError):
        parse_check_run_signal({"action": "completed"})
```

Run: `docker compose run --rm app pytest tests/adapters/github/test_check_run_signal_parser.py -v`
Expected: fails with `ModuleNotFoundError`.

- [ ] **Step 2: Implement**

```python
# src/mergency/adapters/github/check_run_signal_parser.py
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
        action=payload["action"],
        conclusion=check_run["conclusion"],
        head_branch=check_run["check_suite"]["head_branch"],
        default_branch=repository["default_branch"],
        completed_at=datetime.fromisoformat(completed_at) if completed_at else None,
    )
```

Run: `docker compose run --rm app pytest tests/adapters/github/test_check_run_signal_parser.py -v`
Expected: 3 passed.

- [ ] **Step 3:** commit: `feat: add check_run webhook payload parser`.

---

## Task 5: `push` payload parser

**Files:** Create `tests/adapters/github/test_push_signal_parser.py`, `src/mergency/adapters/github/push_signal_parser.py`.

- [ ] **Step 1: Write the test**

```python
# tests/adapters/github/test_push_signal_parser.py
import pytest

from mergency.adapters.github.push_signal_parser import parse_push_signal


def _payload():
    return {
        "ref": "refs/heads/main",
        "repository": {"full_name": "acme/widgets", "default_branch": "main"},
        "installation": {"id": 1},
        "commits": [
            {"id": "sha1", "message": 'Revert "add flaky feature"', "timestamp": "2026-09-14T10:00:00Z"},
        ],
    }


def test_parses_push_with_commits():
    signal = parse_push_signal(_payload())

    assert signal.installation_id == 1
    assert signal.repo == "acme/widgets"
    assert signal.ref == "refs/heads/main"
    assert signal.default_branch == "main"
    assert len(signal.commits) == 1
    assert signal.commits[0].sha == "sha1"
    assert signal.commits[0].message == 'Revert "add flaky feature"'


def test_missing_repository_field_raises_key_error():
    with pytest.raises(KeyError):
        parse_push_signal({"ref": "refs/heads/main", "commits": []})
```

Run: `docker compose run --rm app pytest tests/adapters/github/test_push_signal_parser.py -v`
Expected: fails with `ModuleNotFoundError`.

- [ ] **Step 2: Implement**

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

Run: `docker compose run --rm app pytest tests/adapters/github/test_push_signal_parser.py -v`
Expected: 2 passed.

- [ ] **Step 3:** commit: `feat: add push webhook payload parser`.

---

## Task 6: `EventClassifier` domain service

**Files:** Create `tests/domain/test_event_classifier.py`, `src/mergency/domain/event_classifier.py`.

- [ ] **Step 1: Write the test**

```python
# tests/domain/test_event_classifier.py
from datetime import datetime, timezone

import pytest

from mergency.adapters.memory.event_repository import InMemoryEventRepository
from mergency.domain.event_classifier import EventClassifier
from mergency.domain.models.check_run_signal import CheckRunSignal
from mergency.domain.models.event_type import EventType
from mergency.domain.models.push_commit import PushCommit
from mergency.domain.models.push_signal import PushSignal


@pytest.fixture
def repository() -> InMemoryEventRepository:
    return InMemoryEventRepository()


@pytest.fixture
def classifier(repository) -> EventClassifier:
    return EventClassifier(repository)


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


async def test_duplicate_check_run_delivery_is_not_reclassified(classifier):
    await classifier.classify(_check_run_signal())

    assert await classifier.classify(_check_run_signal()) is None


async def test_recognizes_explicit_revert_mention(classifier):
    event = await classifier.classify(_push_signal(message="Undo bad change\n\nThis reverts commit abc123."))

    assert event is not None
    assert event.event_type == EventType.REVERT
```

Run: `docker compose run --rm app pytest tests/domain/test_event_classifier.py -v`
Expected: fails with `ModuleNotFoundError`.

- [ ] **Step 2: Implement**

```python
# src/mergency/domain/event_classifier.py
import re

from mergency.domain.models.check_run_signal import CheckRunSignal
from mergency.domain.models.event import Event
from mergency.domain.models.event_type import EventType
from mergency.domain.models.push_signal import PushSignal
from mergency.domain.ports.event_repository import EventRepository

_QUALIFYING_CONCLUSIONS = {"failure", "timed_out"}
_REVERT_SUBJECT_PATTERN = re.compile(r'^Revert "')
_REVERT_MENTION = "this reverts commit"


class EventClassifier:
    def __init__(self, event_repository: EventRepository) -> None:
        self._event_repository = event_repository

    async def classify(self, signal: CheckRunSignal | PushSignal) -> Event | None:
        match signal:
            case CheckRunSignal():
                event = self._classify_check_run(signal)
            case PushSignal():
                event = self._classify_push(signal)

        if event is None:
            return None

        saved = await self._event_repository.save_if_new(event)
        return event if saved else None

    def _classify_check_run(self, signal: CheckRunSignal) -> Event | None:
        if signal.action != "completed":
            return None
        if signal.conclusion not in _QUALIFYING_CONCLUSIONS:
            return None
        if signal.head_branch != signal.default_branch:
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
    first_line = message.splitlines()[0]
    return bool(_REVERT_SUBJECT_PATTERN.match(first_line)) or _REVERT_MENTION in message.lower()
```

Run: `docker compose run --rm app pytest tests/domain/test_event_classifier.py -v`
Expected: 9 passed.

- [ ] **Step 3:** commit: `feat: add EventClassifier domain service`.

---

## Task 7: Wire `EventRepository`/`EventClassifier` into `deps.py`

**Files:** Modify `src/mergency/api/deps.py`, `tests/api/test_deps.py`.

- [ ] **Step 1: Add the test** (append to `tests/api/test_deps.py`, keep existing tests untouched)

```python
def test_get_event_classifier_is_cached_and_resettable():
    from mergency.api import deps

    first = deps.get_event_classifier()
    assert deps.get_event_classifier() is first

    deps.reset_dependency_caches()

    assert deps.get_event_classifier() is not first
```

Run: `docker compose run --rm app pytest tests/api/test_deps.py -v`
Expected: new test fails with `AttributeError: module 'mergency.api.deps' has no attribute 'get_event_classifier'`.

- [ ] **Step 2: Implement** — modify `src/mergency/api/deps.py`:

```python
from mergency.adapters.memory.event_repository import InMemoryEventRepository
from mergency.domain.event_classifier import EventClassifier
from mergency.domain.ports.event_repository import EventRepository
```

Add alongside the other factories:

```python
@lru_cache
def get_event_repository() -> EventRepository:
    return InMemoryEventRepository()


@lru_cache
def get_event_classifier() -> EventClassifier:
    return EventClassifier(get_event_repository())
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
```

Run: `docker compose run --rm app pytest tests/api/test_deps.py -v`
Expected: all passed.

- [ ] **Step 3:** commit: `feat: wire EventRepository and EventClassifier into deps`.

---

## Task 8: `classify_activity_event` Celery task

**Files:** Create `tests/worker/__init__.py`, `tests/worker/test_classify_activity_event.py`, `src/mergency/worker/classify_activity_event.py`; modify `src/mergency/worker/celery_app.py`.

- [ ] **Step 1: Write the test**

```python
# tests/worker/test_classify_activity_event.py
import asyncio

from mergency.adapters.memory.event_repository import InMemoryEventRepository
from mergency.domain.event_classifier import EventClassifier
from mergency.domain.models.event_type import EventType
from mergency.worker import classify_activity_event as task_module


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


def test_classify_activity_event_persists_build_failure(monkeypatch):
    repository = InMemoryEventRepository()
    monkeypatch.setattr(task_module, "get_event_classifier", lambda: EventClassifier(repository))

    task_module.classify_activity_event("check_run", _check_run_payload())

    stored = asyncio.run(repository.get(1, "acme/widgets", "abc123", EventType.BUILD_FAILURE))
    assert stored is not None


def test_classify_activity_event_is_idempotent_across_redelivery(monkeypatch):
    repository = InMemoryEventRepository()
    monkeypatch.setattr(task_module, "get_event_classifier", lambda: EventClassifier(repository))

    task_module.classify_activity_event("check_run", _check_run_payload())
    task_module.classify_activity_event("check_run", _check_run_payload())

    stored = asyncio.run(repository.get(1, "acme/widgets", "abc123", EventType.BUILD_FAILURE))
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
Expected: fails with `ModuleNotFoundError`.

- [ ] **Step 2: Implement**

```python
# src/mergency/worker/classify_activity_event.py
import asyncio
import logging

from mergency.adapters.github.check_run_signal_parser import parse_check_run_signal
from mergency.adapters.github.push_signal_parser import parse_push_signal
from mergency.api.deps import get_event_classifier
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

    asyncio.run(get_event_classifier().classify(signal))
```

Modify `src/mergency/worker/celery_app.py`:

```python
from celery import Celery

celery_app = Celery(
    "mergency",
    broker="redis://localhost:6379/0",
    backend="redis://localhost:6379/0",
    include=["mergency.worker.classify_activity_event"],
)
```

Run: `docker compose run --rm app pytest tests/worker/test_classify_activity_event.py -v`
Expected: 4 passed. (Calling `task_module.classify_activity_event(...)` directly executes the task body synchronously in-process — no Redis/broker needed for this test.)

- [ ] **Step 3:** commit: `feat: add classify_activity_event Celery task`.

---

## Task 9: Wire `push`/`check_run` webhook dispatch

**Files:** Modify `src/mergency/api/webhooks.py`, `tests/api/test_webhooks.py`.

- [ ] **Step 1: Update the test file**

Retarget the existing catch-all test — it currently uses `push`, which is about to become a handled event type, so its intent ("an event type we don't handle yet is acknowledged") needs a different event to stay true:

```python
async def test_unhandled_event_type_is_acknowledged(override_dependencies):
    payload = json.dumps({"action": "opened"}).encode()
    headers = _signed_headers(payload, "pull_request")

    async with await _client() as client:
        response = await client.post("/webhooks/github", content=payload, headers=headers)

    assert response.status_code == 200
```

Add two new tests:

```python
async def test_check_run_event_enqueues_classify_activity_event(override_dependencies, monkeypatch):
    from mergency.api import webhooks

    calls = []
    monkeypatch.setattr(webhooks.classify_activity_event, "delay", lambda *a: calls.append(a))

    payload = json.dumps({"action": "completed", "check_run": {}}).encode()
    headers = _signed_headers(payload, "check_run")

    async with await _client() as client:
        response = await client.post("/webhooks/github", content=payload, headers=headers)

    assert response.status_code == 200
    assert calls == [("check_run", {"action": "completed", "check_run": {}})]


async def test_push_event_enqueues_classify_activity_event(override_dependencies, monkeypatch):
    from mergency.api import webhooks

    calls = []
    monkeypatch.setattr(webhooks.classify_activity_event, "delay", lambda *a: calls.append(a))

    payload = json.dumps({"ref": "refs/heads/main"}).encode()
    headers = _signed_headers(payload, "push")

    async with await _client() as client:
        response = await client.post("/webhooks/github", content=payload, headers=headers)

    assert response.status_code == 200
    assert calls == [("push", {"ref": "refs/heads/main"})]
```

Run: `docker compose run --rm app pytest tests/api/test_webhooks.py -v`
Expected: the two new tests fail with `AttributeError: module 'mergency.api.webhooks' has no attribute 'classify_activity_event'`; the retargeted test still passes.

- [ ] **Step 2: Implement** — modify `src/mergency/api/webhooks.py`:

```python
from mergency.worker.classify_activity_event import classify_activity_event
```

```python
    if x_github_event == "installation":
        await _handle_installation_event(payload, installation_service)
    elif x_github_event == "installation_repositories":
        logger.info("installation_repositories event acknowledged, no-op for now")
    elif x_github_event in ("push", "check_run"):
        classify_activity_event.delay(x_github_event, payload)
    else:
        logger.info(
            "event acknowledged, processing not yet implemented",
            extra={"event": x_github_event},
        )
```

Run: `docker compose run --rm app pytest tests/api/test_webhooks.py -v`
Expected: all passed, no real Redis touched (`.delay` is monkeypatched).

- [ ] **Step 3:** commit: `feat: enqueue classify_activity_event for push/check_run webhooks`.

---

## Verification (full suite, after all tasks)

1. Full suite: `docker compose run --rm app pytest -v` — all tests pass, old and new.
2. Lint (if configured): `docker compose run --rm app ruff check src tests` — no errors.
3. Domain purity: `docker compose run --rm app grep -rniE "celery|fastapi|pygithub|sqlalchemy" src/mergency/domain/` — no matches (confirms `EventClassifier` and `domain/models/*` stay framework-free, per `CLAUDE.md`'s hexagonal rule).
4. Business-rule containment: `docker compose run --rm app grep -rn "completed\|failure\|timed_out\|Revert" src/mergency/adapters/` — no matches (confirms the qualifying-conclusion/branch/revert-pattern logic lives only in `domain/event_classifier.py`; adapters only reshape JSON).
5. `git diff` on `tests/api/test_webhooks.py` shows exactly: the retargeted catch-all test plus two additions — no other behavior change.
6. Manual smoke (optional, not part of CI): `docker compose up -d`, send a signed `check_run` webhook with `conclusion: failure` against the default branch via curl, confirm no 500s.
