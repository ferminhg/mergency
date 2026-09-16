from datetime import datetime, timedelta, timezone

from mergency.adapters.memory.event_repository import InMemoryEventRepository
from mergency.adapters.memory.tenant_config_repository import InMemoryTenantConfigRepository
from mergency.domain.budget_calculator import BudgetCalculator
from mergency.domain.models.event import Event
from mergency.domain.models.event_type import EventType
from mergency.domain.models.tenant_config import TenantConfig


def _event(event_type: EventType, sha: str, owner: str, ts: datetime) -> Event:
    return Event(
        installation_id=1, repo="acme/widgets", sha=sha, event_type=event_type, owner=owner, ts=ts
    )


async def test_status_for_counts_allow_listed_events_within_the_window():
    event_repository = InMemoryEventRepository()
    config_repository = InMemoryTenantConfigRepository()
    await config_repository.upsert(
        TenantConfig(1, rolling_window_days=28, default_team="unassigned", max_events_per_window=5, warn_threshold_pct=50)
    )
    now = datetime.now(timezone.utc)
    await event_repository.save_if_new(_event(EventType.BUILD_FAILURE, "sha1", "@org/backend-team", now))
    await event_repository.save_if_new(_event(EventType.REVERT, "sha2", "@org/backend-team", now))
    calculator = BudgetCalculator(event_repository, config_repository)

    status = await calculator.status_for(1, "@org/backend-team")

    assert status.owner == "@org/backend-team"
    assert status.window_days == 28
    assert status.limit == 5
    assert status.consumed == 2
    assert status.remaining_pct == 60.0


async def test_status_for_excludes_events_outside_the_rolling_window():
    event_repository = InMemoryEventRepository()
    config_repository = InMemoryTenantConfigRepository()
    await config_repository.upsert(
        TenantConfig(1, rolling_window_days=28, default_team="unassigned", max_events_per_window=5, warn_threshold_pct=50)
    )
    stale_ts = datetime.now(timezone.utc) - timedelta(days=40)
    await event_repository.save_if_new(_event(EventType.BUILD_FAILURE, "sha1", "@org/backend-team", stale_ts))
    calculator = BudgetCalculator(event_repository, config_repository)

    status = await calculator.status_for(1, "@org/backend-team")

    assert status.consumed == 0
    assert status.remaining_pct == 100.0


async def test_status_for_never_goes_below_zero_percent_when_over_budget():
    event_repository = InMemoryEventRepository()
    config_repository = InMemoryTenantConfigRepository()
    await config_repository.upsert(
        TenantConfig(1, rolling_window_days=28, default_team="unassigned", max_events_per_window=1, warn_threshold_pct=50)
    )
    now = datetime.now(timezone.utc)
    await event_repository.save_if_new(_event(EventType.BUILD_FAILURE, "sha1", "@org/backend-team", now))
    await event_repository.save_if_new(_event(EventType.REVERT, "sha2", "@org/backend-team", now))
    calculator = BudgetCalculator(event_repository, config_repository)

    status = await calculator.status_for(1, "@org/backend-team")

    assert status.consumed == 2
    assert status.remaining_pct == 0.0


async def test_status_for_uses_hardcoded_defaults_when_no_config_exists():
    event_repository = InMemoryEventRepository()
    config_repository = InMemoryTenantConfigRepository()
    calculator = BudgetCalculator(event_repository, config_repository)

    status = await calculator.status_for(1, "@org/backend-team")

    assert status.window_days == 28
    assert status.limit == 5
    assert status.consumed == 0
    assert status.remaining_pct == 100.0


async def test_status_for_excludes_flaky_test_events_from_consumption():
    event_repository = InMemoryEventRepository()
    config_repository = InMemoryTenantConfigRepository()
    await config_repository.upsert(
        TenantConfig(1, rolling_window_days=28, default_team="unassigned", max_events_per_window=5, warn_threshold_pct=50)
    )
    now = datetime.now(timezone.utc)
    await event_repository.save_if_new(_event(EventType.FLAKY_TEST, "sha1", "@org/backend-team", now))
    calculator = BudgetCalculator(event_repository, config_repository)

    status = await calculator.status_for(1, "@org/backend-team")

    assert status.consumed == 0
    assert status.remaining_pct == 100.0


async def test_status_for_returns_zero_percent_when_limit_is_non_positive():
    event_repository = InMemoryEventRepository()
    config_repository = InMemoryTenantConfigRepository()
    await config_repository.upsert(
        TenantConfig(1, rolling_window_days=28, default_team="unassigned", max_events_per_window=0, warn_threshold_pct=50)
    )
    now = datetime.now(timezone.utc)
    await event_repository.save_if_new(_event(EventType.BUILD_FAILURE, "sha1", "@org/backend-team", now))
    calculator = BudgetCalculator(event_repository, config_repository)

    status = await calculator.status_for(1, "@org/backend-team")

    assert status.window_days == 28
    assert status.limit == 0
    assert status.consumed == 1
    assert status.remaining_pct == 0.0
