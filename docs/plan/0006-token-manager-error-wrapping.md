# Wrap token-fetch failures in PyGithubInstallationTokenProvider

## Status

implemented

## Context

GitHub issue [#5](https://github.com/ferminhg/mergency/issues/5) tracks `docs/adr/0004-token-manager-known-gaps.md`. Gap #1 (concurrent-fetch duplication) was closed in `docs/plan/0005-token-manager-concurrent-fetch-lock.md`. Gaps #2 (no error handling around `GithubIntegration.get_access_token()`) and #3 (the `@lru_cache` test-isolation caveat) are still open.

ADR 0004 says gap #2 needs "the first real caller" to decide how failures should surface: propagate, log-and-skip, or retry via Celery. There is still no real caller of `get_token()`, so that policy decision genuinely cannot be made yet — this plan does not make it.

What this plan closes is a narrower, caller-agnostic slice of gap #2: today, `get_token()` lets whatever exception PyGithub happens to raise (`GithubException` and its subclasses, or a lower-level network/transport error) propagate straight out, unwrapped. That means every future caller — whichever failure-surfacing policy it picks — has to know about and depend on PyGithub's exception hierarchy directly, which leaks an adapter-level implementation detail across the port boundary (`domain/ports/installation_token_provider.py` declares no exceptions). Wrapping the raw failure into one stable domain-level exception (`TokenFetchError`) is a generic correctness fix, not a guess at retry/logging policy — the same reasoning `docs/plan/0005-token-manager-concurrent-fetch-lock.md` used to close gap #1 ahead of its trigger condition. The actual "propagate vs. log vs. retry" decision remains for the first real caller, and `TokenFetchError` is designed so that decision can still be made later without another change to `token_manager.py`.

Gap #3 stays open — no test today overrides `Settings` after calling `get_installation_token_provider()`, so there's nothing concrete to fix yet.

## Change

**File:** `src/mergency/domain/errors/token_fetch_error.py` (new)

A single `TokenFetchError(Exception)` class (one class per file, per this repo's convention). It carries `installation_id: int` and wraps the original exception via `raise ... from err` (accessible as `__cause__`), with a message like `"failed to fetch an installation token for installation 42: <original message>"`.

**File:** `src/mergency/adapters/github/token_manager.py`

`get_token()`'s call to `self._integration.get_access_token(...)` is wrapped in `try/except Exception as err: raise TokenFetchError(installation_id, err) from err`. The `try` covers only the `get_access_token` call, not the cache read/write, so a cache-write bug is never mis-reported as a token-fetch failure. The `async with lock:` block still exits normally on exception (context managers always release), so a failed fetch doesn't deadlock later calls for the same `installation_id`.

**File:** `tests/adapters/github/test_token_manager.py`

Adds coverage for: `get_access_token` raising wraps into `TokenFetchError` with the right `installation_id` and `__cause__`; and a failed fetch releases the lock so a subsequent call can retry successfully.

## Implementation steps

### Step 1: Add the `TokenFetchError` domain error, with a unit test

- Create `tests/domain/errors/test_token_fetch_error.py`:

```python
from mergency.domain.errors.token_fetch_error import TokenFetchError


def test_token_fetch_error_message_includes_installation_id():
    cause = ValueError("bad credentials")

    error = TokenFetchError(42, cause)

    assert "42" in str(error)
    assert "bad credentials" in str(error)


def test_token_fetch_error_chains_the_original_exception():
    cause = ValueError("bad credentials")

    error = TokenFetchError(42, cause)

    assert error.installation_id == 42
    assert error.__cause__ is None  # not raised yet, so no __cause__ until `raise ... from`
```

- Run: `docker compose run --rm app pytest tests/domain/errors/test_token_fetch_error.py -v`
  Expected: FAIL with `ModuleNotFoundError: No module named 'mergency.domain.errors'`.

- Create `src/mergency/domain/errors/__init__.py` (empty).
- Create `src/mergency/domain/errors/token_fetch_error.py`:

```python
class TokenFetchError(Exception):
    def __init__(self, installation_id: int, cause: Exception) -> None:
        super().__init__(
            f"failed to fetch an installation token for installation {installation_id}: {cause}"
        )
        self.installation_id = installation_id
```

- Run: `docker compose run --rm app pytest tests/domain/errors/test_token_fetch_error.py -v`
  Expected: 2 passed.

- Commit:
  ```bash
  git add src/mergency/domain/errors/__init__.py src/mergency/domain/errors/token_fetch_error.py tests/domain/errors/test_token_fetch_error.py
  git commit -m "feat: add TokenFetchError domain error"
  ```

### Step 2: Add failing tests for wrapping and lock release on failure

- Modify `tests/adapters/github/test_token_manager.py` — add:

```python
import pytest

from mergency.domain.errors.token_fetch_error import TokenFetchError


async def test_get_token_wraps_get_access_token_failures():
    provider = _make_provider()
    cause = RuntimeError("503 from GitHub")
    provider._integration.get_access_token = MagicMock(side_effect=cause)

    with pytest.raises(TokenFetchError) as exc_info:
        await provider.get_token(42)

    assert exc_info.value.installation_id == 42
    assert exc_info.value.__cause__ is cause


async def test_get_token_releases_the_lock_after_a_failed_fetch():
    provider = _make_provider()
    provider._integration.get_access_token = MagicMock(
        side_effect=[RuntimeError("503 from GitHub"), _make_auth("recovered-token")]
    )

    with pytest.raises(TokenFetchError):
        await provider.get_token(1)
    token = await provider.get_token(1)

    assert token == "recovered-token"
    assert provider._integration.get_access_token.call_count == 2
```

- Run: `docker compose run --rm app pytest tests/adapters/github/test_token_manager.py -v`
  Expected: the two new tests FAIL — `get_token` currently lets `RuntimeError` propagate unwrapped (first test fails on `pytest.raises(TokenFetchError)` not matching), and the deadlock-check test either fails the same way or hangs — confirms the gap.

### Step 3: Wrap the fetch call

- Modify `src/mergency/adapters/github/token_manager.py`:

```python
import asyncio
from datetime import datetime, timedelta, timezone

from github import GithubIntegration

from mergency.domain.errors.token_fetch_error import TokenFetchError


class PyGithubInstallationTokenProvider:
    def __init__(self, app_id: str, private_key: str, ttl_skew_seconds: int = 60) -> None:
        self._integration = GithubIntegration(app_id, private_key)
        self._ttl_skew_seconds = ttl_skew_seconds
        self._cache: dict[int, tuple[str, datetime]] = {}
        self._locks: dict[int, asyncio.Lock] = {}

    async def get_token(self, installation_id: int) -> str:
        fresh = self._fresh_cached_token(installation_id)
        if fresh is not None:
            return fresh

        lock = self._locks.setdefault(installation_id, asyncio.Lock())
        async with lock:
            fresh = self._fresh_cached_token(installation_id)
            if fresh is not None:
                return fresh

            try:
                auth = await asyncio.to_thread(self._integration.get_access_token, installation_id)
            except Exception as err:
                raise TokenFetchError(installation_id, err) from err
            self._cache[installation_id] = (auth.token, auth.expires_at)
            return auth.token

    def _fresh_cached_token(self, installation_id: int) -> str | None:
        cached = self._cache.get(installation_id)
        if cached is None:
            return None

        token, expires_at = cached
        if expires_at > datetime.now(timezone.utc) + timedelta(seconds=self._ttl_skew_seconds):
            return token
        return None
```

- Run: `docker compose run --rm app pytest tests/adapters/github/test_token_manager.py -v`
  Expected: all 6 tests PASS (4 pre-existing + 2 new).
- Run: `docker compose run --rm app pytest -v`
  Expected: full suite passes.
- Run: `docker compose run --rm app ruff check src tests`
  Expected: no errors.
- Commit:
  ```bash
  git add src/mergency/adapters/github/token_manager.py tests/adapters/github/test_token_manager.py
  git commit -m "fix: wrap installation-token fetch failures in TokenFetchError"
  ```

### Step 4: Record the ADR outcome

- Modify `docs/adr/0004-token-manager-known-gaps.md` — append to the existing `## Update (partially implemented)` section (or add a new `## Update` paragraph), noting: gap #2 is partially closed — failures from `get_access_token` now surface as a stable `TokenFetchError` instead of a raw PyGithub exception — but the actual surfacing policy (propagate vs. log vs. retry) is still deferred to the first real caller of `get_token()`, unchanged from the original decision. Gap #3 remains fully open.
- Commit:
  ```bash
  git add docs/adr/0004-token-manager-known-gaps.md
  git commit -m "docs: record that ADR 0004's error-wrapping gap has been narrowed"
  ```

### Step 5: Write this plan file

- Create `docs/plan/0006-token-manager-error-wrapping.md` (this file), and update its `## Status` to `implemented` once steps 1-4 land.

## Verification

1. `docker compose run --rm app pytest -v` — full suite passes, no regressions.
2. `docker compose run --rm app ruff check src tests` — no errors.
3. `grep -n "TokenFetchError" src/mergency/adapters/github/token_manager.py` — confirms the wrapping is in place.
4. `grep -n "installation_token_provider.py" -r src/mergency/domain/ports/` shows the port's `get_token` signature is untouched (`-> str`) — `TokenFetchError` is a raised exception, not a return-type change, so no port/interface change is needed.
5. Gap #3 remains open and undocumented-as-fixed — confirmed by `docs/adr/0004-token-manager-known-gaps.md`'s update only claiming gap #2 is narrowed, not closed, and only for the wrapping, not the surfacing policy.
