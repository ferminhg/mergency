from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy.exc import IntegrityError

from mergency.adapters.db.event_repository import SqlAlchemyEventRepository
from mergency.domain.models.daily_event_count import DailyEventCount
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


async def test_save_if_new_persists_check_name(db_engine):
    repository = SqlAlchemyEventRepository(db_engine)
    event = Event(
        installation_id=1,
        repo="acme/widgets",
        sha="abc123",
        event_type=EventType.BUILD_FAILURE,
        owner="@org/team-a",
        ts=datetime.now(timezone.utc),
        check_name="ci/build",
    )

    await repository.save_if_new(event)

    stored = await repository.get(1, "acme/widgets", "abc123", EventType.BUILD_FAILURE, "@org/team-a")
    assert stored.check_name == "ci/build"


async def test_save_if_new_persists_null_check_name_for_revert_events(db_engine):
    repository = SqlAlchemyEventRepository(db_engine)
    event = Event(
        installation_id=1,
        repo="acme/widgets",
        sha="sha1",
        event_type=EventType.REVERT,
        owner="@org/team-a",
        ts=datetime.now(timezone.utc),
    )

    await repository.save_if_new(event)

    stored = await repository.get(1, "acme/widgets", "sha1", EventType.REVERT, "@org/team-a")
    assert stored.check_name is None


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


async def test_daily_counts_since_buckets_events_by_day(db_engine):
    repository = SqlAlchemyEventRepository(db_engine)
    day1 = datetime(2026, 9, 1, 10, 0, tzinfo=timezone.utc)
    day2 = datetime(2026, 9, 2, 10, 0, tzinfo=timezone.utc)
    await repository.save_if_new(_event(sha="sha1", ts=day1))
    await repository.save_if_new(_event(sha="sha2", ts=day2))

    buckets = await repository.daily_counts_since(
        1, "@org/team-a", [EventType.BUILD_FAILURE], day1 - timedelta(days=1)
    )

    assert buckets == [
        DailyEventCount(day=date(2026, 9, 1), count=1),
        DailyEventCount(day=date(2026, 9, 2), count=1),
    ]


async def test_daily_counts_since_excludes_events_outside_the_window(db_engine):
    repository = SqlAlchemyEventRepository(db_engine)
    old_ts = datetime.now(timezone.utc) - timedelta(days=100)
    await repository.save_if_new(_event(sha="old-sha", ts=old_ts))

    buckets = await repository.daily_counts_since(
        1, "@org/team-a", [EventType.BUILD_FAILURE], datetime.now(timezone.utc) - timedelta(days=28)
    )

    assert buckets == []


async def test_find_recent_returns_matching_events_within_window(db_engine):
    repository = SqlAlchemyEventRepository(db_engine)
    now = datetime.now(timezone.utc)
    await repository.save_if_new(Event(
        installation_id=1, repo="acme/widgets", sha="abc123",
        event_type=EventType.BUILD_FAILURE, owner="@org/team-a", ts=now, check_name="ci/build",
    ))

    found = await repository.find_recent(
        1, "acme/widgets", "abc123", "ci/build", EventType.BUILD_FAILURE,
        now - timedelta(hours=1),
    )

    assert len(found) == 1
    assert found[0].check_name == "ci/build"


async def test_find_recent_excludes_events_outside_the_window(db_engine):
    repository = SqlAlchemyEventRepository(db_engine)
    stale_ts = datetime.now(timezone.utc) - timedelta(hours=48)
    await repository.save_if_new(Event(
        installation_id=1, repo="acme/widgets", sha="abc123",
        event_type=EventType.BUILD_FAILURE, owner="@org/team-a", ts=stale_ts, check_name="ci/build",
    ))

    found = await repository.find_recent(
        1, "acme/widgets", "abc123", "ci/build", EventType.BUILD_FAILURE,
        datetime.now(timezone.utc) - timedelta(hours=24),
    )

    assert found == []
