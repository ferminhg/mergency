from fastapi import APIRouter, Depends, Header, HTTPException

from mergency.api.auth import token_matches
from mergency.api.deps import get_budget_history_query, get_tenant_repository
from mergency.domain.budget_history_query import BudgetHistoryQuery
from mergency.domain.models.budget_history import BudgetHistory
from mergency.domain.ports.tenant_repository import TenantRepository

router = APIRouter()


@router.get("/api/v1/installations/{installation_id}/owners/{owner:path}/budget")
async def get_owner_budget_history(
    installation_id: int,
    owner: str,
    authorization: str | None = Header(default=None),
    tenant_repository: TenantRepository = Depends(get_tenant_repository),
    budget_history_query: BudgetHistoryQuery = Depends(get_budget_history_query),
) -> BudgetHistory:
    installation = await tenant_repository.get(installation_id)
    if installation is None:
        raise HTTPException(status_code=404, detail="installation not found")

    if not token_matches(installation, authorization):
        raise HTTPException(status_code=401, detail="invalid or missing token")

    return await budget_history_query.for_owner(installation_id, owner)
