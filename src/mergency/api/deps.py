from functools import lru_cache

from mergency.adapters.memory.tenant_repository import InMemoryTenantRepository
from mergency.api.settings import Settings
from mergency.domain.installation_service import InstallationService
from mergency.domain.ports.tenant_repository import TenantRepository

_tenant_repository: TenantRepository = InMemoryTenantRepository()
_installation_service = InstallationService(_tenant_repository)


@lru_cache
def get_settings() -> Settings:
    return Settings()


def get_tenant_repository() -> TenantRepository:
    return _tenant_repository


def get_installation_service() -> InstallationService:
    return _installation_service
