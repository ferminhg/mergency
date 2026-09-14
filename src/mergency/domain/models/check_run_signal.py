from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class CheckRunSignal:
    installation_id: int
    repo: str
    sha: str
    action: str
    conclusion: str | None
    head_branch: str
    default_branch: str
    completed_at: datetime | None
