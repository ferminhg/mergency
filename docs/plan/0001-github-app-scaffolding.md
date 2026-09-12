# GitHub App Scaffolding Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stand up Mergency's webhook receiver and installation lifecycle (install/suspend/unsuspend/uninstall), running entirely through Docker Compose, with the hexagonal domain/adapters/api boundary in place from the start.

**Architecture:** FastAPI receives and HMAC-verifies GitHub webhooks, dispatches `installation` events into a pure-Python `InstallationService` domain layer that persists tenants through a `TenantRepository` port (in-memory adapter for now), plus a stub Celery worker entrypoint and a PyGithub-based installation-token provider wired into dependency injection but not yet called by anything.

**Tech Stack:** Python 3.12, FastAPI, PyGithub, Celery (stub only), pydantic-settings, pytest/pytest-asyncio/httpx, Docker Compose. No Postgres/SQLAlchemy or real Celery jobs in this plan — see Context.

---

## Status

proposed

## Context

Mergency is a GitHub App with no code yet — only docs (`README.md`, `ARQUITECTURE.md`, ADR 0001 specifying Python/FastAPI/PyGithub/SQLAlchemy/Celery/Redis, hexagonal architecture). This is the first roadmap item: get webhook reception and the installation lifecycle working end-to-end locally, before any build-failure/revert processing, ownership resolution, or budget logic exists.

