from datetime import datetime
from typing import Protocol

from mergency.domain.models.event import Event
from mergency.domain.models.event_type import EventType


class EventRepository(Protocol):
    async def save_if_new(self, event: Event) -> bool: ...

    async def get(
        self, installation_id: int, repo: str, sha: str, event_type: EventType, owner: str
    ) -> Event | None: ...

    async def count_since(
        self,
        installation_id: int,
        owner: str,
        event_types: list[EventType],
        since: datetime,
    ) -> int: ...
