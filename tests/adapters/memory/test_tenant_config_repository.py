from mergency.adapters.memory.tenant_config_repository import InMemoryTenantConfigRepository
from mergency.domain.models.tenant_config import TenantConfig


def _config(installation_id: int = 1, default_team: str = "team-a") -> TenantConfig:
    return TenantConfig(
        installation_id=installation_id,
        rolling_window_days=28,
        default_team=default_team,
        max_events_per_window=5,
    )


async def test_upsert_then_get_returns_the_stored_config():
    repository = InMemoryTenantConfigRepository()

    await repository.upsert(_config())

    assert await repository.get(1) == _config()


async def test_upsert_overwrites_the_previous_config():
    repository = InMemoryTenantConfigRepository()
    await repository.upsert(_config(default_team="team-a"))

    await repository.upsert(_config(default_team="team-b"))

    stored = await repository.get(1)
    assert stored is not None
    assert stored.default_team == "team-b"


async def test_get_returns_none_when_absent():
    repository = InMemoryTenantConfigRepository()

    assert await repository.get(999) is None
