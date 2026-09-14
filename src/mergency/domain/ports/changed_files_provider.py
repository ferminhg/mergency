from typing import Protocol


class ChangedFilesProvider(Protocol):
    async def files_changed_in_commit(
        self, installation_id: int, repo: str, sha: str
    ) -> list[str]: ...
