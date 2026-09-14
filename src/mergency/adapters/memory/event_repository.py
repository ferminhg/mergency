import asyncio

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
