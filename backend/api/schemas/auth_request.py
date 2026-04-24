import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field

from models.auth_request import AuthType, EventType, PriorityLevel


class AuthRequestCreate(BaseModel):
    """
    Pydantic schema for creating a new Prior Authorization Request.
    Validates incoming payload before inserting into the database.
    """
    patient_id: str = Field(
        ..., 
        min_length=1, 
        description="Unique identifier for the patient"
    )
    auth_type: AuthType = Field(
        ..., 
        description="Type of authorization request (medication, imaging, procedure, dme)"
    )
    service_requested: str = Field(
        ..., 
        min_length=1, 
        description="The specific service, medication, or procedure requested"
    )
    diagnosis_codes: List[Dict[str, Any]] = Field(
        default_factory=list, 
        description="List of diagnosis codes (e.g., ICD-10) and descriptions"
    )
    payer_id: str = Field(
        ..., 
        min_length=1, 
        description="Unique identifier for the payer/insurance company"
    )
    plan_id: str = Field(
        ..., 
        min_length=1, 
        description="Unique identifier for the specific insurance plan"
    )
    priority: PriorityLevel = Field(
        default=PriorityLevel.standard, 
        description="Priority level of the request (urgent or standard)"
    )
    fhir_bundle: Optional[Dict[str, Any]] = Field(
        default=None, 
        description="Optional raw FHIR bundle containing supporting clinical data"
    )

    model_config = ConfigDict(
        from_attributes=True,
        populate_by_name=True,
        str_strip_whitespace=True,
    )


class AuthRequestResponse(BaseModel):
    """
    Pydantic schema for returning a Prior Authorization Request.
    Field names exactly match the SQLAlchemy AuthRequest model columns.
    """
    id: uuid.UUID = Field(
        ..., 
        description="Unique identifier for the authorization request"
    )
    patient_id: str = Field(
        ..., 
        description="Unique identifier for the patient"
    )
    auth_type: AuthType = Field(
        ..., 
        description="Type of authorization request"
    )
    service_requested: str = Field(
        ..., 
        description="The specific service, medication, or procedure requested"
    )
    diagnosis_codes: List[Dict[str, Any]] = Field(
        ..., 
        description="List of diagnosis codes (e.g., ICD-10) and descriptions"
    )
    payer_id: str = Field(
        ..., 
        description="Unique identifier for the payer/insurance company"
    )
    plan_id: str = Field(
        ..., 
        description="Unique identifier for the specific insurance plan"
    )
    priority: PriorityLevel = Field(
        ..., 
        description="Priority level of the request"
    )
    fhir_bundle: Optional[Dict[str, Any]] = Field(
        default=None, 
        description="Optional raw FHIR bundle containing supporting clinical data"
    )
    created_at: datetime = Field(
        ..., 
        description="Timestamp when the request was created"
    )
    updated_at: datetime = Field(
        ..., 
        description="Timestamp when the request was last updated"
    )

    model_config = ConfigDict(
        from_attributes=True,
        populate_by_name=True,
        str_strip_whitespace=True,
    )


class AuthEventResponse(BaseModel):
    """
    Pydantic schema for returning an AuthEvent (audit trail entry).
    Field names exactly match the SQLAlchemy AuthEvent model columns.
    """
    id: uuid.UUID = Field(
        ..., 
        description="Unique identifier for the event"
    )
    auth_request_id: uuid.UUID = Field(
        ..., 
        description="ID of the associated authorization request"
    )
    event_type: EventType = Field(
        ..., 
        description="Type of event in the authorization lifecycle"
    )
    agent_name: Optional[str] = Field(
        default=None, 
        description="Name of the AI agent or system that generated the event"
    )
    model_used: Optional[str] = Field(
        default=None, 
        description="Identifier of the ML model used, if applicable"
    )
    payload: Optional[Dict[str, Any]] = Field(
        default=None, 
        description="Structured data payload associated with the event"
    )
    confidence_score: Optional[float] = Field(
        default=None, 
        ge=0.0, 
        le=1.0, 
        description="Confidence score of the AI prediction, if applicable"
    )
    latency_ms: Optional[int] = Field(
        default=None, 
        ge=0, 
        description="Latency of the operation in milliseconds"
    )
    timestamp: datetime = Field(
        ..., 
        description="Timestamp when the event occurred"
    )

    model_config = ConfigDict(
        from_attributes=True,
        populate_by_name=True,
        str_strip_whitespace=True,
    )