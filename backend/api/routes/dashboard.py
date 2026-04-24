import logging
from datetime import datetime, timezone
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import get_db
from models.auth_request import AuthEvent, AuthRequest, EventType

logger = logging.getLogger(__name__)

router = APIRouter()


class DashboardMetricsResponse(BaseModel):
    """Pydantic schema for the dashboard metrics response."""
    approval_rate: float = Field(
        ..., 
        description="Percentage of processed requests that were approved, from 0.0 to 100.0"
    )
    avg_time_hours: float = Field(
        ..., 
        description="Average processing time from creation to decision in hours"
    )
    total_processed: int = Field(
        ..., 
        description="Total number of authorization requests that have reached a decision"
    )
    today_count: int = Field(
        ..., 
        description="Number of authorization requests created today"
    )


class DashboardImpactResponse(BaseModel):
    """Pydantic schema for the AI vs Manual impact comparison response."""
    ai_avg_processing_time_hours: float = Field(
        ..., 
        description="Average processing time using the AI agent in hours"
    )
    manual_avg_processing_time_hours: float = Field(
        ..., 
        description="Industry average manual processing time in hours (baseline)"
    )
    time_saved_hours_per_request: float = Field(
        ..., 
        description="Average time saved per request in hours"
    )
    total_time_saved_hours: float = Field(
        ..., 
        description="Total cumulative time saved across all processed requests"
    )
    cost_savings_estimated_usd: float = Field(
        ..., 
        description="Estimated cost savings in USD based on time saved"
    )


@router.get("/metrics", response_model=DashboardMetricsResponse)
async def get_metrics(
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db)
) -> DashboardMetricsResponse:
    """
    Retrieve high-level metrics for the analytics dashboard.
    Calculates total processed requests, today's volume, approval rate, and average processing time.
    """
    try:
        # 1. Total Processed (Count of distinct requests with a decision_made event)
        stmt_total_processed = select(func.count(func.distinct(AuthEvent.auth_request_id))).where(
            AuthEvent.event_type == EventType.decision_made
        )
        total_processed = await db.scalar(stmt_total_processed) or 0

        # 2. Today's Count (Count of requests created since midnight UTC today)
        today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        stmt_today = select(func.count(AuthRequest.id)).where(
            AuthRequest.created_at >= today
        )
        today_count = await db.scalar(stmt_today) or 0

        # 3. Approval Rate
        approval_rate = 0.0
        if total_processed > 0:
            stmt_approved = select(func.count(AuthEvent.id)).where(
                AuthEvent.event_type == EventType.decision_made,
                AuthEvent.payload.op('->>')('decision') == 'approve'
            )
            approved_count = await db.scalar(stmt_approved) or 0
            approval_rate = round((approved_count / total_processed) * 100.0, 2)

        # 4. Average Processing Time (Difference between decision event timestamp and request created_at)
        stmt_avg_time = select(
            func.avg(
                func.extract('epoch', AuthEvent.timestamp) - func.extract('epoch', AuthRequest.created_at)
            )
        ).join(
            AuthRequest, AuthRequest.id == AuthEvent.auth_request_id
        ).where(
            AuthEvent.event_type == EventType.decision_made
        )
        avg_time_seconds = await db.scalar(stmt_avg_time) or 0.0
        avg_time_hours = round(avg_time_seconds / 3600.0, 2)

        return DashboardMetricsResponse(
            approval_rate=approval_rate,
            avg_time_hours=avg_time_hours,
            total_processed=total_processed,
            today_count=today_count
        )

    except Exception as e:
        logger.error("Failed to retrieve dashboard metrics", extra={"error": str(e)})
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An error occurred while calculating dashboard metrics."
        )


@router.get("/impact", response_model=DashboardImpactResponse)
async def get_impact(
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db)
) -> DashboardImpactResponse:
    """
    Retrieve impact metrics comparing AI processing against traditional manual processing.
    Calculates time and cost savings based on historical data and industry baselines.
    """
    try:
        # Calculate AI average processing time
        stmt_avg_time = select(
            func.avg(
                func.extract('epoch', AuthEvent.timestamp) - func.extract('epoch', AuthRequest.created_at)
            )
        ).join(
            AuthRequest, AuthRequest.id == AuthEvent.auth_request_id
        ).where(
            AuthEvent.event_type == EventType.decision_made
        )
        avg_time_seconds = await db.scalar(stmt_avg_time) or 0.0
        ai_avg_processing_time_hours = round(avg_time_seconds / 3600.0, 2)

        # Get total processed to calculate cumulative savings
        stmt_total_processed = select(func.count(func.distinct(AuthEvent.auth_request_id))).where(
            AuthEvent.event_type == EventType.decision_made
        )
        total_processed = await db.scalar(stmt_total_processed) or 0

        # Industry baseline assumptions
        # Assume average manual prior auth takes 14 days (336 hours) end-to-end
        manual_avg_processing_time_hours = 336.0
        
        # Assume administrative cost savings of $45 per automated authorization
        cost_savings_per_request_usd = 45.0

        time_saved_hours_per_request = max(0.0, manual_avg_processing_time_hours - ai_avg_processing_time_hours)
        total_time_saved_hours = round(time_saved_hours_per_request * total_processed, 2)
        cost_savings_estimated_usd = round(cost_savings_per_request_usd * total_processed, 2)

        return DashboardImpactResponse(
            ai_avg_processing_time_hours=ai_avg_processing_time_hours,
            manual_avg_processing_time_hours=manual_avg_processing_time_hours,
            time_saved_hours_per_request=round(time_saved_hours_per_request, 2),
            total_time_saved_hours=total_time_saved_hours,
            cost_savings_estimated_usd=cost_savings_estimated_usd
        )

    except Exception as e:
        logger.error("Failed to retrieve impact metrics", extra={"error": str(e)})
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An error occurred while calculating impact metrics."
        )