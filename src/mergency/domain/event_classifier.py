import re

from mergency.domain.models.activity_event import ActivityEvent
from mergency.domain.models.activity_event_type import ActivityEventType
from mergency.domain.models.check_run_signal import CheckRunSignal
from mergency.domain.models.push_signal import PushSignal

_QUALIFYING_CONCLUSIONS = {"failure", "timed_out"}
_REVERT_SUBJECT_PATTERN = re.compile(r'^Revert "')
_REVERT_MENTION = "this reverts commit"


class EventClassifier:
    async def classify(self, signal: CheckRunSignal | PushSignal) -> ActivityEvent | None:
        match signal:
            case CheckRunSignal():
                return self._classify_check_run(signal)
            case PushSignal():
                return self._classify_push(signal)
            case _:
                raise TypeError(f"unsupported signal type: {type(signal)!r}")

    def is_flaky_candidate(self, signal: CheckRunSignal) -> bool:
        if signal.action != "completed":
            return False
        if signal.conclusion != "success":
            return False
        if signal.head_branch != signal.default_branch:
            return False
        if signal.completed_at is None:
            return False
        return True

    def _classify_check_run(self, signal: CheckRunSignal) -> ActivityEvent | None:
        if signal.action != "completed":
            return None
        if signal.conclusion not in _QUALIFYING_CONCLUSIONS:
            return None
        if signal.head_branch != signal.default_branch:
            return None
        if signal.completed_at is None:
            return None
        return ActivityEvent(
            installation_id=signal.installation_id,
            repo=signal.repo,
            sha=signal.sha,
            event_type=ActivityEventType.BUILD_FAILURE,
            owner=None,
            ts=signal.completed_at,
            check_name=signal.check_name,
        )

    def _classify_push(self, signal: PushSignal) -> ActivityEvent | None:
        if signal.ref != f"refs/heads/{signal.default_branch}":
            return None
        for commit in signal.commits:
            if _looks_like_revert(commit.message):
                return ActivityEvent(
                    installation_id=signal.installation_id,
                    repo=signal.repo,
                    sha=commit.sha,
                    event_type=ActivityEventType.REVERT,
                    owner=None,
                    ts=commit.timestamp,
                )
        return None


def _looks_like_revert(message: str) -> bool:
    first_line = message.splitlines()[0] if message else ""
    return bool(_REVERT_SUBJECT_PATTERN.match(first_line)) or _REVERT_MENTION in message.lower()
