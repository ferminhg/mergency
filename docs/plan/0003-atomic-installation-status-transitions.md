# Atomic Installation Status Transitions Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the check-then-act race and the duplicated status-transition logic accepted in `docs/adr/0002-installation-status-transitions-non-atomic.md`, and resolve the suspend/unsuspend source-of-truth asymmetry noted in the same ADR.

**Architecture:** Add a single atomic `TenantRepository.transition(installation_id, status)` method — implemented as one `asyncio.Lock`-guarded read-modify-write inside `InMemoryTenantRepository` — and make `InstallationService` use it for every lifecycle transition (`deleted`, `suspended`, `unsuspended`) instead of each call site reimplementing "fetch, replace status, store". `handle_installation_unsuspended` changes from taking a full `Installation` (trusting the incoming webhook payload) to taking just an `installation_id` (trusting the stored record), matching how `handle_installation_suspended` already behaves.

**Tech Stack:** Python 3.12, pytest/pytest-asyncio, Docker Compose (no new dependencies).

---

## Status

implemented

## Context

`docs/adr/0002-installation-status-transitions-non-atomic.md` accepted two known issues in the Task 4 code from `docs/plan/0001-github-app-scaffolding.md`, deferring the fix until either `InMemoryTenantRepository` is replaced by a Postgres-backed adapter, or concurrent workers are introduced:

1. `InstallationService.handle_installation_suspended` composes `TenantRepository.get` then `TenantRepository.upsert` with an `await` boundary in between — each call is individually lock-protected, but the read-modify-write sequence across them is not.
2. The "fetch (or already have) an installation, replace its `status`, persist" pattern is reimplemented independently in three places: `InMemoryTenantRepository.mark_deleted`, `InstallationService.handle_installation_suspended`, and `InstallationService.handle_installation_unsuspended` (with a different input shape — a full `Installation` from the webhook payload instead of a stored-record lookup).

This plan implements the fix the ADR describes as the eventual remedy: a single atomic `TenantRepository.transition(installation_id, status)` method used by all three call sites, and resolves the noted asymmetry by making `handle_installation_unsuspended` trust the stored record (like `handle_installation_suspended`) instead of the incoming webhook payload. Once this lands, ADR 0002's `## Consequences` section should be updated to note it was implemented ahead of the originally planned trigger condition (see Task 5).

No new files or directories beyond one new test file — this is a refactor of `src/mergency/domain/ports/tenant_repository.py`, `src/mergency/adapters/memory/tenant_repository.py`, `src/mergency/domain/installation_service.py`, and `src/mergency/api/webhooks.py`.

## Implementation steps

### Task 1: Add atomic `transition` to the repository port and in-memory adapter

**Files:**
- Modify: `src/mergency/domain/ports/tenant_repository.py`
- Modify: `src/mergency/adapters/memory/tenant_repository.py`
- Test: `tests/adapters/memory/test_tenant_repository.py` (new)
- Create: `tests/adapters/memory/__init__.py` (empty)

This task is additive only — `mark_deleted` stays in place for now (removed in Task 4, once nothing calls it) so the diff is reviewable on its own without breaking existing callers.

- [ ] **Step 1: Write the failing test**

Create `tests/adapters/memory/__init__.py` (empty file), then create `tests/adapters/memory/test_tenant_repository.py`:

