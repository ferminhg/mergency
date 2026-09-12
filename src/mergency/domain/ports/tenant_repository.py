from typing import Protocol

from mergency.domain.models.installation import Installation


class TenantRepository(Protocol):
    async def upsert(self, installation: Installation) -> None: ...

    async def mark_deleted(self, installation_id: int) -> None: ...

    async def get(self, installation_id: int) -> Installation | None: ...
