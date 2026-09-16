from dataclasses import dataclass
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Header, HTTPException

from mergency.api.auth import token_matches
from mergency.api.deps import get_tenant_repository
from mergency.domain.ports.tenant_repository import TenantRepository
from mergency.worker.report_incident import report_incident

router = APIRouter()


@dataclass
class IncidentReportRequest:
    repo: str
    base_sha: str
    head_sha: str
    severity: str | None = None
    occurred_at: datetime | None = None


@router.post("/api/v1/installations/{installation_id}/incidents", status_code=202)
async def report_incident_endpoint(
    installation_id: int,
    incident_report: IncidentReportRequest,
    authorization: str | None = Header(default=None),
    tenant_repository: TenantRepository = Depends(get_tenant_repository),
) -> dict:
    installation = await tenant_repository.get(installation_id)
    if installation is None:
        raise HTTPException(status_code=404, detail="installation not found")

    if not token_matches(installation, authorization):
        raise HTTPException(status_code=401, detail="invalid or missing token")

    occurred_at = incident_report.occurred_at or datetime.now(timezone.utc)
    report_incident.delay(
        installation_id=installation_id,
        repo=incident_report.repo,
        base_sha=incident_report.base_sha,
        head_sha=incident_report.head_sha,
        severity=incident_report.severity,
        occurred_at=occurred_at.isoformat(),
    )
    return {"accepted": True}