```python
import pytest

from mergency.adapters.memory.tenant_repository import InMemoryTenantRepository
from mergency.domain.models.installation import Installation
from mergency.domain.models.tenant_status import TenantStatus


def _installation(status: TenantStatus = TenantStatus.ACTIVE) -> Installation:
    return Installation(
        installation_id=42,
        account_login="acme",
        account_type="Organization",
        status=status,
        repository_selection="all",
    )


@pytest.fixture
def repository() -> InMemoryTenantRepository:
    return InMemoryTenantRepository()


async def test_transition_updates_status_and_returns_updated_record(repository):
    await repository.upsert(_installation())

    updated = await repository.transition(42, TenantStatus.SUSPENDED)

    assert updated is not None
    assert updated.status == TenantStatus.SUSPENDED
    stored = await repository.get(42)
    assert stored is not None
    assert stored.status == TenantStatus.SUSPENDED


async def test_transition_preserves_other_fields(repository):
    await repository.upsert(_installation())

    updated = await repository.transition(42, TenantStatus.DELETED)

    assert updated is not None
    assert updated.account_login == "acme"
    assert updated.repository_selection == "all"


async def test_transition_on_unknown_installation_returns_none(repository):
    updated = await repository.transition(999, TenantStatus.SUSPENDED)

    assert updated is None
    assert await repository.get(999) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker compose run --rm app pytest tests/adapters/memory/test_tenant_repository.py -v`
Expected: FAIL with `AttributeError: 'InMemoryTenantRepository' object has no attribute 'transition'`

- [ ] **Step 3: Add `transition` to the `TenantRepository` protocol**

Replace the contents of `src/mergency/domain/ports/tenant_repository.py` with:

```python
from typing import Protocol

from mergency.domain.models.installation import Installation
from mergency.domain.models.tenant_status import TenantStatus


class TenantRepository(Protocol):
    async def upsert(self, installation: Installation) -> None: ...

    async def mark_deleted(self, installation_id: int) -> None: ...

    async def get(self, installation_id: int) -> Installation | None: ...

    async def transition(
        self, installation_id: int, status: TenantStatus
    ) -> Installation | None: ...
```

- [ ] **Step 4: Implement `transition` in `InMemoryTenantRepository`**

Replace the contents of `src/mergency/adapters/memory/tenant_repository.py` with:

```python
import asyncio
import dataclasses

from mergency.domain.models.installation import Installation
from mergency.domain.models.tenant_status import TenantStatus


class InMemoryTenantRepository:
    def __init__(self) -> None:
        self._installations: dict[int, Installation] = {}
        self._lock = asyncio.Lock()

    async def upsert(self, installation: Installation) -> None:
        async with self._lock:
            self._installations[installation.installation_id] = installation

    async def mark_deleted(self, installation_id: int) -> None:
        async with self._lock:
            existing = self._installations.get(installation_id)
            if existing is not None:
                self._installations[installation_id] = dataclasses.replace(
                    existing, status=TenantStatus.DELETED
                )

    async def get(self, installation_id: int) -> Installation | None:
        async with self._lock:
            return self._installations.get(installation_id)

    async def transition(
        self, installation_id: int, status: TenantStatus
    ) -> Installation | None:
        async with self._lock:
            existing = self._installations.get(installation_id)
            if existing is None:
                return None
            updated = dataclasses.replace(existing, status=status)
            self._installations[installation_id] = updated
            return updated
```

- [ ] **Step 5: Run test to verify it passes**

Run: `docker compose run --rm app pytest tests/adapters/memory/test_tenant_repository.py -v`
Expected: PASS (3 passed)

- [ ] **Step 6: Commit**

```bash
git add src/mergency/domain/ports/tenant_repository.py src/mergency/adapters/memory/tenant_repository.py tests/adapters/memory/__init__.py tests/adapters/memory/test_tenant_repository.py
git commit -m "feat: add atomic transition method to TenantRepository"
```

---

### Task 2: Migrate `handle_installation_deleted` and `handle_installation_suspended` to use `transition`

**Files:**
- Modify: `src/mergency/domain/installation_service.py`
- Test: `tests/domain/test_installation_service.py` (existing — no new tests, must keep passing unchanged)

These two methods keep their external signature and behavior; only their internal implementation changes to call the new atomic `transition` instead of `mark_deleted` (for delete) or a `get` + `upsert` pair (for suspend). Existing tests already pin the required black-box behavior, so this step is verified by re-running them rather than adding new ones.

- [ ] **Step 1: Run the existing tests to confirm the current baseline passes**

Run: `docker compose run --rm app pytest tests/domain/test_installation_service.py -v`
Expected: PASS (5 passed) — this is the pre-refactor baseline.

