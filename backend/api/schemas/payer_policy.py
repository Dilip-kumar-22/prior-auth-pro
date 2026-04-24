import uuid
from datetime import date
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field

from models.payer_policy import ServiceCategory


class PayerPolicyCreate(BaseModel):
    """
    Pydantic schema for creating a new Payer Policy.
    Validates incoming payload before inserting into the database.
    """
    payer_name: str = Field(
        ...,
        min_length=1,
        description="Name of the payer or insurance company"
    )
    policy_code: str = Field(
        ...,
        min_length=1,
        description="Unique code identifying this specific policy"
    )
    service_category: ServiceCategory = Field(
        ...,
        description="Category of service covered by this policy (medication, imaging, procedure, dme)"
    )
    cpt_codes: List[str] = Field(
        default_factory=list,
        description="List of applicable CPT codes for this policy"
    )
    icd10_required: List[str] = Field(
        default_factory=list,
        description="List of required ICD-10 diagnosis codes"
    )
    documentation_required: List[str] = Field(
        default_factory=list,
        description="List of required documentation types (e.g., 'clinical_notes', 'lab_results')"
    )
    auto_approve_criteria: Dict[str, Any] = Field(
        default_factory=dict,
        description="Rules and criteria for automatic approval"
    )
    auto_deny_criteria: Dict[str, Any] = Field(
        default_factory=dict,
        description="Rules and criteria for automatic denial"
    )
    requires_ai_review: bool = Field(
        default=False,
        description="Flag indicating if this policy requires AI reasoning review"
    )
    effective_date: date = Field(
        ...,
        description="Date when this policy becomes effective"
    )
    expiry_date: Optional[date] = Field(
        default=None,
        description="Optional date when this policy expires"
    )

    model_config = ConfigDict(
        from_attributes=True,
        populate_by_name=True,
        str_strip_whitespace=True,
    )


class PayerPolicyResponse(BaseModel):
    """
    Pydantic schema for returning a Payer Policy.
    Field names exactly match the SQLAlchemy PayerPolicy model columns.
    """
    id: uuid.UUID = Field(
        ...,
        description="Unique identifier for the payer policy"
    )
    payer_name: str = Field(
        ...,
        description="Name of the payer or insurance company"
    )
    policy_code: str = Field(
        ...,
        description="Unique code identifying this specific policy"
    )
    service_category: ServiceCategory = Field(
        ...,
        description="Category of service covered by this policy"
    )
    cpt_codes: List[str] = Field(
        ...,
        description="List of applicable CPT codes for this policy"
    )
    icd10_required: List[str] = Field(
        ...,
        description="List of required ICD-10 diagnosis codes"
    )
    documentation_required: List[str] = Field(
        ...,
        description="List of required documentation types"
    )
    auto_approve_criteria: Dict[str, Any] = Field(
        ...,
        description="Rules and criteria for automatic approval"
    )
    auto_deny_criteria: Dict[str, Any] = Field(
        ...,
        description="Rules and criteria for automatic denial"
    )
    requires_ai_review: bool = Field(
        ...,
        description="Flag indicating if this policy requires AI reasoning review"
    )
    effective_date: date = Field(
        ...,
        description="Date when this policy becomes effective"
    )
    expiry_date: Optional[date] = Field(
        default=None,
        description="Optional date when this policy expires"
    )

    model_config = ConfigDict(
        from_attributes=True,
        populate_by_name=True,
        str_strip_whitespace=True,
    )