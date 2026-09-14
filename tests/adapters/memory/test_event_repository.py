from datetime import datetime, timedelta, timezone

from mergency.adapters.memory.event_repository import InMemoryEventRepository
from mergency.domain.models.event import Event
from mergency.domain.models.event_type import EventType


def _event(sha: str = "abc123", owner: str = "@org/team-a") -> Event:
    return Event(
        installation_id=1,
        repo="acme/widgets",
        sha=sha,
        event_type=EventType.BUILD_FAILURE,
        owner=owner,
        ts=datetime.now(timezone.utc),
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
