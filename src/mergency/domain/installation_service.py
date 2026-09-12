import dataclasses

from mergency.domain.models.installation import Installation
from mergency.domain.models.tenant_status import TenantStatus
from mergency.domain.ports.tenant_repository import TenantRepository


class InstallationService:
    def __init__(self, tenant_repository: TenantRepository) -> None:
        self._tenant_repository = tenant_repository

    async def handle_installation_created(self, installation: Installation) -> None:
        await self._tenant_repository.upsert(installation)

    async def handle_installation_deleted(self, installation_id: int) -> None:
        await self._tenant_repository.mark_deleted(installation_id)

    async def handle_installation_suspended(self, installation_id: int) -> None:
        existing = await self._tenant_repository.get(installation_id)
        if existing is not None:
            suspended = dataclasses.replace(existing, status=TenantStatus.SUSPENDED)
            await self._tenant_repository.upsert(suspended)

    async def handle_installation_unsuspended(self, installation: Installation) -> None:
        active = dataclasses.replace(installation, status=TenantStatus.ACTIVE)
        await self._tenant_repository.upsert(active)
