import dataclasses

import pytest

from mergency.domain.models.budget_status import BudgetStatus


def test_budget_status_is_immutable():
    status = BudgetStatus(
        owner="@org/backend-team", window_days=28, limit=5, consumed=2, remaining_pct=60.0
    )

    with pytest.raises(dataclasses.FrozenInstanceError):
        status.consumed = 3
