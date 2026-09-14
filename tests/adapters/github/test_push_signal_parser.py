import pytest

from mergency.adapters.github.push_signal_parser import parse_push_signal


def _payload():
    return {
        "ref": "refs/heads/main",
        "repository": {"full_name": "acme/widgets", "default_branch": "main"},
        "installation": {"id": 1},
        "commits": [
            {"id": "sha1", "message": 'Revert "add flaky feature"', "timestamp": "2026-09-14T10:00:00Z"},
        ],
    }


def test_parses_push_with_commits():
    signal = parse_push_signal(_payload())

    assert signal.installation_id == 1
    assert signal.repo == "acme/widgets"
    assert signal.ref == "refs/heads/main"
    assert signal.default_branch == "main"
    assert len(signal.commits) == 1
    assert signal.commits[0].sha == "sha1"
    assert signal.commits[0].message == 'Revert "add flaky feature"'


def test_missing_repository_field_raises_key_error():
    with pytest.raises(KeyError):
        parse_push_signal({"ref": "refs/heads/main", "commits": []})


def test_parses_commit_added_removed_and_modified_files():
    payload = {
        "ref": "refs/heads/main",
        "repository": {"full_name": "acme/widgets", "default_branch": "main"},
        "installation": {"id": 1},
        "commits": [
            {
                "id": "sha1",
                "message": "fix bug",
                "timestamp": "2026-09-14T10:00:00Z",
                "added": ["src/new.py"],
                "removed": ["src/old.py"],
                "modified": ["src/changed.py"],
            }
        ],
    }

    signal = parse_push_signal(payload)

    assert signal.commits[0].files == ["src/new.py", "src/old.py", "src/changed.py"]
