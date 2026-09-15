import asyncio
import logging

from mergency.adapters.github.pull_request_signal_parser import parse_pull_request_signal
from mergency.api.deps import (
    get_config_resolver,
    get_pr_budget_evaluator,
    get_pr_comment_client,
    get_pull_request_files_provider,
)
from mergency.domain.models.pull_request_signal import PullRequestSignal
from mergency.domain.pr_comment_formatter import (
    format_recovered_comment,
    format_shrinking_budget_comment,
)
from mergency.worker.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(name="evaluate_pr_budget")
def evaluate_pr_budget(payload: dict) -> None:
    try:
        signal = parse_pull_request_signal(payload)
    except (KeyError, ValueError, TypeError) as error:
        logger.warning(
            "pull_request payload could not be parsed, dropped", extra={"error": str(error)}
        )
        return

    asyncio.run(_evaluate_and_comment(signal))


async def _evaluate_and_comment(signal: PullRequestSignal) -> None:
    changed_files = await get_pull_request_files_provider().files_changed_in_pull_request(
        signal.installation_id, signal.repo, signal.pr_number
    )
    config = await get_config_resolver().resolve(signal.installation_id, signal.repo)
    shrinking = await get_pr_budget_evaluator().evaluate(
        signal.installation_id,
        signal.repo,
        changed_files,
        config.default_team,
        config.warn_threshold_pct,
    )

    comment_client = get_pr_comment_client()
    existing_comment_id = await comment_client.find_marked_comment(
        signal.installation_id, signal.repo, signal.pr_number
    )

    if shrinking:
        body = format_shrinking_budget_comment(shrinking)
        if existing_comment_id is not None:
            await comment_client.update_comment(
                signal.installation_id, signal.repo, existing_comment_id, body
            )
        else:
            await comment_client.create_comment(
                signal.installation_id, signal.repo, signal.pr_number, body
            )
    elif existing_comment_id is not None:
        await comment_client.update_comment(
            signal.installation_id, signal.repo, existing_comment_id, format_recovered_comment()
        )
