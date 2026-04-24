import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from models.workflow import StepType, WorkflowStatus


class WorkflowStepResponse(BaseModel):
    """
    Pydantic schema for returning a WorkflowStep.
    Field names exactly match the SQLAlchemy WorkflowStep model columns.
    Used to represent a single execution step in the AI pipeline.
    """
    id: uuid.UUID = Field(
        ...,
        description="Unique identifier for the workflow step"
    )
    auth_request_id: uuid.UUID = Field(
        ...,
        description="Unique identifier of the associated authorization request"
    )
    step_type: StepType = Field(
        ...,
        description="Type of step in the AI workflow pipeline (e.g., extraction, classification)"
    )
    status: WorkflowStatus = Field(
        ...,
        description="Current execution status of the workflow step"
    )
    agent_name: Optional[str] = Field(
        default=None,
        description="Name of the specific AI agent or component executing this step"
    )
    started_at: datetime = Field(
        ...,
        description="Timestamp when the workflow step started execution"
    )
    completed_at: Optional[datetime] = Field(
        default=None,
        description="Timestamp when the workflow step completed execution, if finished"
    )
    input_hash: Optional[str] = Field(
        default=None,
        description="Hash of the input data provided to this step for data lineage tracking"
    )
    output_hash: Optional[str] = Field(
        default=None,
        description="Hash of the output data produced by this step for data lineage tracking"
    )
    retry_count: int = Field(
        ...,
        ge=0,
        description="Number of times this step has been retried due to failures"
    )

    model_config = ConfigDict(
        from_attributes=True,
        populate_by_name=True,
        str_strip_whitespace=True,
    )