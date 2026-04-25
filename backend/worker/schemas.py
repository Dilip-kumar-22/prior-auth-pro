"""Pydantic v2 models used by the worker layer for structured LLM output.

These are the clinical-domain data classes — they shape what Gemini returns
when generating an authorisation decision or an appeal letter, and what the
worker tasks pass between the rules engine, RAG engine, and downstream code.
"""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


class ClinicalContext(BaseModel):
    """Distilled clinical picture extracted from a FHIR Bundle.

    Produced by the FHIR extraction step and consumed by both the rules engine
    and (when AI review is required) the GeminiClient.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    patient_age: Optional[int] = Field(default=None, ge=0, le=130)
    patient_sex: Optional[str] = None
    primary_diagnosis_icd10: list[str] = Field(default_factory=list)
    secondary_diagnoses_icd10: list[str] = Field(default_factory=list)
    relevant_medications: list[str] = Field(default_factory=list)
    failed_prior_therapies: list[str] = Field(default_factory=list)
    lab_results_summary: Optional[str] = None
    clinical_narrative: str = ""


class AuthDecision(BaseModel):
    """Gemini's prior-auth determination.

    Returned by `worker.llm_client.generate_auth_decision`. The decision and
    reasoning are persisted to AuthEvent rows so the dashboard can render the
    full audit trail.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    decision: Literal["approve", "deny", "pend"]
    reasoning: str = Field(
        ...,
        min_length=1,
        description="3-5 sentences explaining the determination.",
    )
    confidence: float = Field(..., ge=0.0, le=1.0)
    key_factors: list[str] = Field(
        default_factory=list,
        description="Bullet-point factors weighed in the decision.",
    )
    cited_guidelines: list[str] = Field(
        default_factory=list,
        description="Policy codes or guideline IDs referenced.",
    )
    required_documentation_missing: list[str] = Field(default_factory=list)


class AppealContext(BaseModel):
    """Inputs to the appeal letter generator.

    Built by `generate_appeal_task` from the denied AuthRequest, its Decision,
    and any associated Appeal record. Passed to `generate_appeal_letter`.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    denial_reason: str = Field(..., min_length=1)
    clinical_summary: str = Field(..., min_length=1)
    policy_citations: list[str] = Field(default_factory=list)
    patient_age: Optional[int] = Field(default=None, ge=0, le=130)
    primary_diagnosis_icd10: Optional[str] = None


class AppealLetter(BaseModel):
    """Structured output of the appeal-letter generator.

    Each field is one paragraph in the rendered Markdown letter. The task
    layer concatenates them with double newlines for the persisted document.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    introduction: str = Field(..., min_length=1)
    clinical_justification: str = Field(
        ...,
        min_length=1,
        description="Paragraph tying patient facts to coverage criteria.",
    )
    policy_citations: str = Field(
        ...,
        min_length=1,
        description="Paragraph citing the relevant payer/medical guidelines.",
    )
    conclusion: str = Field(..., min_length=1)
