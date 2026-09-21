from mergency.domain.models.budget_severity import BudgetSeverity


def test_budget_severity_has_warn_and_breach_values():
    assert BudgetSeverity.WARN.value == "warn"
    assert BudgetSeverity.BREACH.value == "breach"
