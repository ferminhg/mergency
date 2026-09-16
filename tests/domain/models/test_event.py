import dataclasses
from datetime import datetime, timezone

import pytest

from mergency.domain.models.event import Event
from mergency.domain.models.event_type import EventType


def test_event_type_values_match_adr():
    assert EventType.BUILD_FAILURE == "build_failure"
    assert EventType.REVERT == "revert"
    assert EventType.INCIDENT == "incident"


def test_event_is_immutable():
    event = Event(
        installation_id=1,
        repo="acme/widgets",
        sha="abc123",
        event_type=EventType.BUILD_FAILURE,
        owner=None,
        ts=datetime.now(timezone.utc),
    )

    with pytest.raises(dataclasses.FrozenInstanceError):
        event.owner = "team-x"
