# Installation write-outcome observability

While manually testing `POST /webhooks/github` with signed curl requests, we found that a webhook can silently do nothing and still return `200 OK` with no way to tell from the outside. `_handle_installation_event` in `src/mergency/api/webhooks.py` builds a `TransitionInstallation` command and calls `installation_service.handle(command)`. `InstallationService.handle` calls `tenant_repository.transition(installation_id, status)`, which returns `None` when `installation_id` is not in the store (see `InMemoryTenantRepository.transition` in `src/mergency/adapters/memory/tenant_repository.py`). `InstallationService.handle` never inspects that return value, and `_handle_installation_event` never inspects what `handle` does — so a `suspend`/`unsuspend`/`deleted` event for an installation that was never created (or already deleted) produces the exact same response as one that worked.

There is also no way to read installation state back at all today: the only mounted route is `POST /webhooks/github` (see `src/mergency/api/app.py`). `InMemoryTenantRepository` is an `@lru_cache`-wrapped singleton (`src/mergency/api/deps.py`) that lives only in the running process's memory — there's no database yet (`docker-compose.yml` defines only the `app` service, no Postgres), so there's also no way to inspect state from outside the process.

This is separate from ADR 0002 (accepted non-atomic `get`-then-`upsert` races) and ADR 0009 (proposed, budget-focused historical query API): this ADR is about not being able to observe whether an installation-lifecycle write actually happened, independent of atomicity or of budget data existing yet.

## Status

📋 proposed

## Considered Options

- **Log a warning when `transition` returns `None` (no-op), keep returning `200` to GitHub.** Cheapest fix: makes silent no-ops visible in logs without changing the webhook contract GitHub expects (GitHub only cares about a fast `2xx` ack, not the outcome). Does not add a way to read state back, only a way to notice a no-op after the fact via logs.
- **Add a minimal internal read endpoint, e.g. `GET /internal/installations/{installation_id}`, returning the stored `Installation` or `404`.** Lets us (and tests) directly confirm state instead of inferring it from side effects. Scoped deliberately smaller than ADR 0009's historical query API: no auth, no budget data, no time-bucketed history — just "does this installation exist and what's its status." Would need to be clearly internal-only (not part of the GitHub-facing webhook contract) until ADR 0009's auth model exists, since anyone who can reach the app could otherwise read installation status for any `installation_id`.
- **Both of the above** (chosen). They address two different blind spots: the log fixes "did this write do anything," the endpoint fixes "what is the current state." Neither depends on the other or on Postgres existing — both are cheap against the current in-memory adapter and remain useful once a real adapter replaces it.
- **Do nothing until ADR 0009's historical query API is implemented.** Rejected: ADR 0009 is scoped to budgets per owner, authenticated, and not yet scheduled. Installation lifecycle observability is a smaller, more immediate gap that blocks even manual/local verification of the control-plane path, and doesn't need to wait on that larger, auth-bearing feature.
- **Make `transition`/`upsert` raise on no-op instead of returning `None`/silently succeeding, and turn that into a non-`200` HTTP response.** Rejected: GitHub webhooks expect a `2xx` ack regardless of processing outcome (this repo already treats malformed installation payloads this way — see the `except KeyError` branch in `_handle_installation_event`, which logs and returns rather than raising). Surfacing failures as HTTP errors would fight that existing convention and could cause GitHub to retry events that are logically fine to no-op (e.g. a redundant `suspend` for an already-suspended installation).

## Consequences

- `InstallationService.handle` (or `_handle_installation_event`, whichever ends up owning the check) starts inspecting the result of `transition`/`upsert` and logs a warning when a transition targets an unknown `installation_id`, mirroring the existing `except KeyError` warning-and-acknowledge pattern already used for malformed payloads.
- A new, explicitly internal `GET /internal/installations/{installation_id}` route is added, backed by `TenantRepository.get` (already exists, unused by any route today). No new repository method needed.
- This read endpoint has no authentication for now, since it's local-dev/internal-only; it must not be exposed the same way ADR 0009's tenant-scoped, token-authenticated endpoints are, and should be revisited (moved behind the same auth, or removed) once this app has a real deployment target beyond local Docker Compose.
- Does not touch ADR 0002's accepted non-atomic-transition risk or ADR 0009's budget query API — both remain as separately tracked, unimplemented decisions.
- Not implemented yet — unblocks a future implementation plan.
