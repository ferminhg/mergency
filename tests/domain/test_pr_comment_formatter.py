from mergency.domain.models.budget_status import BudgetStatus
from mergency.domain.pr_comment_formatter import (
    MARKER,
    format_recovered_comment,
    format_shrinking_budget_comment,
)

_GIF_URL = "https://giphy.example/alarm.gif"


def _status(owner: str, remaining_pct: float = 20.0) -> BudgetStatus:
    return BudgetStatus(
        owner=owner, window_days=28, limit=5, consumed=4, remaining_pct=remaining_pct
    )


def test_shrinking_comment_starts_with_the_marker():
    body = format_shrinking_budget_comment([_status("@org/team-a")], _GIF_URL)

    assert body.startswith(MARKER)


def test_shrinking_comment_lists_every_shrinking_owner():
    body = format_shrinking_budget_comment(
        [_status("@org/team-a"), _status("@org/team-b")], _GIF_URL
    )

    assert "@org/team-a" in body
    assert "@org/team-b" in body


def test_shrinking_comment_includes_consumed_limit_and_remaining_pct():
    body = format_shrinking_budget_comment([_status("@org/team-a")], _GIF_URL)

    assert "4/5" in body
    assert "20" in body


def test_shrinking_comment_embeds_the_gif_url():
    body = format_shrinking_budget_comment([_status("@org/team-a")], _GIF_URL)

    assert _GIF_URL in body


def test_shrinking_comment_uses_the_warn_headline_when_no_owner_has_breached():
    body = format_shrinking_budget_comment([_status("@org/team-a", remaining_pct=20.0)], _GIF_URL)

    assert "Budget getting tight" in body


def test_shrinking_comment_uses_the_breach_headline_when_an_owner_has_breached():
    body = format_shrinking_budget_comment([_status("@org/team-a", remaining_pct=0.0)], _GIF_URL)

    assert "Budget blown" in body


def test_recovered_comment_starts_with_the_marker_and_mentions_recovery():
    body = format_recovered_comment()

    assert body.startswith(MARKER)
    assert "recovered" in body.lower()


def test_recovered_comment_has_no_gif():
    body = format_recovered_comment()

    assert "![" not in body
