import pytest

from mergency.adapters.github.installation_command_parser import parse_installation_command
from mergency.domain.models.create_installation_command import CreateInstallation
from mergency.domain.models.tenant_status import TenantStatus
from mergency.domain.models.transition_installation_command import TransitionInstallation


def _payload(action: str, installation_id: int = 1) -> dict:
    return {
        "action": action,
        "installation": {
            "id": installation_id,
            "account": {"login": "acme", "type": "Organization"},
            "repository_selection": "all",
        },
    }


def test_created_action_produces_create_installation_command():
    command = parse_installation_command(_payload("created"))

    assert isinstance(command, CreateInstallation)
    assert command.installation.installation_id == 1
    assert command.installation.account_login == "acme"
    assert command.installation.account_type == "Organization"
    assert command.installation.status == TenantStatus.ACTIVE
    assert command.installation.repository_selection == "all"


def test_deleted_action_produces_transition_to_deleted():
    command = parse_installation_command(_payload("deleted"))

    assert command == TransitionInstallation(installation_id=1, status=TenantStatus.DELETED)


def test_suspend_action_produces_transition_to_suspended():
    command = parse_installation_command(_payload("suspend"))

    assert command == TransitionInstallation(installation_id=1, status=TenantStatus.SUSPENDED)


def test_unsuspend_action_produces_transition_to_active():
    command = parse_installation_command(_payload("unsuspend"))

    assert command == TransitionInstallation(installation_id=1, status=TenantStatus.ACTIVE)


def test_unknown_action_produces_no_command():
    command = parse_installation_command(_payload("new_permissions_accepted"))

    assert command is None


def test_missing_installation_field_raises_key_error():
    with pytest.raises(KeyError):
        parse_installation_command({"action": "created"})


def test_missing_account_field_raises_key_error():
    payload = {"action": "created", "installation": {"id": 1, "repository_selection": "all"}}

    with pytest.raises(KeyError):
        parse_installation_command(payload)
