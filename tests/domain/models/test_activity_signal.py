import dataclasses
from datetime import datetime, timezone

import pytest

from mergency.domain.models.check_run_signal import CheckRunSignal
from mergency.domain.models.push_commit import PushCommit
from mergency.domain.models.push_signal import PushSignal


def test_check_run_signal_is_immutable():
    signal = CheckRunSignal(
        installation_id=1,
        repo="acme/widgets",
        sha="abc123",
        action="completed",
        conclusion="failure",
        head_branch="main",
        default_branch="main",
        completed_at=datetime.now(timezone.utc),
    )

    with pytest.raises(dataclasses.FrozenInstanceError):
        signal.conclusion = "success"


def test_push_signal_is_immutable():
    commit = PushCommit(sha="abc123", message='Revert "x"', timestamp=datetime.now(timezone.utc))
    signal = PushSignal(
        installation_id=1,
        repo="acme/widgets",
        ref="refs/heads/main",
        default_branch="main",
        commits=[commit],
    )

    with pytest.raises(dataclasses.FrozenInstanceError):
        signal.ref = "refs/heads/other"
