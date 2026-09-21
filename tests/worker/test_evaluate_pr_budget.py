from mergency.domain.models.budget_severity import BudgetSeverity
from mergency.domain.models.budget_status import BudgetStatus
from mergency.domain.models.tenant_config import TenantConfig
from mergency.domain.pr_comment_formatter import MARKER
from mergency.worker import evaluate_pr_budget as task_module


def _payload(action: str = "opened") -> dict:
    return {
        "action": action,
        "installation": {"id": 1},
        "repository": {"full_name": "acme/widgets"},
        "number": 42,
    }


class _StubFilesProvider:
    async def files_changed_in_pull_request(self, installation_id, repo, pr_number):
        return ["src/a.py"]


class _StubConfigResolver:
    async def resolve(self, installation_id, repo):
        return TenantConfig(installation_id, 28, "unassigned", 5, 50)


class _StubEvaluator:
    def __init__(self, shrinking: list[BudgetStatus]) -> None:
        self._shrinking = shrinking

    async def evaluate(self, installation_id, repo, changed_files, default_team, warn_threshold_pct):
        return self._shrinking


class _RecordingCommentClient:
    def __init__(self, existing_comment_id: int | None) -> None:
        self._existing_comment_id = existing_comment_id
        self.created: list[tuple] = []
        self.updated: list[tuple] = []

    async def find_marked_comment(self, installation_id, repo, pr_number):
        return self._existing_comment_id

    async def create_comment(self, installation_id, repo, pr_number, body):
        self.created.append((installation_id, repo, pr_number, body))

    async def update_comment(self, installation_id, repo, comment_id, body):
        self.updated.append((installation_id, repo, comment_id, body))


class _RecordingGifProvider:
    def __init__(self, url: str = "https://giphy.example/gif.gif") -> None:
        self.url = url
        self.calls: list[BudgetSeverity] = []

    async def gif_for_severity(self, severity):
        self.calls.append(severity)
        return self.url


def _shrinking_status(remaining_pct: float = 20.0) -> BudgetStatus:
    return BudgetStatus(
        owner="@org/team-a", window_days=28, limit=5, consumed=4, remaining_pct=remaining_pct
    )


def _wire(monkeypatch, *, shrinking: list[BudgetStatus], existing_comment_id: int | None):
    comment_client = _RecordingCommentClient(existing_comment_id)
    gif_provider = _RecordingGifProvider()
    monkeypatch.setattr(task_module, "get_pull_request_files_provider", lambda: _StubFilesProvider())
    monkeypatch.setattr(task_module, "get_config_resolver", lambda: _StubConfigResolver())
    monkeypatch.setattr(task_module, "get_pr_budget_evaluator", lambda: _StubEvaluator(shrinking))
    monkeypatch.setattr(task_module, "get_pr_comment_client", lambda: comment_client)
    monkeypatch.setattr(task_module, "get_gif_provider", lambda: gif_provider)
    return comment_client, gif_provider


def test_creates_a_comment_with_a_gif_when_an_owner_is_shrinking_and_none_exists_yet(monkeypatch):
    comment_client, gif_provider = _wire(
        monkeypatch, shrinking=[_shrinking_status()], existing_comment_id=None
    )

    task_module.evaluate_pr_budget(_payload())

    assert len(comment_client.created) == 1
    assert comment_client.updated == []
    installation_id, repo, pr_number, body = comment_client.created[0]
    assert (installation_id, repo, pr_number) == (1, "acme/widgets", 42)
    assert MARKER in body
    assert "@org/team-a" in body
    assert gif_provider.url in body
    assert gif_provider.calls == [BudgetSeverity.WARN]


def test_updates_the_existing_comment_when_still_shrinking(monkeypatch):
    comment_client, gif_provider = _wire(
        monkeypatch, shrinking=[_shrinking_status()], existing_comment_id=999
    )

    task_module.evaluate_pr_budget(_payload())

    assert comment_client.created == []
    assert len(comment_client.updated) == 1
    installation_id, repo, comment_id, body = comment_client.updated[0]
    assert (installation_id, repo, comment_id) == (1, "acme/widgets", 999)
    assert "@org/team-a" in body
    assert gif_provider.url in body


def test_uses_the_breach_severity_gif_when_an_owner_has_fully_consumed_its_budget(monkeypatch):
    _comment_client, gif_provider = _wire(
        monkeypatch, shrinking=[_shrinking_status(remaining_pct=0.0)], existing_comment_id=None
    )

    task_module.evaluate_pr_budget(_payload())

    assert gif_provider.calls == [BudgetSeverity.BREACH]


def test_updates_the_existing_comment_to_recovered_when_no_longer_shrinking(monkeypatch):
    comment_client, gif_provider = _wire(monkeypatch, shrinking=[], existing_comment_id=999)

    task_module.evaluate_pr_budget(_payload())

    assert comment_client.created == []
    assert len(comment_client.updated) == 1
    _, _, comment_id, body = comment_client.updated[0]
    assert comment_id == 999
    assert "recovered" in body.lower()
    assert gif_provider.calls == []


def test_does_nothing_when_healthy_and_no_existing_comment(monkeypatch):
    comment_client, gif_provider = _wire(monkeypatch, shrinking=[], existing_comment_id=None)

    task_module.evaluate_pr_budget(_payload())

    assert comment_client.created == []
    assert comment_client.updated == []
    assert gif_provider.calls == []


def test_malformed_payload_is_dropped_without_error():
    task_module.evaluate_pr_budget({"action": "opened"})
