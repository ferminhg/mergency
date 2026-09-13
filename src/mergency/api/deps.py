from functools import lru_cache

from mergency.adapters.github.token_manager import PyGithubInstallationTokenProvider
from mergency.adapters.memory.tenant_repository import InMemoryTenantRepository
from mergency.api.settings import Settings
from mergency.domain.installation_service import InstallationService
from mergency.domain.ports.installation_token_provider import InstallationTokenProvider
from mergency.domain.ports.tenant_repository import TenantRepository


@lru_cache
def get_settings() -> Settings:
    return Settings()


@lru_cache
def get_tenant_repository() -> TenantRepository:
    return InMemoryTenantRepository()


@lru_cache
def get_installation_service() -> InstallationService:
    return InstallationService(get_tenant_repository())


@lru_cache
def get_installation_token_provider() -> InstallationTokenProvider:
    settings = get_settings()
    return PyGithubInstallationTokenProvider(
        app_id=settings.github_app_id,
        private_key=settings.github_private_key,
    )
