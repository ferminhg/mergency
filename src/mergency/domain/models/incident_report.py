from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class IncidentReport:
    installation_id: int
    repo: str
    base_sha: str
    head_sha: str
    severity: str | None
    occurred_at: datetime
