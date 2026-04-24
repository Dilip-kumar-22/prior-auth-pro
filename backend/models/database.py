import logging
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from core.config import get_settings
from models.base import Base

logger = logging.getLogger(__name__)

settings = get_settings()

engine = create_async_engine(
    settings.DATABASE_URL,
    echo=settings.ENVIRONMENT.lower() == "development" and settings.LOG_LEVEL.lower() == "debug",
    pool_pre_ping=True,
    pool_size=20,
    max_overflow=10,
    pool_timeout=30.0,
    pool_recycle=1800,
)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    autocommit=False,
    autoflush=False,
    expire_on_commit=False,
)

async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """
    FastAPI dependency that provides an asynchronous SQLAlchemy session.
    
    Yields:
        AsyncSession: An active SQLAlchemy async session.
        
    The session is automatically closed when the request context ends,
    and any uncommitted transactions are rolled back by the context manager.
    """
    async with AsyncSessionLocal() as session:
        yield session

get_session = get_db_session

__all__ = ["Base", "engine", "AsyncSessionLocal", "get_db_session", "get_session"]