# Installation Webhook Command Translator Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Split `_handle_installation_event`'s if-chain into two concerns: an adapter-layer translator that maps GitHub's installation webhook JSON into a small domain command, and a domain service that only knows how to execute commands — no GitHub vocabulary left in the dispatch logic.

**Architecture:** Introduce `InstallationCommand` (`CreateInstallation | TransitionInstallation`) in `domain/models/`, a `parse_installation_command` translator in `adapters/github/`, and collapse `InstallationService`'s four methods into one `handle(command)`. `webhooks.py`'s `_handle_installation_event` shrinks to: parse, then dispatch.

**Tech Stack:** Python 3.12, pytest/pytest-asyncio, Docker Compose (no new dependencies).

---

## Status

proposed

## Context

`_handle_installation_event` in [webhooks.py:46-84](src/mergency/api/webhooks.py:46) currently both parses GitHub's installation payload into domain types (`Installation`, `installation_id`) and decides what to call on `InstallationService` — an if-chain mixing adapter parsing with dispatch. `InstallationService` mirrors this by exposing one method per GitHub action name (`handle_installation_created`, `_deleted`, `_suspended`, `_unsuspended`), so the domain layer's public surface is shaped by GitHub's webhook vocabulary rather than by the two things that actually happen to a tenant: it is created, or its status transitions.

This plan applies the parse-then-handle (command) pattern agreed in code review: a translator produces a domain command from the raw payload, and the service executes commands. This is a refactor only — no observable behavior change. [tests/api/test_webhooks.py](tests/api/test_webhooks.py) is the regression guard: it exercises the whole path through raw JSON and HTTP status codes and must pass **unmodified** throughout.

Confirmed against current code: `TenantRepository` ([tenant_repository.py](src/mergency/domain/ports/tenant_repository.py)) already exposes `upsert(installation)` and `transition(installation_id, status) -> Installation | None`, so `InstallationService.handle` can delegate directly to those without any port changes. No new dependencies.

## Implementation steps

### Task 1: Add the `InstallationCommand` domain types

**Files:**
- Create: `tests/domain/models/__init__.py` (empty)
- Create: `tests/domain/models/test_installation_command.py`
- Create: `src/mergency/domain/models/create_installation_command.py`
- Create: `src/mergency/domain/models/transition_installation_command.py`
- Create: `src/mergency/domain/models/installation_command.py`

One class per file, matching the existing convention (`installation.py`, `tenant_status.py`).

- [ ] **Step 1: Write the failing test**

`tests/domain/models/test_installation_command.py`:

```python
import dataclasses

import pytest

from mergency.domain.models.create_installation_command import CreateInstallation
from mergency.domain.models.installation import Installation
from mergency.domain.models.tenant_status import TenantStatus
from mergency.domain.models.transition_installation_command import TransitionInstallation


def _installation() -> Installation:
    return Installation(
        installation_id=42,
        account_login="acme",
        account_type="Organization",
        status=TenantStatus.ACTIVE,
        repository_selection="all",
    )


def test_create_installation_is_immutable():
    command = CreateInstallation(installation=_installation())

    with pytest.raises(dataclasses.FrozenInstanceError):
        command.installation = _installation()


def test_transition_installation_is_immutable():
    command = TransitionInstallation(installation_id=42, status=TenantStatus.SUSPENDED)

    with pytest.raises(dataclasses.FrozenInstanceError):
        command.status = TenantStatus.ACTIVE
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker compose run --rm app pytest tests/domain/models/test_installation_command.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'mergency.domain.models.create_installation_command'`

- [ ] **Step 3: Write `CreateInstallation`**

`src/mergency/domain/models/create_installation_command.py`:

```python
from dataclasses import dataclass

from mergency.domain.models.installation import Installation


@dataclass(frozen=True)
class CreateInstallation:
    installation: Installation
```

- [ ] **Step 4: Write `TransitionInstallation`**

`src/mergency/domain/models/transition_installation_command.py`:

```python
from dataclasses import dataclass

from mergency.domain.models.tenant_status import TenantStatus


@dataclass(frozen=True)
class TransitionInstallation:
    installation_id: int
    status: TenantStatus
```

- [ ] **Step 5: Write the `InstallationCommand` union**

`src/mergency/domain/models/installation_command.py`:

```python
from mergency.domain.models.create_installation_command import CreateInstallation
from mergency.domain.models.transition_installation_command import TransitionInstallation

InstallationCommand = CreateInstallation | TransitionInstallation
```

