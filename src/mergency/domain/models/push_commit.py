from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class PushCommit:
    sha: str
    message: str
    timestamp: datetime
