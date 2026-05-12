from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase
from typing import AsyncGenerator

from app.config import get_settings


engine = create_async_engine(
    get_settings().DATABASE_URL,
    echo=False,
    pool_pre_ping=True,
)

async_session_factory = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


class Base(DeclarativeBase):
    pass


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    # Local import to avoid a circular dep on app.events (which has none here,
    # but keep this defensive — events imports nothing from app).
    from app.events import flush_session_events, discard_session_events

    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
            flush_session_events(session)
        except Exception:
            await session.rollback()
            discard_session_events(session)
            raise
