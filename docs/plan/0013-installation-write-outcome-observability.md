# Installation Write-Outcome Observability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make it possible to tell, from outside the process, whether an installation-lifecycle webhook actually changed anything — by logging a warning when a `transition` targets an unknown installation, and by adding a minimal internal read endpoint to inspect stored installation state.

**Architecture:** `InstallationService.handle` starts inspecting the result of `TenantRepository.transition` and logs a warning (still returning normally, still acking `200` to GitHub) when the targeted `installation_id` is unknown. A new `api/internal.py` router adds `GET /internal/installations/{installation_id}`, backed by the already-existing `TenantRepository.get`, mounted alongside the webhook router in `api/app.py`.

**Tech Stack:** Python 3.12, FastAPI, pytest/pytest-asyncio (`asyncio_mode = "auto"`), Docker Compose (no new dependencies).

---

## Status

implemented

## Context

This plan implements [ADR 0015](../adr/0015-installation-write-outcome-observability.md) (issue [#28](https://github.com/ferminhg/mergency/issues/28)).

Today, `InstallationService.handle` ([installation_service.py:11-16](src/mergency/domain/installation_service.py:11)) calls `self._tenant_repository.transition(installation_id, status)` for a `TransitionInstallation` command but discards the return value. `InMemoryTenantRepository.transition` ([tenant_repository.py:21-30](src/mergency/adapters/memory/tenant_repository.py:21)) returns `None` when `installation_id` isn't in the store, meaning a `suspend`/`unsuspend`/`deleted` webhook for an installation that was never created (or already deleted) silently does nothing, and the caller (`_handle_installation_event` in `webhooks.py`) has no way to know. There is also no route to read installation state back — the only mounted route is `POST /webhooks/github` ([app.py](src/mergency/api/app.py)).

ADR 0015 chose two independent, additive fixes (see the ADR for the full list of rejected alternatives, including "make no-op writes raise/return non-200" — rejected because GitHub webhooks expect a fast `2xx` ack regardless of processing outcome, a convention this repo already follows for malformed payloads via the `except KeyError` branch in `_handle_installation_event`):

1. Log a warning when `transition` returns `None`, still acking `200`.
2. Add `GET /internal/installations/{installation_id}` → the stored `Installation` or `404`. Explicitly internal/unauthenticated for now (no auth model exists yet — that's ADR 0009, not this).

This plan puts the no-op check in `InstallationService.handle` rather than in `_handle_installation_event`: `handle` is the one calling `transition` and already pattern-matches on command type, so it can inspect the result at the same call site without `webhooks.py` needing to know about `TenantRepository` return semantics. `webhooks.py` is unchanged by this plan — [tests/api/test_webhooks.py](tests/api/test_webhooks.py) keeps passing unmodified.

Confirmed against current code:
- `TenantRepository.transition` ([tenant_repository.py port](src/mergency/domain/ports/tenant_repository.py:12)) already returns `Installation | None` — no port change needed.
- `TenantRepository.get` ([tenant_repository.py port](src/mergency/domain/ports/tenant_repository.py:10)) already exists and is unused by any route — no repository change needed for Task 2.
- `deps.get_tenant_repository` ([deps.py:29-31](src/mergency/api/deps.py:29)) already exists and is what the new route will depend on.
- FastAPI (`>=0.115`, pinned in `pyproject.toml`) serializes a returned `@dataclass` (like `Installation`) via its default `jsonable_encoder`, including nested `str`-subclass `Enum` fields like `TenantStatus` — no Pydantic model needed for the response.

## Implementation steps

### Task 1: Log a warning on no-op transitions

**Files:**
- Modify: `src/mergency/domain/installation_service.py`
- Modify: `tests/domain/test_installation_service.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/domain/test_installation_service.py` (after the existing tests, keeping the existing imports and fixtures):

```python
async def test_handle_transition_on_unknown_installation_logs_warning(service, caplog):
    with caplog.at_level("WARNING"):
        await service.handle(TransitionInstallation(installation_id=999, status=TenantStatus.SUSPENDED))

    assert len(caplog.records) == 1
    record = caplog.records[0]
    assert record.levelname == "WARNING"
    assert record.installation_id == 999
    assert record.status == "suspended"


async def test_handle_transition_on_known_installation_does_not_log(service, repository, caplog):
    await service.handle(CreateInstallation(installation=_installation()))

    with caplog.at_level("WARNING"):
        await service.handle(TransitionInstallation(installation_id=42, status=TenantStatus.SUSPENDED))

    assert caplog.records == []
```

- [ ] **Step 2: Run tests to verify the first one fails**

Run: `docker compose run --rm app pytest tests/domain/test_installation_service.py -v`
Expected: `test_handle_transition_on_unknown_installation_logs_warning` FAILS with `assert 0 == 1` (no records logged); the rest, including `test_handle_transition_on_known_installation_does_not_log`, PASS (nothing is logged today either way).

- [ ] **Step 3: Add the warning log to `InstallationService.handle`**

Replace the full contents of `src/mergency/domain/installation_service.py`:

```python
import logging

from mergency.domain.models.create_installation_command import CreateInstallation
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
                await self._tenant_repository.upsert(installation)
            case TransitionInstallation(installation_id=installation_id, status=status):
                updated = await self._tenant_repository.transition(installation_id, status)
                if updated is None:
                    logger.warning(
                        "transition targeted unknown installation, acknowledged as no-op",
                        extra={"installation_id": installation_id, "status": status.value},
                    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `docker compose run --rm app pytest tests/domain/test_installation_service.py -v`
Expected: PASS (7 passed)

- [ ] **Step 5: Commit**

```bash
git add src/mergency/domain/installation_service.py tests/domain/test_installation_service.py
git commit -m "feat: log warning when installation transition targets unknown installation_id"
```

---

### Task 2: Add the internal installation-read endpoint

**Files:**
- Create: `src/mergency/api/internal.py`
- Modify: `src/mergency/api/app.py`
- Create: `tests/api/test_internal.py`

- [ ] **Step 1: Write the failing tests**

`tests/api/test_internal.py`:

```python
import pytest
from httpx import ASGITransport, AsyncClient

from mergency.adapters.memory.tenant_repository import InMemoryTenantRepository
from mergency.api.app import app
from mergency.api.deps import get_tenant_repository
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


@pytest.fixture(autouse=True)
def override_dependencies():
    repository = InMemoryTenantRepository()
    app.dependency_overrides[get_tenant_repository] = lambda: repository

    yield repository

    app.dependency_overrides.clear()


async def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def test_get_known_installation_returns_stored_state(override_dependencies):
    await override_dependencies.upsert(_installation())

    async with await _client() as client:
        response = await client.get("/internal/installations/42")

    assert response.status_code == 200
    body = response.json()
    assert body["installation_id"] == 42
    assert body["account_login"] == "acme"
    assert body["status"] == "active"


async def test_get_unknown_installation_returns_404(override_dependencies):
    async with await _client() as client:
        response = await client.get("/internal/installations/999")

    assert response.status_code == 404
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `docker compose run --rm app pytest tests/api/test_internal.py -v`
Expected: FAIL with `404 Not Found` on the first test (no route mounted yet, `ModuleNotFoundError` guarded against since the test file itself imports only existing modules).

- [ ] **Step 3: Write the internal router**

`src/mergency/api/internal.py`:

```python
from fastapi import APIRouter, Depends, HTTPException

from mergency.api.deps import get_tenant_repository
from mergency.domain.models.installation import Installation
from mergency.domain.ports.tenant_repository import TenantRepository

router = APIRouter()


@router.get("/internal/installations/{installation_id}")
async def get_installation(
    installation_id: int,
    tenant_repository: TenantRepository = Depends(get_tenant_repository),
) -> Installation:
    installation = await tenant_repository.get(installation_id)
    if installation is None:
        raise HTTPException(status_code=404, detail="installation not found")
    return installation
```

- [ ] **Step 4: Mount the internal router**

Modify `src/mergency/api/app.py`:

```python
from fastapi import FastAPI

from mergency.api.internal import router as internal_router
from mergency.api.webhooks import router as webhooks_router


def create_app() -> FastAPI:
    app = FastAPI(title="mergency")
    app.include_router(webhooks_router)
    app.include_router(internal_router)
    return app


app = create_app()
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `docker compose run --rm app pytest tests/api/test_internal.py -v`
Expected: PASS (2 passed)

- [ ] **Step 6: Commit**

```bash
git add src/mergency/api/internal.py src/mergency/api/app.py tests/api/test_internal.py
git commit -m "feat: add internal GET /internal/installations/{installation_id} endpoint"
```

---

## Verification

Run the full suite and lints to confirm nothing else regressed:

```bash
docker compose run --rm app pytest -v
docker compose run --rm app ruff check .
```

Expected: all tests pass (existing suite plus the 4 new tests from this plan), `ruff check` reports no issues.

Manual end-to-end check (mirrors the original bug report from ADR 0015 — signed curl requests against the running app):

```bash
docker compose up -d app
```

```bash
docker compose logs -f app
```

In another terminal, send a `suspend` webhook for an installation that was never created, and confirm:
1. The response is still `200 OK`.
2. The app logs a `WARNING` line for `installation_id`/`status` matching the request.
3. `curl http://localhost:8000/internal/installations/<that-id>` returns `404`.

Then send a `created` webhook for the same `installation_id`, and confirm `curl http://localhost:8000/internal/installations/<that-id>` now returns `200` with the stored installation JSON.

Once verified end-to-end, update this plan's `## Status` line to `implemented`.
