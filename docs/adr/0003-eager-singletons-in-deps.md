# Accept eager module-level singletons in api/deps.py for the MVP

A code quality review of Task 5 (`docs/plan/0001-github-app-scaffolding.md`) found that `src/mergency/api/deps.py` uses two different singleton strategies inconsistently:

- `get_settings()` is lazy: it's only constructed on first call, and cached with `@lru_cache`.
- `_tenant_repository` and `_installation_service` are plain module-level globals, constructed eagerly the moment `deps.py` is imported.

Today this is harmless: `InMemoryTenantRepository` has no I/O in its constructor. But it sets a precedent that will cause a real problem once a task swaps it for a real adapter (a Postgres-backed `TenantRepository`, for example): constructing that adapter would attempt a database connection at *import time* rather than lazily, which can fail before settings are even read or before a Docker Compose dependency (like the database service) is up.

## Status

accepted

## Considered Options

- **Fix now: wrap `get_tenant_repository`/`get_installation_service` in `@lru_cache`, matching `get_settings`'s pattern** (chosen: rejected for now, see Consequences). Would make all three dependencies lazy and consistent in one change.
- **Accept as-is for the MVP** (chosen). `InMemoryTenantRepository`'s constructor does no I/O, so the eager/lazy distinction has zero observable effect right now. Fixing it means touching `deps.py` beyond what Task 5 specified, for a problem that only manifests once a real (I/O-performing) adapter exists.
- **Block Task 5 and re-plan it.** Rejected — the same reasoning as ADR 0002: the task's code is otherwise correct and spec-compliant; reopening it for a currently-inert inconsistency is more overhead than the risk warrants today.

## Consequences

- `deps.py` keeps its current mixed pattern (`get_settings` lazy + cached, `_tenant_repository`/`_installation_service` eager module globals) — no code change from this ADR.
- This is an accepted, temporary inconsistency: the task that introduces the first adapter with real I/O in its constructor (most likely the Postgres-backed `TenantRepository`, or the PyGithub-backed `InstallationTokenProvider` from Task 6, if its constructor ever grows I/O) **must** switch `deps.py` to the `@lru_cache`-wrapped lazy pattern for every dependency, so construction happens on first use rather than at import time.
- Until then, `deps.py`'s three dependency functions should be treated as "these will become `@lru_cache`d lazily-constructed singletons soon" rather than a settled design.
