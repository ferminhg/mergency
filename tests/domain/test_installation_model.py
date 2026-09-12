import dataclasses

import pytest

from mergency.domain.models.installation import Installation
from mergency.domain.models.tenant_status import TenantStatus


def test_installation_is_immutable():
    installation = Installation(
        installation_id=1,
        account_login="acme",
        account_type="Organization",
        status=TenantStatus.ACTIVE,
        repository_selection="all",
    )

    with pytest.raises(dataclasses.FrozenInstanceError):
        installation.status = TenantStatus.DELETED


def test_tenant_status_has_exactly_three_values():
    assert {status.value for status in TenantStatus} == {"active", "suspended", "deleted"}
