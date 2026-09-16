import dataclasses
from datetime import datetime, timezone

import pytest

from mergency.domain.models.activity_event import ActivityEvent
from mergency.domain.models.activity_event_type import ActivityEventType


def test_event_type_values_match_adr():
    assert ActivityEventType.BUILD_FAILURE == "build_failure"
    assert ActivityEventType.REVERT == "revert"
    assert ActivityEventType.INCIDENT == "incident"


def test_event_is_immutable():
    event = ActivityEvent(
        installation_id=1,
        repo="acme/widgets",
        sha="abc123",
        event_type=ActivityEventType.BUILD_FAILURE,
        owner=None,
        ts=datetime.now(timezone.utc),
    )

    with pytest.raises(dataclasses.FrozenInstanceError):
        event.owner = "team-x"
