from dataclasses import dataclass


@dataclass(frozen=True)
class BudgetStatus:
    owner: str
    window_days: int
    limit: int
    consumed: int
    remaining_pct: float
