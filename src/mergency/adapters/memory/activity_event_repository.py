import asyncio
import dataclasses
from datetime import date, datetime, timezone

from mergency.domain.models.activity_event import ActivityEvent
from mergency.domain.models.activity_event_type import ActivityEventType
from mergency.domain.models.daily_event_count import DailyEventCount


class InMemoryActivityEventRepository:
    def __init__(self) -> None:
        self._events: dict[tuple[int, str, str, ActivityEventType, str | None], ActivityEvent] = {}
        self._lock = asyncio.Lock()

    async def save_if_new(self, event: ActivityEvent) -> bool:
        key = (event.installation_id, event.repo, event.sha, event.event_type, event.owner)
        async with self._lock:
            if key in self._events:
                return False
            self._events[key] = event
            return True

    async def get(
        self, installation_id: int, repo: str, sha: str, event_type: ActivityEventType, owner: str
    ) -> ActivityEvent | None:
        async with self._lock:
            return self._events.get((installation_id, repo, sha, event_type, owner))

    async def count_since(
        self,
        installation_id: int,
        owner: str,
        event_types: list[ActivityEventType],
        since: datetime,
    ) -> int:
        allow_list = set(event_types)
        async with self._lock:
            return sum(
                1
                for event in self._events.values()
                if event.installation_id == installation_id
                and event.owner == owner
                and event.event_type in allow_list
                and event.ts >= since
            )

    async def daily_counts_since(
        self,
        installation_id: int,
        owner: str,
        event_types: list[ActivityEventType],
        since: datetime,
    ) -> list[DailyEventCount]:
        allow_list = set(event_types)
        counts: dict[date, int] = {}
        async with self._lock:
            for event in self._events.values():
                if not (
                    event.installation_id == installation_id
                    and event.owner == owner
                    and event.event_type in allow_list
                    and event.ts >= since
                ):
                    continue
                day = event.ts.astimezone(timezone.utc).date()
                counts[day] = counts.get(day, 0) + 1
        return [DailyEventCount(day=day, count=count) for day, count in sorted(counts.items())]

    async def find_recent(
        self,
        installation_id: int,
        repo: str,
        sha: str,
        check_name: str,
        event_type: ActivityEventType,
        since: datetime,
    ) -> list[ActivityEvent]:
        async with self._lock:
            return [
                event
                for event in self._events.values()
                if event.installation_id == installation_id
                and event.repo == repo
                and event.sha == sha
                and event.check_name == check_name
                and event.event_type == event_type
                and event.ts >= since
            ]

    async def retype(self, event: ActivityEvent, new_type: ActivityEventType) -> bool:
        old_key = (event.installation_id, event.repo, event.sha, event.event_type, event.owner)
        new_key = (event.installation_id, event.repo, event.sha, new_type, event.owner)
        async with self._lock:
            if old_key not in self._events:
                return False
            if new_key in self._events:
                return False
            retyped = dataclasses.replace(self._events.pop(old_key), event_type=new_type)
            self._events[new_key] = retyped
            return True
