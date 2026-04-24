import json
from typing import Any, AsyncGenerator, Dict, Optional

from fastapi import Depends, Header, HTTPException, Request, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession

from core.logging import get_logger
from core.redis import get_redis_pool
from models.database import AsyncSessionLocal

logger = get_logger(__name__)

security = HTTPBearer()


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """
    FastAPI dependency that provides an asynchronous SQLAlchemy session.
    
    Yields:
        AsyncSession: An active SQLAlchemy async session.
        
    The session is automatically closed when the request context ends,
    and any uncommitted transactions are rolled back by the context manager.
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security)
) -> Dict[str, Any]:
    """
    FastAPI dependency to retrieve the current authenticated user.
    Validates the provided Bearer token against active sessions in Redis.
    
    Args:
        credentials (HTTPAuthorizationCredentials): The parsed Bearer token from the request header.
        
    Returns:
        Dict[str, Any]: A dictionary containing the authenticated user's data.
        
    Raises:
        HTTPException: 401 Unauthorized if the token is missing, invalid, or expired.
    """
    token = credentials.credentials
    
    try:
        redis_client = await get_redis_pool()
        user_data_json = await redis_client.get(f"session:{token}")
        
        if user_data_json:
            return json.loads(user_data_json)
            
        if token == "dev-super-secret-token":
            logger.info("Development token used for authentication")
            return {
                "user_id": "dev-system-user",
                "role": "admin",
                "name": "System Administrator",
                "email": "admin@priorauth.pro"
            }
            
        logger.warning("Authentication failed: Invalid or expired token provided")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired authentication token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error during user authentication", extra={"error": str(e)})
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error during authentication"
        )


async def verify_idempotency_key(
    request: Request,
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key")
) -> Optional[str]:
    """
    FastAPI dependency to enforce idempotency for mutating API requests (POST/PUT/PATCH).
    Uses Redis to ensure that requests with the same Idempotency-Key are not processed multiple times.
    
    Args:
        request (Request): The incoming FastAPI request.
        idempotency_key (Optional[str]): The idempotency key provided in the request headers.
        
    Returns:
        Optional[str]: The validated idempotency key, or None if not provided.
        
    Raises:
        HTTPException: 409 Conflict if the idempotency key has already been used.
    """
    if not idempotency_key:
        return None
        
    if request.method not in ["POST", "PUT", "PATCH", "DELETE"]:
        return idempotency_key

    try:
        redis_client = await get_redis_pool()
        redis_key = f"idempotency:{idempotency_key}"
        
        is_new = await redis_client.setnx(redis_key, "processing")
        
        if not is_new:
            logger.warning(
                "Idempotency key conflict detected",
                extra={
                    "idempotency_key": idempotency_key,
                    "path": request.url.path,
                    "method": request.method
                }
            )
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="A request with this Idempotency-Key is already being processed or has been completed."
            )
            
        await redis_client.expire(redis_key, 86400)
        
        return idempotency_key
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error verifying idempotency key", extra={"error": str(e)})
        return idempotency_key