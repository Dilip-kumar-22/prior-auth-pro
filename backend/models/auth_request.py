import enum
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import DateTime, Enum, Float, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from models.base import Base


class AuthType(str, enum.Enum):
    """Enumeration for types of authorization requests."""
    medication = "medication"
    imaging = "imaging"
    procedure = "procedure"
    dme = "dme"


class PriorityLevel(str, enum.Enum):
    """Enumeration for priority levels of authorization requests."""
    urgent = "urgent"
    standard = "standard"


class EventType(str, enum.Enum):
    """Enumeration for the types of events in the authorization lifecycle."""
    created = "created"
    data_extracted = "data_extracted"
    classified = "classified"
    rule_matched = "rule_matched"
    rule_no_match = "rule_no_match"
    rag_queried = "rag_queried"
    decision_made = "decision_made"
    appealed = "appealed"
    appeal_resolved = "appeal_resolved"
    flagged_for_review = "flagged_for_review"
    clinician_override = "clinician_override"


class AuthRequest(Base):
    """
    SQLAlchemy model representing a Prior Authorization Request.
    Acts as the root aggregate in the event-sourced architecture.
    """
    __tablename__ = "auth_requests"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True
    )
    patient_id: Mapped[str] = mapped_column(String, index=True, nullable=False)
    auth_type: Mapped[AuthType] = mapped_column(
        Enum(AuthType, name="auth_type_enum"), nullable=False
    )
    service_requested: Mapped[str] = mapped_column(String, nullable=False)
    diagnosis_codes: Mapped[List[Dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, default=list
    )
    payer_id: Mapped[str] = mapped_column(String, index=True, nullable=False)
    plan_id: Mapped[str] = mapped_column(String, index=True, nullable=False)
    priority: Mapped[PriorityLevel] = mapped_column(
        Enum(PriorityLevel, name="priority_level_enum"),
        nullable=False,
        default=PriorityLevel.standard,
    )
    fhir_bundle: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    # Relationships
    events: Mapped[List["AuthEvent"]] = relationship(
        "AuthEvent",
        back_populates="auth_request",
        cascade="all, delete-orphan",
        order_by="AuthEvent.timestamp",
    )
    appeals: Mapped[List["Appeal"]] = relationship(
        "Appeal",
        back_populates="auth_request",
        cascade="all, delete-orphan",
    )
    workflow_steps: Mapped[List["WorkflowStep"]] = relationship(
        "WorkflowStep",
        back_populates="auth_request",
        cascade="all, delete-orphan",
        order_by="WorkflowStep.started_at",
    )


class AuthEvent(Base):
    """
    SQLAlchemy model representing an event in the lifecycle of an AuthRequest.
    Implements the event-sourced architecture for full auditability.
    """
    __tablename__ = "auth_events"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True
    )
    auth_request_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("auth_requests.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    event_type: Mapped[EventType] = mapped_column(
        Enum(EventType, name="event_type_enum"), nullable=False
    )
    agent_name: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    model_used: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    payload: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSONB, nullable=True)
    confidence_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    latency_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
        index=True,
    )

    # Relationships
    auth_request: Mapped["AuthRequest"] = relationship(
        "AuthRequest", back_populates="events"
    )