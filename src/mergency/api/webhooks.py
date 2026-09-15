import json
import logging

from fastapi import APIRouter, Depends, Header, HTTPException, Request

from mergency.adapters.github.installation_command_parser import parse_installation_command
from mergency.adapters.github.signature import verify_signature
from mergency.api.deps import get_installation_service, get_settings
from mergency.api.settings import Settings
from mergency.domain.installation_service import InstallationService
from mergency.worker.classify_activity_event import classify_activity_event
from mergency.worker.evaluate_pr_budget import evaluate_pr_budget

logger = logging.getLogger(__name__)

router = APIRouter()

_PR_TRIGGER_ACTIONS = {"opened", "synchronize", "reopened"}


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
    elif x_github_event in ("push", "check_run"):
        classify_activity_event.delay(x_github_event, payload)
    elif x_github_event == "pull_request" and payload.get("action") in _PR_TRIGGER_ACTIONS:
        evaluate_pr_budget.delay(payload)
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
        command = parse_installation_command(payload)
    except KeyError as error:
        logger.warning(
            "installation payload missing expected field, acknowledged without processing",
            extra={"action": action, "missing_field": str(error)},
        )
        return

    if command is None:
        logger.info("unhandled installation action acknowledged", extra={"action": action})
        return

    await installation_service.handle(command)
