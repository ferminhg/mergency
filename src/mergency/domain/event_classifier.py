import re

from mergency.domain.models.check_run_signal import CheckRunSignal
from mergency.domain.models.event import Event
from mergency.domain.models.event_type import EventType
from mergency.domain.models.push_signal import PushSignal
from mergency.domain.ports.event_repository import EventRepository

_QUALIFYING_CONCLUSIONS = {"failure", "timed_out"}
_REVERT_SUBJECT_PATTERN = re.compile(r'^Revert "')
_REVERT_MENTION = "this reverts commit"


class EventClassifier:
    def __init__(self, event_repository: EventRepository) -> None:
        self._event_repository = event_repository

    async def classify(self, signal: CheckRunSignal | PushSignal) -> Event | None:
        match signal:
            case CheckRunSignal():
                event = self._classify_check_run(signal)
            case PushSignal():
                event = self._classify_push(signal)
            case _:
                raise TypeError(f"unsupported signal type: {type(signal)!r}")

        if event is None:
            return None

        saved = await self._event_repository.save_if_new(event)
        return event if saved else None

    def _classify_check_run(self, signal: CheckRunSignal) -> Event | None:
        if signal.action != "completed":
            return None
        if signal.conclusion not in _QUALIFYING_CONCLUSIONS:
            return None
        if signal.head_branch != signal.default_branch:
            return None
        if signal.completed_at is None:
            return None
        return Event(
            installation_id=signal.installation_id,
            repo=signal.repo,
            sha=signal.sha,
            event_type=EventType.BUILD_FAILURE,
            owner=None,
            ts=signal.completed_at,
        )

    def _classify_push(self, signal: PushSignal) -> Event | None:
        if signal.ref != f"refs/heads/{signal.default_branch}":
            return None
        for commit in signal.commits:
            if _looks_like_revert(commit.message):
                return Event(
                    installation_id=signal.installation_id,
                    repo=signal.repo,
                    sha=commit.sha,
                    event_type=EventType.REVERT,
                    owner=None,
                    ts=commit.timestamp,
                )
        return None


def _looks_like_revert(message: str) -> bool:
    first_line = message.splitlines()[0] if message else ""
    return bool(_REVERT_SUBJECT_PATTERN.match(first_line)) or _REVERT_MENTION in message.lower()
