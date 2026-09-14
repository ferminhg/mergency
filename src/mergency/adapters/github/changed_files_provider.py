import asyncio

from github import Auth, Github

from mergency.domain.ports.installation_token_provider import InstallationTokenProvider


class GithubChangedFilesProvider:
    def __init__(self, token_provider: InstallationTokenProvider) -> None:
        self._token_provider = token_provider

    async def files_changed_in_commit(
        self, installation_id: int, repo: str, sha: str
    ) -> list[str]:
        token = await self._token_provider.get_token(installation_id)
        client = Github(auth=Auth.Token(token))

        def _fetch() -> list[str]:
            commit = client.get_repo(repo).get_commit(sha)
            return [f.filename for f in commit.files]

        return await asyncio.to_thread(_fetch)
