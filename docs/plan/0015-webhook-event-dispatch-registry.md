# Webhook Event Dispatch Registry Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace `receive_webhook`'s `if`/`elif`/`else` chain in [webhooks.py](../../src/mergency/api/webhooks.py) with a `dict[str, Handler]` dispatch table, per [ADR 0014](../adr/0014-webhook-event-dispatch-registry.md), so adding a new webhook event type is a registration, not an edit to a shared conditional.

**Architecture:** Build a local `handlers: dict[str, EventHandler]` inside `receive_webhook` (rebuilt per request, since one entry — `installation` — needs the request-scoped `installation_service` dependency bound via a closure). Every handler shares the signature `async def handler(event_type: str, payload: dict) -> None`, so the same function can serve more than one registry key (`push` and `check_run` both point at `_handle_activity_event`). `receive_webhook` shrinks to signature verification, JSON parsing, one `handlers.get(x_github_event, _handle_unimplemented_event)` lookup, and one `await`.

**Tech Stack:** Python 3.12, FastAPI, pytest + pytest-asyncio + httpx (existing black-box tests in `tests/api/test_webhooks.py` are the regression guard — this is a dispatch-shape refactor, not a behavior change), Docker Compose for all commands (per `CLAUDE.md`).

---

## Status

implemented

## Context

`src/mergency/api/webhooks.py`'s `receive_webhook` has grown to a 4-way `if`/`elif`/`elif`/`elif`/`else` chain (`installation`, `installation_repositories`, `push`/`check_run`, `pull_request`, and an unimplemented-event fallback — one branch more than ADR 0014 shows, since `pull_request` handling landed after the ADR was written). The roadmap (ADR 0006 ownership, ADR 0010/0011 flaky-test/deploy-to-incident v2) keeps implying new webhook-driven event types, and each one currently means editing this function's body again — the open/closed violation ADR 0014 calls out.

ADR 0014 decided the fix: a plain `dict[str, Handler]` registry, mirroring the `_PARSERS` dict already used in `worker/classify_activity_event.py`. This plan is the follow-up the ADR asks for: turn the decision into code, TDD-first, with the existing test suite as the byte-for-byte regression guard.

## Current state (baseline)

[webhooks.py](../../src/mergency/api/webhooks.py):

```python
    if x_github_event == "installation":
        await _handle_installation_event(payload, installation_service)
    elif x_github_event == "installation_repositories":
        logger.info("installation_repositories event acknowledged, no-op for now")
    elif x_github_event in ("push", "check_run"):
        classify_activity_event.delay(x_github_event, payload)
    elif x_github_event == "pull_request" and payload.get("action") in _PR_TRIGGER_ACTIONS:
        evaluate_pr_budget.delay(payload)
    else:
        logger.info(
            "event acknowledged, processing not yet implemented",
            extra={"event": x_github_event},
        )
```

`tests/api/test_webhooks.py` already covers every branch at the HTTP level (status codes and side effects: installation stored, `classify_activity_event.delay` called for `push`/`check_run`, `evaluate_pr_budget.delay` called only for `pull_request` actions in `_PR_TRIGGER_ACTIONS`, unimplemented events acknowledged with 200). None of these tests should need to change — that's the regression guard for this refactor.

## Target state

```python
EventHandler = Callable[[str, dict], Awaitable[None]]


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

    async def _installation_handler(_event_type: str, payload: dict) -> None:
        await _handle_installation_event(payload, installation_service)

    handlers: dict[str, EventHandler] = {
        "installation": _installation_handler,
        "installation_repositories": _handle_installation_repositories_event,
        "push": _handle_activity_event,
        "check_run": _handle_activity_event,
        "pull_request": _handle_pull_request_event,
    }

    handler = handlers.get(x_github_event, _handle_unimplemented_event)
    await handler(x_github_event, payload)

    return {"status": "ok"}
```

