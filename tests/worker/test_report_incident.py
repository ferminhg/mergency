from datetime import datetime, timezone

from mergency.adapters.memory.event_repository import InMemoryEventRepository
from mergency.adapters.memory.tenant_config_repository import InMemoryTenantConfigRepository
from mergency.domain.config_resolver import ConfigResolver
from mergency.domain.models.event_type import EventType
from mergency.domain.ownership_resolver import OwnershipResolver
from mergency.worker import report_incident as task_module


class _StubContentProvider:
    async def get_file(self, installation_id, repo, path):
        return None


class _StubCodeownersProvider:
    def __init__(self, owners_by_path: dict[str, list[tuple[str, str]]]) -> None:
        self._owners_by_path = owners_by_path

    async def owners_for(self, installation_id, repo, path):
        return self._owners_by_path.get(path, [])


class _StubChangedFilesProvider:
    def __init__(self, files_by_sha: dict[str, list[str]]) -> None:
        self._files_by_sha = files_by_sha

    async def files_changed_in_commit(self, installation_id, repo, sha):
        return self._files_by_sha.get(sha, [])


class _StubCommitRangeProvider:
    def __init__(self, shas: list[str]) -> None:
        self._shas = shas

    async def commits_between(self, installation_id, repo, base_sha, head_sha):
        return self._shas


def _wire(monkeypatch, *, shas, files_by_sha, codeowners_by_path):
    event_repository = InMemoryEventRepository()
    monkeypatch.setattr(
        task_module, "get_commit_range_provider", lambda: _StubCommitRangeProvider(shas)
    )
    monkeypatch.setattr(task_module, "get_event_repository", lambda: event_repository)
    monkeypatch.setattr(
        task_module,
        "get_config_resolver",
        lambda: ConfigResolver(_StubContentProvider(), InMemoryTenantConfigRepository()),
    )
    monkeypatch.setattr(
        task_module,
        "get_ownership_resolver",
        lambda: OwnershipResolver(_StubCodeownersProvider(codeowners_by_path)),
    )
    monkeypatch.setattr(
        task_module,
        "get_changed_files_provider",
        lambda: _StubChangedFilesProvider(files_by_sha),
    )
    return event_repository


async def test_persists_one_incident_event_per_commit_and_owner_in_the_range(monkeypatch):
    event_repository = _wire(
        monkeypatch,
        shas=["sha-a", "sha-b"],
        files_by_sha={"sha-a": ["src/a.py"], "sha-b": ["src/b.py"]},
        codeowners_by_path={
            "src/a.py": [("TEAM", "@org/team-a")],
            "src/b.py": [("TEAM", "@org/team-b")],
        },
    )
    occurred_at = datetime(2026, 1, 1, tzinfo=timezone.utc)

    await task_module._correlate_resolve_and_persist(
        installation_id=1,
        repo="acme/widgets",
        base_sha="base123",
        head_sha="head456",
        severity="P1",
        occurred_at_iso=occurred_at.isoformat(),
    )

    stored_a = await event_repository.get(1, "acme/widgets", "sha-a", EventType.INCIDENT, "@org/team-a")
    stored_b = await event_repository.get(1, "acme/widgets", "sha-b", EventType.INCIDENT, "@org/team-b")
    assert stored_a is not None
    assert stored_a.ts == occurred_at
    assert stored_b is not None


async def test_falls_back_to_default_team_when_no_codeowners_match(monkeypatch):
    event_repository = _wire(
        monkeypatch,
        shas=["sha-a"],
        files_by_sha={"sha-a": ["src/a.py"]},
        codeowners_by_path={},
    )

    await task_module._correlate_resolve_and_persist(
        installation_id=1,
        repo="acme/widgets",
        base_sha="base123",
        head_sha="head456",
        severity=None,
        occurred_at_iso=datetime.now(timezone.utc).isoformat(),
    )

    stored = await event_repository.get(1, "acme/widgets", "sha-a", EventType.INCIDENT, "unassigned")
    assert stored is not None


def test_report_incident_task_delegates_to_the_async_pipeline(monkeypatch):
    captured = {}

    async def _fake(**kwargs):
        captured.update(kwargs)

    monkeypatch.setattr(task_module, "_correlate_resolve_and_persist", _fake)

    task_module.report_incident(
        installation_id=1,
        repo="acme/widgets",
        base_sha="base123",
        head_sha="head456",
        occurred_at="2026-01-01T00:00:00+00:00",
        severity="P2",
    )

    assert captured["installation_id"] == 1
    assert captured["occurred_at_iso"] == "2026-01-01T00:00:00+00:00"
    assert captured["severity"] == "P2"
