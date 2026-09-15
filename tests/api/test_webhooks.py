import hashlib
import hmac
import json

import pytest
from httpx import ASGITransport, AsyncClient

from mergency.adapters.memory.tenant_repository import InMemoryTenantRepository
from mergency.api.app import app
from mergency.api.deps import get_installation_service, get_settings
from mergency.api.settings import Settings
from mergency.domain.installation_service import InstallationService

TEST_SECRET = "test-webhook-secret"


def _signed_headers(payload: bytes, event: str, secret: str = TEST_SECRET) -> dict[str, str]:
    digest = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
    return {
        "X-Hub-Signature-256": f"sha256={digest}",
        "X-GitHub-Event": event,
        "Content-Type": "application/json",
    }


def _installation_payload(action: str, installation_id: int = 1) -> bytes:
    return json.dumps(
        {
            "action": action,
            "installation": {
                "id": installation_id,
                "account": {"login": "acme", "type": "Organization"},
                "repository_selection": "all",
            },
        }
    ).encode()


@pytest.fixture(autouse=True)
def override_dependencies():
    repository = InMemoryTenantRepository()
    service = InstallationService(repository)

    app.dependency_overrides[get_settings] = lambda: Settings(
        github_app_id="test-app-id",
        github_private_key="test-key",
        github_webhook_secret=TEST_SECRET,
    )
    app.dependency_overrides[get_installation_service] = lambda: service

    yield repository

    app.dependency_overrides.clear()


async def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def test_valid_installation_created_webhook_stores_installation(override_dependencies):
    payload = _installation_payload("created")
    headers = _signed_headers(payload, "installation")

    async with await _client() as client:
        response = await client.post("/webhooks/github", content=payload, headers=headers)

    assert response.status_code == 200
    stored = await override_dependencies.get(1)
    assert stored is not None
    assert stored.account_login == "acme"


async def test_invalid_signature_is_rejected(override_dependencies):
    payload = _installation_payload("created")
    headers = _signed_headers(payload, "installation", secret="wrong-secret")

    async with await _client() as client:
        response = await client.post("/webhooks/github", content=payload, headers=headers)

    assert response.status_code == 401
    stored = await override_dependencies.get(1)
    assert stored is None


async def test_unhandled_event_type_is_acknowledged(override_dependencies):
    payload = json.dumps({"action": "some-future-event"}).encode()
    headers = _signed_headers(payload, "some_future_event_type")

    async with await _client() as client:
        response = await client.post("/webhooks/github", content=payload, headers=headers)

    assert response.status_code == 200


async def test_pull_request_with_untracked_action_is_acknowledged_without_enqueueing(
    override_dependencies, monkeypatch
):
    from mergency.api import webhooks

    calls = []
    monkeypatch.setattr(webhooks.evaluate_pr_budget, "delay", lambda *a: calls.append(a))

    payload = json.dumps({"action": "labeled"}).encode()
    headers = _signed_headers(payload, "pull_request")

    async with await _client() as client:
        response = await client.post("/webhooks/github", content=payload, headers=headers)

    assert response.status_code == 200
    assert calls == []


async def test_check_run_event_enqueues_classify_activity_event(override_dependencies, monkeypatch):
    from mergency.api import webhooks

    calls = []
    monkeypatch.setattr(webhooks.classify_activity_event, "delay", lambda *a: calls.append(a))

    payload = json.dumps({"action": "completed", "check_run": {}}).encode()
    headers = _signed_headers(payload, "check_run")

    async with await _client() as client:
        response = await client.post("/webhooks/github", content=payload, headers=headers)

    assert response.status_code == 200
    assert calls == [("check_run", {"action": "completed", "check_run": {}})]


async def test_push_event_enqueues_classify_activity_event(override_dependencies, monkeypatch):
    from mergency.api import webhooks

    calls = []
    monkeypatch.setattr(webhooks.classify_activity_event, "delay", lambda *a: calls.append(a))

    payload = json.dumps({"ref": "refs/heads/main"}).encode()
    headers = _signed_headers(payload, "push")

    async with await _client() as client:
        response = await client.post("/webhooks/github", content=payload, headers=headers)

    assert response.status_code == 200
    assert calls == [("push", {"ref": "refs/heads/main"})]


async def test_installation_repositories_event_is_acknowledged(override_dependencies):
    payload = json.dumps({"action": "added"}).encode()
    headers = _signed_headers(payload, "installation_repositories")

    async with await _client() as client:
        response = await client.post("/webhooks/github", content=payload, headers=headers)

    assert response.status_code == 200


async def test_unhandled_installation_action_is_acknowledged(override_dependencies):
    payload = _installation_payload("new_permissions_accepted")
    headers = _signed_headers(payload, "installation")

    async with await _client() as client:
        response = await client.post("/webhooks/github", content=payload, headers=headers)

    assert response.status_code == 200
    stored = await override_dependencies.get(1)
    assert stored is None


async def test_malformed_installation_payload_is_acknowledged_without_crashing(override_dependencies):
    payload = json.dumps({"action": "created", "installation": {"id": 1}}).encode()
    headers = _signed_headers(payload, "installation")

    async with await _client() as client:
        response = await client.post("/webhooks/github", content=payload, headers=headers)

    assert response.status_code == 200
    stored = await override_dependencies.get(1)
    assert stored is None


async def test_pull_request_opened_enqueues_evaluate_pr_budget(override_dependencies, monkeypatch):
    from mergency.api import webhooks

    calls = []
    monkeypatch.setattr(webhooks.evaluate_pr_budget, "delay", lambda *a: calls.append(a))

    payload = json.dumps({"action": "opened", "number": 42}).encode()
    headers = _signed_headers(payload, "pull_request")

    async with await _client() as client:
        response = await client.post("/webhooks/github", content=payload, headers=headers)

    assert response.status_code == 200
    assert calls == [({"action": "opened", "number": 42},)]


async def test_pull_request_synchronize_enqueues_evaluate_pr_budget(override_dependencies, monkeypatch):
    from mergency.api import webhooks

    calls = []
    monkeypatch.setattr(webhooks.evaluate_pr_budget, "delay", lambda *a: calls.append(a))

    payload = json.dumps({"action": "synchronize", "number": 42}).encode()
    headers = _signed_headers(payload, "pull_request")

    async with await _client() as client:
        response = await client.post("/webhooks/github", content=payload, headers=headers)

    assert response.status_code == 200
    assert len(calls) == 1


async def test_pull_request_reopened_enqueues_evaluate_pr_budget(override_dependencies, monkeypatch):
    from mergency.api import webhooks

    calls = []
    monkeypatch.setattr(webhooks.evaluate_pr_budget, "delay", lambda *a: calls.append(a))

    payload = json.dumps({"action": "reopened", "number": 42}).encode()
    headers = _signed_headers(payload, "pull_request")

    async with await _client() as client:
        response = await client.post("/webhooks/github", content=payload, headers=headers)

    assert response.status_code == 200
    assert len(calls) == 1
