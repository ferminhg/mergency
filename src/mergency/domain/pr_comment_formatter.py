from mergency.domain.models.budget_severity import BudgetSeverity
from mergency.domain.models.budget_status import BudgetStatus
from mergency.domain.severity_resolver import worst_severity

MARKER = "<!-- mergency:budget-status -->"

_HEADLINES = {
    BudgetSeverity.WARN: "⚠️ Budget getting tight",
    BudgetSeverity.BREACH: "🚨 Budget blown",
}


def format_shrinking_budget_comment(statuses: list[BudgetStatus], gif_url: str) -> str:
    headline = _HEADLINES[worst_severity(statuses)]
    header = "| Team | Window | Consumed/Limit | Remaining | Status |"
    separator = "| --- | --- | --- | --- | --- |"
    rows = [
        f"| {status.owner} | {status.window_days}d | {status.consumed}/{status.limit} "
        f"| {status.remaining_pct:.0f}% | ⚠️ |"
        for status in statuses
    ]
    table = "\n".join([header, separator, *rows])
    return f"{MARKER}\n### {headline}\n\n![]({gif_url})\n\n{table}\n"


def format_recovered_comment() -> str:
    return f"{MARKER}\n### ✅ Budget recovered\n\nAll touched teams are back within budget.\n"
