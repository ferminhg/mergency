import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest

from mergency.adapters.github.token_manager import PyGithubInstallationTokenProvider
from mergency.domain.errors.token_fetch_error import TokenFetchError


def _make_auth(token: str, expires_in_seconds: int = 3600) -> MagicMock:
    auth = MagicMock()
    auth.token = token
    auth.expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in_seconds)
    return auth


def _make_provider() -> PyGithubInstallationTokenProvider:
    return PyGithubInstallationTokenProvider(app_id="123", private_key="not-a-real-key")


async def test_get_token_returns_cached_token_without_refetching():
    provider = _make_provider()
    provider._integration.get_access_token = MagicMock(return_value=_make_auth("cached-token"))

    first = await provider.get_token(1)
    second = await provider.get_token(1)

    assert first == "cached-token"
    assert second == "cached-token"
    assert provider._integration.get_access_token.call_count == 1


async def test_get_token_refetches_once_the_cached_token_is_near_expiry():
    provider = _make_provider()
    provider._integration.get_access_token = MagicMock(
        side_effect=[_make_auth("stale-token", expires_in_seconds=10), _make_auth("fresh-token")]
    )

    stale = await provider.get_token(1)
    fresh = await provider.get_token(1)

    assert stale == "stale-token"
    assert fresh == "fresh-token"
    assert provider._integration.get_access_token.call_count == 2


async def test_concurrent_cache_misses_for_the_same_installation_fetch_only_once():
    provider = _make_provider()
    call_count = 0

    def slow_get_access_token(installation_id: int) -> MagicMock:
        nonlocal call_count
        call_count += 1
        return _make_auth(f"token-{call_count}")

    provider._integration.get_access_token = MagicMock(side_effect=slow_get_access_token)

    tokens = await asyncio.gather(*(provider.get_token(1) for _ in range(5)))

    assert call_count == 1
    assert set(tokens) == {"token-1"}


async def test_concurrent_cache_misses_for_different_installations_fetch_independently():
    provider = _make_provider()
    provider._integration.get_access_token = MagicMock(
        side_effect=lambda installation_id: _make_auth(f"token-for-{installation_id}")
    )

    token_1, token_2 = await asyncio.gather(provider.get_token(1), provider.get_token(2))

    assert token_1 == "token-for-1"
    assert token_2 == "token-for-2"
    assert provider._integration.get_access_token.call_count == 2


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
