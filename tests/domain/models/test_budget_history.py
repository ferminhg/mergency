from datetime import date

from mergency.domain.models.budget_history import BudgetHistory
from mergency.domain.models.budget_status import BudgetStatus
from mergency.domain.models.daily_event_count import DailyEventCount


def test_budget_history_pairs_a_status_with_its_daily_counts():
    status = BudgetStatus(
        owner="@org/team-a", window_days=28, limit=5, consumed=2, remaining_pct=60.0
    )
    daily_counts = [DailyEventCount(day=date(2026, 9, 1), count=2)]

    history = BudgetHistory(status=status, daily_counts=daily_counts)

    assert history.status is status
    assert history.daily_counts == daily_counts
