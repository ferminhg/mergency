from datetime import datetime, timedelta

from mergency.domain.models.activity_event_type import ActivityEventType
from mergency.domain.ports.activity_event_repository import ActivityEventRepository

_CORRELATION_WINDOW = timedelta(hours=24)


class FlakyTestDetector:
    def __init__(self, event_repository: ActivityEventRepository) -> None:
        self._event_repository = event_repository

    async def detect_and_reclassify(
        self,
        installation_id: int,
        repo: str,
        sha: str,
        check_name: str,
        observed_at: datetime,
    ) -> int:
        since = observed_at - _CORRELATION_WINDOW
        prior_failures = await self._event_repository.find_recent(
            installation_id, repo, sha, check_name, ActivityEventType.BUILD_FAILURE, since
        )

        reclassified = 0
        for failure in prior_failures:
            if await self._event_repository.retype(failure, ActivityEventType.FLAKY_TEST):
                reclassified += 1
        return reclassified
