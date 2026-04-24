import enum
import uuid
from datetime import date
from typing import Any, Dict, List, Optional

from sqlalchemy import Boolean, Date, Enum, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base


class ServiceCategory(str, enum.Enum):
    """Enumeration for service categories covered by payer policies."""
    medication = "medication"
    imaging = "imaging"
    procedure = "procedure"
    dme = "dme"


class PayerPolicy(Base):
    """
    SQLAlchemy model representing a Payer Policy.
    Stores rules, CPT codes, and auto-approve/deny criteria for prior authorizations.
    """
    __tablename__ = "payer_policies"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True
    )
    payer_name: Mapped[str] = mapped_column(String, index=True, nullable=False)
    policy_code: Mapped[str] = mapped_column(
        String, unique=True, index=True, nullable=False
    )
    service_category: Mapped[ServiceCategory] = mapped_column(
        Enum(ServiceCategory, name="service_category_enum"), nullable=False
    )
    cpt_codes: Mapped[List[str]] = mapped_column(
        JSONB, nullable=False, default=list
    )
    icd10_required: Mapped[List[str]] = mapped_column(
        JSONB, nullable=False, default=list
    )
    documentation_required: Mapped[List[str]] = mapped_column(
        JSONB, nullable=False, default=list
    )
    auto_approve_criteria: Mapped[Dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict
    )
    auto_deny_criteria: Mapped[Dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict
    )
    requires_ai_review: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    effective_date: Mapped[date] = mapped_column(Date, nullable=False)
    expiry_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)