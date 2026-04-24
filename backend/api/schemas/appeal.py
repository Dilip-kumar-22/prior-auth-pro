import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field

from models.appeal import AppealOutcome, AppealStatus


class AppealCreate(BaseModel):
    """
    Pydantic schema for creating a new Appeal for a denied Prior Authorization Request.
    Validates incoming payload before inserting into the database.
    """
    auth_request_id: uuid.UUID = Field(
        ...,
        description="Unique identifier of the denied authorization request"
    )
    denial_reason: str = Field(
        ...,
        min_length=1,
        description="The reason provided by the payer for denying the original request"
    )
    counter_evidence: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="Optional initial counter-evidence to support the appeal"
    )
    guidelines_cited: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="Optional initial clinical guidelines cited to support the appeal"
    )

    model_config = ConfigDict(
        from_attributes=True,
        populate_by_name=True,
        str_strip_whitespace=True,
    )


class AppealResponse(BaseModel):
    """
    Pydantic schema for returning an Appeal.
    Field names exactly match the SQLAlchemy Appeal model columns.
    """
    id: uuid.UUID = Field(
        ...,
        description="Unique identifier for the appeal"
    )
    auth_request_id: uuid.UUID = Field(
        ...,
        description="Unique identifier of the associated authorization request"
    )
    denial_reason: str = Field(
        ...,
        description="The reason provided by the payer for denying the original request"
    )
    counter_evidence: List[Dict[str, Any]] = Field(
        ...,
        description="AI-generated or manually provided counter-evidence"
    )
    appeal_letter: Optional[str] = Field(
        default=None,
        description="The generated appeal letter text"
    )
    guidelines_cited: List[Dict[str, Any]] = Field(
        ...,
        description="Clinical guidelines cited in the appeal"
    )
    status: AppealStatus = Field(
        ...,
        description="Current status of the appeal process"
    )
    outcome: Optional[AppealOutcome] = Field(
        default=None,
        description="Final outcome of the appeal, if resolved"
    )
    created_at: datetime = Field(
        ...,
        description="Timestamp when the appeal was created"
    )

    model_config = ConfigDict(
        from_attributes=True,
        populate_by_name=True,
        str_strip_whitespace=True,
    )