- [ ] **Step 6: Run test to verify it passes**

Run: `docker compose run --rm app pytest tests/domain/models/test_installation_command.py -v`
Expected: PASS (2 passed)

- [ ] **Step 7: Commit**

```bash
git add tests/domain/models/__init__.py tests/domain/models/test_installation_command.py \
        src/mergency/domain/models/create_installation_command.py \
        src/mergency/domain/models/transition_installation_command.py \
        src/mergency/domain/models/installation_command.py
git commit -m "feat: add InstallationCommand domain types"
```

---

### Task 2: Add the GitHub-payload-to-command translator

**Files:**
- Create: `tests/adapters/github/test_installation_command_parser.py`
- Create: `src/mergency/adapters/github/installation_command_parser.py`

This lives in `adapters/github/` (alongside `signature.py`, `token_manager.py`), not in `api/webhooks.py` — `webhooks.py`'s job is FastAPI routing/HTTP concerns, not GitHub payload shape parsing. This module is the only place allowed to know both the domain vocabulary and GitHub's action strings.

- [ ] **Step 1: Write the failing test**

`tests/adapters/github/test_installation_command_parser.py`:

```python
import pytest

from mergency.adapters.github.installation_command_parser import parse_installation_command
from mergency.domain.models.create_installation_command import CreateInstallation
from mergency.domain.models.tenant_status import TenantStatus
from mergency.domain.models.transition_installation_command import TransitionInstallation


def _payload(action: str, installation_id: int = 1) -> dict:
    return {
        "action": action,
        "installation": {
            "id": installation_id,
            "account": {"login": "acme", "type": "Organization"},
            "repository_selection": "all",
        },
    }


def test_created_action_produces_create_installation_command():
    command = parse_installation_command(_payload("created"))

    assert isinstance(command, CreateInstallation)
    assert command.installation.installation_id == 1
    assert command.installation.account_login == "acme"
    assert command.installation.account_type == "Organization"
    assert command.installation.status == TenantStatus.ACTIVE
    assert command.installation.repository_selection == "all"


def test_deleted_action_produces_transition_to_deleted():
    command = parse_installation_command(_payload("deleted"))

    assert command == TransitionInstallation(installation_id=1, status=TenantStatus.DELETED)


def test_suspend_action_produces_transition_to_suspended():
    command = parse_installation_command(_payload("suspend"))

    assert command == TransitionInstallation(installation_id=1, status=TenantStatus.SUSPENDED)


def test_unsuspend_action_produces_transition_to_active():
    command = parse_installation_command(_payload("unsuspend"))

    assert command == TransitionInstallation(installation_id=1, status=TenantStatus.ACTIVE)


def test_unknown_action_produces_no_command():
    command = parse_installation_command(_payload("new_permissions_accepted"))

    assert command is None


def test_missing_installation_field_raises_key_error():
    with pytest.raises(KeyError):
        parse_installation_command({"action": "created"})


def test_missing_account_field_raises_key_error():
    payload = {"action": "created", "installation": {"id": 1, "repository_selection": "all"}}

    with pytest.raises(KeyError):
        parse_installation_command(payload)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker compose run --rm app pytest tests/adapters/github/test_installation_command_parser.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'mergency.adapters.github.installation_command_parser'`

- [ ] **Step 3: Write the translator**

`src/mergency/adapters/github/installation_command_parser.py`:

```python
from mergency.domain.models.create_installation_command import CreateInstallation
from mergency.domain.models.installation import Installation
from mergency.domain.models.installation_command import InstallationCommand
from mergency.domain.models.tenant_status import TenantStatus
from mergency.domain.models.transition_installation_command import TransitionInstallation

_ACTION_TO_STATUS: dict[str, TenantStatus] = {
    "deleted": TenantStatus.DELETED,
    "suspend": TenantStatus.SUSPENDED,
    "unsuspend": TenantStatus.ACTIVE,
}


def parse_installation_command(payload: dict) -> InstallationCommand | None:
    action = payload.get("action")
    installation_payload = payload["installation"]
    installation_id = installation_payload["id"]

    if action == "created":
        return CreateInstallation(
            installation=Installation(
                installation_id=installation_id,
                account_login=installation_payload["account"]["login"],
                account_type=installation_payload["account"]["type"],
                status=TenantStatus.ACTIVE,
                repository_selection=installation_payload["repository_selection"],
            )
        )

    status = _ACTION_TO_STATUS.get(action)
    if status is not None:
        return TransitionInstallation(installation_id=installation_id, status=status)

    return None
```

