import enum
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import DateTime, Enum, ForeignKey, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from models.base import Base


class AppealStatus(str, enum.Enum):
    """Enumeration for the current status of an appeal."""
    draft = "draft"
    submitted = "submitted"
    under_review = "under_review"
    resolved = "resolved"


class AppealOutcome(str, enum.Enum):
    """Enumeration for the final outcome of a resolved appeal."""
    overturned = "overturned"
    upheld = "upheld"


class Appeal(Base):
    """
    SQLAlchemy model representing an Appeal for a denied Prior Authorization Request.
    Stores the denial reason, AI-generated counter-evidence, the generated appeal letter,
    and tracks the lifecycle of the appeal process.
    """
    __tablename__ = "appeals"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True
    )
    auth_request_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("auth_requests.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    denial_reason: Mapped[str] = mapped_column(Text, nullable=False)
    counter_evidence: Mapped[List[Dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, default=list
    )
    appeal_letter: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    guidelines_cited: Mapped[List[Dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, default=list
    )
    status: Mapped[AppealStatus] = mapped_column(
        Enum(AppealStatus, name="appeal_status_enum"),
        nullable=False,
        default=AppealStatus.draft,
    )
    outcome: Mapped[Optional[AppealOutcome]] = mapped_column(
        Enum(AppealOutcome, name="appeal_outcome_enum"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    # Relationships
    auth_request: Mapped["AuthRequest"] = relationship(
        "AuthRequest", back_populates="appeals"
    )