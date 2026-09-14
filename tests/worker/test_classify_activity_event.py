import asyncio

from mergency.adapters.memory.event_repository import InMemoryEventRepository
from mergency.domain.event_classifier import EventClassifier
from mergency.domain.models.event_type import EventType
from mergency.worker import classify_activity_event as task_module


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


def test_classify_activity_event_persists_build_failure(monkeypatch):
    repository = InMemoryEventRepository()
    monkeypatch.setattr(task_module, "get_event_classifier", lambda: EventClassifier(repository))

    task_module.classify_activity_event("check_run", _check_run_payload())

    stored = asyncio.run(repository.get(1, "acme/widgets", "abc123", EventType.BUILD_FAILURE))
    assert stored is not None


def test_classify_activity_event_is_idempotent_across_redelivery(monkeypatch):
    repository = InMemoryEventRepository()
    monkeypatch.setattr(task_module, "get_event_classifier", lambda: EventClassifier(repository))

    task_module.classify_activity_event("check_run", _check_run_payload())
    task_module.classify_activity_event("check_run", _check_run_payload())

    stored = asyncio.run(repository.get(1, "acme/widgets", "abc123", EventType.BUILD_FAILURE))
    assert stored is not None


def test_unknown_event_type_is_dropped_without_error(monkeypatch):
    def _fail():
        raise AssertionError("classifier should not be constructed for an unknown event type")

    monkeypatch.setattr(task_module, "get_event_classifier", _fail)

    task_module.classify_activity_event("pull_request", {})


def test_malformed_payload_is_dropped_without_error():
    task_module.classify_activity_event("check_run", {"action": "completed"})


def test_malformed_timestamp_is_dropped_without_error():
    payload = _check_run_payload()
    payload["check_run"]["completed_at"] = "not-a-date"

    task_module.classify_activity_event("check_run", payload)
