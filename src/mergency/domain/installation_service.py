from mergency.domain.models.create_installation_command import CreateInstallation
from mergency.domain.models.installation_command import InstallationCommand
from mergency.domain.models.transition_installation_command import TransitionInstallation
from mergency.domain.ports.tenant_repository import TenantRepository


class InstallationService:
    def __init__(self, tenant_repository: TenantRepository) -> None:
        self._tenant_repository = tenant_repository

    async def handle(self, command: InstallationCommand) -> None:
        match command:
            case CreateInstallation(installation=installation):
                await self._tenant_repository.upsert(installation)
            case TransitionInstallation(installation_id=installation_id, status=status):
                await self._tenant_repository.transition(installation_id, status)
