from typing import Protocol


class PrCommentClient(Protocol):
    async def find_marked_comment(
        self, installation_id: int, repo: str, pr_number: int
    ) -> int | None: ...

    async def create_comment(
        self, installation_id: int, repo: str, pr_number: int, body: str
    ) -> None: ...

    async def update_comment(
        self, installation_id: int, repo: str, comment_id: int, body: str
    ) -> None: ...
