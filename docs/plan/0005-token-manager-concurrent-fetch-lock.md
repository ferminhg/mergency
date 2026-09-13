# Close the concurrent-fetch gap in PyGithubInstallationTokenProvider

## Status

implemented

## Context

GitHub issue [#5](https://github.com/ferminhg/mergency/issues/5) tracks `docs/adr/0004-token-manager-known-gaps.md`, which accepted three known gaps in `src/mergency/adapters/github/token_manager.py`'s `PyGithubInstallationTokenProvider`, since nothing called `get_token()` yet:

1. Duplicate-fetch on concurrent cache misses (no lock/de-dup).
2. No error handling around `GithubIntegration.get_access_token()`.
3. An `@lru_cache` test-isolation caveat on `get_installation_token_provider()`.

ADR 0004 is explicit that gap #2 needs the first real caller to decide how failures should surface (propagate, log, retry via Celery) — fixing it now would mean guessing that policy, exactly what the ADR warned against. Gap #3 is a testing caveat with no tests yet exercising it (no test overrides `Settings` after calling `get_installation_token_provider()`), so there is nothing to fix without a concrete test that needs it.

Gap #1 is different: closing it is a self-contained, generic caching-correctness fix (a per-installation lock around the fetch) that doesn't depend on who calls `get_token()` or why. This is the same reasoning `docs/plan/0003-atomic-installation-status-transitions.md` and `docs/plan/0004-lazy-deps-singletons.md` used to fix ADR 0002 and ADR 0003 ahead of their own trigger conditions: small, low-risk, no requirements-guessing involved. So this plan closes gap #1 now and leaves gaps #2 and #3 open, still waiting on the first real caller as ADR 0004 specifies.

## Change

**File:** `src/mergency/adapters/github/token_manager.py`

Added a per-`installation_id` `asyncio.Lock` (`self._locks`) and double-checked-locking around the cache-miss path: a caller first checks the cache without the lock (cheap fast path), and only acquires the lock on a miss. Once inside the lock, it re-checks the cache before calling GitHub — so if another coroutine already fetched a fresh token while this one was waiting for the lock, it reuses that result instead of fetching again. The cache-freshness check was extracted into `_fresh_cached_token` so both call sites share the exact same freshness logic.

**File:** `tests/adapters/github/test_token_manager.py` (new)

Covers: cached-token reuse, refetch on near-expiry, concurrent same-installation misses collapsing into a single `get_access_token` call, and concurrent different-installation misses still fetching independently (proving the lock is per-installation, not global).

## Implementation steps

### Step 1: Add failing tests for the concurrent-miss behavior

- Create `tests/adapters/github/test_token_manager.py` with the four cases described above.
- Run: `docker compose run --rm app pytest tests/adapters/github/test_token_manager.py -v`
  Expected: 3 pass, `test_concurrent_cache_misses_for_the_same_installation_fetch_only_once` FAILS (`call_count == 5`, not `1`) — confirms the gap reproduces.

### Step 2: Add the per-installation lock

- Modify: `src/mergency/adapters/github/token_manager.py` as described above.
- Run: `docker compose run --rm app pytest tests/adapters/github/test_token_manager.py -v`
  Expected: all 4 tests PASS.
- Run: `docker compose run --rm app pytest -v`
  Expected: full suite passes (24 passed — 20 pre-existing + 4 new).
- Run: `docker compose run --rm app ruff check src tests`
  Expected: no errors.
- Commit:
  ```bash
  git add src/mergency/adapters/github/token_manager.py tests/adapters/github/test_token_manager.py
  git commit -m "fix: de-dup concurrent installation-token fetches per installation"
  ```

### Step 3: Record the ADR outcome

- Modify: `docs/adr/0004-token-manager-known-gaps.md` — append an `## Update (implemented)` section after `## Consequences`, noting gap #1 is closed and gaps #2/#3 are still open, per ADR 0002/0003's own "Update (implemented)" precedent.
- Commit:
  ```bash
  git add docs/adr/0004-token-manager-known-gaps.md
  git commit -m "docs: record that ADR 0004's concurrent-fetch gap has been closed"
  ```

### Step 4: Write this plan file

- Create `docs/plan/0005-token-manager-concurrent-fetch-lock.md` (this file).

## Verification

1. `docker compose run --rm app pytest -v` — full suite passes (24 passed, no regressions).
2. `docker compose run --rm app ruff check src tests` — no errors.
3. `grep -n "_locks" src/mergency/adapters/github/token_manager.py` — confirms the per-installation lock dict is in place.
4. Gaps #2 and #3 from ADR 0004 remain open and undocumented-as-fixed anywhere — confirmed by `docs/adr/0004-token-manager-known-gaps.md`'s `## Update (implemented)` section only claiming gap #1.

Note: this session's sandbox had no running Docker daemon, so verification was run directly via `uv run pytest` and `uv run ruff check` instead of through `docker compose`, per the same note in `docs/plan/0004-lazy-deps-singletons.md`. All commands above are the ones a contributor with a working Docker Compose setup should use going forward.
