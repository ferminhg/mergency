import asyncio

from github import Auth, Github
from github.GithubException import UnknownObjectException

from mergency.domain.ports.installation_token_provider import InstallationTokenProvider


class GithubRepositoryContentProvider:
    def __init__(self, token_provider: InstallationTokenProvider) -> None:
        self._token_provider = token_provider

    async def get_file(self, installation_id: int, repo: str, path: str) -> str | None:
        token = await self._token_provider.get_token(installation_id)
        client = Github(auth=Auth.Token(token))

        def _fetch():
            return client.get_repo(repo).get_contents(path)

        try:
            content_file = await asyncio.to_thread(_fetch)
        except UnknownObjectException:
            return None
        return content_file.decoded_content.decode("utf-8")
