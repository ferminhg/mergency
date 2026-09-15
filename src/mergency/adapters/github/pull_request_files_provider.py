import asyncio

from github import Auth, Github

from mergency.domain.ports.installation_token_provider import InstallationTokenProvider


class GithubPullRequestFilesProvider:
    def __init__(self, token_provider: InstallationTokenProvider) -> None:
        self._token_provider = token_provider

    async def files_changed_in_pull_request(
        self, installation_id: int, repo: str, pr_number: int
    ) -> list[str]:
        token = await self._token_provider.get_token(installation_id)
        client = Github(auth=Auth.Token(token))

        def _fetch() -> list[str]:
            pull_request = client.get_repo(repo).get_pull(pr_number)
            return [file.filename for file in pull_request.get_files()]

        return await asyncio.to_thread(_fetch)
