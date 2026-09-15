import asyncio
from datetime import datetime

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
