import logging

from mergency.domain.ports.codeowners_provider import CodeownersProvider

logger = logging.getLogger(__name__)


class OwnershipResolver:
    def __init__(self, codeowners_provider: CodeownersProvider) -> None:
        self._codeowners_provider = codeowners_provider

    async def resolve_owners(
        self, installation_id: int, repo: str, changed_files: list[str], default_team: str
    ) -> list[str]:
        teams: set[str] = set()
        for path in changed_files:
            for owner_type, owner_name in await self._codeowners_provider.owners_for(
                installation_id, repo, path
            ):
                if owner_type == "TEAM":
                    teams.add(owner_name)
                else:
                    logger.info(
                        "non-team CODEOWNERS entry discarded, falling back to default team",
                        extra={
                            "installation_id": installation_id,
                            "repo": repo,
                            "path": path,
                            "owner": owner_name,
                        },
                    )

        if not teams:
            return [default_team]
        return sorted(teams)
