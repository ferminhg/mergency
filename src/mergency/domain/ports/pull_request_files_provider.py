from typing import Protocol


class PullRequestFilesProvider(Protocol):
    async def files_changed_in_pull_request(
        self, installation_id: int, repo: str, pr_number: int
    ) -> list[str]: ...
