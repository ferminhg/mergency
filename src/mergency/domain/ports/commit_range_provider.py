from typing import Protocol


class CommitRangeProvider(Protocol):
    async def commits_between(
        self, installation_id: int, repo: str, base_sha: str, head_sha: str
    ) -> list[str]: ...
