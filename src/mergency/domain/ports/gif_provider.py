from typing import Protocol

from mergency.domain.models.budget_severity import BudgetSeverity


class GifProvider(Protocol):
    async def gif_for_severity(self, severity: BudgetSeverity) -> str: ...
