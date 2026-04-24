import enum
import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from models.base import Base

if TYPE_CHECKING:
    from models.auth_request import AuthRequest


class StepType(str, enum.Enum):
    """Enumeration for the types of steps in the AI workflow pipeline."""
    extraction = "extraction"
    classification = "classification"
    rules_check = "rules_check"
    rag_lookup = "rag_lookup"
    reasoning = "reasoning"
    decision = "decision"


class WorkflowStatus(str, enum.Enum):
    """Enumeration for the execution status of a workflow step."""
    queued = "queued"
    running = "running"
    completed = "completed"
    failed = "failed"


class WorkflowStep(Base):
    """
    SQLAlchemy model representing a single execution step in the AI pipeline
    for processing a Prior Authorization Request.
    Tracks the state, timing, and data lineage (via hashes) of each agent's work.
    """
    __tablename__ = "workflow_steps"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True
    )
    auth_request_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("auth_requests.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    step_type: Mapped[StepType] = mapped_column(
        Enum(StepType, name="step_type_enum"), nullable=False
    )
    status: Mapped[WorkflowStatus] = mapped_column(
        Enum(WorkflowStatus, name="workflow_status_enum"),
        nullable=False,
        default=WorkflowStatus.queued,
    )
    agent_name: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    input_hash: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    output_hash: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    retry_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )

    # Relationships
    auth_request: Mapped["AuthRequest"] = relationship(
        "AuthRequest", back_populates="workflow_steps"
    )