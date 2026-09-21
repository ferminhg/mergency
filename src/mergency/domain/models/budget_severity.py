from enum import Enum


class BudgetSeverity(str, Enum):
    WARN = "warn"
    BREACH = "breach"
