import asyncio

from github import Auth, Github

from mergency.domain.ports.installation_token_provider import InstallationTokenProvider
from mergency.domain.pr_comment_formatter import MARKER


class GithubPrCommentClient:
    def __init__(self, token_provider: InstallationTokenProvider) -> None:
        self._token_provider = token_provider

    async def find_marked_comment(
        self, installation_id: int, repo: str, pr_number: int
    ) -> int | None:
        client = await self._client(installation_id)

        def _find() -> int | None:
            issue = client.get_repo(repo).get_issue(pr_number)
            for comment in issue.get_comments():
                if MARKER in comment.body:
                    return comment.id
            return None

        return await asyncio.to_thread(_find)

    async def create_comment(
        self, installation_id: int, repo: str, pr_number: int, body: str
    ) -> None:
        client = await self._client(installation_id)

        def _create() -> None:
            client.get_repo(repo).get_issue(pr_number).create_comment(body)

        await asyncio.to_thread(_create)

    async def update_comment(
        self, installation_id: int, repo: str, comment_id: int, body: str
    ) -> None:
        client = await self._client(installation_id)

        def _update() -> None:
            client.get_repo(repo).get_issue_comment(comment_id).edit(body)

        await asyncio.to_thread(_update)

    async def _client(self, installation_id: int) -> Github:
        token = await self._token_provider.get_token(installation_id)
        return Github(auth=Auth.Token(token))