- [ ] **Step 2: Replace `handle_installation_deleted` and `handle_installation_suspended` implementations**

In `src/mergency/domain/installation_service.py`, replace the whole file with:

```python
import dataclasses

from mergency.domain.models.installation import Installation
from mergency.domain.models.tenant_status import TenantStatus
from mergency.domain.ports.tenant_repository import TenantRepository


class InstallationService:
    def __init__(self, tenant_repository: TenantRepository) -> None:
        self._tenant_repository = tenant_repository

    async def handle_installation_created(self, installation: Installation) -> None:
        await self._tenant_repository.upsert(installation)

    async def handle_installation_deleted(self, installation_id: int) -> None:
        await self._tenant_repository.transition(installation_id, TenantStatus.DELETED)

    async def handle_installation_suspended(self, installation_id: int) -> None:
        await self._tenant_repository.transition(installation_id, TenantStatus.SUSPENDED)

    async def handle_installation_unsuspended(self, installation: Installation) -> None:
        active = dataclasses.replace(installation, status=TenantStatus.ACTIVE)
        await self._tenant_repository.upsert(active)
```

(`handle_installation_unsuspended` is left untouched here on purpose — Task 3 changes it. This step only touches the two methods above.)

- [ ] **Step 3: Run the tests to verify they still pass**

Run: `docker compose run --rm app pytest tests/domain/test_installation_service.py -v`
Expected: PASS (5 passed) — same count and names as the baseline in Step 1, confirming the refactor didn't change behavior.

- [ ] **Step 4: Commit**

```bash
git add src/mergency/domain/installation_service.py
git commit -m "refactor: use atomic transition for installation delete/suspend"
```

---

### Task 3: Fix the suspend/unsuspend source-of-truth asymmetry

**Files:**
- Modify: `src/mergency/domain/installation_service.py`
- Modify: `src/mergency/api/webhooks.py`
- Test: `tests/domain/test_installation_service.py:55-61` (modify existing test)

`handle_installation_unsuspended` currently takes a full `Installation` built from the incoming webhook payload, unlike `handle_installation_suspended`, which trusts the stored record. This step changes `handle_installation_unsuspended` to take just `installation_id: int` and use `transition`, so both suspend and unsuspend agree on the same source of truth (the stored record), closing the asymmetry ADR 0002 flagged.

- [ ] **Step 1: Update the failing test first**

In `tests/domain/test_installation_service.py`, replace the `test_handle_installation_unsuspended_reactivates` test (currently lines 55-61):

```python
async def test_handle_installation_unsuspended_reactivates(service, repository):
    await service.handle_installation_created(_installation(status=TenantStatus.SUSPENDED))
    await service.handle_installation_unsuspended(42)

    stored = await repository.get(42)
    assert stored is not None
    assert stored.status == TenantStatus.ACTIVE
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker compose run --rm app pytest tests/domain/test_installation_service.py::test_handle_installation_unsuspended_reactivates -v`
Expected: FAIL — `TypeError` or assertion error, since `handle_installation_unsuspended` still expects an `Installation` object, not an `int`.

- [ ] **Step 3: Change `handle_installation_unsuspended`'s signature and implementation**

In `src/mergency/domain/installation_service.py`, replace the whole file with:

```python
from mergency.domain.models.installation import Installation
from mergency.domain.models.tenant_status import TenantStatus
from mergency.domain.ports.tenant_repository import TenantRepository


class InstallationService:
    def __init__(self, tenant_repository: TenantRepository) -> None:
        self._tenant_repository = tenant_repository

    async def handle_installation_created(self, installation: Installation) -> None:
        await self._tenant_repository.upsert(installation)

    async def handle_installation_deleted(self, installation_id: int) -> None:
        await self._tenant_repository.transition(installation_id, TenantStatus.DELETED)

    async def handle_installation_suspended(self, installation_id: int) -> None:
        await self._tenant_repository.transition(installation_id, TenantStatus.SUSPENDED)

    async def handle_installation_unsuspended(self, installation_id: int) -> None:
        await self._tenant_repository.transition(installation_id, TenantStatus.ACTIVE)
```

