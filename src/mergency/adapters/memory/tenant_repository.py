import asyncio
import dataclasses

from mergency.domain.models.installation import Installation
from mergency.domain.models.tenant_status import TenantStatus


class InMemoryTenantRepository:
    def __init__(self) -> None:
        self._installations: dict[int, Installation] = {}
        self._lock = asyncio.Lock()

    async def upsert(self, installation: Installation) -> None:
        async with self._lock:
            self._installations[installation.installation_id] = installation

    async def mark_deleted(self, installation_id: int) -> None:
        async with self._lock:
            existing = self._installations.get(installation_id)
            if existing is not None:
                self._installations[installation_id] = dataclasses.replace(
                    existing, status=TenantStatus.DELETED
                )

    async def get(self, installation_id: int) -> Installation | None:
        async with self._lock:
            return self._installations.get(installation_id)
