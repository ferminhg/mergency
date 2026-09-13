# Lazy dependency construction in api/deps.py

## Status

implemented

## Context

GitHub issue [#4](https://github.com/ferminhg/mergency/issues/4) tracks `docs/adr/0003-eager-singletons-in-deps.md`, which accepted a known inconsistency in `src/mergency/api/deps.py`:

- `get_settings()` is lazy and `@lru_cache`-wrapped.
- `get_installation_token_provider()` (added later, Task 6 of `docs/plan/0001-github-app-scaffolding.md`) already follows the same lazy `@lru_cache` pattern.
- `_tenant_repository` and `_installation_service`, however, were still plain module-level globals, constructed eagerly at import time.

ADR 0003 deferred fixing this until "the task that introduces the first adapter with real I/O in its constructor." That trigger hadn't happened yet (still `InMemoryTenantRepository`, no Postgres adapter). Same situation as ADR 0002, which `docs/plan/0003-atomic-installation-status-transitions.md` chose to fix ahead of its own trigger condition rather than wait — this plan does the same for ADR 0003: it's a small, self-contained, low-risk change, and closing it now removes a footgun before anyone adds a real I/O-performing adapter under time pressure.

Confirmed via grep before implementing: nothing outside `deps.py` referenced the `_tenant_repository`/`_installation_service` globals directly — all consumers (`webhooks.py`, `tests/api/test_webhooks.py`) go through the `get_tenant_repository()`/`get_installation_service()` functions or FastAPI's `app.dependency_overrides`, both of which are agnostic to whether the underlying function is `@lru_cache`-wrapped. So this was a pure internal refactor: no observable behavior change, no new domain behavior, hence no new tests were required — the existing suite (`tests/api/test_webhooks.py`) served as the regression check, per the same reasoning `docs/plan/0003-...md` used for its Task 2 (a refactor step that reused existing tests as the baseline instead of writing new ones).

## Change

**File:** `src/mergency/api/deps.py`

The two eager module-level globals were replaced with `@lru_cache`-wrapped functions, matching `get_settings` and `get_installation_token_provider`:

```python
from functools import lru_cache

from mergency.adapters.github.token_manager import PyGithubInstallationTokenProvider
from mergency.adapters.memory.tenant_repository import InMemoryTenantRepository
from mergency.api.settings import Settings
from mergency.domain.installation_service import InstallationService
from mergency.domain.ports.installation_token_provider import InstallationTokenProvider
from mergency.domain.ports.tenant_repository import TenantRepository


@lru_cache
def get_settings() -> Settings:
    return Settings()


@lru_cache
def get_tenant_repository() -> TenantRepository:
    return InMemoryTenantRepository()


@lru_cache
def get_installation_service() -> InstallationService:
    return InstallationService(get_tenant_repository())


@lru_cache
def get_installation_token_provider() -> InstallationTokenProvider:
    settings = get_settings()
    return PyGithubInstallationTokenProvider(
        app_id=settings.github_app_id,
        private_key=settings.github_private_key,
    )
```

No other file needed changes: `webhooks.py` and `tests/api/test_webhooks.py` already depended on the function objects (`get_tenant_repository`, `get_installation_service`), not the globals, so this was a drop-in replacement.

## Implementation steps

### Step 1: Refactor `deps.py` to the lazy `@lru_cache` pattern

- Modify: `src/mergency/api/deps.py` as shown above.
- Run: `docker compose run --rm app pytest -v`
  Expected: PASS, full suite unchanged (same test count/names as before — confirms the refactor is behavior-preserving).
- Run: `docker compose run --rm app ruff check src tests`
  Expected: no errors.
- Run: `docker compose up app` (Ctrl-C after it boots)
  Expected: uvicorn starts cleanly — confirms nothing at import time silently depended on eager construction.
- Commit:
  ```bash
  git add src/mergency/api/deps.py
  git commit -m "refactor: make tenant repository and installation service lazily constructed"
  ```

### Step 2: Record the ADR outcome

- Modify: `docs/adr/0003-eager-singletons-in-deps.md` — append an `## Update (implemented)` section after `## Consequences` (append-only, per `CLAUDE.md`'s Plans as code section and the precedent in ADR 0002's own "Update (implemented)" note).
- Commit:
  ```bash
  git add docs/adr/0003-eager-singletons-in-deps.md
  git commit -m "docs: record that ADR 0003's deferred fix has been implemented"
  ```

### Step 3: Write this plan file

- Create `docs/plan/0004-lazy-deps-singletons.md` (this file), documenting the change for the permanent record required by `CLAUDE.md`'s "Plans as code" section.

## Verification

1. `docker compose run --rm app pytest -v` — full suite passes, same tests as before the change (20 passed).
2. `docker compose run --rm app ruff check src tests` — no errors.
3. `grep -n "^_" src/mergency/api/deps.py` — no output (confirms no more eager module-level globals).
4. `grep -n "@lru_cache" src/mergency/api/deps.py` — 4 matches (`get_settings`, `get_tenant_repository`, `get_installation_service`, `get_installation_token_provider`), confirming all four dependencies now follow the same lazy pattern.
5. `docker compose up app` boots without error.

Note: this session's sandbox had no running Docker daemon, so verification was run directly via `uv run pytest`, `uv run ruff check`, and `uv run uvicorn` instead of through `docker compose`. All commands above are the ones a contributor with a working Docker Compose setup should use going forward, per `CLAUDE.md`'s Development environment section.
