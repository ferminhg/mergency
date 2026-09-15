from mergency.domain.models.budget_status import BudgetStatus

MARKER = "<!-- mergency:budget-status -->"


def format_shrinking_budget_comment(statuses: list[BudgetStatus]) -> str:
    header = "| Team | Window | Consumed/Limit | Remaining | Status |"
    separator = "| --- | --- | --- | --- | --- |"
    rows = [
        f"| {status.owner} | {status.window_days}d | {status.consumed}/{status.limit} "
        f"| {status.remaining_pct:.0f}% | ⚠️ |"
        for status in statuses
    ]
    table = "\n".join([header, separator, *rows])
    return f"{MARKER}\n### 🚨 Error budget warning\n\n{table}\n"


def format_recovered_comment() -> str:
    return f"{MARKER}\n### ✅ Budget recovered\n\nAll touched teams are back within budget.\n"
