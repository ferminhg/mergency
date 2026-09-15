from mergency.adapters.db.tenant_config_repository import SqlAlchemyTenantConfigRepository
from mergency.domain.models.tenant_config import TenantConfig


def _config(installation_id: int = 1) -> TenantConfig:
    return TenantConfig(
        installation_id=installation_id,
        rolling_window_days=28,
        default_team="platform-team",
        max_events_per_window=5,
        warn_threshold_pct=50,
    )


async def test_get_returns_none_when_absent(db_engine):
    repository = SqlAlchemyTenantConfigRepository(db_engine)

    assert await repository.get(1) is None


async def test_upsert_then_get_returns_stored_config(db_engine):
    repository = SqlAlchemyTenantConfigRepository(db_engine)

    await repository.upsert(_config())

    assert await repository.get(1) == _config()


async def test_upsert_overwrites_existing_config(db_engine):
    repository = SqlAlchemyTenantConfigRepository(db_engine)
    await repository.upsert(_config())

    await repository.upsert(TenantConfig(1, 14, "other-team", 10, 25))

    stored = await repository.get(1)
    assert stored.rolling_window_days == 14
    assert stored.default_team == "other-team"
    assert stored.warn_threshold_pct == 25