with the branch bodies extracted into module-level handler functions (`_handle_installation_repositories_event`, `_handle_activity_event`, `_handle_pull_request_event`, `_handle_unimplemented_event`), all sharing the `(event_type: str, payload: dict) -> None` signature so `push`/`check_run` can share one function and the registry has a single value type. `_handle_installation_event` keeps its existing two-argument signature (it's wrapped by the closure, not put in the dict directly) since it's also called the same way today.

No new file is added — per ADR 0014's own consequences section, this stays "a small, private, module-level handler registry" inside `webhooks.py`. These are plain functions, not classes, so the repo's one-class-per-file convention doesn't apply here.

## Implementation steps

### Task 1: Establish the regression baseline

**Files:**
- None modified — this task only runs the existing suite to confirm it is green before refactoring.

- [x] **Step 1: Run the full webhook test file to confirm it's green before any change**

Run:
```bash
docker compose run --rm app pytest tests/api/test_webhooks.py -v
```
Expected: all 12 tests PASS (`test_valid_installation_created_webhook_stores_installation`, `test_invalid_signature_is_rejected`, `test_unhandled_event_type_is_acknowledged`, `test_pull_request_with_untracked_action_is_acknowledged_without_enqueueing`, `test_check_run_event_enqueues_classify_activity_event`, `test_push_event_enqueues_classify_activity_event`, `test_installation_repositories_event_is_acknowledged`, `test_unhandled_installation_action_is_acknowledged`, `test_malformed_installation_payload_is_acknowledged_without_crashing`, `test_pull_request_opened_enqueues_evaluate_pr_budget`, `test_pull_request_synchronize_enqueues_evaluate_pr_budget`, `test_pull_request_reopened_enqueues_evaluate_pr_budget`).

If any test fails here, stop — that failure is pre-existing and unrelated to this refactor; fix or report it before continuing.

### Task 2: Replace the if/elif chain with the handler registry

**Files:**
- Modify: [`src/mergency/api/webhooks.py`](../../src/mergency/api/webhooks.py) (full file below)
- Test: `tests/api/test_webhooks.py` (unchanged — it is the regression guard, not modified by this task)

- [x] **Step 1: Replace the full contents of `src/mergency/api/webhooks.py`**

```python
import json
import logging
from collections.abc import Awaitable, Callable

from fastapi import APIRouter, Depends, Header, HTTPException, Request

from mergency.adapters.github.installation_command_parser import parse_installation_command
from mergency.adapters.github.signature import verify_signature
from mergency.api.deps import get_installation_service, get_settings
from mergency.api.settings import Settings
from mergency.domain.installation_service import InstallationService
from mergency.worker.classify_activity_event import classify_activity_event
from mergency.worker.evaluate_pr_budget import evaluate_pr_budget

logger = logging.getLogger(__name__)

router = APIRouter()

_PR_TRIGGER_ACTIONS = {"opened", "synchronize", "reopened"}

EventHandler = Callable[[str, dict], Awaitable[None]]


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

    async def _installation_handler(_event_type: str, payload: dict) -> None:
        await _handle_installation_event(payload, installation_service)

    handlers: dict[str, EventHandler] = {
        "installation": _installation_handler,
        "installation_repositories": _handle_installation_repositories_event,
        "push": _handle_activity_event,
        "check_run": _handle_activity_event,
        "pull_request": _handle_pull_request_event,
    }

    handler = handlers.get(x_github_event, _handle_unimplemented_event)
    await handler(x_github_event, payload)

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


async def _handle_installation_repositories_event(_event_type: str, _payload: dict) -> None:
    logger.info("installation_repositories event acknowledged, no-op for now")


async def _handle_activity_event(event_type: str, payload: dict) -> None:
    classify_activity_event.delay(event_type, payload)


async def _handle_pull_request_event(_event_type: str, payload: dict) -> None:
    if payload.get("action") in _PR_TRIGGER_ACTIONS:
        evaluate_pr_budget.delay(payload)


async def _handle_unimplemented_event(event_type: str, _payload: dict) -> None:
    logger.info(
        "event acknowledged, processing not yet implemented",
        extra={"event": event_type},
    )
```

- [x] **Step 2: Run the webhook test file again and confirm it is still green, unmodified**

Run:
```bash
docker compose run --rm app pytest tests/api/test_webhooks.py -v
```
Expected: the same 12 tests PASS as in Task 1, Step 1 — same names, same count. If any test now fails, the refactor changed behavior; compare the failing test's assertion against the matching branch in the "Current state" section above and fix the handler, not the test (the tests are the spec here).

- [x] **Step 3: Run the linter**

Run:
```bash
docker compose run --rm app ruff check src/mergency/api/webhooks.py
```
Expected: `All checks passed!` — `EventHandler`'s `Callable`/`Awaitable` import must come from `collections.abc` (not `typing`) to satisfy the `I` (isort) and modern-typing rules already enabled in `pyproject.toml`.

- [x] **Step 4: Run the full test suite as a final regression check**

Run:
```bash
docker compose run --rm app pytest -v
```
Expected: all tests PASS (no test outside `tests/api/test_webhooks.py` imports or monkeypatches internals of `webhooks.py` other than the two module-level task functions `classify_activity_event` and `evaluate_pr_budget`, both of which are untouched by this refactor).

Note: this run's environment could not bind Postgres to host port 5432 (another concurrent worktree session already held it), so `tests/adapters/db/test_event_repository.py` and `tests/adapters/db/test_tenant_config_repository.py` (12 tests requiring a live Postgres) were excluded via `--ignore=tests/adapters/db`. The remaining 162 tests passed — the same count as before this refactor, and none of the excluded tests touch `webhooks.py`. This is a pre-existing environment constraint, not a regression from this change.

- [x] **Step 5: Commit**

```bash
git add src/mergency/api/webhooks.py
git commit -m "refactor: replace webhook event if/elif chain with handler registry"
```

### Task 3: Close out ADR 0014 and this plan

**Files:**
- Modify: [`docs/adr/0014-webhook-event-dispatch-registry.md`](../adr/0014-webhook-event-dispatch-registry.md) (Status line only)
- Modify: `docs/plan/0015-webhook-event-dispatch-registry.md` (this file — Status line only)

- [x] **Step 1: Flip ADR 0014's status from proposed to accepted**

In `docs/adr/0014-webhook-event-dispatch-registry.md`, change:
```markdown
## Status

📋 proposed
```
to:
```markdown
## Status

✅ accepted
```

- [x] **Step 2: Update this plan's status**

In `docs/plan/0015-webhook-event-dispatch-registry.md`, change the `## Status` section near the top of the file from:
```markdown
## Status

proposed
```
to:
```markdown
## Status

implemented
```

- [x] **Step 3: Commit**

```bash
git add docs/adr/0014-webhook-event-dispatch-registry.md docs/plan/0015-webhook-event-dispatch-registry.md
git commit -m "docs: mark ADR 0014 accepted and its implementation plan complete"
```

## Verification

End-to-end confirmation that the refactor is complete and safe:

1. `docker compose run --rm app pytest tests/api/test_webhooks.py -v` — all 12 existing tests pass, unmodified, with the same names as before the refactor (proves the dispatch-shape change didn't alter behavior).
2. `docker compose run --rm app pytest -v` — the full suite is green (proves no other module relies on the removed `if`/`elif` structure or on internals that moved). See the note under Task 2, Step 4 about this run's Postgres port constraint.
3. `docker compose run --rm app ruff check src/mergency/api/webhooks.py` — passes with no lint errors (import ordering, typing style).
4. Manual read-through of `receive_webhook`: it should contain signature verification, JSON parsing, one dict-literal build, one `.get(...)` lookup, and one `await handler(...)` call — no `if`/`elif` branching on `x_github_event` remains in the function body (the only remaining `if` is the unrelated signature-verification guard).
5. ADR 0014's `## Status` reads `✅ accepted` and this plan's `## Status` reads `implemented`.
