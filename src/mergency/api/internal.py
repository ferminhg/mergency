from fastapi import APIRouter, Depends, HTTPException

from mergency.api.deps import get_tenant_repository
from mergency.domain.models.installation import Installation
from mergency.domain.ports.tenant_repository import TenantRepository

router = APIRouter()


@router.get("/internal/installations/{installation_id}", response_model_exclude={"api_token"})
async def get_installation(
    installation_id: int,
    tenant_repository: TenantRepository = Depends(get_tenant_repository),
) -> Installation:
    installation = await tenant_repository.get(installation_id)
    if installation is None:
        raise HTTPException(status_code=404, detail="installation not found")
    return installation
