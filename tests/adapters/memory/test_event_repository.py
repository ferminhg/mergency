from datetime import date, datetime, timedelta, timezone

from mergency.adapters.memory.event_repository import InMemoryEventRepository
from mergency.domain.models.daily_event_count import DailyEventCount
from mergency.domain.models.event import Event
from mergency.domain.models.event_type import EventType


def _event(
    sha: str = "abc123",
    owner: str = "@org/team-a",
    event_type: EventType = EventType.BUILD_FAILURE,
    ts: datetime | None = None,
) -> Event:
    return Event(
        installation_id=1,
        repo="acme/widgets",
        sha=sha,
        event_type=event_type,
        owner=owner,
        ts=ts or datetime.now(timezone.utc),
    )


async def test_save_if_new_persists_and_reports_new():
    repository = InMemoryEventRepository()

    saved = await repository.save_if_new(_event())

    assert saved is True
    stored = await repository.get(
        1, "acme/widgets", "abc123", EventType.BUILD_FAILURE, "@org/team-a"
    )
    assert stored is not None


async def test_save_if_new_is_idempotent_on_dedupe_key():
    repository = InMemoryEventRepository()
    await repository.save_if_new(_event())

    saved_again = await repository.save_if_new(_event())

    assert saved_again is False


async def test_different_sha_is_a_distinct_event():
    repository = InMemoryEventRepository()
    await repository.save_if_new(_event(sha="abc123"))

    saved = await repository.save_if_new(_event(sha="def456"))

    assert saved is True


async def test_same_raw_event_with_a_different_owner_is_a_distinct_row():
    repository = InMemoryEventRepository()
    await repository.save_if_new(_event(owner="@org/team-a"))

    saved = await repository.save_if_new(_event(owner="@org/team-b"))

    assert saved is True
    assert (
        await repository.get(1, "acme/widgets", "abc123", EventType.BUILD_FAILURE, "@org/team-a")
        is not None
    )
    assert (
        await repository.get(1, "acme/widgets", "abc123", EventType.BUILD_FAILURE, "@org/team-b")
        is not None
    )


async def test_get_returns_none_when_absent():
    repository = InMemoryEventRepository()

    assert (
        await repository.get(1, "acme/widgets", "missing", EventType.BUILD_FAILURE, "@org/team-a")
        is None
    )


async def test_count_since_counts_matching_owner_and_type_within_window():
    repository = InMemoryEventRepository()
    await repository.save_if_new(_event(owner="@org/team-a"))

    count = await repository.count_since(
        1,
        "@org/team-a",
        [EventType.BUILD_FAILURE, EventType.REVERT],
        datetime.now(timezone.utc) - timedelta(days=1),
    )

    assert count == 1


async def test_count_since_excludes_events_outside_the_window():
    old_event = Event(
        installation_id=1,
        repo="acme/widgets",
        sha="old-sha",
        event_type=EventType.BUILD_FAILURE,
        owner="@org/team-a",
        ts=datetime.now(timezone.utc) - timedelta(days=100),
    )
    repository = InMemoryEventRepository()
    await repository.save_if_new(old_event)

    count = await repository.count_since(
        1, "@org/team-a", [EventType.BUILD_FAILURE], datetime.now(timezone.utc) - timedelta(days=28)
    )

    assert count == 0


async def test_count_since_excludes_event_types_not_in_the_allow_list():
    repository = InMemoryEventRepository()
    await repository.save_if_new(_event(owner="@org/team-a"))

    count = await repository.count_since(
        1, "@org/team-a", [EventType.REVERT], datetime.now(timezone.utc) - timedelta(days=1)
    )

    assert count == 0


async def test_count_since_excludes_other_owners():
    repository = InMemoryEventRepository()
    await repository.save_if_new(_event(owner="@org/team-a"))

    count = await repository.count_since(
        1, "@org/team-b", [EventType.BUILD_FAILURE], datetime.now(timezone.utc) - timedelta(days=1)
    )

    assert count == 0


async def test_daily_counts_since_buckets_by_day_for_matching_owner_and_type():
    repository = InMemoryEventRepository()
    day1 = datetime(2026, 9, 1, 10, 0, tzinfo=timezone.utc)
    day2 = datetime(2026, 9, 2, 10, 0, tzinfo=timezone.utc)
    await repository.save_if_new(_event(sha="sha1", ts=day1))
    await repository.save_if_new(_event(sha="sha2", event_type=EventType.REVERT, ts=day1))
    await repository.save_if_new(_event(sha="sha3", ts=day2))

    buckets = await repository.daily_counts_since(
        1, "@org/team-a", [EventType.BUILD_FAILURE, EventType.REVERT], day1 - timedelta(days=1)
    )

    assert buckets == [
        DailyEventCount(day=date(2026, 9, 1), count=2),
        DailyEventCount(day=date(2026, 9, 2), count=1),
    ]


