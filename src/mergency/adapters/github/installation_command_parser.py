from mergency.domain.models.create_installation_command import CreateInstallation
from mergency.domain.models.installation import Installation
from mergency.domain.models.installation_command import InstallationCommand
from mergency.domain.models.tenant_status import TenantStatus
from mergency.domain.models.transition_installation_command import TransitionInstallation

_ACTION_TO_STATUS: dict[str, TenantStatus] = {
    "deleted": TenantStatus.DELETED,
    "suspend": TenantStatus.SUSPENDED,
    "unsuspend": TenantStatus.ACTIVE,
}


def parse_installation_command(payload: dict) -> InstallationCommand | None:
    action = payload.get("action")
    installation_payload = payload["installation"]
    installation_id = installation_payload["id"]

    if action == "created":
        return CreateInstallation(
            installation=Installation(
                installation_id=installation_id,
                account_login=installation_payload["account"]["login"],
                account_type=installation_payload["account"]["type"],
                status=TenantStatus.ACTIVE,
                repository_selection=installation_payload["repository_selection"],
            )
        )

    status = _ACTION_TO_STATUS.get(action)
    if status is not None:
        return TransitionInstallation(installation_id=installation_id, status=status)

    return None
