import time

from codeowners import CodeOwners

from mergency.domain.ports.repository_content_provider import RepositoryContentProvider

_CODEOWNERS_PATHS = ("CODEOWNERS", ".github/CODEOWNERS", "docs/CODEOWNERS")
_CACHE_TTL_SECONDS = 300.0


class GithubCodeownersProvider:
    def __init__(self, repository_content_provider: RepositoryContentProvider) -> None:
        self._repository_content_provider = repository_content_provider
        self._cache: dict[tuple[int, str], tuple[CodeOwners, float]] = {}

    async def owners_for(
        self, installation_id: int, repo: str, path: str
    ) -> list[tuple[str, str]]:
        rules = await self._rules_for(installation_id, repo)
        return rules.of(path)

    async def _rules_for(self, installation_id: int, repo: str) -> CodeOwners:
        key = (installation_id, repo)
        cached = self._cache.get(key)
        now = time.monotonic()
        if cached is not None and cached[1] > now:
            return cached[0]

        text = await self._fetch_codeowners_text(installation_id, repo)
        rules = CodeOwners(text or "")
        self._cache[key] = (rules, now + _CACHE_TTL_SECONDS)
        return rules

    async def _fetch_codeowners_text(self, installation_id: int, repo: str) -> str | None:
        for path in _CODEOWNERS_PATHS:
            content = await self._repository_content_provider.get_file(
                installation_id, repo, path
            )
            if content is not None:
                return content
        return None
