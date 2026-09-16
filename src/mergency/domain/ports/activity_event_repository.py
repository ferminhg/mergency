from datetime import datetime
from typing import Protocol

from mergency.domain.models.activity_event import ActivityEvent
from mergency.domain.models.activity_event_type import ActivityEventType
from mergency.domain.models.daily_event_count import DailyEventCount


class ActivityEventRepository(Protocol):
    async def save_if_new(self, event: ActivityEvent) -> bool: ...

    async def get(
        self, installation_id: int, repo: str, sha: str, event_type: ActivityEventType, owner: str
    ) -> ActivityEvent | None: ...

    async def count_since(
        self,
        installation_id: int,
        owner: str,
        event_types: list[ActivityEventType],
        since: datetime,
    ) -> int: ...

    async def daily_counts_since(
        self,
        installation_id: int,
        owner: str,
        event_types: list[ActivityEventType],
        since: datetime,
    ) -> list[DailyEventCount]: ...

    async def find_recent(
        self,
        installation_id: int,
        repo: str,
        sha: str,
        check_name: str,
        event_type: ActivityEventType,
        since: datetime,
    ) -> list[ActivityEvent]: ...

    async def retype(self, event: ActivityEvent, new_type: ActivityEventType) -> bool: ...
