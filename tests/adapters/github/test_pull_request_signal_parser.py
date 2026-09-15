import pytest

from mergency.adapters.github.pull_request_signal_parser import parse_pull_request_signal


def _payload(**overrides) -> dict:
    payload = {
        "action": "opened",
        "number": 42,
        "repository": {"full_name": "acme/widgets"},
        "installation": {"id": 1},
    }
    payload.update(overrides)
    return payload


def test_parses_installation_repo_pr_number_and_action():
    signal = parse_pull_request_signal(_payload())

    assert signal.installation_id == 1
    assert signal.repo == "acme/widgets"
    assert signal.pr_number == 42
    assert signal.action == "opened"


def test_raises_key_error_when_repository_is_missing():
    payload = _payload()
    del payload["repository"]

    with pytest.raises(KeyError):
        parse_pull_request_signal(payload)
