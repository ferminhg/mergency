import asyncio

from github import Auth, Github

from mergency.domain.ports.installation_token_provider import InstallationTokenProvider


class GithubCommitRangeProvider:
    def __init__(self, token_provider: InstallationTokenProvider) -> None:
        self._token_provider = token_provider

    async def commits_between(
        self, installation_id: int, repo: str, base_sha: str, head_sha: str
    ) -> list[str]:
        if base_sha == head_sha:
            return [head_sha]

        token = await self._token_provider.get_token(installation_id)
        client = Github(auth=Auth.Token(token))

        def _fetch() -> list[str]:
            comparison = client.get_repo(repo).compare(base_sha, head_sha)
            return [commit.sha for commit in comparison.commits]

        return await asyncio.to_thread(_fetch)
