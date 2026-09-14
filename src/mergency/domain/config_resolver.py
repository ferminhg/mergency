import yaml

from mergency.domain.models.tenant_config import TenantConfig
from mergency.domain.ports.repository_content_provider import RepositoryContentProvider
from mergency.domain.ports.tenant_config_repository import TenantConfigRepository

_CONFIG_PATH = "mergency.yml"
_DEFAULT_ROLLING_WINDOW_DAYS = 28
_DEFAULT_TEAM = "unassigned"
_DEFAULT_MAX_EVENTS_PER_WINDOW = 5


class ConfigResolver:
    def __init__(
        self,
        repository_content_provider: RepositoryContentProvider,
        tenant_config_repository: TenantConfigRepository,
    ) -> None:
        self._repository_content_provider = repository_content_provider
        self._tenant_config_repository = tenant_config_repository

    async def resolve(self, installation_id: int, repo: str) -> TenantConfig:
        text = await self._repository_content_provider.get_file(
            installation_id, repo, _CONFIG_PATH
        )
        config = _parse(installation_id, text)
        await self._tenant_config_repository.upsert(config)
        return config


def _parse(installation_id: int, text: str | None) -> TenantConfig:
    data: dict = {}
    if text is not None:
        try:
            loaded = yaml.safe_load(text)
            if isinstance(loaded, dict):
                data = loaded
        except yaml.YAMLError:
            data = {}

    budget = data.get("budget")
    budget = budget if isinstance(budget, dict) else {}

    return TenantConfig(
        installation_id=installation_id,
        rolling_window_days=data.get("rolling_window_days", _DEFAULT_ROLLING_WINDOW_DAYS),
        default_team=data.get("default_team", _DEFAULT_TEAM),
        max_events_per_window=budget.get("max_events_per_window", _DEFAULT_MAX_EVENTS_PER_WINDOW),
    )
