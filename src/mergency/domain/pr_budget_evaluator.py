from mergency.domain.budget_calculator import BudgetCalculator
from mergency.domain.models.budget_status import BudgetStatus
from mergency.domain.ownership_resolver import OwnershipResolver


class PrBudgetEvaluator:
    def __init__(
        self, ownership_resolver: OwnershipResolver, budget_calculator: BudgetCalculator
    ) -> None:
        self._ownership_resolver = ownership_resolver
        self._budget_calculator = budget_calculator

    async def evaluate(
        self,
        installation_id: int,
        repo: str,
        changed_files: list[str],
        default_team: str,
        warn_threshold_pct: int,
    ) -> list[BudgetStatus]:
        owners = await self._ownership_resolver.resolve_owners(
            installation_id, repo, changed_files, default_team
        )
        statuses = [
            await self._budget_calculator.status_for(installation_id, owner) for owner in owners
        ]
        return [status for status in statuses if status.remaining_pct <= warn_threshold_pct]
