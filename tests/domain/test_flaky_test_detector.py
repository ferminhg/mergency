from datetime import datetime, timedelta, timezone

from mergency.adapters.memory.activity_event_repository import InMemoryActivityEventRepository
from mergency.domain.flaky_test_detector import FlakyTestDetector
from mergency.domain.models.activity_event import ActivityEvent
from mergency.domain.models.activity_event_type import ActivityEventType


async def test_reclassifies_a_prior_failure_on_the_same_sha_and_check_within_the_window():
    event_repository = InMemoryActivityEventRepository()
    now = datetime.now(timezone.utc)
    await event_repository.save_if_new(ActivityEvent(
        installation_id=1, repo="acme/widgets", sha="abc123",
        event_type=ActivityEventType.BUILD_FAILURE, owner="@org/team-a", ts=now, check_name="ci/build",
    ))
    detector = FlakyTestDetector(event_repository)

    reclassified = await detector.detect_and_reclassify(
        1, "acme/widgets", "abc123", "ci/build", now + timedelta(hours=1)
    )

    assert reclassified == 1
    assert await event_repository.get(1, "acme/widgets", "abc123", ActivityEventType.BUILD_FAILURE, "@org/team-a") is None
    assert await event_repository.get(1, "acme/widgets", "abc123", ActivityEventType.FLAKY_TEST, "@org/team-a") is not None


async def test_reclassifies_every_owner_fanned_out_row_for_the_same_check():
    event_repository = InMemoryActivityEventRepository()
    now = datetime.now(timezone.utc)
    await event_repository.save_if_new(ActivityEvent(
        installation_id=1, repo="acme/widgets", sha="abc123",
        event_type=ActivityEventType.BUILD_FAILURE, owner="@org/team-a", ts=now, check_name="ci/build",
    ))
    await event_repository.save_if_new(ActivityEvent(
        installation_id=1, repo="acme/widgets", sha="abc123",
        event_type=ActivityEventType.BUILD_FAILURE, owner="@org/team-b", ts=now, check_name="ci/build",
    ))
    detector = FlakyTestDetector(event_repository)

    reclassified = await detector.detect_and_reclassify(
        1, "acme/widgets", "abc123", "ci/build", now + timedelta(hours=1)
    )

    assert reclassified == 2


async def test_does_not_reclassify_a_failure_outside_the_correlation_window():
    event_repository = InMemoryActivityEventRepository()
    now = datetime.now(timezone.utc)
    await event_repository.save_if_new(ActivityEvent(
        installation_id=1, repo="acme/widgets", sha="abc123",
        event_type=ActivityEventType.BUILD_FAILURE, owner="@org/team-a", ts=now, check_name="ci/build",
    ))
    detector = FlakyTestDetector(event_repository)

    reclassified = await detector.detect_and_reclassify(
        1, "acme/widgets", "abc123", "ci/build", now + timedelta(hours=25)
    )

    assert reclassified == 0
    assert await event_repository.get(1, "acme/widgets", "abc123", ActivityEventType.BUILD_FAILURE, "@org/team-a") is not None


async def test_does_not_reclassify_a_failure_for_a_different_check_name():
    event_repository = InMemoryActivityEventRepository()
    now = datetime.now(timezone.utc)
    await event_repository.save_if_new(ActivityEvent(
        installation_id=1, repo="acme/widgets", sha="abc123",
        event_type=ActivityEventType.BUILD_FAILURE, owner="@org/team-a", ts=now, check_name="ci/lint",
    ))
    detector = FlakyTestDetector(event_repository)

    reclassified = await detector.detect_and_reclassify(
        1, "acme/widgets", "abc123", "ci/build", now + timedelta(hours=1)
    )

    assert reclassified == 0


async def test_is_a_noop_when_there_is_no_prior_failure():
    event_repository = InMemoryActivityEventRepository()
    detector = FlakyTestDetector(event_repository)

    reclassified = await detector.detect_and_reclassify(
        1, "acme/widgets", "abc123", "ci/build", datetime.now(timezone.utc)
    )

    assert reclassified == 0
