from typing import Protocol


class InstallationTokenProvider(Protocol):
    async def get_token(self, installation_id: int) -> str: ...
