from mergency.adapters.memory.tenant_config_repository import InMemoryTenantConfigRepository
from mergency.domain.config_resolver import ConfigResolver


class _StubContentProvider:
    def __init__(self, content: str | None) -> None:
        self._content = content

    async def get_file(self, installation_id, repo, path):
        return self._content


async def test_resolves_config_from_valid_yaml():
    resolver = ConfigResolver(
        _StubContentProvider(
            "rolling_window_days: 14\ndefault_team: platform-team\n"
            "budget:\n  max_events_per_window: 3\n  warn_threshold_pct: 40\n"
        ),
        InMemoryTenantConfigRepository(),
    )

    config = await resolver.resolve(1, "acme/widgets")

    assert config.installation_id == 1
    assert config.rolling_window_days == 14
    assert config.default_team == "platform-team"
    assert config.max_events_per_window == 3
    assert config.warn_threshold_pct == 40


async def test_falls_back_to_defaults_when_file_is_absent():
    resolver = ConfigResolver(_StubContentProvider(None), InMemoryTenantConfigRepository())

    config = await resolver.resolve(1, "acme/widgets")

    assert config.rolling_window_days == 28
    assert config.default_team == "unassigned"
    assert config.max_events_per_window == 5
    assert config.warn_threshold_pct == 50


async def test_falls_back_to_defaults_when_yaml_is_invalid():
    resolver = ConfigResolver(
        _StubContentProvider("not: valid: yaml: ["), InMemoryTenantConfigRepository()
    )

    config = await resolver.resolve(1, "acme/widgets")

    assert config.default_team == "unassigned"
    assert config.warn_threshold_pct == 50


async def test_missing_budget_section_uses_default_max_events():
    resolver = ConfigResolver(
        _StubContentProvider("rolling_window_days: 10\ndefault_team: team-x\n"),
        InMemoryTenantConfigRepository(),
    )

    config = await resolver.resolve(1, "acme/widgets")

    assert config.max_events_per_window == 5
    assert config.warn_threshold_pct == 50


async def test_warn_threshold_pct_alone_overrides_only_itself():
    resolver = ConfigResolver(
        _StubContentProvider("budget:\n  warn_threshold_pct: 25\n"),
        InMemoryTenantConfigRepository(),
    )

    config = await resolver.resolve(1, "acme/widgets")

    assert config.warn_threshold_pct == 25
    assert config.max_events_per_window == 5


async def test_resolve_persists_config_into_repository():
    repository = InMemoryTenantConfigRepository()
    resolver = ConfigResolver(_StubContentProvider(None), repository)

    config = await resolver.resolve(1, "acme/widgets")

    assert await repository.get(1) == config
