import pytest
from httpx import ASGITransport, AsyncClient

from mergency.adapters.memory.tenant_repository import InMemoryTenantRepository
from mergency.api.app import app
from mergency.api.deps import get_tenant_repository
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


@pytest.fixture(autouse=True)
def override_dependencies():
    repository = InMemoryTenantRepository()
    app.dependency_overrides[get_tenant_repository] = lambda: repository

    yield repository

    app.dependency_overrides.clear()


async def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def test_get_known_installation_returns_stored_state(override_dependencies):
    await override_dependencies.upsert(_installation())

    async with await _client() as client:
        response = await client.get("/internal/installations/42")

    assert response.status_code == 200
    body = response.json()
    assert body["installation_id"] == 42
    assert body["account_login"] == "acme"
    assert body["status"] == "active"


async def test_get_known_installation_never_returns_the_api_token(override_dependencies):
    installation = Installation(
        installation_id=42,
        account_login="acme",
        account_type="Organization",
        status=TenantStatus.ACTIVE,
        repository_selection="all",
        api_token="secret-token-value",
    )
    await override_dependencies.upsert(installation)

    async with await _client() as client:
        response = await client.get("/internal/installations/42")

    assert response.status_code == 200
    body = response.json()
    assert "api_token" not in body


async def test_get_unknown_installation_returns_404(override_dependencies):
    async with await _client() as client:
        response = await client.get("/internal/installations/999")

    assert response.status_code == 404
