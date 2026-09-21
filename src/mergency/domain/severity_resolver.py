from mergency.domain.models.budget_severity import BudgetSeverity
from mergency.domain.models.budget_status import BudgetStatus


def severity_for(status: BudgetStatus) -> BudgetSeverity:
    return BudgetSeverity.BREACH if status.remaining_pct <= 0 else BudgetSeverity.WARN


def worst_severity(statuses: list[BudgetStatus]) -> BudgetSeverity:
    if any(severity_for(status) == BudgetSeverity.BREACH for status in statuses):
        return BudgetSeverity.BREACH
    return BudgetSeverity.WARN
