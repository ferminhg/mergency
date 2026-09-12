import pytest

from mergency.adapters.memory.tenant_repository import InMemoryTenantRepository
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


async def test_transition_updates_status_and_returns_updated_record(repository):
    await repository.upsert(_installation())

    updated = await repository.transition(42, TenantStatus.SUSPENDED)

    assert updated is not None
    assert updated.status == TenantStatus.SUSPENDED
    stored = await repository.get(42)
    assert stored is not None
    assert stored.status == TenantStatus.SUSPENDED


async def test_transition_preserves_other_fields(repository):
    await repository.upsert(_installation())

    updated = await repository.transition(42, TenantStatus.DELETED)

    assert updated is not None
    assert updated.account_login == "acme"
    assert updated.repository_selection == "all"


async def test_transition_on_unknown_installation_returns_none(repository):
    updated = await repository.transition(999, TenantStatus.SUSPENDED)

    assert updated is None
    assert await repository.get(999) is None
