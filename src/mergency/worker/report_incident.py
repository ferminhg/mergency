import asyncio
from datetime import datetime

from mergency.api.deps import (
    get_changed_files_provider,
    get_commit_range_provider,
    get_config_resolver,
    get_event_repository,
    get_ownership_resolver,
)
from mergency.domain.models.event import Event
from mergency.domain.models.event_type import EventType
from mergency.worker.celery_app import celery_app


@celery_app.task(name="report_incident")
def report_incident(
    installation_id: int,
    repo: str,
    base_sha: str,
    head_sha: str,
    occurred_at: str,
    severity: str | None = None,
) -> None:
    asyncio.run(
        _correlate_resolve_and_persist(
            installation_id=installation_id,
            repo=repo,
            base_sha=base_sha,
            head_sha=head_sha,
            severity=severity,
            occurred_at_iso=occurred_at,
        )
    )


async def _correlate_resolve_and_persist(
    *,
    installation_id: int,
    repo: str,
    base_sha: str,
    head_sha: str,
    severity: str | None,
    occurred_at_iso: str,
) -> None:
    occurred_at = datetime.fromisoformat(occurred_at_iso)

    shas = await get_commit_range_provider().commits_between(
        installation_id, repo, base_sha, head_sha
    )
    config = await get_config_resolver().resolve(installation_id, repo)
    event_repository = get_event_repository()

    for sha in shas:
        changed_files = await get_changed_files_provider().files_changed_in_commit(
            installation_id, repo, sha
        )
        owners = await get_ownership_resolver().resolve_owners(
            installation_id, repo, changed_files, config.default_team
        )
        for owner in owners:
            await event_repository.save_if_new(
                Event(
                    installation_id=installation_id,
                    repo=repo,
                    sha=sha,
                    event_type=EventType.INCIDENT,
                    owner=owner,
                    ts=occurred_at,
                )
            )
