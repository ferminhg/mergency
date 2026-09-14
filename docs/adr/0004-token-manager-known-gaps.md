# Accept known gaps in PyGithubInstallationTokenProvider for the MVP

A code quality review of Task 6 (`docs/plan/0001-github-app-scaffolding.md`) found three gaps in `src/mergency/adapters/github/token_manager.py`. None of them are correctness bugs today, since nothing calls `get_token()` yet — they're flagged here so the first real caller doesn't have to rediscover them.

1. **Duplicate-fetch on concurrent cache misses.** Two concurrent `get_token()` calls for the same `installation_id` that both miss the cache will each independently call GitHub's API; the second write just overwrites the first (last-write-wins). Both tokens are valid, so this can't corrupt state, but it wastes GitHub API calls and installation-token rate-limit budget under bursty concurrent access.
2. **No error handling around `GithubIntegration.get_access_token()`.** A bad credential, network failure, or GitHub rate limit/5xx propagates straight out of `get_token()` uncaught. Fine while nothing calls this method; the first real caller needs to decide how a failure here should surface (fail loudly, log and skip, retry via Celery).
3. **`@lru_cache` test-isolation caveat.** `get_installation_token_provider()` is `@lru_cache`-wrapped and calls `get_settings()` internally. Once called, the `Settings` instance is baked into the cached provider for the rest of the process — a test overriding `get_settings()` after `get_installation_token_provider()` has already run once won't see the change take effect. Standard `lru_cache`-on-settings caveat, not unique to this file.

## Status

accepted

## Considered Options

- **Fix now**: add a per-installation `asyncio.Lock` (or single-flight de-dup) to close gap #1, wrap `get_access_token` with explicit error handling for gap #2, and document a `cache_clear()` pattern for gap #3 (chosen: rejected for now, see Consequences).
- **Accept as-is for the MVP** (chosen). Consistent with ADR 0002 and ADR 0003's precedent: these gaps are currently inert (no caller exists), and fixing them now means guessing at requirements (retry policy, failure surfacing) that the first real caller should actually decide.
- **Block Task 6 and re-plan it.** Rejected — same reasoning as ADR 0002/0003: the task's code is otherwise correct and spec-compliant.

## Consequences

- `token_manager.py` and `deps.py` are left exactly as implemented in Task 6 — no code change from this ADR.
- The task that adds the first real caller of `get_token()` (most likely a PR comment bot or similar GitHub-API-calling component) must:
  - Decide how `get_access_token` failures should surface (exception propagation vs. logged failure vs. retry), and implement that decision explicitly rather than relying on the current silent propagation.
  - Consider whether concurrent-miss duplicate fetches are still acceptable at that point, or whether a lock/de-dup is worth adding.
- Any task that writes tests exercising `get_installation_token_provider()` and needs to vary `Settings` between cases must call `get_installation_token_provider.cache_clear()` (and likely `get_settings.cache_clear()`) between test cases, or restructure the fixture to avoid relying on the cached instance.

## Update (partially implemented)

Gap #1 (duplicate-fetch on concurrent cache misses) was closed in `docs/plan/0005-token-manager-concurrent-fetch-lock.md`, ahead of the originally planned trigger condition (the first real caller of `get_token()`) — see that plan's `## Context` for the rationale. `PyGithubInstallationTokenProvider` now holds a per-`installation_id` `asyncio.Lock` and re-checks the cache after acquiring it, so concurrent cache misses for the same installation collapse into a single `get_access_token` call instead of one per caller.

Gaps #2 (no error handling around `get_access_token`) and #3 (the `@lru_cache` test-isolation caveat) are left open, unchanged from the original decision above: both still depend on context that doesn't exist yet (a real caller to decide failure-surfacing policy for #2; a test that actually varies `Settings` for #3), and closing them now would still mean guessing.

Gap #2 was later narrowed in `docs/plan/0006-token-manager-error-wrapping.md`: `get_token()` now wraps any failure from `get_access_token()` in a stable `TokenFetchError` (`domain/errors/token_fetch_error.py`) instead of letting a raw PyGithub exception cross the port boundary. This closes only the "don't leak an adapter-specific exception type" part of the gap. The actual failure-surfacing policy (propagate vs. log vs. retry) is still deferred to the first real caller of `get_token()`, exactly as originally decided — `TokenFetchError` is designed so that decision can be made later without another change to `token_manager.py`.

Gap #3 was closed in `docs/plan/0007-token-manager-settings-cache-isolation.md`: `deps.py` gained a `reset_dependency_caches()` function clearing all four `@lru_cache`d singletons (`get_settings`, `get_tenant_repository`, `get_installation_service`, `get_installation_token_provider`), and `tests/conftest.py` now calls it in an autouse fixture after every test. This removes the caveat for the whole test suite going forward, rather than requiring each test author to remember `.cache_clear()` individually — unlike gap #2's remaining half, this didn't depend on a real caller existing.

Gap #2's failure-surfacing policy (propagate vs. log vs. retry) remains the only open item, still deferred to the first real caller of `get_token()`.
