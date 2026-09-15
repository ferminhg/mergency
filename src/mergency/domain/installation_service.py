import dataclasses
import logging
import secrets

from mergency.domain.models.create_installation_command import CreateInstallation
from mergency.domain.models.installation import Installation
from mergency.domain.models.installation_command import InstallationCommand
from mergency.domain.models.transition_installation_command import TransitionInstallation
from mergency.domain.ports.tenant_repository import TenantRepository

logger = logging.getLogger(__name__)


class InstallationService:
    def __init__(self, tenant_repository: TenantRepository) -> None:
        self._tenant_repository = tenant_repository

    async def handle(self, command: InstallationCommand) -> None:
        match command:
            case CreateInstallation(installation=installation):
                await self._create_or_update(installation)
            case TransitionInstallation(installation_id=installation_id, status=status):
                updated = await self._tenant_repository.transition(installation_id, status)
                if updated is None:
                    logger.warning(
                        "transition targeted unknown installation, acknowledged as no-op",
                        extra={"installation_id": installation_id, "status": status.value},
                    )

    async def _create_or_update(self, installation: Installation) -> None:
        existing = await self._tenant_repository.get(installation.installation_id)
        api_token = existing.api_token if existing and existing.api_token else secrets.token_urlsafe(32)
        await self._tenant_repository.upsert(dataclasses.replace(installation, api_token=api_token))
