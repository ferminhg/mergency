from typing import Protocol


class RepositoryContentProvider(Protocol):
    async def get_file(self, installation_id: int, repo: str, path: str) -> str | None: ...
