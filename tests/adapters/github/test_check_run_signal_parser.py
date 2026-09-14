import pytest

from mergency.adapters.github.check_run_signal_parser import parse_check_run_signal


def _payload(action="completed", conclusion="failure", head_branch="main", default_branch="main"):
    return {
        "action": action,
        "check_run": {
            "head_sha": "abc123",
            "conclusion": conclusion,
            "completed_at": "2026-09-14T10:00:00Z",
            "check_suite": {"head_branch": head_branch},
        },
        "repository": {"full_name": "acme/widgets", "default_branch": default_branch},
        "installation": {"id": 1},
    }


def test_parses_completed_failure_on_default_branch():
    signal = parse_check_run_signal(_payload())

    assert signal.installation_id == 1
    assert signal.repo == "acme/widgets"
    assert signal.sha == "abc123"
    assert signal.action == "completed"
    assert signal.conclusion == "failure"
    assert signal.head_branch == "main"
    assert signal.default_branch == "main"
    assert signal.completed_at.isoformat() == "2026-09-14T10:00:00+00:00"


def test_parses_non_completed_action_with_null_conclusion():
    payload = _payload(action="in_progress", conclusion=None)
    payload["check_run"]["completed_at"] = None

    signal = parse_check_run_signal(payload)

    assert signal.action == "in_progress"
    assert signal.conclusion is None
    assert signal.completed_at is None


def test_missing_check_run_field_raises_key_error():
    with pytest.raises(KeyError):
        parse_check_run_signal({"action": "completed"})
