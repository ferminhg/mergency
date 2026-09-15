import dataclasses

import pytest

from mergency.domain.models.pull_request_signal import PullRequestSignal


def test_pull_request_signal_is_immutable():
    signal = PullRequestSignal(installation_id=1, repo="acme/widgets", pr_number=42, action="opened")

    with pytest.raises(dataclasses.FrozenInstanceError):
        signal.action = "closed"
