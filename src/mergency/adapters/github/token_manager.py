import asyncio
from datetime import datetime, timedelta, timezone

from github import GithubIntegration


class PyGithubInstallationTokenProvider:
    def __init__(self, app_id: str, private_key: str, ttl_skew_seconds: int = 60) -> None:
        self._integration = GithubIntegration(app_id, private_key)
        self._ttl_skew_seconds = ttl_skew_seconds
        self._cache: dict[int, tuple[str, datetime]] = {}

    async def get_token(self, installation_id: int) -> str:
        cached = self._cache.get(installation_id)
        if cached is not None:
            token, expires_at = cached
            if expires_at > datetime.now(timezone.utc) + timedelta(seconds=self._ttl_skew_seconds):
                return token

        auth = await asyncio.to_thread(self._integration.get_access_token, installation_id)
        self._cache[installation_id] = (auth.token, auth.expires_at)
        return auth.token
