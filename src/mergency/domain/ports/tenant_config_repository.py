from typing import Protocol

from mergency.domain.models.tenant_config import TenantConfig


class TenantConfigRepository(Protocol):
    async def upsert(self, config: TenantConfig) -> None: ...

    async def get(self, installation_id: int) -> TenantConfig | None: ...