async def test_find_recent_returns_matching_events_within_window():
    repository = InMemoryEventRepository()
    now = datetime.now(timezone.utc)
    matching = Event(
        installation_id=1, repo="acme/widgets", sha="abc123",
        event_type=EventType.BUILD_FAILURE, owner="@org/team-a", ts=now, check_name="ci/build",
    )
    await repository.save_if_new(matching)

    found = await repository.find_recent(
        1, "acme/widgets", "abc123", "ci/build", EventType.BUILD_FAILURE, now - timedelta(hours=1)
    )

    assert found == [matching]


async def test_find_recent_excludes_events_outside_the_window():
    repository = InMemoryEventRepository()
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


async def test_find_recent_excludes_a_different_check_name():
    repository = InMemoryEventRepository()
    now = datetime.now(timezone.utc)
    await repository.save_if_new(Event(
        installation_id=1, repo="acme/widgets", sha="abc123",
        event_type=EventType.BUILD_FAILURE, owner="@org/team-a", ts=now, check_name="ci/lint",
    ))

    found = await repository.find_recent(
        1, "acme/widgets", "abc123", "ci/build", EventType.BUILD_FAILURE, now - timedelta(hours=1)
    )

    assert found == []


async def test_retype_changes_the_event_type_in_place():
    repository = InMemoryEventRepository()
    now = datetime.now(timezone.utc)
    original = Event(
        installation_id=1, repo="acme/widgets", sha="abc123",
        event_type=EventType.BUILD_FAILURE, owner="@org/team-a", ts=now, check_name="ci/build",
    )
    await repository.save_if_new(original)

    retyped = await repository.retype(original, EventType.FLAKY_TEST)

    assert retyped is True
    assert await repository.get(1, "acme/widgets", "abc123", EventType.BUILD_FAILURE, "@org/team-a") is None
    stored = await repository.get(1, "acme/widgets", "abc123", EventType.FLAKY_TEST, "@org/team-a")
    assert stored is not None
    assert stored.ts == now
    assert stored.check_name == "ci/build"


async def test_retype_is_a_noop_when_the_source_event_is_missing():
    repository = InMemoryEventRepository()
    missing = Event(
        installation_id=1, repo="acme/widgets", sha="abc123",
        event_type=EventType.BUILD_FAILURE, owner="@org/team-a", ts=datetime.now(timezone.utc),
    )

    assert await repository.retype(missing, EventType.FLAKY_TEST) is False


async def test_retype_is_a_noop_when_the_target_already_exists():
    repository = InMemoryEventRepository()
    now = datetime.now(timezone.utc)
    original = Event(
        installation_id=1, repo="acme/widgets", sha="abc123",
        event_type=EventType.BUILD_FAILURE, owner="@org/team-a", ts=now, check_name="ci/build",
    )
    already_flaky = Event(
        installation_id=1, repo="acme/widgets", sha="abc123",
        event_type=EventType.FLAKY_TEST, owner="@org/team-a", ts=now, check_name="ci/build",
    )
    await repository.save_if_new(original)
    await repository.save_if_new(already_flaky)

    assert await repository.retype(original, EventType.FLAKY_TEST) is False


async def test_daily_counts_since_excludes_other_owners_types_installations_and_stale_events():
    repository = InMemoryEventRepository()
    now = datetime.now(timezone.utc)
    await repository.save_if_new(_event(sha="sha1", ts=now))
    await repository.save_if_new(
        Event(installation_id=2, repo="acme/widgets", sha="sha2", event_type=EventType.BUILD_FAILURE, owner="@org/team-a", ts=now)
    )
    await repository.save_if_new(_event(sha="sha3", owner="@org/team-b", ts=now))
    old = now - timedelta(days=100)
    await repository.save_if_new(_event(sha="sha4", ts=old))

    buckets = await repository.daily_counts_since(
        1, "@org/team-a", [EventType.BUILD_FAILURE], now - timedelta(days=1)
    )

    assert buckets == [DailyEventCount(day=now.date(), count=1)]