`dataclasses` is no longer used in this file, so its import is dropped too.

- [ ] **Step 4: Run test to verify it passes**

Run: `docker compose run --rm app pytest tests/domain/test_installation_service.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Update the webhook dispatcher to call the new signature**

In `src/mergency/api/webhooks.py`, replace `_handle_installation_event` (currently lines 46-83) with:

```python
async def _handle_installation_event(
    payload: dict, installation_service: InstallationService
) -> None:
    action = payload.get("action")

    try:
        installation_payload = payload["installation"]
        installation_id = installation_payload["id"]

        if action == "deleted":
            await installation_service.handle_installation_deleted(installation_id)
            return

        if action == "suspend":
            await installation_service.handle_installation_suspended(installation_id)
            return

        if action == "unsuspend":
            await installation_service.handle_installation_unsuspended(installation_id)
            return

        if action == "created":
            installation = Installation(
                installation_id=installation_id,
                account_login=installation_payload["account"]["login"],
                account_type=installation_payload["account"]["type"],
                status=TenantStatus.ACTIVE,
                repository_selection=installation_payload["repository_selection"],
            )
            await installation_service.handle_installation_created(installation)
            return

        logger.info("unhandled installation action acknowledged", extra={"action": action})
    except KeyError as error:
        logger.warning(
            "installation payload missing expected field, acknowledged without processing",
            extra={"action": action, "missing_field": str(error)},
        )
```

This only restructures the `if`/`elif` chain so `unsuspend` no longer shares a branch with `created` — it no longer needs `account`/`repository_selection` from the payload at all, since it now trusts the stored record via `installation_id`.

- [ ] **Step 6: Run the full test suite to check for regressions**

Run: `docker compose run --rm app pytest -v`
Expected: PASS, all tests (including `tests/api/test_webhooks.py`, which does not exercise `unsuspend` today and is unaffected).

- [ ] **Step 7: Commit**

```bash
git add src/mergency/domain/installation_service.py src/mergency/api/webhooks.py tests/domain/test_installation_service.py
git commit -m "fix: make unsuspend trust the stored installation record, not the webhook payload"
```

---

### Task 4: Remove the now-unused `mark_deleted` method

**Files:**
- Modify: `src/mergency/domain/ports/tenant_repository.py`
- Modify: `src/mergency/adapters/memory/tenant_repository.py`

After Task 2, nothing calls `TenantRepository.mark_deleted` any more (`handle_installation_deleted` uses `transition`). Confirmed by `grep -rn "mark_deleted" --include="*.py" .` returning only the port and adapter definitions at this point. Removing it finishes the deduplication the ADR called for: one status-transition code path (`transition`), not two.

- [ ] **Step 1: Confirm no remaining callers**

Run: `grep -rn "mark_deleted" --include="*.py" .`
Expected output: only the two definition lines, in `src/mergency/domain/ports/tenant_repository.py` and `src/mergency/adapters/memory/tenant_repository.py` — no call sites.

- [ ] **Step 2: Remove `mark_deleted` from the port**

In `src/mergency/domain/ports/tenant_repository.py`, remove the line:

```python
    async def mark_deleted(self, installation_id: int) -> None: ...
```

The file becomes:

```python
from typing import Protocol

from mergency.domain.models.installation import Installation
from mergency.domain.models.tenant_status import TenantStatus


class TenantRepository(Protocol):
    async def upsert(self, installation: Installation) -> None: ...

    async def get(self, installation_id: int) -> Installation | None: ...

    async def transition(
        self, installation_id: int, status: TenantStatus
    ) -> Installation | None: ...
