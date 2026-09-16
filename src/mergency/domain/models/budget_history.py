from dataclasses import dataclass

from mergency.domain.models.budget_status import BudgetStatus
from mergency.domain.models.daily_event_count import DailyEventCount


@dataclass(frozen=True)
class BudgetHistory:
    status: BudgetStatus
    daily_counts: list[DailyEventCount]
