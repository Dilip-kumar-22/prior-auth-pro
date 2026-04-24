import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import get_db
from core.logging import get_logger
from core.redis import get_redis_pool

logger = get_logger(__name__)

router = APIRouter()


class DependencyStatus(BaseModel):
    """Pydantic schema for individual dependency health status."""
    database: str = Field(
        ..., 
        description="Status of the PostgreSQL database connection"
    )
    redis: str = Field(
        ..., 
        description="Status of the Redis connection pool"
    )


class HealthResponse(BaseModel):
    """Pydantic schema for the overall health check response."""
    status: str = Field(
        ..., 
        description="Overall health status of the API (ok or degraded)"
    )
    dependencies: DependencyStatus = Field(
        ..., 
        description="Status of individual external dependencies"
    )
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc), 
        description="Current UTC timestamp of the health check"
    )


async def check_db(db: AsyncSession) -> bool:
    """
    Check the health of the PostgreSQL database connection.
    
    Args:
        db (AsyncSession): The active SQLAlchemy asynchronous session.
        
    Returns:
        bool: True if the database is reachable and responsive, False otherwise.
    """
    try:
        await db.execute(text("SELECT 1"))
        return True
    except Exception as e:
        logger.error("Database health check failed", extra={"error": str(e)})
        return False


async def check_redis() -> bool:
    """
    Check the health of the Redis connection pool.
    
    Returns:
        bool: True if Redis is reachable and responsive, False otherwise.
    """
    try:
        redis_client = await get_redis_pool()
        return await redis_client.ping()
    except Exception as e:
        logger.error("Redis health check failed", extra={"error": str(e)})
        return False


@router.get("/health", response_model=HealthResponse, summary="API Health Check")
async def health_check(
    response: Response,
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db)
) -> HealthResponse:
    """
    Observability endpoint to check the health of the API and its dependencies.
    Verifies connectivity to the PostgreSQL database and Redis cache.
    Returns a 503 Service Unavailable status code if any critical dependency is unreachable.
    """
    db_ok = await check_db(db)
    redis_ok = await check_redis()

    overall_status = "ok" if db_ok and redis_ok else "degraded"

    if overall_status == "degraded":
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    else:
        response.status_code = status.HTTP_200_OK

    return HealthResponse(
        status=overall_status,
        dependencies=DependencyStatus(
            database="ok" if db_ok else "unreachable",
            redis="ok" if redis_ok else "unreachable"
        ),
        timestamp=datetime.now(timezone.utc)
    )