Scope is deliberately narrow — no real Postgres persistence, no Celery jobs, no CI — to avoid building persistence and infra ahead of the domain logic that needs it. Docker Compose, however, is required from the start (per `CLAUDE.md`'s Development environment section): there is no bare-metal `uv`/`venv` workflow for this project, so the app runs in a container from Task 1 onward.

This revision (a) splits every multi-class module into one file per class, (b) breaks the work into bite-sized tasks with literal test/implementation code and exact commands so an engineer with zero context on this codebase can execute it without guessing, and (c) expresses every command through Docker Compose.

## Directory structure

```
mergency/
├── pyproject.toml
├── .env.example
├── .gitignore
├── Dockerfile
├── docker-compose.yml
├── src/mergency/
│   ├── domain/
│   │   ├── models/
│   │   │   ├── installation.py       # Installation — zero framework imports
│   │   │   └── tenant_status.py      # TenantStatus enum
│   │   ├── ports/
│   │   │   ├── tenant_repository.py           # TenantRepository (Protocol)
│   │   │   └── installation_token_provider.py # InstallationTokenProvider (Protocol)
│   │   └── installation_service.py   # InstallationService — the "installation handler"
│   ├── adapters/
│   │   ├── github/
│   │   │   ├── signature.py     # HMAC-SHA256 webhook verification
│   │   │   └── token_manager.py # PyGithub-based InstallationTokenProvider + in-memory TTL cache
│   │   └── memory/
│   │       └── tenant_repository.py  # in-memory TenantRepository impl
│   ├── api/
│   │   ├── app.py               # FastAPI app factory
│   │   ├── deps.py              # dependency wiring
│   │   ├── settings.py          # pydantic-settings Settings
│   │   └── webhooks.py          # POST /webhooks/github, event dispatch
│   └── worker/
│       └── celery_app.py        # stub Celery app, no tasks yet
├── scripts/
│   └── github_app_manifest.py   # one-shot dev script: manifest flow → prints APP_ID/PRIVATE_KEY/WEBHOOK_SECRET
└── tests/
    ├── adapters/github/test_signature.py
    ├── domain/test_installation_model.py
    ├── domain/test_installation_service.py
    └── api/test_webhooks.py
```

The hexagonal boundary is structural: `domain/` never imports FastAPI, Celery, SQLAlchemy, or PyGithub — only `adapters/` and `api/` do. `api/webhooks.py` is the composition point where GitHub payloads get turned into domain calls.

**One class (or Protocol/enum) per file, applied across the whole domain package**: `domain/models/installation.py` holds only `Installation`, `domain/models/tenant_status.py` holds only `TenantStatus`, `domain/ports/tenant_repository.py` and `domain/ports/installation_token_provider.py` each hold a single `Protocol`. `domain/installation_service.py` keeps its own name (not folded into `models/` or `ports/`) since it's the one piece of actual domain *logic*.

---

## Task 1: Project scaffolding + Docker Compose

**Files:**
- Create: `pyproject.toml`
- Create: `Dockerfile`
- Create: `docker-compose.yml`
- Create: `.env.example`
- Modify: `.gitignore` (append — it already contains `!CLAUDE.md`, do not remove that line)
- Create: `src/mergency/__init__.py` and one empty `__init__.py` in each of `domain/`, `domain/models/`, `domain/ports/`, `adapters/`, `adapters/github/`, `adapters/memory/`, `api/`, `worker/`
- Create: `tests/__init__.py`, `tests/adapters/__init__.py`, `tests/adapters/github/__init__.py`, `tests/domain/__init__.py`, `tests/api/__init__.py`, `tests/conftest.py` (empty)

No application behavior yet — this task only makes the container buildable and `pytest` runnable inside it.

- [ ] **Step 1: Write `pyproject.toml`**

```toml
[project]
name = "mergency"
version = "0.1.0"
description = "Error budget bot for pull requests"
requires-python = ">=3.12"
dependencies = [
    "fastapi>=0.115",
    "pydantic-settings>=2.5",
    "pygithub>=2.4",
    "celery>=5.4",
    "uvicorn[standard]>=0.32",
]

[dependency-groups]
dev = [
    "pytest>=8.3",
    "pytest-asyncio>=0.24",
    "httpx>=0.27",
]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/mergency"]
```

- [ ] **Step 2: Write `Dockerfile`**

```dockerfile
FROM python:3.12-slim

RUN pip install --no-cache-dir uv

WORKDIR /app

COPY pyproject.toml ./
RUN uv sync --no-install-project

COPY src ./src
COPY tests ./tests
COPY scripts ./scripts

RUN uv sync

ENV PATH="/app/.venv/bin:$PATH"

CMD ["uvicorn", "mergency.api.app:app", "--host", "0.0.0.0", "--port", "8000"]
```

- [ ] **Step 3: Write `docker-compose.yml`**

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
```

Only the `app` service for this task — Postgres/Redis are added by the future tasks that actually use them (real persistence, real Celery jobs); adding them unused now would be scope creep.

- [ ] **Step 4: Write `.env.example`**

```
MERGENCY_GITHUB_APP_ID=
MERGENCY_GITHUB_PRIVATE_KEY=
MERGENCY_GITHUB_WEBHOOK_SECRET=
```

- [ ] **Step 5: Append to `.gitignore`**

Existing content is exactly:
```
!CLAUDE.md
```

Append these lines below it (keep the existing line untouched):
```
__pycache__/
*.pyc
.venv/
.pytest_cache/
*.egg-info/
.env
```

- [ ] **Step 6: Create the package skeleton (empty files)**

```bash
mkdir -p src/mergency/domain/models src/mergency/domain/ports \
         src/mergency/adapters/github src/mergency/adapters/memory \
         src/mergency/api src/mergency/worker \
         tests/adapters/github tests/domain tests/api

touch src/mergency/__init__.py \
      src/mergency/domain/__init__.py \
      src/mergency/domain/models/__init__.py \
      src/mergency/domain/ports/__init__.py \
      src/mergency/adapters/__init__.py \
      src/mergency/adapters/github/__init__.py \
      src/mergency/adapters/memory/__init__.py \
      src/mergency/api/__init__.py \
      src/mergency/worker/__init__.py \
      tests/__init__.py \
      tests/adapters/__init__.py \
      tests/adapters/github/__init__.py \
      tests/domain/__init__.py \
      tests/api/__init__.py \
      tests/conftest.py
```

- [ ] **Step 7: Build the image and verify the empty test suite runs**

Run: `docker compose build`
Expected: build succeeds with no errors.

Run: `docker compose run --rm app pytest`
Expected: `collected 0 items` and exit code 0 (no errors, nothing to test yet).

- [ ] **Step 8: Commit**

```bash
git add pyproject.toml Dockerfile docker-compose.yml .env.example .gitignore src tests
git commit -m "chore: scaffold project structure and Docker Compose"
```

---

## Task 2: HMAC webhook signature verification

**Files:**
- Test: `tests/adapters/github/test_signature.py`
- Create: `src/mergency/adapters/github/signature.py`

No dependency on domain or API — the smallest independent unit, done first.

- [ ] **Step 1: Write the failing test**

```python
# tests/adapters/github/test_signature.py
import hashlib
import hmac

from mergency.adapters.github.signature import verify_signature

SECRET = "test-webhook-secret"


def _signature_for(payload: bytes, secret: str = SECRET) -> str:
    digest = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def test_valid_signature_is_accepted():
    payload = b'{"action": "created"}'
    signature = _signature_for(payload)

    assert verify_signature(payload, signature, SECRET) is True


def test_tampered_payload_is_rejected():
    payload = b'{"action": "created"}'
    signature = _signature_for(payload)
    tampered_payload = b'{"action": "deleted"}'

    assert verify_signature(tampered_payload, signature, SECRET) is False


def test_missing_signature_header_is_rejected():
    payload = b'{"action": "created"}'

    assert verify_signature(payload, None, SECRET) is False


def test_malformed_signature_header_is_rejected():
    payload = b'{"action": "created"}'
    digest = hmac.new(SECRET.encode(), payload, hashlib.sha256).hexdigest()

    assert verify_signature(payload, digest, SECRET) is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker compose run --rm app pytest tests/adapters/github/test_signature.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'mergency.adapters.github.signature'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/mergency/adapters/github/signature.py
import hashlib
import hmac

_SIGNATURE_PREFIX = "sha256="


def verify_signature(payload: bytes, signature_header: str | None, secret: str) -> bool:
    if signature_header is None or not signature_header.startswith(_SIGNATURE_PREFIX):
        return False

    expected_digest = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
    expected_header = f"{_SIGNATURE_PREFIX}{expected_digest}"

    return hmac.compare_digest(expected_header, signature_header)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `docker compose run --rm app pytest tests/adapters/github/test_signature.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add tests/adapters/github/test_signature.py src/mergency/adapters/github/signature.py
git commit -m "feat: add HMAC webhook signature verification"
```

---

## Task 3: Domain models

**Files:**
- Test: `tests/domain/test_installation_model.py`
- Create: `src/mergency/domain/models/tenant_status.py`
- Create: `src/mergency/domain/models/installation.py`

Pure data, no ports or services yet — reviewable on its own as the vocabulary the rest of the domain builds on. `Installation` stores only the org/user the app is installed on, never the individual `sender` who triggered the install, per the "no per-author metrics" product constraint (see `README.md`).

- [ ] **Step 1: Write the failing test**

```python
# tests/domain/test_installation_model.py
import dataclasses

import pytest

from mergency.domain.models.installation import Installation
from mergency.domain.models.tenant_status import TenantStatus


def test_installation_is_immutable():
    installation = Installation(
        installation_id=1,
        account_login="acme",
        account_type="Organization",
        status=TenantStatus.ACTIVE,
        repository_selection="all",
    )

    with pytest.raises(dataclasses.FrozenInstanceError):
        installation.status = TenantStatus.DELETED


def test_tenant_status_has_exactly_three_values():
    assert {status.value for status in TenantStatus} == {"active", "suspended", "deleted"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker compose run --rm app pytest tests/domain/test_installation_model.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'mergency.domain.models.installation'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/mergency/domain/models/tenant_status.py
from enum import Enum


class TenantStatus(str, Enum):
    ACTIVE = "active"
    SUSPENDED = "suspended"
    DELETED = "deleted"
```

```python
# src/mergency/domain/models/installation.py
from dataclasses import dataclass

from mergency.domain.models.tenant_status import TenantStatus


@dataclass(frozen=True)
class Installation:
    installation_id: int
    account_login: str
    account_type: str
    status: TenantStatus
    repository_selection: str
```

- [ ] **Step 4: Run test to verify it passes**

Run: `docker compose run --rm app pytest tests/domain/test_installation_model.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add tests/domain/test_installation_model.py src/mergency/domain/models
git commit -m "feat: add Installation and TenantStatus domain models"
```

---

## Task 4: Domain ports + in-memory tenant repository + InstallationService

**Files:**
- Test: `tests/domain/test_installation_service.py`
- Create: `src/mergency/domain/ports/tenant_repository.py`
- Create: `src/mergency/domain/ports/installation_token_provider.py`
- Create: `src/mergency/adapters/memory/tenant_repository.py`
- Create: `src/mergency/domain/installation_service.py`

`InstallationService` is the "installation handler" from `ARQUITECTURE.md`. Re-`created` on an existing `installation_id` updates rather than duplicates; `deleted` marks status `DELETED` rather than removing the record (keeps an audit trail, matches ARQUITECTURE.md's "creates/updates tenant record" language).

- [ ] **Step 1: Write the failing test**

```python
# tests/domain/test_installation_service.py
import pytest

from mergency.adapters.memory.tenant_repository import InMemoryTenantRepository
from mergency.domain.installation_service import InstallationService
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


@pytest.fixture
def service(repository: InMemoryTenantRepository) -> InstallationService:
    return InstallationService(repository)


async def test_handle_installation_created_stores_active_installation(service, repository):
    await service.handle_installation_created(_installation())

    stored = await repository.get(42)
    assert stored is not None
    assert stored.status == TenantStatus.ACTIVE


async def test_handle_installation_deleted_marks_status_deleted(service, repository):
    await service.handle_installation_created(_installation())
    await service.handle_installation_deleted(42)

    stored = await repository.get(42)
    assert stored is not None
    assert stored.status == TenantStatus.DELETED


async def test_handle_installation_suspended_toggles_status(service, repository):
    await service.handle_installation_created(_installation())
    await service.handle_installation_suspended(42)

    stored = await repository.get(42)
    assert stored is not None
    assert stored.status == TenantStatus.SUSPENDED


async def test_handle_installation_unsuspended_reactivates(service, repository):
    await service.handle_installation_created(_installation(status=TenantStatus.SUSPENDED))
    await service.handle_installation_unsuspended(_installation(status=TenantStatus.SUSPENDED))

    stored = await repository.get(42)
    assert stored is not None
    assert stored.status == TenantStatus.ACTIVE


async def test_recreating_an_existing_installation_updates_rather_than_duplicates(service, repository):
    await service.handle_installation_created(_installation())
    await service.handle_installation_created(_installation())

    stored = await repository.get(42)
    assert stored is not None
    assert stored.installation_id == 42
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker compose run --rm app pytest tests/domain/test_installation_service.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'mergency.adapters.memory.tenant_repository'`

- [ ] **Step 3: Write the ports**

```python
# src/mergency/domain/ports/tenant_repository.py
from typing import Protocol

from mergency.domain.models.installation import Installation


class TenantRepository(Protocol):
    async def upsert(self, installation: Installation) -> None: ...

    async def mark_deleted(self, installation_id: int) -> None: ...

    async def get(self, installation_id: int) -> Installation | None: ...
```

```python
# src/mergency/domain/ports/installation_token_provider.py
from typing import Protocol


class InstallationTokenProvider(Protocol):
    async def get_token(self, installation_id: int) -> str: ...
```

- [ ] **Step 4: Write the in-memory adapter**

```python
# src/mergency/adapters/memory/tenant_repository.py
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
```

- [ ] **Step 5: Write the domain service**

```python
# src/mergency/domain/installation_service.py
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
        await self._tenant_repository.mark_deleted(installation_id)

    async def handle_installation_suspended(self, installation_id: int) -> None:
        existing = await self._tenant_repository.get(installation_id)
        if existing is not None:
            suspended = dataclasses.replace(existing, status=TenantStatus.SUSPENDED)
            await self._tenant_repository.upsert(suspended)

    async def handle_installation_unsuspended(self, installation: Installation) -> None:
        active = dataclasses.replace(installation, status=TenantStatus.ACTIVE)
        await self._tenant_repository.upsert(active)
```

- [ ] **Step 6: Run test to verify it passes**

Run: `docker compose run --rm app pytest tests/domain/ -v`
Expected: PASS (7 passed — includes Task 3's tests)

- [ ] **Step 7: Commit**

```bash
git add tests/domain/test_installation_service.py src/mergency/domain/ports src/mergency/domain/installation_service.py src/mergency/adapters/memory
git commit -m "feat: add InstallationService with in-memory tenant repository"
```

---

## Task 5: API settings + webhook endpoint + install-flow wiring

**Files:**
- Test: `tests/api/test_webhooks.py`
- Create: `src/mergency/api/settings.py`
- Create: `src/mergency/api/deps.py`
- Create: `src/mergency/api/webhooks.py`
- Create: `src/mergency/api/app.py`

`webhooks.py` verifies the signature (401 on failure) and dispatches on the `X-GitHub-Event` header: `installation` maps `payload["action"]` to the matching `InstallationService` method; `installation_repositories`, `push`, `pull_request`, `check_run`, and any other event type are acknowledged with a log line and a 200 (no-op) — those are future roadmap items, this task only builds the plug-in point. Only signature failures return non-200; everything else always acks fast.

- [ ] **Step 1: Write the failing test**

```python
# tests/api/test_webhooks.py
import hashlib
import hmac
import json

import pytest
from httpx import ASGITransport, AsyncClient

from mergency.adapters.memory.tenant_repository import InMemoryTenantRepository
from mergency.api.app import app
from mergency.api.deps import get_installation_service, get_settings
from mergency.api.settings import Settings
from mergency.domain.installation_service import InstallationService

TEST_SECRET = "test-webhook-secret"


def _signed_headers(payload: bytes, event: str, secret: str = TEST_SECRET) -> dict[str, str]:
    digest = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
    return {
        "X-Hub-Signature-256": f"sha256={digest}",
        "X-GitHub-Event": event,
        "Content-Type": "application/json",
    }


def _installation_payload(action: str, installation_id: int = 1) -> bytes:
    return json.dumps(
        {
            "action": action,
            "installation": {
                "id": installation_id,
                "account": {"login": "acme", "type": "Organization"},
                "repository_selection": "all",
            },
        }
    ).encode()


@pytest.fixture(autouse=True)
def override_dependencies():
    repository = InMemoryTenantRepository()
    service = InstallationService(repository)

    app.dependency_overrides[get_settings] = lambda: Settings(
        github_app_id="test-app-id",
        github_private_key="test-key",
        github_webhook_secret=TEST_SECRET,
    )
    app.dependency_overrides[get_installation_service] = lambda: service

    yield repository

    app.dependency_overrides.clear()


async def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def test_valid_installation_created_webhook_stores_installation(override_dependencies):
    payload = _installation_payload("created")
    headers = _signed_headers(payload, "installation")

    async with await _client() as client:
        response = await client.post("/webhooks/github", content=payload, headers=headers)

    assert response.status_code == 200
    stored = await override_dependencies.get(1)
    assert stored is not None
    assert stored.account_login == "acme"


async def test_invalid_signature_is_rejected(override_dependencies):
    payload = _installation_payload("created")
    headers = _signed_headers(payload, "installation", secret="wrong-secret")

    async with await _client() as client:
        response = await client.post("/webhooks/github", content=payload, headers=headers)

    assert response.status_code == 401
    stored = await override_dependencies.get(1)
    assert stored is None


async def test_unhandled_event_type_is_acknowledged(override_dependencies):
    payload = json.dumps({"zen": "hello"}).encode()
    headers = _signed_headers(payload, "push")

    async with await _client() as client:
        response = await client.post("/webhooks/github", content=payload, headers=headers)

    assert response.status_code == 200


async def test_installation_repositories_event_is_acknowledged(override_dependencies):
    payload = json.dumps({"action": "added"}).encode()
    headers = _signed_headers(payload, "installation_repositories")

    async with await _client() as client:
        response = await client.post("/webhooks/github", content=payload, headers=headers)

    assert response.status_code == 200
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker compose run --rm app pytest tests/api/test_webhooks.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'mergency.api.app'`

- [ ] **Step 3: Write settings**

```python
# src/mergency/api/settings.py
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="MERGENCY_")

    github_app_id: str
    github_private_key: str
    github_webhook_secret: str
```

- [ ] **Step 4: Write dependency wiring**

```python
# src/mergency/api/deps.py
from functools import lru_cache

from mergency.adapters.memory.tenant_repository import InMemoryTenantRepository
from mergency.api.settings import Settings
from mergency.domain.installation_service import InstallationService
from mergency.domain.ports.tenant_repository import TenantRepository

_tenant_repository: TenantRepository = InMemoryTenantRepository()
_installation_service = InstallationService(_tenant_repository)


@lru_cache
def get_settings() -> Settings:
    return Settings()


def get_tenant_repository() -> TenantRepository:
    return _tenant_repository


def get_installation_service() -> InstallationService:
    return _installation_service
```

- [ ] **Step 5: Write the webhook endpoint**

```python
# src/mergency/api/webhooks.py
import json
import logging

from fastapi import APIRouter, Depends, Header, HTTPException, Request

from mergency.adapters.github.signature import verify_signature
from mergency.api.deps import get_installation_service, get_settings
from mergency.api.settings import Settings
from mergency.domain.installation_service import InstallationService
from mergency.domain.models.installation import Installation
from mergency.domain.models.tenant_status import TenantStatus

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
    installation_payload = payload["installation"]
    installation_id = installation_payload["id"]

    if action == "deleted":
        await installation_service.handle_installation_deleted(installation_id)
        return

    if action == "suspend":
        await installation_service.handle_installation_suspended(installation_id)
        return

    installation = Installation(
        installation_id=installation_id,
        account_login=installation_payload["account"]["login"],
        account_type=installation_payload["account"]["type"],
        status=TenantStatus.ACTIVE,
        repository_selection=installation_payload["repository_selection"],
    )

    if action == "created":
        await installation_service.handle_installation_created(installation)
    elif action == "unsuspend":
        await installation_service.handle_installation_unsuspended(installation)
    else:
        logger.info("unhandled installation action acknowledged", extra={"action": action})
```

- [ ] **Step 6: Write the app factory**

```python
# src/mergency/api/app.py
from fastapi import FastAPI

from mergency.api.webhooks import router as webhooks_router


def create_app() -> FastAPI:
    app = FastAPI(title="mergency")
    app.include_router(webhooks_router)
    return app


app = create_app()
```

- [ ] **Step 7: Run test to verify it passes**

Run: `docker compose run --rm app pytest tests/api/test_webhooks.py -v`
Expected: PASS (4 passed)

- [ ] **Step 8: Verify the server boots**

Run: `docker compose up app`
Expected: uvicorn starts and logs "Uvicorn running on http://0.0.0.0:8000" with no errors. Stop with Ctrl-C.

- [ ] **Step 9: Commit**

```bash
git add tests/api/test_webhooks.py src/mergency/api
git commit -m "feat: add webhook endpoint and installation-flow wiring"
```

---

## Task 6: GitHub installation token manager

**Files:**
- Create: `src/mergency/adapters/github/token_manager.py`
- Modify: `src/mergency/api/deps.py`

No test in this task — nothing in scope calls `get_token()` yet (deferred until a real caller, e.g. the future comment bot, exists). The interface is designed so a future Redis-backed cache swaps in later without call-site changes.

- [ ] **Step 1: Write the token manager**

```python
# src/mergency/adapters/github/token_manager.py
import asyncio
from datetime import datetime, timedelta, timezone

from github import GithubIntegration


class PyGithubInstallationTokenProvider:
    def __init__(self, app_id: str, private_key: str, ttl_skew_seconds: int = 60) -> None:
        self._integration = GithubIntegration(app_id, private_key)
        self._ttl_skew_seconds = ttl_skew_seconds
        self._cache: dict[int, tuple[str, datetime]] = {}

    async def get_token(self, installation_id: int) -> str:
        cached = self._cache.get(installation_id)
        if cached is not None:
            token, expires_at = cached
            if expires_at > datetime.now(timezone.utc) + timedelta(seconds=self._ttl_skew_seconds):
                return token

        auth = await asyncio.to_thread(self._integration.get_access_token, installation_id)
        self._cache[installation_id] = (auth.token, auth.expires_at)
        return auth.token
```

- [ ] **Step 2: Wire it into `deps.py`**

Add to `src/mergency/api/deps.py`:

```python
from mergency.adapters.github.token_manager import PyGithubInstallationTokenProvider
from mergency.domain.ports.installation_token_provider import InstallationTokenProvider
```

```python
@lru_cache
def get_installation_token_provider() -> InstallationTokenProvider:
    settings = get_settings()
    return PyGithubInstallationTokenProvider(
        app_id=settings.github_app_id,
        private_key=settings.github_private_key,
    )
```

- [ ] **Step 3: Verify it imports and the app still boots**

Run: `docker compose run --rm app python -c "from mergency.adapters.github.token_manager import PyGithubInstallationTokenProvider"`
Expected: no output, exit code 0.

Run: `docker compose up app`
Expected: uvicorn starts with no errors (constructing the provider is lazy via `lru_cache`, so missing real GitHub credentials in `.env` doesn't block boot unless the route is actually called).

- [ ] **Step 4: Commit**

```bash
git add src/mergency/adapters/github/token_manager.py src/mergency/api/deps.py
git commit -m "feat: add PyGithub-based installation token manager"
```

---

## Task 7: Worker stub

**Files:**
- Create: `src/mergency/worker/celery_app.py`

Establishes the second entrypoint from ADR 0001 so the next roadmap item (event ingestion) doesn't need to restructure the package. No tasks registered yet.

- [ ] **Step 1: Write the stub**

```python
# src/mergency/worker/celery_app.py
from celery import Celery

celery_app = Celery(
    "mergency",
    broker="redis://localhost:6379/0",
    backend="redis://localhost:6379/0",
)
```

- [ ] **Step 2: Verify it imports without a running broker**

Run: `docker compose run --rm app python -c "from mergency.worker.celery_app import celery_app"`
Expected: no output, exit code 0 (Celery app construction doesn't connect to the broker).

- [ ] **Step 3: Commit**

```bash
git add src/mergency/worker/celery_app.py
git commit -m "chore: add Celery worker stub entrypoint"
```

---

## Task 8: Local GitHub App manifest-flow script + docs

**Files:**
- Create: `scripts/github_app_manifest.py`
- Modify: `README.md` ("Getting started" section)

One-shot developer script implementing [GitHub's manifest flow](https://docs.github.com/en/apps/sharing-github-apps/registering-a-github-app-from-a-manifest). It's dev tooling, not runtime code, so it doesn't need to respect hexagonal boundaries.

- [ ] **Step 1: Write the script**

```python
# scripts/github_app_manifest.py
"""One-shot helper to register the Mergency GitHub App via GitHub's manifest flow.

Usage:
    python scripts/github_app_manifest.py --hook-url https://example.ngrok.io/webhooks/github
"""
import argparse
import json
import secrets
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

CALLBACK_PORT = 8000
CALLBACK_PATH = "/setup/callback"


def _build_manifest(hook_url: str, app_name: str) -> dict:
    return {
        "name": app_name,
        "url": "https://github.com/mergency",
        "hook_attributes": {"url": hook_url},
        "redirect_url": f"http://localhost:{CALLBACK_PORT}{CALLBACK_PATH}",
        "public": False,
        "default_permissions": {
            "contents": "read",
            "checks": "read",
            "pull_requests": "write",
        },
        "default_events": [
            "installation",
            "installation_repositories",
            "push",
            "pull_request",
            "check_run",
        ],
    }


def _render_redirect_page(manifest: dict, state: str) -> bytes:
    manifest_json = json.dumps(manifest)
    return f"""<!doctype html>
<html>
<body onload="document.forms[0].submit()">
  <form method="post" action="https://github.com/settings/apps/new?state={state}">
    <input type="hidden" name="manifest" value='{manifest_json}'>
  </form>
</body>
</html>""".encode()


def _exchange_code(code: str) -> dict:
    request = urllib.request.Request(
        f"https://api.github.com/app-manifests/{code}/conversions",
        method="POST",
        headers={"Accept": "application/vnd.github+json"},
    )
    with urllib.request.urlopen(request) as response:
        return json.loads(response.read())


class _CallbackHandler(BaseHTTPRequestHandler):
    manifest: dict = {}
    state: str = ""
    result: dict | None = None

    def do_GET(self) -> None:
        parsed = urlparse(self.path)

        if parsed.path == "/":
            body = _render_redirect_page(self.manifest, self.state)
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(body)
            return

        if parsed.path == CALLBACK_PATH:
            query = parse_qs(parsed.query)
            code = query["code"][0]
            _CallbackHandler.result = _exchange_code(code)
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(b"App created, check your terminal, you can close this tab.")
            return

        self.send_response(404)
        self.end_headers()

    def log_message(self, format: str, *args) -> None:
        pass


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hook-url", required=True, help="Public URL GitHub should deliver webhooks to")
    parser.add_argument("--app-name", default=f"mergency-dev-{secrets.token_hex(4)}")
    args = parser.parse_args()

    _CallbackHandler.manifest = _build_manifest(args.hook_url, args.app_name)
    _CallbackHandler.state = secrets.token_urlsafe(16)

    server = HTTPServer(("0.0.0.0", CALLBACK_PORT), _CallbackHandler)
    print(f"Open http://localhost:{CALLBACK_PORT}/ in your browser to create the GitHub App.")

    while _CallbackHandler.result is None:
        server.handle_request()

    result = _CallbackHandler.result
    print("\nGitHub App created. Paste this into your .env:\n")
    print(f"MERGENCY_GITHUB_APP_ID={result['id']}")
    print(f"MERGENCY_GITHUB_WEBHOOK_SECRET={result['webhook_secret']}")
    pem_escaped = result["pem"].replace("\n", "\\n")
    print(f"MERGENCY_GITHUB_PRIVATE_KEY={pem_escaped}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Replace README.md's "Getting started" section**

Replace the current placeholder block (the one starting with "🚧 Mergency is early stage...") with:

```markdown
## Getting started

1. `docker compose build`
2. Start a tunnel so GitHub can reach your local webhook endpoint, e.g. `ngrok http 8000` or `smee --url https://smee.io/<channel> --path /webhooks/github --port 8000`.
3. Run `docker compose run --rm --service-ports app python scripts/github_app_manifest.py --hook-url <tunnel-url>/webhooks/github`, follow the browser flow, paste the printed values into `.env` (copy `.env.example` first).
4. `docker compose up app`
5. Install the GitHub App on a test org/repo from its GitHub settings page.
```

- [ ] **Step 3: Manual end-to-end verification**

Run the script against a real tunnel URL, create a test GitHub App, install it on a scratch repo, confirm the `installation.created` webhook hits `/webhooks/github`, returns 200, and the in-memory tenant record is populated (check via a temporary debug log during this manual test — not a permanent route).

- [ ] **Step 4: Commit**

```bash
git add scripts/github_app_manifest.py README.md
git commit -m "docs: add GitHub App manifest-flow script and local setup steps"
```

---

## Verification (full suite, after all tasks)

- `docker compose build` succeeds.
- `docker compose run --rm app pytest` — all tests from Tasks 2, 3, 4, 5 pass (15 passed: 4 signature + 2 model + 5 service + 4 webhook).
- Manual end-to-end from Task 8, Step 3.
- `docker compose up app` starts without error even with `worker/celery_app.py` present (Celery app construction doesn't require a running broker to import).
