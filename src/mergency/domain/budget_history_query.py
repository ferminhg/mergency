from datetime import datetime, timedelta, timezone

from mergency.domain.budget_calculator import BudgetCalculator
from mergency.domain.models.activity_event_type import ActivityEventType
from mergency.domain.models.budget_history import BudgetHistory
from mergency.domain.ports.activity_event_repository import ActivityEventRepository

_COUNTED_EVENT_TYPES = (ActivityEventType.BUILD_FAILURE, ActivityEventType.REVERT)


class BudgetHistoryQuery:
    def __init__(
        self, budget_calculator: BudgetCalculator, event_repository: ActivityEventRepository
    ) -> None:
        self._budget_calculator = budget_calculator
        self._event_repository = event_repository

    async def for_owner(self, installation_id: int, owner: str) -> BudgetHistory:
        status = await self._budget_calculator.status_for(installation_id, owner)
        since = datetime.now(timezone.utc) - timedelta(days=status.window_days)
        daily_counts = await self._event_repository.daily_counts_since(
            installation_id, owner, _COUNTED_EVENT_TYPES, since
        )
        return BudgetHistory(status=status, daily_counts=daily_counts)
