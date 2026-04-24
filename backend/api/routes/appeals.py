import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import desc, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from api.schemas.appeal import AppealCreate, AppealResponse
from models.appeal import Appeal
from models.auth_request import AuthRequest
from models.database import get_db

router = APIRouter(prefix="/appeals", tags=["Appeals"])


@router.post(
    "",
    response_model=AppealResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new Appeal",
    description="Creates a new appeal for a denied authorization request."
)
async def create_appeal(
    appeal_data: AppealCreate,
    db: AsyncSession = Depends(get_db)
) -> Any:
    """
    Create a new appeal for a denied authorization request.
    
    Validates that the associated authorization request exists before creating the appeal.
    """
    auth_stmt = select(AuthRequest.id).where(AuthRequest.id == appeal_data.auth_request_id)
    if not (await db.execute(auth_stmt)).scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"AuthRequest with id {appeal_data.auth_request_id} not found"
        )

    new_appeal = Appeal(**appeal_data.model_dump())
    db.add(new_appeal)
    
    try:
        await db.commit()
        await db.refresh(new_appeal)
        return new_appeal
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Database integrity error. Verify related entities exist and are valid."
        )


@router.get(
    "",
    response_model=List[AppealResponse],
    status_code=status.HTTP_200_OK,
    summary="List Appeals",
    description="Retrieves a paginated list of appeals, optionally filtered by auth_request_id."
)
async def list_appeals(
    skip: int = Query(0, ge=0, description="Number of records to skip for pagination"),
    limit: int = Query(50, ge=1, le=100, description="Maximum number of records to return"),
    auth_request_id: Optional[uuid.UUID] = Query(None, description="Filter appeals by a specific auth request ID"),
    db: AsyncSession = Depends(get_db)
) -> Any:
    """
    List appeals with pagination and optional filtering by authorization request ID.
    """
    stmt = select(Appeal).order_by(desc(Appeal.created_at)).offset(skip).limit(limit)
    
    if auth_request_id:
        stmt = stmt.where(Appeal.auth_request_id == auth_request_id)
        
    result = await db.execute(stmt)
    return result.scalars().all()


@router.get(
    "/{id}",
    response_model=AppealResponse,
    status_code=status.HTTP_200_OK,
    summary="Get a specific Appeal",
    description="Retrieves the details of a single appeal by its UUID."
)
async def get_appeal(
    id: uuid.UUID,
    db: AsyncSession = Depends(get_db)
) -> Any:
    """
    Retrieve a specific appeal by its ID.
    """
    stmt = select(Appeal).where(Appeal.id == id)
    result = await db.execute(stmt)
    appeal = result.scalar_one_or_none()
    
    if not appeal:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Appeal with id {id} not found"
        )
        
    return appeal


@router.post(
    "/{id}/generate",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Trigger AI Appeal Generation",
    description="Enqueues the appeal for asynchronous AI generation of the appeal letter and counter-evidence via ARQ."
)
async def generate_appeal(
    id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db)
) -> Dict[str, Any]:
    """
    Trigger the background AI processing pipeline to generate an appeal letter and gather counter-evidence.
    """
    stmt = select(Appeal).where(Appeal.id == id)
    result = await db.execute(stmt)
    appeal = result.scalar_one_or_none()
    
    if not appeal:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Appeal with id {id} not found"
        )
        
    redis_pool = getattr(request.app.state, "redis_pool", None)
    if not redis_pool:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Background processing queue is currently unavailable."
        )
        
    await redis_pool.enqueue_job("generate_appeal_task", str(id))
    
    appeal.status = "under_review"
    await db.commit()
    
    return {
        "message": "AI appeal generation successfully triggered.",
        "appeal_id": str(id),
        "status": "queued"
    }