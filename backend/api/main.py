import logging
import os
from contextlib import asynccontextmanager
from typing import AsyncGenerator, Callable, List

from arq import create_pool
from arq.connections import ArqRedis, RedisSettings
from fastapi import FastAPI, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import Field
from pydantic_settings import BaseSettings
from starlette.middleware.base import BaseHTTPMiddleware

from api.routes.appeals import router as appeals_router
from api.routes.audit import router as audit_router
from api.routes.auth_requests import router as auth_requests_router
from api.routes.dashboard import router as dashboard_router
from api.websocket import router as websocket_router
from models.database import engine

logger = logging.getLogger(__name__)


class Settings(BaseSettings):
    """
    Application settings loaded from environment variables.
    """
    project_name: str = "Prior Auth Pro API"
    version: str = "1.0.0"
    cors_origins: str = Field(default="http://localhost:3000,http://localhost:8080")
    redis_url: str = Field(default="redis://localhost:6379")
    secret_key: str = Field(default_factory=lambda: os.environ.get("SECRET_KEY", os.urandom(32).hex()))
    rate_limit_requests: int = Field(default=100)
    rate_limit_window_seconds: int = Field(default=60)

    @property
    def cors_origins_list(self) -> List[str]:
        """Parses the comma-separated CORS origins into a list."""
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


settings = Settings()


class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    Simple Redis-based rate limiting middleware for auth endpoints.
    """
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        if request.url.path.startswith("/auth-requests"):
            redis_pool: ArqRedis = getattr(request.app.state, "redis_pool", None)
            if redis_pool:
                client_ip = request.client.host if request.client else "unknown_client"
                key = f"rate_limit:auth_requests:{client_ip}"
                
                try:
                    current_requests = await redis_pool.get(key)
                    if current_requests and int(current_requests) >= settings.rate_limit_requests:
                        logger.warning(f"Rate limit exceeded for IP: {client_ip}")
                        return Response(
                            content='{"detail": "Too many requests. Please try again later."}',
                            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                            media_type="application/json"
                        )
                    
                    pipe = redis_pool.pipeline()
                    pipe.incr(key)
                    if not current_requests:
                        pipe.expire(key, settings.rate_limit_window_seconds)
                    await pipe.execute()
                except Exception as e:
                    logger.error(f"Rate limiting error: {str(e)}")

        return await call_next(request)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """
    FastAPI lifespan manager for startup and shutdown events.
    Initializes Redis pool for ARQ and cleans up database connections.
    """
    logger.info("Starting up Prior Auth Pro API...")
    
    try:
        redis_settings = RedisSettings.from_dsn(settings.redis_url)
        app.state.redis_pool = await create_pool(redis_settings)
        logger.info("Redis pool initialized successfully.")
    except Exception as e:
        logger.error(f"Failed to initialize Redis pool: {str(e)}")
        raise

    yield

    logger.info("Shutting down Prior Auth Pro API...")
    
    if hasattr(app.state, "redis_pool"):
        try:
            await app.state.redis_pool.close()
            logger.info("Redis pool closed successfully.")
        except Exception as e:
            logger.error(f"Error closing Redis pool: {str(e)}")

    try:
        await engine.dispose()
        logger.info("Database engine disposed successfully.")
    except Exception as e:
        logger.error(f"Error disposing database engine: {str(e)}")


def create_app() -> FastAPI:
    """
    Factory function to create and configure the FastAPI application instance.
    """
    app = FastAPI(
        title=settings.project_name,
        version=settings.version,
        lifespan=lifespan,
        description="Enterprise-grade Prior Authorization AI Agent backend.",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.add_middleware(RateLimitMiddleware)

    app.include_router(auth_requests_router)
    app.include_router(appeals_router)
    app.include_router(dashboard_router)
    app.include_router(audit_router)
    app.include_router(websocket_router)

    @app.get("/health", tags=["System"], status_code=status.HTTP_200_OK)
    async def health_check() -> dict[str, str]:
        """
        Health check endpoint to verify API is running.
        """
        return {
            "status": "healthy",
            "version": settings.version,
            "environment": os.environ.get("ENVIRONMENT", "development")
        }

    return app


app = create_app()