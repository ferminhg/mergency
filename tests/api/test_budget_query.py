from datetime import datetime, timezone

import pytest
from httpx import ASGITransport, AsyncClient

from mergency.adapters.memory.activity_event_repository import InMemoryActivityEventRepository
from mergency.adapters.memory.tenant_config_repository import InMemoryTenantConfigRepository
from mergency.adapters.memory.tenant_repository import InMemoryTenantRepository
from mergency.api.app import app
from mergency.api.deps import get_budget_history_query, get_tenant_repository
from mergency.domain.budget_calculator import BudgetCalculator
from mergency.domain.budget_history_query import BudgetHistoryQuery
from mergency.domain.models.activity_event import ActivityEvent
from mergency.domain.models.activity_event_type import ActivityEventType
from mergency.domain.models.installation import Installation
from mergency.domain.models.tenant_config import TenantConfig
from mergency.domain.models.tenant_status import TenantStatus


def _installation(api_token: str | None = "the-real-token") -> Installation:
    return Installation(
        installation_id=42,
        account_login="acme",
        account_type="Organization",
        status=TenantStatus.ACTIVE,
        repository_selection="all",
        api_token=api_token,
    )


@pytest.fixture(autouse=True)
def override_dependencies():
    tenant_repository = InMemoryTenantRepository()
    event_repository = InMemoryActivityEventRepository()
    config_repository = InMemoryTenantConfigRepository()
    budget_history_query = BudgetHistoryQuery(
        BudgetCalculator(event_repository, config_repository), event_repository
    )

    app.dependency_overrides[get_tenant_repository] = lambda: tenant_repository
    app.dependency_overrides[get_budget_history_query] = lambda: budget_history_query

    yield tenant_repository, event_repository, config_repository

    app.dependency_overrides.clear()


async def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def test_returns_status_and_daily_history_for_a_valid_token(override_dependencies):
    tenant_repository, event_repository, config_repository = override_dependencies
    await tenant_repository.upsert(_installation())
    await config_repository.upsert(
        TenantConfig(42, rolling_window_days=28, default_team="unassigned", max_events_per_window=5, warn_threshold_pct=50)
    )
    now = datetime.now(timezone.utc)
    await event_repository.save_if_new(
        ActivityEvent(installation_id=42, repo="acme/widgets", sha="sha1", event_type=ActivityEventType.BUILD_FAILURE, owner="@org/team-a", ts=now)
    )

    async with await _client() as client:
        response = await client.get(
            "/api/v1/installations/42/owners/@org/team-a/budget",
            headers={"Authorization": "Bearer the-real-token"},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["status"]["owner"] == "@org/team-a"
    assert body["status"]["consumed"] == 1
    assert body["daily_counts"] == [{"day": now.date().isoformat(), "count": 1}]


async def test_returns_404_for_an_unknown_installation(override_dependencies):
    async with await _client() as client:
        response = await client.get(
            "/api/v1/installations/999/owners/@org/team-a/budget",
            headers={"Authorization": "Bearer whatever"},
        )

    assert response.status_code == 404


async def test_returns_401_for_a_missing_token(override_dependencies):
    tenant_repository, _, _ = override_dependencies
    await tenant_repository.upsert(_installation())

    async with await _client() as client:
        response = await client.get("/api/v1/installations/42/owners/@org/team-a/budget")

    assert response.status_code == 401


async def test_returns_401_for_a_wrong_token(override_dependencies):
    tenant_repository, _, _ = override_dependencies
    await tenant_repository.upsert(_installation())

    async with await _client() as client:
        response = await client.get(
            "/api/v1/installations/42/owners/@org/team-a/budget",
            headers={"Authorization": "Bearer not-the-token"},
        )

    assert response.status_code == 401


async def test_a_different_installations_token_cannot_read_this_installations_data(override_dependencies):
    tenant_repository, _, _ = override_dependencies
    await tenant_repository.upsert(_installation(api_token="token-for-42"))
    await tenant_repository.upsert(
        Installation(
            installation_id=7,
            account_login="other",
            account_type="Organization",
            status=TenantStatus.ACTIVE,
            repository_selection="all",
            api_token="token-for-7",
        )
    )

    async with await _client() as client:
        response = await client.get(
            "/api/v1/installations/42/owners/@org/team-a/budget",
            headers={"Authorization": "Bearer token-for-7"},
        )

    assert response.status_code == 401
