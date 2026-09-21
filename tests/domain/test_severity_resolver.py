from mergency.domain.models.budget_severity import BudgetSeverity
from mergency.domain.models.budget_status import BudgetStatus
from mergency.domain.severity_resolver import severity_for, worst_severity


def _status(remaining_pct: float) -> BudgetStatus:
    return BudgetStatus(
        owner="@org/team-a", window_days=28, limit=5, consumed=2, remaining_pct=remaining_pct
    )


def test_severity_for_is_warn_when_budget_still_has_headroom():
    assert severity_for(_status(20.0)) == BudgetSeverity.WARN


def test_severity_for_is_breach_when_budget_is_fully_consumed():
    assert severity_for(_status(0.0)) == BudgetSeverity.BREACH


def test_worst_severity_is_breach_when_any_status_has_breached():
    statuses = [_status(20.0), _status(0.0)]

    assert worst_severity(statuses) == BudgetSeverity.BREACH


def test_worst_severity_is_warn_when_no_status_has_breached():
    statuses = [_status(20.0), _status(30.0)]

    assert worst_severity(statuses) == BudgetSeverity.WARN
