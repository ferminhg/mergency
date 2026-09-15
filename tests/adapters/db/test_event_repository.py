from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.exc import IntegrityError

from mergency.adapters.db.event_repository import SqlAlchemyEventRepository
from mergency.domain.models.event import Event
from mergency.domain.models.event_type import EventType


def _event(sha: str = "abc123", owner: str = "@org/team-a", ts: datetime | None = None) -> Event:
    return Event(
        installation_id=1,
        repo="acme/widgets",
        sha=sha,
        event_type=EventType.BUILD_FAILURE,
        owner=owner,
        ts=ts or datetime.now(timezone.utc),
    )


async def test_save_if_new_persists_and_reports_new(db_engine):
    repository = SqlAlchemyEventRepository(db_engine)

    saved = await repository.save_if_new(_event())

    assert saved is True
    stored = await repository.get(1, "acme/widgets", "abc123", EventType.BUILD_FAILURE, "@org/team-a")
    assert stored is not None
    assert stored.owner == "@org/team-a"


async def test_save_if_new_is_idempotent_on_dedupe_key(db_engine):
    repository = SqlAlchemyEventRepository(db_engine)
    await repository.save_if_new(_event())

    saved_again = await repository.save_if_new(_event())

    assert saved_again is False


async def test_same_raw_event_with_a_different_owner_is_a_distinct_row(db_engine):
    repository = SqlAlchemyEventRepository(db_engine)
    await repository.save_if_new(_event(owner="@org/team-a"))

    saved = await repository.save_if_new(_event(owner="@org/team-b"))

    assert saved is True


async def test_save_if_new_reraises_on_not_null_violation(db_engine):
    repository = SqlAlchemyEventRepository(db_engine)
    event_with_no_owner = _event(owner=None)

    with pytest.raises(IntegrityError):
        await repository.save_if_new(event_with_no_owner)


async def test_get_returns_none_when_absent(db_engine):
    repository = SqlAlchemyEventRepository(db_engine)

    assert (
        await repository.get(1, "acme/widgets", "missing", EventType.BUILD_FAILURE, "@org/team-a")
        is None
    )


async def test_count_since_counts_matching_owner_and_type_within_window(db_engine):
    repository = SqlAlchemyEventRepository(db_engine)
    await repository.save_if_new(_event())

    count = await repository.count_since(
        1,
        "@org/team-a",
        [EventType.BUILD_FAILURE, EventType.REVERT],
        datetime.now(timezone.utc) - timedelta(days=1),
    )

    assert count == 1


async def test_count_since_excludes_events_outside_the_window(db_engine):
    repository = SqlAlchemyEventRepository(db_engine)
    old_ts = datetime.now(timezone.utc) - timedelta(days=100)
    await repository.save_if_new(_event(sha="old-sha", ts=old_ts))

    count = await repository.count_since(
        1, "@org/team-a", [EventType.BUILD_FAILURE], datetime.now(timezone.utc) - timedelta(days=28)
    )

    assert count == 0
