import logging
from typing import Optional

from redis.asyncio import ConnectionPool, Redis

from core.config import get_settings
from core.logging import get_logger

logger = get_logger(__name__)

# Global Redis client instance to maintain the connection pool
_redis_client: Optional[Redis] = None


async def get_redis_pool() -> Redis:
    """
    Initialize and return the Redis connection pool.
    Reuses the existing connection pool if it has already been initialized.
    
    This client is configured to decode responses to strings automatically,
    which is ideal for rate limiting, state management, and WebSocket pub/sub.
    
    Returns:
        Redis: An asynchronous Redis client instance connected to the configured URL.
    """
    global _redis_client
    
    if _redis_client is None:
        settings = get_settings()
        logger.info(
            "Initializing Redis connection pool",
            extra={"redis_url_scheme": settings.REDIS_URL.split("://")[0]}
        )
        
        # Configure robust connection pooling with health checks and timeouts
        pool = ConnectionPool.from_url(
            url=settings.REDIS_URL,
            decode_responses=True,
            max_connections=100,
            socket_timeout=5.0,
            socket_connect_timeout=5.0,
            retry_on_timeout=True,
            health_check_interval=30
        )
        _redis_client = Redis(connection_pool=pool)
        
    return _redis_client


async def close_redis_pool() -> None:
    """
    Close the Redis connection pool gracefully.
    This function should be called during the application's shutdown lifespan event
    to ensure all connections are properly released and no data is lost.
    """
    global _redis_client
    
    if _redis_client is not None:
        logger.info("Closing Redis connection pool")
        # redis.asyncio.Redis.aclose() is the standard way to close connections in redis-py >= 5.0
        await _redis_client.aclose()
        _redis_client = None