import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import desc, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from api.schemas.auth_request import (
    AuthEventResponse,
    AuthRequestCreate,
    AuthRequestResponse,
)
from api.schemas.workflow import WorkflowStepResponse
from models.auth_request import AuthEvent, AuthRequest
from models.database import get_db
from models.workflow import WorkflowStep

router = APIRouter(prefix="/auth-requests", tags=["Auth Requests"])


@router.post(
    "",
    response_model=AuthRequestResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new Prior Authorization Request",
    description="Creates a new auth request and initializes the event log. Implements idempotency to prevent duplicate submissions within 24 hours."
)
async def create_auth_request(
    request_data: AuthRequestCreate,
    db: AsyncSession = Depends(get_db)
) -> Any:
    """
    Create a new authorization request.
    
    Checks for recent identical requests (same patient, service, and payer) 
    within the last 24 hours to ensure idempotency.
    """
    twenty_four_hours_ago = datetime.now(timezone.utc) - timedelta(hours=24)
    
    idempotency_stmt = select(AuthRequest).where(
        AuthRequest.patient_id == request_data.patient_id,
        AuthRequest.service_requested == request_data.service_requested,
        AuthRequest.payer_id == request_data.payer_id,
        AuthRequest.created_at >= twenty_four_hours_ago
    )
    
    existing_request = (await db.execute(idempotency_stmt)).scalar_one_or_none()
    if existing_request:
        return existing_request

    new_request = AuthRequest(**request_data.model_dump())
    db.add(new_request)
    
    try:
        await db.flush()
        
        initial_event = AuthEvent(
            auth_request_id=new_request.id,
            event_type="created",
            agent_name="api_system",
            payload={"message": "Authorization request received and created."},
            confidence_score=1.0,
            latency_ms=0
        )
        db.add(initial_event)
        
        await db.commit()
        await db.refresh(new_request)
        return new_request
        
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Database integrity error. Verify related entities like payer_id or patient_id exist."
        )


@router.get(
    "",
    response_model=List[AuthRequestResponse],
    status_code=status.HTTP_200_OK,
    summary="List Prior Authorization Requests",
    description="Retrieves a paginated list of authorization requests, optionally filtered by patient_id."
)
async def list_auth_requests(
    skip: int = Query(0, ge=0, description="Number of records to skip for pagination"),
    limit: int = Query(50, ge=1, le=100, description="Maximum number of records to return"),
    patient_id: Optional[str] = Query(None, description="Filter requests by a specific patient ID"),
    db: AsyncSession = Depends(get_db)
) -> Any:
    """
    List authorization requests with pagination and optional filtering.
    """
    stmt = select(AuthRequest).order_by(desc(AuthRequest.created_at)).offset(skip).limit(limit)
    
    if patient_id:
        stmt = stmt.where(AuthRequest.patient_id == patient_id)
        
    result = await db.execute(stmt)
    return result.scalars().all()


@router.get(
    "/{id}",
    response_model=AuthRequestResponse,
    status_code=status.HTTP_200_OK,
    summary="Get a specific Prior Authorization Request",
    description="Retrieves the details of a single authorization request by its UUID."
)
async def get_auth_request(
    id: uuid.UUID,
    db: AsyncSession = Depends(get_db)
) -> Any:
    """
    Retrieve a specific authorization request by ID.
    """
    stmt = select(AuthRequest).where(AuthRequest.id == id)
    result = await db.execute(stmt)
    auth_req = result.scalar_one_or_none()
    
    if not auth_req:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"AuthRequest with id {id} not found"
        )
        
    return auth_req


@router.get(
    "/{id}/events",
    response_model=List[AuthEventResponse],
    status_code=status.HTTP_200_OK,
    summary="Get Audit Trail Events for a Request",
    description="Retrieves the event-sourced audit trail for a specific authorization request."
)
async def get_auth_events(
    id: uuid.UUID,
    db: AsyncSession = Depends(get_db)
) -> Any:
    """
    Retrieve all audit events associated with a specific authorization request.
    """
    req_stmt = select(AuthRequest.id).where(AuthRequest.id == id)
    if not (await db.execute(req_stmt)).scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"AuthRequest with id {id} not found"
        )
        
    stmt = select(AuthEvent).where(AuthEvent.auth_request_id == id).order_by(AuthEvent.timestamp)
    result = await db.execute(stmt)
    return result.scalars().all()


@router.get(
    "/{id}/workflow",
    response_model=List[WorkflowStepResponse],
    status_code=status.HTTP_200_OK,
    summary="Get AI Pipeline Workflow Steps",
    description="Retrieves the execution steps and status of the AI pipeline for a specific request."
)
async def get_auth_workflow(
    id: uuid.UUID,
    db: AsyncSession = Depends(get_db)
) -> Any:
    """
    Retrieve all workflow pipeline steps associated with a specific authorization request.
    """
    req_stmt = select(AuthRequest.id).where(AuthRequest.id == id)
    if not (await db.execute(req_stmt)).scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"AuthRequest with id {id} not found"
        )
        
    stmt = select(WorkflowStep).where(WorkflowStep.auth_request_id == id).order_by(WorkflowStep.started_at)
    result = await db.execute(stmt)
    return result.scalars().all()


@router.post(
    "/{id}/process",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Trigger AI Processing Pipeline",
    description="Enqueues the authorization request for asynchronous AI processing via ARQ."
)
async def process_auth_request(
    id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db)
) -> Dict[str, Any]:
    """
    Trigger the background AI processing pipeline for a specific authorization request.
    """
    req_stmt = select(AuthRequest.id).where(AuthRequest.id == id)
    if not (await db.execute(req_stmt)).scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"AuthRequest with id {id} not found"
        )
        
    redis_pool = getattr(request.app.state, "redis_pool", None)
    if not redis_pool:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Background processing queue is currently unavailable."
        )
        
    await redis_pool.enqueue_job("process_auth_request_task", str(id))
    
    return {
        "message": "AI processing pipeline successfully triggered.",
        "auth_request_id": str(id),
        "status": "queued"
    }