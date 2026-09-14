import dataclasses

import pytest

from mergency.domain.models.create_installation_command import CreateInstallation
from mergency.domain.models.installation import Installation
from mergency.domain.models.tenant_status import TenantStatus
from mergency.domain.models.transition_installation_command import TransitionInstallation


def _installation() -> Installation:
    return Installation(
        installation_id=42,
        account_login="acme",
        account_type="Organization",
        status=TenantStatus.ACTIVE,
        repository_selection="all",
    )


def test_create_installation_is_immutable():
    command = CreateInstallation(installation=_installation())

    with pytest.raises(dataclasses.FrozenInstanceError):
        command.installation = _installation()


def test_transition_installation_is_immutable():
    command = TransitionInstallation(installation_id=42, status=TenantStatus.SUSPENDED)

    with pytest.raises(dataclasses.FrozenInstanceError):
        command.status = TenantStatus.ACTIVE
