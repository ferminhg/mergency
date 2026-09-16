from datetime import datetime, timezone

import pytest

from mergency.domain.event_classifier import EventClassifier
from mergency.domain.models.check_run_signal import CheckRunSignal
from mergency.domain.models.event_type import EventType
from mergency.domain.models.push_commit import PushCommit
from mergency.domain.models.push_signal import PushSignal


@pytest.fixture
def classifier() -> EventClassifier:
    return EventClassifier()


def _check_run_signal(**overrides) -> CheckRunSignal:
    defaults = dict(
        installation_id=1,
        repo="acme/widgets",
        sha="abc123",
        check_name="ci/build",
        action="completed",
        conclusion="failure",
        head_branch="main",
        default_branch="main",
        completed_at=datetime.now(timezone.utc),
    )
    defaults.update(overrides)
    return CheckRunSignal(**defaults)


def _push_signal(message: str = 'Revert "x"') -> PushSignal:
    return PushSignal(
        installation_id=1,
        repo="acme/widgets",
        ref="refs/heads/main",
        default_branch="main",
        commits=[PushCommit(sha="sha1", message=message, timestamp=datetime.now(timezone.utc))],
    )


async def test_classifies_completed_failure_on_default_branch_as_build_failure(classifier):
    event = await classifier.classify(_check_run_signal())

    assert event is not None
    assert event.event_type == EventType.BUILD_FAILURE
    assert event.owner is None


async def test_ignores_non_completed_check_run(classifier):
    assert await classifier.classify(_check_run_signal(action="in_progress")) is None


async def test_ignores_success_conclusion(classifier):
    assert await classifier.classify(_check_run_signal(conclusion="success")) is None


async def test_ignores_check_run_on_feature_branch(classifier):
    assert await classifier.classify(_check_run_signal(head_branch="feature-x")) is None


async def test_build_failure_event_carries_the_check_name(classifier):
    event = await classifier.classify(_check_run_signal(check_name="ci/integration"))

    assert event.check_name == "ci/integration"


async def test_revert_event_has_no_check_name(classifier):
    event = await classifier.classify(_push_signal())

    assert event.check_name is None


async def test_classifies_revert_push_on_default_branch(classifier):
    event = await classifier.classify(_push_signal())

    assert event is not None
    assert event.event_type == EventType.REVERT
    assert event.sha == "sha1"


async def test_ignores_push_without_revert_commit(classifier):
    assert await classifier.classify(_push_signal(message="fix typo")) is None


async def test_ignores_push_to_non_default_branch(classifier):
    signal = PushSignal(
        installation_id=1,
        repo="acme/widgets",
        ref="refs/heads/feature-x",
        default_branch="main",
        commits=[PushCommit(sha="sha1", message='Revert "x"', timestamp=datetime.now(timezone.utc))],
    )
    assert await classifier.classify(signal) is None


async def test_recognizes_explicit_revert_mention(classifier):
    event = await classifier.classify(
        _push_signal(message="Undo bad change\n\nThis reverts commit abc123.")
    )

    assert event is not None
    assert event.event_type == EventType.REVERT
