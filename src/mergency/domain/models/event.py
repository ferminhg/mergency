from dataclasses import dataclass
from datetime import datetime

from mergency.domain.models.event_type import EventType


@dataclass(frozen=True)
class Event:
    installation_id: int
    repo: str
    sha: str
    event_type: EventType
    owner: str | None
    ts: datetime
    check_name: str | None = None
