# Accept non-atomic installation status transitions for the MVP

Task 4 of `docs/plan/0001-github-app-scaffolding.md` added `InstallationService` and `InMemoryTenantRepository`. A code quality review of that task found two related issues we're accepting for the MVP rather than fixing immediately:

1. **Check-then-act race.** `InMemoryTenantRepository`'s `asyncio.Lock` protects each individual method call (`get`, `upsert`, `mark_deleted`), but `InstallationService.handle_installation_suspended` composes two separate calls (`get` then `upsert`) with an `await` boundary in between. Two events for the same `installation_id` interleaving at that boundary (e.g. a `deleted` event racing a `suspend` event) could produce a stale write — the lock makes each dict operation atomic, but not the read-modify-write sequence across them.
2. **Duplicated status-transition logic.** The "fetch (or already have) an installation, replace its `status` field, persist" pattern is reimplemented independently in three places: `mark_deleted` (repository), `handle_installation_suspended` (service), and `handle_installation_unsuspended` (service, with a different input shape). This is a maintenance smell as more lifecycle events get added.

## Status

accepted

## Considered Options

- **Fix now: add an atomic `transition(installation_id, status)` method to `TenantRepository`, used by all three call sites** (chosen: rejected for now, see Consequences). Would close both the race and the duplication in one change, entirely inside the repository's lock.
- **Accept as-is for the MVP** (chosen). GitHub delivers webhook events for a given installation sequentially in practice, this is a single-process in-memory adapter with no concurrent workers yet (Celery jobs don't exist until a later roadmap item), and no test or production incident currently demonstrates this causing a real bug. Fixing it now means deviating from the exact code `docs/plan/0001-github-app-scaffolding.md` specified for Task 4, which was already implemented and independently verified against that plan.
- **Block Task 4 and re-plan it.** Rejected — the plan's Task 4 code is otherwise correct and spec-compliant; reopening it for an MVP-scoped, low-likelihood race is more process overhead than the risk currently warrants.

## Consequences

- `InstallationService` and `InMemoryTenantRepository` are left exactly as implemented in Task 4 — no code changes from this ADR.
- This is a known, accepted limitation, not an oversight: a future task (the one that swaps `InMemoryTenantRepository` for a real Postgres-backed adapter, or any task that introduces concurrent workers processing installation events) must revisit this. At that point, prefer a single atomic `TenantRepository.transition(installation_id, status)` method (or equivalent compare-and-swap primitive at the storage layer) over the current `get` + `upsert` pattern, and use it consistently instead of reimplementing "fetch, replace status, store" per call site.
- The asymmetry between `handle_installation_suspended` (trusts the stored record) and `handle_installation_unsuspended` (trusts the incoming webhook payload) is left as-is too, and should be revisited alongside the atomicity fix above — both should agree on which source of truth wins.

## Update (implemented)

The atomic `TenantRepository.transition(installation_id, status)` method described in `## Consequences` above was implemented in `docs/plan/0003-atomic-installation-status-transitions.md`, ahead of the originally planned trigger condition (Postgres migration or concurrent workers) — see that plan's `## Context` for the rationale. `InstallationService.handle_installation_suspended`, `handle_installation_deleted`, and `handle_installation_unsuspended` all use `transition` now; the duplicated `mark_deleted` method was removed. The suspend/unsuspend source-of-truth asymmetry is also resolved: both now trust the stored record via `installation_id`, rather than `handle_installation_unsuspended` trusting the incoming webhook payload.
