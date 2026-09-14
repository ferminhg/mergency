import asyncio

from mergency.domain.models.tenant_config import TenantConfig


class InMemoryTenantConfigRepository:
    def __init__(self) -> None:
        self._configs: dict[int, TenantConfig] = {}
        self._lock = asyncio.Lock()

    async def upsert(self, config: TenantConfig) -> None:
        async with self._lock:
            self._configs[config.installation_id] = config

    async def get(self, installation_id: int) -> TenantConfig | None:
        async with self._lock:
            return self._configs.get(installation_id)
