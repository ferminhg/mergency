import json
import logging

from fastapi import APIRouter, Depends, Header, HTTPException, Request

from mergency.adapters.github.signature import verify_signature
from mergency.api.deps import get_installation_service, get_settings
from mergency.api.settings import Settings
from mergency.domain.installation_service import InstallationService
from mergency.domain.models.installation import Installation
from mergency.domain.models.tenant_status import TenantStatus

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/webhooks/github")
async def receive_webhook(
    request: Request,
    x_hub_signature_256: str | None = Header(default=None),
    x_github_event: str | None = Header(default=None),
    settings: Settings = Depends(get_settings),
    installation_service: InstallationService = Depends(get_installation_service),
) -> dict[str, str]:
    body = await request.body()

    if not verify_signature(body, x_hub_signature_256, settings.github_webhook_secret):
        raise HTTPException(status_code=401, detail="invalid signature")

    payload = json.loads(body)

    if x_github_event == "installation":
        await _handle_installation_event(payload, installation_service)
    elif x_github_event == "installation_repositories":
        logger.info("installation_repositories event acknowledged, no-op for now")
    else:
        logger.info(
            "event acknowledged, processing not yet implemented",
            extra={"event": x_github_event},
        )

    return {"status": "ok"}


async def _handle_installation_event(
    payload: dict, installation_service: InstallationService
) -> None:
    action = payload.get("action")

    try:
        installation_payload = payload["installation"]
        installation_id = installation_payload["id"]

        if action == "deleted":
            await installation_service.handle_installation_deleted(installation_id)
            return

        if action == "suspend":
            await installation_service.handle_installation_suspended(installation_id)
            return

        if action == "created" or action == "unsuspend":
            installation = Installation(
                installation_id=installation_id,
                account_login=installation_payload["account"]["login"],
                account_type=installation_payload["account"]["type"],
                status=TenantStatus.ACTIVE,
                repository_selection=installation_payload["repository_selection"],
            )
            if action == "created":
                await installation_service.handle_installation_created(installation)
            else:
                await installation_service.handle_installation_unsuspended(installation)
            return

        logger.info("unhandled installation action acknowledged", extra={"action": action})
    except KeyError as error:
        logger.warning(
            "installation payload missing expected field, acknowledged without processing",
            extra={"action": action, "missing_field": str(error)},
        )
