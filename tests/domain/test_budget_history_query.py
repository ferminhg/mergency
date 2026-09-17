from datetime import datetime, timedelta, timezone

from mergency.adapters.memory.activity_event_repository import InMemoryActivityEventRepository
from mergency.adapters.memory.tenant_config_repository import InMemoryTenantConfigRepository
from mergency.domain.budget_calculator import BudgetCalculator
from mergency.domain.budget_history_query import BudgetHistoryQuery
from mergency.domain.models.activity_event import ActivityEvent
from mergency.domain.models.activity_event_type import ActivityEventType
from mergency.domain.models.daily_event_count import DailyEventCount
from mergency.domain.models.tenant_config import TenantConfig


def _event(event_type: ActivityEventType, sha: str, owner: str, ts: datetime) -> ActivityEvent:
    return ActivityEvent(
        installation_id=1, repo="acme/widgets", sha=sha, event_type=event_type, owner=owner, ts=ts
    )


async def test_for_owner_returns_current_status_and_daily_history_within_the_window():
    event_repository = InMemoryActivityEventRepository()
    config_repository = InMemoryTenantConfigRepository()
    await config_repository.upsert(
        TenantConfig(1, rolling_window_days=28, default_team="unassigned", max_events_per_window=5, warn_threshold_pct=50)
    )
    now = datetime.now(timezone.utc)
    await event_repository.save_if_new(_event(ActivityEventType.BUILD_FAILURE, "sha1", "@org/team-a", now))
    query = BudgetHistoryQuery(BudgetCalculator(event_repository, config_repository), event_repository)

    history = await query.for_owner(1, "@org/team-a")

    assert history.status.owner == "@org/team-a"
    assert history.status.consumed == 1
    assert history.daily_counts == [DailyEventCount(day=now.date(), count=1)]


async def test_for_owner_excludes_history_outside_the_configured_window():
    event_repository = InMemoryActivityEventRepository()
    config_repository = InMemoryTenantConfigRepository()
    await config_repository.upsert(
        TenantConfig(1, rolling_window_days=28, default_team="unassigned", max_events_per_window=5, warn_threshold_pct=50)
    )
    stale_ts = datetime.now(timezone.utc) - timedelta(days=40)
    await event_repository.save_if_new(_event(ActivityEventType.BUILD_FAILURE, "sha1", "@org/team-a", stale_ts))
    query = BudgetHistoryQuery(BudgetCalculator(event_repository, config_repository), event_repository)

    history = await query.for_owner(1, "@org/team-a")

    assert history.status.consumed == 0
    assert history.daily_counts == []
