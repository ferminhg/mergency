# Close the `@lru_cache` settings test-isolation gap (ADR 0004, gap #3)

## Status

implemented

## Context

Issue #5 tracks ADR 0004 (`docs/adr/0004-token-manager-known-gaps.md`), which listed three gaps around `PyGithubInstallationTokenProvider` and `src/mergency/api/deps.py`. Gap #1 (duplicate-fetch on concurrent cache misses) was closed in `docs/plan/0005-token-manager-concurrent-fetch-lock.md`. Gap #2 (no error handling around `GithubIntegration.get_access_token()`) was narrowed in `docs/plan/0006-token-manager-error-wrapping.md`, which wraps failures in a domain `TokenFetchError`; the remaining part of gap #2 — deciding the actual failure-surfacing policy (propagate vs. log vs. retry) — still depends on a real caller of `get_token()`, which doesn't exist yet, and is out of scope here.

Gap #3, the `@lru_cache` test-isolation caveat, was the only gap left fully open. `get_settings()` and `get_installation_token_provider()` in `deps.py` are both `@lru_cache`-wrapped, and the latter calls the former internally. Once either is called once in a process, the cached `Settings` instance is baked in — a test overriding settings afterward silently sees the stale value. `tests/conftest.py` was empty, and nothing in the suite called `.cache_clear()`.

Unlike gap #2's remaining half, this gap didn't depend on a real caller — it's a self-contained testing/DI concern, so it was closed now rather than waiting, the same way gap #1 was closed ahead of its originally planned trigger.

## Change

- Added `reset_dependency_caches()` to `src/mergency/api/deps.py`, clearing all four `@lru_cache`d singletons there (`get_settings`, `get_tenant_repository`, `get_installation_service`, `get_installation_token_provider`) — they share the identical caching gotcha, so all four are reset together rather than just the two named in the ADR.
- Added an autouse fixture in `tests/conftest.py` that calls `reset_dependency_caches()` after every test, so no test author has to remember to call `.cache_clear()` manually going forward.
- Added `tests/api/test_deps.py` with two regression tests proving settings changes take effect across a cache-clear boundary, for both `get_settings()` directly and for `get_installation_token_provider()`'s dependent cache.

## Implementation steps

### Step 1 — Sync `main` with `origin/main`
Fast-forwarded local `main` to pick up the already-merged gap #2 work (PR #21).
Verification: `git log --oneline -1` shows `a2f7769` as the base commit.

### Step 2 — Regression test for settings cache isolation (written first, failing)
File: `tests/api/test_deps.py`.
- `test_get_settings_reflects_env_change_after_cache_clear`
- `test_get_installation_token_provider_rebuilds_from_current_settings_after_cache_clear`

Verification: `docker compose run --rm app pytest tests/api/test_deps.py -v` failed with `AttributeError: module 'mergency.api.deps' has no attribute 'reset_dependency_caches'` before step 3.

### Step 3 — Implement `reset_dependency_caches()`
File: `src/mergency/api/deps.py`.
Verification: `docker compose run --rm app pytest tests/api/test_deps.py -v` — one test still failed at this point due to cross-test cache leakage (no autouse fixture yet), which itself demonstrated the gap being closed.

### Step 4 — Autouse fixture in `tests/conftest.py`
Verification: `docker compose run --rm app pytest -v` — full suite (30 tests) passed.

### Step 5 — Update ADR 0004 and add this plan file
Recorded gap #3 as closed in `docs/adr/0004-token-manager-known-gaps.md`, explicitly leaving gap #2's failure-surfacing policy open.

## Verification

1. `docker compose run --rm app pytest -v` — 30 passed.
2. `docker compose run --rm app ruff check src tests` — all checks passed.
3. `grep -rn "reset_dependency_caches" src tests` — present in `deps.py`, `conftest.py`, `test_deps.py`.
4. `docs/adr/0004-token-manager-known-gaps.md` updated to mark gap #3 closed and gap #2's remaining half still open.
