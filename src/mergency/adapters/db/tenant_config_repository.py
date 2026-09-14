import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncEngine

from mergency.adapters.db.tables import tenant_config_table
from mergency.domain.models.tenant_config import TenantConfig


class SqlAlchemyTenantConfigRepository:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def upsert(self, config: TenantConfig) -> None:
        statement = pg_insert(tenant_config_table).values(
            installation_id=config.installation_id,
            rolling_window_days=config.rolling_window_days,
            default_team=config.default_team,
            max_events_per_window=config.max_events_per_window,
            warn_threshold_pct=config.warn_threshold_pct,
        )
        statement = statement.on_conflict_do_update(
            index_elements=[tenant_config_table.c.installation_id],
            set_={
                "rolling_window_days": statement.excluded.rolling_window_days,
                "default_team": statement.excluded.default_team,
                "max_events_per_window": statement.excluded.max_events_per_window,
                "warn_threshold_pct": statement.excluded.warn_threshold_pct,
            },
        )
        async with self._engine.begin() as conn:
            await conn.execute(statement)

    async def get(self, installation_id: int) -> TenantConfig | None:
        async with self._engine.connect() as conn:
            row = (
                await conn.execute(
                    sa.select(tenant_config_table).where(
                        tenant_config_table.c.installation_id == installation_id
                    )
                )
            ).first()
        if row is None:
            return None
        return TenantConfig(
            installation_id=row.installation_id,
            rolling_window_days=row.rolling_window_days,
            default_team=row.default_team,
            max_events_per_window=row.max_events_per_window,
            warn_threshold_pct=row.warn_threshold_pct,
        )
