import asyncio
import dataclasses
import logging

from mergency.adapters.github.check_run_signal_parser import parse_check_run_signal
from mergency.adapters.github.push_signal_parser import parse_push_signal
from mergency.api.deps import (
    get_changed_files_provider,
    get_config_resolver,
    get_event_classifier,
    get_event_repository,
    get_flaky_test_detector,
    get_ownership_resolver,
)
from mergency.domain.models.check_run_signal import CheckRunSignal
from mergency.domain.models.event import Event
from mergency.domain.models.push_signal import PushSignal
from mergency.worker.celery_app import celery_app

logger = logging.getLogger(__name__)

_PARSERS = {
    "check_run": parse_check_run_signal,
    "push": parse_push_signal,
}


@celery_app.task(name="classify_activity_event")
def classify_activity_event(event_type: str, payload: dict) -> None:
    parser = _PARSERS.get(event_type)
    if parser is None:
        logger.warning("no signal parser registered", extra={"event_type": event_type})
        return

    try:
        signal = parser(payload)
    except (KeyError, ValueError, TypeError) as error:
        logger.warning(
            "activity payload could not be parsed, dropped",
            extra={"event_type": event_type, "error": str(error)},
        )
        return

    asyncio.run(_classify_resolve_and_persist(signal))


async def _classify_resolve_and_persist(signal: CheckRunSignal | PushSignal) -> None:
    event_classifier = get_event_classifier()
    event = await event_classifier.classify(signal)
    if event is not None:
        changed_files = await _changed_files_for(signal, event)
        config = await get_config_resolver().resolve(event.installation_id, event.repo)
        owners = await get_ownership_resolver().resolve_owners(
            event.installation_id, event.repo, changed_files, config.default_team
        )

        event_repository = get_event_repository()
        for owner in owners:
            await event_repository.save_if_new(dataclasses.replace(event, owner=owner))
        return

    if isinstance(signal, CheckRunSignal) and event_classifier.is_flaky_candidate(signal):
        await get_flaky_test_detector().detect_and_reclassify(
            signal.installation_id, signal.repo, signal.sha, signal.check_name, signal.completed_at
        )


async def _changed_files_for(signal: CheckRunSignal | PushSignal, event: Event) -> list[str]:
    if isinstance(signal, PushSignal):
        commit = next(commit for commit in signal.commits if commit.sha == event.sha)
        return commit.files
    return await get_changed_files_provider().files_changed_in_commit(
        event.installation_id, event.repo, event.sha
    )
