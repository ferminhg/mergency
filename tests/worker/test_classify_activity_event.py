import asyncio

from mergency.adapters.memory.event_repository import InMemoryEventRepository
from mergency.adapters.memory.tenant_config_repository import InMemoryTenantConfigRepository
from mergency.domain.config_resolver import ConfigResolver
from mergency.domain.event_classifier import EventClassifier
from mergency.domain.models.event_type import EventType
from mergency.domain.ownership_resolver import OwnershipResolver
from mergency.worker import classify_activity_event as task_module


class _StubContentProvider:
    def __init__(self, content: str | None = None) -> None:
        self._content = content

    async def get_file(self, installation_id, repo, path):
        return self._content


class _StubCodeownersProvider:
    def __init__(self, owners_by_path: dict[str, list[tuple[str, str]]]) -> None:
        self._owners_by_path = owners_by_path

    async def owners_for(self, installation_id, repo, path):
        return self._owners_by_path.get(path, [])


class _StubChangedFilesProvider:
    def __init__(self, files: list[str]) -> None:
        self._files = files

    async def files_changed_in_commit(self, installation_id, repo, sha):
        return self._files


def _wire(monkeypatch, *, codeowners_by_path=None, changed_files=None):
    event_repository = InMemoryEventRepository()
    monkeypatch.setattr(task_module, "get_event_classifier", lambda: EventClassifier())
    monkeypatch.setattr(task_module, "get_event_repository", lambda: event_repository)
    monkeypatch.setattr(
        task_module,
        "get_config_resolver",
        lambda: ConfigResolver(_StubContentProvider(None), InMemoryTenantConfigRepository()),
    )
    monkeypatch.setattr(
        task_module,
        "get_ownership_resolver",
        lambda: OwnershipResolver(_StubCodeownersProvider(codeowners_by_path or {})),
    )
    monkeypatch.setattr(
        task_module,
        "get_changed_files_provider",
        lambda: _StubChangedFilesProvider(changed_files or []),
    )
    return event_repository


def _check_run_payload():
    return {
        "action": "completed",
        "check_run": {
            "head_sha": "abc123",
            "conclusion": "failure",
            "completed_at": "2026-09-14T10:00:00Z",
            "check_suite": {"head_branch": "main"},
        },
        "repository": {"full_name": "acme/widgets", "default_branch": "main"},
        "installation": {"id": 1},
    }


def _push_payload():
    return {
        "ref": "refs/heads/main",
        "repository": {"full_name": "acme/widgets", "default_branch": "main"},
        "installation": {"id": 1},
        "commits": [
            {
                "id": "sha1",
                "message": 'Revert "add flaky feature"',
                "timestamp": "2026-09-14T10:00:00Z",
                "added": [],
                "removed": [],
                "modified": ["src/a.py"],
            }
        ],
    }


def test_build_failure_is_persisted_with_owner_from_commits_api(monkeypatch):
    event_repository = _wire(
        monkeypatch,
        codeowners_by_path={"src/build.py": [("TEAM", "@org/team-a")]},
        changed_files=["src/build.py"],
    )

    task_module.classify_activity_event("check_run", _check_run_payload())

    stored = asyncio.run(
        event_repository.get(1, "acme/widgets", "abc123", EventType.BUILD_FAILURE, "@org/team-a")
    )
    assert stored is not None


def test_revert_is_persisted_with_owner_from_push_commit_files(monkeypatch):
    event_repository = _wire(monkeypatch, codeowners_by_path={"src/a.py": [("TEAM", "@org/team-b")]})

    task_module.classify_activity_event("push", _push_payload())

    stored = asyncio.run(
        event_repository.get(1, "acme/widgets", "sha1", EventType.REVERT, "@org/team-b")
    )
    assert stored is not None


def test_fans_out_into_one_row_per_distinct_owning_team(monkeypatch):
    event_repository = _wire(
        monkeypatch,
        codeowners_by_path={"src/build.py": [("TEAM", "@org/team-a"), ("TEAM", "@org/team-b")]},
        changed_files=["src/build.py"],
    )

    task_module.classify_activity_event("check_run", _check_run_payload())

    stored_a = asyncio.run(
        event_repository.get(1, "acme/widgets", "abc123", EventType.BUILD_FAILURE, "@org/team-a")
    )
    stored_b = asyncio.run(
        event_repository.get(1, "acme/widgets", "abc123", EventType.BUILD_FAILURE, "@org/team-b")
    )
    assert stored_a is not None
    assert stored_b is not None


def test_falls_back_to_default_team_when_no_codeowners_match(monkeypatch):
    event_repository = _wire(monkeypatch, codeowners_by_path={}, changed_files=["src/build.py"])

    task_module.classify_activity_event("check_run", _check_run_payload())

    stored = asyncio.run(
        event_repository.get(1, "acme/widgets", "abc123", EventType.BUILD_FAILURE, "unassigned")
    )
    assert stored is not None


def test_classify_activity_event_is_idempotent_across_redelivery(monkeypatch):
    event_repository = _wire(
        monkeypatch,
        codeowners_by_path={"src/build.py": [("TEAM", "@org/team-a")]},
        changed_files=["src/build.py"],
    )

    task_module.classify_activity_event("check_run", _check_run_payload())
    task_module.classify_activity_event("check_run", _check_run_payload())

    stored = asyncio.run(
        event_repository.get(1, "acme/widgets", "abc123", EventType.BUILD_FAILURE, "@org/team-a")
    )
    assert stored is not None


def test_unknown_event_type_is_dropped_without_error(monkeypatch):
    def _fail():
        raise AssertionError("classifier should not be constructed for an unknown event type")

    monkeypatch.setattr(task_module, "get_event_classifier", _fail)

    task_module.classify_activity_event("pull_request", {})


def test_malformed_payload_is_dropped_without_error():
    task_module.classify_activity_event("check_run", {"action": "completed"})
