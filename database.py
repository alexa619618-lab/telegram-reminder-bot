"""
Database setup - async SQLAlchemy engine and session factory.
"""
import logging
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from config import config

logger = logging.getLogger(__name__)

# Async engine
engine = create_async_engine(
    config.DATABASE_URL,
    echo=False,
    future=True,
)

# Session factory
AsyncSessionFactory = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
    autocommit=False,
)


class Base(DeclarativeBase):
    """Base class for all ORM models."""
    pass


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """Dependency: yield a database session and close it afterward."""
    async with AsyncSessionFactory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def init_db() -> None:
    """Create all tables (if they don't exist) on startup."""
    # Import all models so SQLAlchemy knows about them before create_all
    import models  # noqa: F401

    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        logger.info("Database tables created / verified.")
    except Exception as exc:
        logger.exception("Failed to initialise database schema: %s", exc)
        raise


async def close_db() -> None:
    """Dispose the engine on shutdown."""
    await engine.dispose()
    logger.info("Database engine disposed.")
