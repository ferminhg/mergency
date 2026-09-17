from dataclasses import dataclass
from datetime import datetime

from mergency.domain.models.activity_event_type import ActivityEventType


@dataclass(frozen=True)
class ActivityEvent:
    installation_id: int
    repo: str
    sha: str
    event_type: ActivityEventType
    owner: str | None
    ts: datetime
    check_name: str | None = None
