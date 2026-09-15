from mergency.domain.models.budget_status import BudgetStatus
from mergency.domain.pr_budget_evaluator import PrBudgetEvaluator


class _StubOwnershipResolver:
    def __init__(self, owners: list[str]) -> None:
        self._owners = owners

    async def resolve_owners(self, installation_id, repo, changed_files, default_team):
        return self._owners


class _StubBudgetCalculator:
    def __init__(self, statuses_by_owner: dict[str, BudgetStatus]) -> None:
        self._statuses_by_owner = statuses_by_owner

    async def status_for(self, installation_id, owner):
        return self._statuses_by_owner[owner]


def _status(owner: str, remaining_pct: float) -> BudgetStatus:
    return BudgetStatus(owner=owner, window_days=28, limit=5, consumed=2, remaining_pct=remaining_pct)


async def test_returns_only_owners_at_or_below_the_warn_threshold():
    evaluator = PrBudgetEvaluator(
        _StubOwnershipResolver(["@org/team-a", "@org/team-b"]),
        _StubBudgetCalculator(
            {
                "@org/team-a": _status("@org/team-a", remaining_pct=30.0),
                "@org/team-b": _status("@org/team-b", remaining_pct=80.0),
            }
        ),
    )

    shrinking = await evaluator.evaluate(
        1, "acme/widgets", ["src/a.py"], "unassigned", warn_threshold_pct=50
    )

    assert [status.owner for status in shrinking] == ["@org/team-a"]


async def test_returns_empty_list_when_every_touched_owner_is_healthy():
    evaluator = PrBudgetEvaluator(
        _StubOwnershipResolver(["@org/team-a"]),
        _StubBudgetCalculator({"@org/team-a": _status("@org/team-a", remaining_pct=80.0)}),
    )

    shrinking = await evaluator.evaluate(
        1, "acme/widgets", ["src/a.py"], "unassigned", warn_threshold_pct=50
    )

    assert shrinking == []


async def test_remaining_pct_exactly_at_the_threshold_counts_as_shrinking():
    evaluator = PrBudgetEvaluator(
        _StubOwnershipResolver(["@org/team-a"]),
        _StubBudgetCalculator({"@org/team-a": _status("@org/team-a", remaining_pct=50.0)}),
    )

    shrinking = await evaluator.evaluate(
        1, "acme/widgets", ["src/a.py"], "unassigned", warn_threshold_pct=50
    )

    assert [status.owner for status in shrinking] == ["@org/team-a"]
