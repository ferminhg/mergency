from dataclasses import dataclass

from mergency.domain.models.tenant_status import TenantStatus


@dataclass(frozen=True)
class TransitionInstallation:
    installation_id: int
    status: TenantStatus
