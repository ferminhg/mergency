from datetime import datetime, timedelta, timezone

from mergency.domain.models.budget_status import BudgetStatus
from mergency.domain.models.event_type import EventType
from mergency.domain.ports.event_repository import EventRepository
from mergency.domain.ports.tenant_config_repository import TenantConfigRepository

_COUNTED_EVENT_TYPES = (EventType.BUILD_FAILURE, EventType.REVERT)
_FALLBACK_ROLLING_WINDOW_DAYS = 28
_FALLBACK_MAX_EVENTS_PER_WINDOW = 5


class BudgetCalculator:
    def __init__(
        self, event_repository: EventRepository, config_repository: TenantConfigRepository
    ) -> None:
        self._event_repository = event_repository
        self._config_repository = config_repository

    async def status_for(self, installation_id: int, owner: str) -> BudgetStatus:
        config = await self._config_repository.get(installation_id)
        window_days = config.rolling_window_days if config else _FALLBACK_ROLLING_WINDOW_DAYS
        limit = config.max_events_per_window if config else _FALLBACK_MAX_EVENTS_PER_WINDOW

        since = datetime.now(timezone.utc) - timedelta(days=window_days)
        consumed = await self._event_repository.count_since(
            installation_id, owner, _COUNTED_EVENT_TYPES, since
        )

        remaining_pct = max(0.0, (limit - consumed) / limit * 100) if limit > 0 else 0.0

        return BudgetStatus(
            owner=owner,
            window_days=window_days,
            limit=limit,
            consumed=consumed,
            remaining_pct=remaining_pct,
        )
