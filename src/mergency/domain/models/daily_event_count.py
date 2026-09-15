from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class DailyEventCount:
    day: date
    count: int
