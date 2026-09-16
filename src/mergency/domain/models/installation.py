from dataclasses import dataclass

from mergency.domain.models.tenant_status import TenantStatus


@dataclass(frozen=True)
class Installation:
    installation_id: int
    account_login: str
    account_type: str
    status: TenantStatus
    repository_selection: str
    api_token: str | None = None
