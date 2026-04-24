import uuid
from datetime import datetime
from typing import Any, List, Optional

from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel
from sqlalchemy import String, asc, desc, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.schemas.auth_request import AuthEventResponse
from models.auth_request import AuthEvent
from models.database import get_db

router = APIRouter(prefix="/audit", tags=["Audit"])


class PaginatedAuditResponse(BaseModel):
    """
    Response schema for cursor-based pagination of audit events.
    """
    items: List[AuthEventResponse]
    next_cursor: Optional[datetime] = None


@router.get(
    "/events",
    response_model=PaginatedAuditResponse,
    status_code=status.HTTP_200_OK,
    summary="List Audit Events",
    description="Searchable, filterable audit log endpoints with cursor-based pagination."
)
async def list_audit_events(
    limit: int = Query(50, ge=1, le=100, description="Maximum number of records to return"),
    cursor: Optional[datetime] = Query(None, description="Cursor for pagination (timestamp of the last seen record)"),
    direction: str = Query("desc", pattern="^(asc|desc)$", description="Sort direction based on timestamp"),
    event_type: Optional[str] = Query(None, description="Filter by specific event type"),
    agent_name: Optional[str] = Query(None, description="Filter by the agent or system that created the event"),
    auth_request_id: Optional[uuid.UUID] = Query(None, description="Filter events for a specific authorization request"),
    search: Optional[str] = Query(None, description="Case-insensitive search within payload or agent name"),
    db: AsyncSession = Depends(get_db)
) -> Any:
    """
    Retrieve a paginated, filterable, and searchable list of audit events.
    
    Implements cursor-based pagination using the event timestamp to ensure stable 
    pagination even as new events are continuously appended to the event store.
    """
    stmt = select(AuthEvent)

    if event_type:
        stmt = stmt.where(AuthEvent.event_type == event_type)
    
    if agent_name:
        stmt = stmt.where(AuthEvent.agent_name == agent_name)
        
    if auth_request_id:
        stmt = stmt.where(AuthEvent.auth_request_id == auth_request_id)

    if search:
        search_term = f"%{search}%"
        stmt = stmt.where(
            or_(
                AuthEvent.agent_name.ilike(search_term),
                AuthEvent.payload.cast(String).ilike(search_term)
            )
        )

    if direction == "desc":
        if cursor:
            stmt = stmt.where(AuthEvent.timestamp < cursor)
        stmt = stmt.order_by(desc(AuthEvent.timestamp))
    else:
        if cursor:
            stmt = stmt.where(AuthEvent.timestamp > cursor)
        stmt = stmt.order_by(asc(AuthEvent.timestamp))

    stmt = stmt.limit(limit + 1)

    result = await db.execute(stmt)
    events = list(result.scalars().all())

    next_cursor = None
    if len(events) > limit:
        next_cursor = events[limit - 1].timestamp
        events = events[:limit]

    return PaginatedAuditResponse(
        items=events,
        next_cursor=next_cursor
    )