from datetime import datetime

import asyncpg
import sqlalchemy as sa
from sqlalchemy import insert, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine

from mergency.adapters.db.tables import events_table
from mergency.domain.models.activity_event import ActivityEvent
from mergency.domain.models.activity_event_type import ActivityEventType
from mergency.domain.models.daily_event_count import DailyEventCount


class SqlAlchemyActivityEventRepository:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def save_if_new(self, event: ActivityEvent) -> bool:
        try:
            async with self._engine.begin() as conn:
                await conn.execute(
                    insert(events_table).values(
                        installation_id=event.installation_id,
                        repo=event.repo,
                        sha=event.sha,
                        event_type=event.event_type.value,
                        owner=event.owner,
                        ts=event.ts,
                        check_name=event.check_name,
                    )
                )
        except IntegrityError as error:
            if isinstance(error.orig.__cause__, asyncpg.exceptions.UniqueViolationError):
                return False
            raise
        return True

    async def get(
        self, installation_id: int, repo: str, sha: str, event_type: ActivityEventType, owner: str
    ) -> ActivityEvent | None:
        async with self._engine.connect() as conn:
            row = (
                await conn.execute(
                    select(events_table).where(
                        events_table.c.installation_id == installation_id,
                        events_table.c.repo == repo,
                        events_table.c.sha == sha,
                        events_table.c.event_type == event_type.value,
                        events_table.c.owner == owner,
                    )
                )
            ).first()
        return _row_to_event(row) if row else None

    async def count_since(
        self,
        installation_id: int,
        owner: str,
        event_types: list[ActivityEventType],
        since: datetime,
    ) -> int:
        async with self._engine.connect() as conn:
            result = await conn.execute(
                select(sa.func.count())
                .select_from(events_table)
                .where(
                    events_table.c.installation_id == installation_id,
                    events_table.c.owner == owner,
                    events_table.c.event_type.in_([t.value for t in event_types]),
                    events_table.c.ts >= since,
                )
            )
        return result.scalar_one()

    async def daily_counts_since(
        self,
        installation_id: int,
        owner: str,
        event_types: list[ActivityEventType],
        since: datetime,
    ) -> list[DailyEventCount]:
        day = sa.cast(events_table.c.ts, sa.Date).label("day")
        async with self._engine.connect() as conn:
            result = await conn.execute(
                select(day, sa.func.count().label("count"))
                .where(
                    events_table.c.installation_id == installation_id,
                    events_table.c.owner == owner,
                    events_table.c.event_type.in_([t.value for t in event_types]),
                    events_table.c.ts >= since,
                )
                .group_by(day)
                .order_by(day)
            )
            rows = result.all()
        return [DailyEventCount(day=row.day, count=row.count) for row in rows]

    async def find_recent(
        self,
        installation_id: int,
        repo: str,
        sha: str,
        check_name: str,
        event_type: ActivityEventType,
        since: datetime,
    ) -> list[ActivityEvent]:
        async with self._engine.connect() as conn:
            rows = (
                await conn.execute(
                    select(events_table).where(
                        events_table.c.installation_id == installation_id,
                        events_table.c.repo == repo,
                        events_table.c.sha == sha,
                        events_table.c.check_name == check_name,
                        events_table.c.event_type == event_type.value,
                        events_table.c.ts >= since,
                    )
                )
            ).all()
        return [_row_to_event(row) for row in rows]

    async def retype(self, event: ActivityEvent, new_type: ActivityEventType) -> bool:
        try:
            async with self._engine.begin() as conn:
                result = await conn.execute(
                    update(events_table)
                    .where(
                        events_table.c.installation_id == event.installation_id,
                        events_table.c.repo == event.repo,
                        events_table.c.sha == event.sha,
                        events_table.c.event_type == event.event_type.value,
                        events_table.c.owner == event.owner,
                    )
                    .values(event_type=new_type.value)
                )
        except IntegrityError as error:
            if isinstance(error.orig.__cause__, asyncpg.exceptions.UniqueViolationError):
                return False
            raise
        return result.rowcount > 0


def _row_to_event(row) -> ActivityEvent:
    return ActivityEvent(
        installation_id=row.installation_id,
        repo=row.repo,
        sha=row.sha,
        event_type=ActivityEventType(row.event_type),
        owner=row.owner,
        ts=row.ts,
        check_name=row.check_name,
    )
