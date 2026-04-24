"""
API routes package initialization.

This module aggregates all the individual API routers into a single main router.
The main FastAPI application can then import and include this single `api_router`.
"""

from fastapi import APIRouter

# Import individual route modules
# Note: These modules must define a `router = APIRouter()` WITHOUT a prefix,
# as the prefix is applied here during inclusion to avoid double-prefixing.
from api.routes.auth_requests import router as auth_requests_router
from api.routes.appeals import router as appeals_router
from api.routes.dashboard import router as dashboard_router
from api.routes.audit import router as audit_router

# Create the main API router
api_router = APIRouter()

# Include sub-routers with their respective prefixes and tags
api_router.include_router(
    auth_requests_router,
    prefix="/auth-requests",
    tags=["Auth Requests"]
)

api_router.include_router(
    appeals_router,
    prefix="/appeals",
    tags=["Appeals"]
)

api_router.include_router(
    dashboard_router,
    prefix="/dashboard",
    tags=["Dashboard"]
)

api_router.include_router(
    audit_router,
    prefix="/audit",
    tags=["Audit"]
)

__all__ = ["api_router"]