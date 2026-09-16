from datetime import datetime, timezone

import pytest
from httpx import ASGITransport, AsyncClient

from mergency.adapters.memory.tenant_repository import InMemoryTenantRepository
from mergency.api.app import app
from mergency.api.deps import get_tenant_repository
from mergency.domain.models.installation import Installation
from mergency.domain.models.tenant_status import TenantStatus
from mergency.worker import report_incident as task_module


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
    app.dependency_overrides[get_tenant_repository] = lambda: tenant_repository
    yield tenant_repository
    app.dependency_overrides.clear()


async def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def test_accepts_a_valid_incident_report_and_enqueues_the_task(monkeypatch, override_dependencies):
    await override_dependencies.upsert(_installation())
    captured = {}
    monkeypatch.setattr(
        task_module.report_incident, "delay", lambda **kwargs: captured.update(kwargs)
    )

    async with await _client() as client:
        response = await client.post(
            "/api/v1/installations/42/incidents",
            json={
                "repo": "acme/widgets",
                "base_sha": "base123",
                "head_sha": "head456",
                "severity": "P1",
                "occurred_at": "2026-01-01T00:00:00Z",
            },
            headers={"Authorization": "Bearer the-real-token"},
        )

    assert response.status_code == 202
    assert captured["installation_id"] == 42
    assert captured["repo"] == "acme/widgets"
    assert captured["base_sha"] == "base123"
    assert captured["head_sha"] == "head456"
    assert captured["severity"] == "P1"


async def test_defaults_occurred_at_to_now_when_omitted(monkeypatch, override_dependencies):
    await override_dependencies.upsert(_installation())
    captured = {}
    monkeypatch.setattr(
        task_module.report_incident, "delay", lambda **kwargs: captured.update(kwargs)
    )

    async with await _client() as client:
        response = await client.post(
            "/api/v1/installations/42/incidents",
            json={"repo": "acme/widgets", "base_sha": "base123", "head_sha": "head456"},
            headers={"Authorization": "Bearer the-real-token"},
        )

    assert response.status_code == 202
    reported_at = datetime.fromisoformat(captured["occurred_at"])
    assert (datetime.now(timezone.utc) - reported_at).total_seconds() < 5


async def test_returns_404_for_an_unknown_installation(override_dependencies):
    async with await _client() as client:
        response = await client.post(
            "/api/v1/installations/999/incidents",
            json={"repo": "acme/widgets", "base_sha": "base123", "head_sha": "head456"},
            headers={"Authorization": "Bearer whatever"},
        )

    assert response.status_code == 404


async def test_returns_401_for_a_missing_token(override_dependencies):
    await override_dependencies.upsert(_installation())

    async with await _client() as client:
        response = await client.post(
            "/api/v1/installations/42/incidents",
            json={"repo": "acme/widgets", "base_sha": "base123", "head_sha": "head456"},
        )

    assert response.status_code == 401


async def test_returns_401_for_a_wrong_token(override_dependencies):
    await override_dependencies.upsert(_installation())

    async with await _client() as client:
        response = await client.post(
            "/api/v1/installations/42/incidents",
            json={"repo": "acme/widgets", "base_sha": "base123", "head_sha": "head456"},
            headers={"Authorization": "Bearer not-the-token"},
        )

    assert response.status_code == 401
