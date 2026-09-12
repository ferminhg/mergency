import pytest

from mergency.adapters.memory.tenant_repository import InMemoryTenantRepository
from mergency.domain.installation_service import InstallationService
from mergency.domain.models.installation import Installation
from mergency.domain.models.tenant_status import TenantStatus


def _installation(status: TenantStatus = TenantStatus.ACTIVE) -> Installation:
    return Installation(
        installation_id=42,
        account_login="acme",
        account_type="Organization",
        status=status,
        repository_selection="all",
    )


@pytest.fixture
def repository() -> InMemoryTenantRepository:
    return InMemoryTenantRepository()


@pytest.fixture
def service(repository: InMemoryTenantRepository) -> InstallationService:
    return InstallationService(repository)


async def test_handle_installation_created_stores_active_installation(service, repository):
    await service.handle_installation_created(_installation())

    stored = await repository.get(42)
    assert stored is not None
    assert stored.status == TenantStatus.ACTIVE


async def test_handle_installation_deleted_marks_status_deleted(service, repository):
    await service.handle_installation_created(_installation())
    await service.handle_installation_deleted(42)

    stored = await repository.get(42)
    assert stored is not None
    assert stored.status == TenantStatus.DELETED


async def test_handle_installation_suspended_toggles_status(service, repository):
    await service.handle_installation_created(_installation())
    await service.handle_installation_suspended(42)

    stored = await repository.get(42)
    assert stored is not None
    assert stored.status == TenantStatus.SUSPENDED


async def test_handle_installation_unsuspended_reactivates(service, repository):
    await service.handle_installation_created(_installation(status=TenantStatus.SUSPENDED))
    await service.handle_installation_unsuspended(_installation(status=TenantStatus.SUSPENDED))

    stored = await repository.get(42)
    assert stored is not None
    assert stored.status == TenantStatus.ACTIVE


async def test_recreating_an_existing_installation_updates_rather_than_duplicates(service, repository):
    await service.handle_installation_created(_installation())
    await service.handle_installation_created(_installation())

    stored = await repository.get(42)
    assert stored is not None
    assert stored.installation_id == 42
