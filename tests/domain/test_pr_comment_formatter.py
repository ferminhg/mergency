from mergency.domain.models.budget_status import BudgetStatus
from mergency.domain.pr_comment_formatter import (
    MARKER,
    format_recovered_comment,
    format_shrinking_budget_comment,
)


def _status(owner: str) -> BudgetStatus:
    return BudgetStatus(owner=owner, window_days=28, limit=5, consumed=4, remaining_pct=20.0)


def test_shrinking_comment_starts_with_the_marker():
    body = format_shrinking_budget_comment([_status("@org/team-a")])

    assert body.startswith(MARKER)


def test_shrinking_comment_lists_every_shrinking_owner():
    body = format_shrinking_budget_comment([_status("@org/team-a"), _status("@org/team-b")])

    assert "@org/team-a" in body
    assert "@org/team-b" in body


def test_shrinking_comment_includes_consumed_limit_and_remaining_pct():
    body = format_shrinking_budget_comment([_status("@org/team-a")])

    assert "4/5" in body
    assert "20" in body


def test_recovered_comment_starts_with_the_marker_and_mentions_recovery():
    body = format_recovered_comment()

    assert body.startswith(MARKER)
    assert "recovered" in body.lower()