`installation_payload`/`installation_id` are read unconditionally before branching, matching today's behavior: any installation event missing `installation`/`installation.id` raises `KeyError` regardless of action, and the caller (Task 4) catches it.

- [ ] **Step 4: Run test to verify it passes**

Run: `docker compose run --rm app pytest tests/adapters/github/test_installation_command_parser.py -v`
Expected: PASS (7 passed)

- [ ] **Step 5: Commit**

```bash
git add tests/adapters/github/test_installation_command_parser.py \
        src/mergency/adapters/github/installation_command_parser.py
git commit -m "feat: add GitHub installation payload to command translator"
```

---

### Task 3: Collapse `InstallationService` to a single `handle(command)`

**Files:**
- Modify: `tests/domain/test_installation_service.py` (rewritten)
- Modify: `src/mergency/domain/installation_service.py`

- [ ] **Step 1: Rewrite the test file first**

Replace the full contents of `tests/domain/test_installation_service.py`:

```python
import pytest

from mergency.adapters.memory.tenant_repository import InMemoryTenantRepository
from mergency.domain.installation_service import InstallationService
from mergency.domain.models.create_installation_command import CreateInstallation
from mergency.domain.models.installation import Installation
from mergency.domain.models.tenant_status import TenantStatus
from mergency.domain.models.transition_installation_command import TransitionInstallation


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


@pytest.fixture
def service(repository: InMemoryTenantRepository) -> InstallationService:
    return InstallationService(repository)


async def test_handle_create_installation_stores_active_installation(service, repository):
    await service.handle(CreateInstallation(installation=_installation()))

    stored = await repository.get(42)
    assert stored is not None
    assert stored.status == TenantStatus.ACTIVE


async def test_handle_transition_to_deleted_marks_status_deleted(service, repository):
    await service.handle(CreateInstallation(installation=_installation()))
    await service.handle(TransitionInstallation(installation_id=42, status=TenantStatus.DELETED))

    stored = await repository.get(42)
    assert stored is not None
    assert stored.status == TenantStatus.DELETED


async def test_handle_transition_to_suspended_toggles_status(service, repository):
    await service.handle(CreateInstallation(installation=_installation()))
    await service.handle(TransitionInstallation(installation_id=42, status=TenantStatus.SUSPENDED))

    stored = await repository.get(42)
    assert stored is not None
    assert stored.status == TenantStatus.SUSPENDED


async def test_handle_transition_to_active_reactivates(service, repository):
    await service.handle(
        CreateInstallation(installation=_installation(status=TenantStatus.SUSPENDED))
    )
    await service.handle(TransitionInstallation(installation_id=42, status=TenantStatus.ACTIVE))

    stored = await repository.get(42)
    assert stored is not None
    assert stored.status == TenantStatus.ACTIVE


async def test_recreating_an_existing_installation_updates_rather_than_duplicates(service, repository):
    await service.handle(CreateInstallation(installation=_installation()))
    await service.handle(CreateInstallation(installation=_installation()))

    stored = await repository.get(42)
    assert stored is not None
    assert stored.installation_id == 42
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker compose run --rm app pytest tests/domain/test_installation_service.py -v`
Expected: FAIL with `AttributeError: 'InstallationService' object has no attribute 'handle'`

- [ ] **Step 3: Rewrite `InstallationService`**

Replace the full contents of `src/mergency/domain/installation_service.py`:

```python
from mergency.domain.models.create_installation_command import CreateInstallation
from mergency.domain.models.installation_command import InstallationCommand
from mergency.domain.models.transition_installation_command import TransitionInstallation
from mergency.domain.ports.tenant_repository import TenantRepository


class InstallationService:
    def __init__(self, tenant_repository: TenantRepository) -> None:
        self._tenant_repository = tenant_repository

    async def handle(self, command: InstallationCommand) -> None:
        match command:
            case CreateInstallation(installation=installation):
                await self._tenant_repository.upsert(installation)
            case TransitionInstallation(installation_id=installation_id, status=status):
                await self._tenant_repository.transition(installation_id, status)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `docker compose run --rm app pytest tests/domain/test_installation_service.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
