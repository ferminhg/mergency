from typing import Protocol


class CodeownersProvider(Protocol):
    async def owners_for(
        self, installation_id: int, repo: str, path: str
    ) -> list[tuple[str, str]]: ...