```

- [ ] **Step 3: Remove `mark_deleted` from `InMemoryTenantRepository`**

In `src/mergency/adapters/memory/tenant_repository.py`, remove the `mark_deleted` method:

```python
    async def mark_deleted(self, installation_id: int) -> None:
        async with self._lock:
            existing = self._installations.get(installation_id)
            if existing is not None:
                self._installations[installation_id] = dataclasses.replace(
                    existing, status=TenantStatus.DELETED
                )
```

The file becomes:

```python
import asyncio
import dataclasses

from mergency.domain.models.installation import Installation
from mergency.domain.models.tenant_status import TenantStatus


class InMemoryTenantRepository:
    def __init__(self) -> None:
        self._installations: dict[int, Installation] = {}
        self._lock = asyncio.Lock()

    async def upsert(self, installation: Installation) -> None:
        async with self._lock:
            self._installations[installation.installation_id] = installation

    async def get(self, installation_id: int) -> Installation | None:
        async with self._lock:
            return self._installations.get(installation_id)

    async def transition(
        self, installation_id: int, status: TenantStatus
    ) -> Installation | None:
        async with self._lock:
            existing = self._installations.get(installation_id)
            if existing is None:
                return None
            updated = dataclasses.replace(existing, status=status)
            self._installations[installation_id] = updated
            return updated
```

- [ ] **Step 4: Run the full test suite and lint**

Run: `docker compose run --rm app pytest -v`
Expected: PASS, all tests.

Run: `docker compose run --rm app ruff check src tests`
Expected: no errors (confirms no unused imports or dead references were left behind).

- [ ] **Step 5: Commit**

```bash
git add src/mergency/domain/ports/tenant_repository.py src/mergency/adapters/memory/tenant_repository.py
git commit -m "chore: remove unused mark_deleted now that transition covers it"
```

---

### Task 5: Record the ADR outcome

**Files:**
- Modify: `docs/adr/0002-installation-status-transitions-non-atomic.md`

ADRs are append-only records (per `CLAUDE.md`'s Plans as code section, the same spirit applies here) — don't delete or rewrite the original decision, add a note that it was implemented.

- [ ] **Step 1: Append an implementation note to the ADR**

At the end of `docs/adr/0002-installation-status-transitions-non-atomic.md`, after the existing `## Consequences` section, add:

```markdown

## Update (implemented)

The atomic `TenantRepository.transition(installation_id, status)` method described in `## Consequences` above was implemented in `docs/plan/0003-atomic-installation-status-transitions.md`, ahead of the originally planned trigger condition (Postgres migration or concurrent workers) — see that plan's `## Context` for the rationale. `InstallationService.handle_installation_suspended`, `handle_installation_deleted`, and `handle_installation_unsuspended` all use `transition` now; the duplicated `mark_deleted` method was removed. The suspend/unsuspend source-of-truth asymmetry is also resolved: both now trust the stored record via `installation_id`, rather than `handle_installation_unsuspended` trusting the incoming webhook payload.
```

- [ ] **Step 2: Commit**

```bash
git add docs/adr/0002-installation-status-transitions-non-atomic.md
git commit -m "docs: record that ADR 0002's deferred fix has been implemented"
```

## Verification

After all five tasks are complete, confirm the whole fix end-to-end:

1. Run the full test suite: `docker compose run --rm app pytest -v` — expect all tests passing, including the three new `tests/adapters/memory/test_tenant_repository.py` tests and the updated `test_handle_installation_unsuspended_reactivates`.
2. Run lint: `docker compose run --rm app ruff check src tests` — expect no errors.
3. Confirm the duplication is gone: `grep -rn "dataclasses.replace" --include="*.py" src/` should show exactly one call site left (`InMemoryTenantRepository.transition`), not three.
4. Confirm the port surface is what the ADR asked for: `grep -n "async def" src/mergency/domain/ports/tenant_repository.py` should list exactly `upsert`, `get`, and `transition` — no `mark_deleted`.
5. Confirm the asymmetry is resolved: `grep -n "async def handle_installation_unsuspended" -A 2 src/mergency/domain/installation_service.py` should show it takes `installation_id: int`, matching `handle_installation_suspended`'s shape.
