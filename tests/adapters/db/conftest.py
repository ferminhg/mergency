import pytest

from mergency.adapters.db.engine import build_engine
from mergency.adapters.db.tables import metadata
from mergency.api.settings import Settings


@pytest.fixture
async def db_engine():
    engine = build_engine(Settings().database_url)
    async with engine.begin() as conn:
        await conn.run_sync(metadata.create_all)
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(metadata.drop_all)
    await engine.dispose()