git add tests/domain/test_installation_service.py src/mergency/domain/installation_service.py
git commit -m "refactor: collapse InstallationService to a single handle(command) method"
```

---

### Task 4: Refactor the webhook handler to parse-then-dispatch

**Files:**
- Modify: `src/mergency/api/webhooks.py`
- Test: `tests/api/test_webhooks.py` (existing — **no changes**, must keep passing unmodified; this is the regression guard for this task)

At this point `InstallationService.handle_installation_created` etc. no longer exist, so `webhooks.py` is currently broken — this task is its own commit since it's a distinct concern (HTTP dispatch) from Task 3 (domain service).

- [ ] **Step 1: Run the existing webhook tests to confirm they currently fail**

Run: `docker compose run --rm app pytest tests/api/test_webhooks.py -v`
Expected: FAIL/ERROR — `webhooks.py` still calls the now-removed per-action methods on `InstallationService`.

- [ ] **Step 2: Rewrite `_handle_installation_event` and imports**

Replace the full contents of `src/mergency/api/webhooks.py`:

```python
import json
import logging

from fastapi import APIRouter, Depends, Header, HTTPException, Request

from mergency.adapters.github.installation_command_parser import parse_installation_command
from mergency.adapters.github.signature import verify_signature
from mergency.api.deps import get_installation_service, get_settings
from mergency.api.settings import Settings
from mergency.domain.installation_service import InstallationService

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/webhooks/github")
async def receive_webhook(
    request: Request,
    x_hub_signature_256: str | None = Header(default=None),
    x_github_event: str | None = Header(default=None),
    settings: Settings = Depends(get_settings),
    installation_service: InstallationService = Depends(get_installation_service),
) -> dict[str, str]:
    body = await request.body()

    if not verify_signature(body, x_hub_signature_256, settings.github_webhook_secret):
        raise HTTPException(status_code=401, detail="invalid signature")

    payload = json.loads(body)

    if x_github_event == "installation":
        await _handle_installation_event(payload, installation_service)
    elif x_github_event == "installation_repositories":
        logger.info("installation_repositories event acknowledged, no-op for now")
    else:
        logger.info(
            "event acknowledged, processing not yet implemented",
            extra={"event": x_github_event},
        )

    return {"status": "ok"}


async def _handle_installation_event(
    payload: dict, installation_service: InstallationService
) -> None:
    action = payload.get("action")

    try:
        command = parse_installation_command(payload)
    except KeyError as error:
        logger.warning(
            "installation payload missing expected field, acknowledged without processing",
            extra={"action": action, "missing_field": str(error)},
        )
        return

    if command is None:
        logger.info("unhandled installation action acknowledged", extra={"action": action})
        return

    await installation_service.handle(command)
```

`Installation` and `TenantStatus` are no longer imported here — payload-to-domain-object construction now lives entirely in `parse_installation_command`.

- [ ] **Step 3: Run the webhook tests to verify they pass unmodified**

Run: `docker compose run --rm app pytest tests/api/test_webhooks.py -v`
Expected: PASS (6 passed), with **zero changes** to the test file — confirms the refactor preserved observable HTTP behavior end-to-end.

- [ ] **Step 4: Run the full test suite and lint**

Run: `docker compose run --rm app pytest -v`
Expected: PASS, all tests.

Run: `docker compose run --rm app ruff check src tests`
Expected: no errors (confirms no leftover unused imports, e.g. `Installation`/`TenantStatus` in `webhooks.py`).

- [ ] **Step 5: Commit**

```bash
git add src/mergency/api/webhooks.py
git commit -m "refactor: dispatch installation webhooks via parsed commands"
```

## Verification

1. Full test suite: `docker compose run --rm app pytest -v` — expect all tests passing, including the two new test files (`tests/domain/models/test_installation_command.py`, `tests/adapters/github/test_installation_command_parser.py`) and the rewritten `tests/domain/test_installation_service.py`.
2. Lint: `docker compose run --rm app ruff check src tests` — expect no errors.
3. Confirm `tests/api/test_webhooks.py` was never modified by this plan (`git diff` on that file across the four commits above should be empty) — it is the black-box regression guard proving observable HTTP behavior is unchanged.
4. Confirm the domain layer no longer speaks GitHub's action vocabulary: `grep -rn '"suspend"\|"unsuspend"\|"deleted"\|"created"' src/mergency/domain/` should return nothing — those strings should only appear in `src/mergency/adapters/github/installation_command_parser.py`.
5. Confirm `InstallationService`'s public surface is exactly what the design calls for: `grep -n "async def" src/mergency/domain/installation_service.py` should list exactly one method, `handle`.
