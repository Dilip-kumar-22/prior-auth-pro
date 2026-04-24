import time
from typing import Optional

from fastapi import HTTPException, Request, status

from core.logging import get_logger
from core.redis import get_redis_pool

logger = get_logger(__name__)

# Lua script for atomic Token Bucket evaluation in Redis.
# KEYS[1]: The rate limit key (e.g., "rate_limit:/api/v1/auth:192.168.1.1")
# ARGV[1]: Bucket capacity (maximum burst size)
# ARGV[2]: Refill rate (tokens added per second)
# ARGV[3]: Current timestamp in seconds
TOKEN_BUCKET_SCRIPT = """
local key = KEYS[1]
local capacity = tonumber(ARGV[1])
local refill_rate = tonumber(ARGV[2])
local now = tonumber(ARGV[3])
local requested = 1

local bucket = redis.call('HMGET', key, 'tokens', 'last_refill')
local tokens = tonumber(bucket[1])
local last_refill = tonumber(bucket[2])

if not tokens then
    tokens = capacity
    last_refill = now
end

local elapsed = math.max(0, now - last_refill)
local tokens_to_add = elapsed * refill_rate
tokens = math.min(capacity, tokens + tokens_to_add)

if tokens >= requested then
    tokens = tokens - requested
    redis.call('HMSET', key, 'tokens', tokens, 'last_refill', now)
    local ttl = math.ceil(capacity / refill_rate)
    redis.call('EXPIRE', key, ttl)
    return 1
else
    return 0
end
"""


async def check_rate_limit(
    identifier: str,
    capacity: int,
    refill_rate: float
) -> bool:
    """
    Evaluates the rate limit for a given identifier using a Redis-backed Token Bucket.

    Args:
        identifier (str): The unique key to track (e.g., IP address or user ID).
        capacity (int): The maximum number of tokens the bucket can hold (burst limit).
        refill_rate (float): The number of tokens added to the bucket per second.

    Returns:
        bool: True if the request is allowed (token consumed), False if rate limited.
    """
    try:
        redis_client = await get_redis_pool()
        now = time.time()
        key = f"rate_limit:{identifier}"

        # Execute the Lua script atomically
        result = await redis_client.eval(
            TOKEN_BUCKET_SCRIPT,
            1,
            key,
            capacity,
            refill_rate,
            now
        )
        return bool(result)
    except Exception as e:
        logger.error(
            "Redis rate limiting failed, failing open to allow request.",
            extra={"error": str(e), "identifier": identifier}
        )
        # Fail open: if Redis is down, we do not want to block legitimate traffic
        return True


class RateLimiter:
    """
    FastAPI dependency class for applying Token Bucket rate limiting to routes.
    """

    def __init__(self, requests: int, window_seconds: int) -> None:
        """
        Initialize the RateLimiter dependency.

        Args:
            requests (int): The maximum number of requests allowed in the window.
            window_seconds (int): The time window in seconds for the request limit.
        """
        if requests <= 0 or window_seconds <= 0:
            raise ValueError("Requests and window_seconds must be strictly positive integers.")
            
        self.capacity = requests
        self.refill_rate = requests / window_seconds

    async def __call__(self, request: Request) -> None:
        """
        Executes the rate limit check when injected as a FastAPI dependency.

        Args:
            request (Request): The incoming FastAPI request object.

        Raises:
            HTTPException: 429 Too Many Requests if the rate limit is exceeded.
        """
        # Extract client IP, respecting standard proxy headers
        forwarded_for: Optional[str] = request.headers.get("X-Forwarded-For")
        if forwarded_for:
            client_ip = forwarded_for.split(",")[0].strip()
        else:
            client_ip = request.client.host if request.client else "unknown_ip"

        # Create a unique identifier combining the route path and the client IP
        identifier = f"{request.url.path}:{client_ip}"

        is_allowed = await check_rate_limit(
            identifier=identifier,
            capacity=self.capacity,
            refill_rate=self.refill_rate
        )

        if not is_allowed:
            logger.warning(
                "Rate limit exceeded",
                extra={
                    "client_ip": client_ip,
                    "path": request.url.path,
                    "capacity": self.capacity,
                    "refill_rate": self.refill_rate
                }
            )
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Too many requests. Please try again later."
            )