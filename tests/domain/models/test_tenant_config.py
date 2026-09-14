import dataclasses

import pytest

from mergency.domain.models.tenant_config import TenantConfig


def test_tenant_config_is_immutable():
    config = TenantConfig(
        installation_id=1,
        rolling_window_days=28,
        default_team="platform-team",
        max_events_per_window=5,
    )

    with pytest.raises(dataclasses.FrozenInstanceError):
        config.default_team = "other-team"
