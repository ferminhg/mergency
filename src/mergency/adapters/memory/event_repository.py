import asyncio
from datetime import date, datetime, timezone

from mergency.domain.models.daily_event_count import DailyEventCount
from mergency.domain.models.event import Event
from mergency.domain.models.event_type import EventType


class InMemoryEventRepository:
    def __init__(self) -> None:
        self._events: dict[tuple[int, str, str, EventType, str | None], Event] = {}
        self._lock = asyncio.Lock()

    async def save_if_new(self, event: Event) -> bool:
        key = (event.installation_id, event.repo, event.sha, event.event_type, event.owner)
        async with self._lock:
            if key in self._events:
                return False
            self._events[key] = event
            return True

    async def get(
        self, installation_id: int, repo: str, sha: str, event_type: EventType, owner: str
    ) -> Event | None:
        async with self._lock:
            return self._events.get((installation_id, repo, sha, event_type, owner))

    async def count_since(
        self,
        installation_id: int,
        owner: str,
        event_types: list[EventType],
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
        event_types: list[EventType],
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
        event_type: EventType,
        since: datetime,
    ) -> list[Event]:
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
