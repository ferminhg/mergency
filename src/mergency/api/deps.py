from functools import lru_cache

from mergency.adapters.github.changed_files_provider import GithubChangedFilesProvider
from mergency.adapters.github.codeowners_provider import GithubCodeownersProvider
from mergency.adapters.github.repository_content_provider import GithubRepositoryContentProvider
from mergency.adapters.github.token_manager import PyGithubInstallationTokenProvider
from mergency.adapters.memory.event_repository import InMemoryEventRepository
from mergency.adapters.memory.tenant_config_repository import InMemoryTenantConfigRepository
from mergency.adapters.memory.tenant_repository import InMemoryTenantRepository
from mergency.api.settings import Settings
from mergency.domain.config_resolver import ConfigResolver
from mergency.domain.event_classifier import EventClassifier
from mergency.domain.installation_service import InstallationService
from mergency.domain.ownership_resolver import OwnershipResolver
from mergency.domain.ports.changed_files_provider import ChangedFilesProvider
from mergency.domain.ports.codeowners_provider import CodeownersProvider
from mergency.domain.ports.event_repository import EventRepository
from mergency.domain.ports.installation_token_provider import InstallationTokenProvider
from mergency.domain.ports.repository_content_provider import RepositoryContentProvider
from mergency.domain.ports.tenant_config_repository import TenantConfigRepository
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


@lru_cache
def get_event_repository() -> EventRepository:
    return InMemoryEventRepository()


@lru_cache
def get_event_classifier() -> EventClassifier:
    return EventClassifier()


@lru_cache
def get_tenant_config_repository() -> TenantConfigRepository:
    return InMemoryTenantConfigRepository()


@lru_cache
def get_repository_content_provider() -> RepositoryContentProvider:
    return GithubRepositoryContentProvider(get_installation_token_provider())


@lru_cache
def get_codeowners_provider() -> CodeownersProvider:
    return GithubCodeownersProvider(get_repository_content_provider())


@lru_cache
def get_changed_files_provider() -> ChangedFilesProvider:
    return GithubChangedFilesProvider(get_installation_token_provider())


@lru_cache
def get_config_resolver() -> ConfigResolver:
    return ConfigResolver(get_repository_content_provider(), get_tenant_config_repository())


@lru_cache
def get_ownership_resolver() -> OwnershipResolver:
    return OwnershipResolver(get_codeowners_provider())


def reset_dependency_caches() -> None:
    get_settings.cache_clear()
    get_tenant_repository.cache_clear()
    get_installation_service.cache_clear()
    get_installation_token_provider.cache_clear()
    get_event_repository.cache_clear()
    get_event_classifier.cache_clear()
    get_tenant_config_repository.cache_clear()
    get_repository_content_provider.cache_clear()
    get_codeowners_provider.cache_clear()
    get_changed_files_provider.cache_clear()
    get_config_resolver.cache_clear()
    get_ownership_resolver.cache_clear()
