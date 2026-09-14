from dataclasses import dataclass, field
from datetime import datetime


@dataclass(frozen=True)
class PushCommit:
    sha: str
    message: str
    timestamp: datetime
    files: list[str] = field(default_factory=list)
