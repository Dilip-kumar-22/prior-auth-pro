"""
Pydantic schemas package initialization.

This package contains all Pydantic v2 models used for request validation
and response serialization across the FastAPI application.

The schemas are organized by domain to maintain clean module boundaries:
- auth_requests: Schemas for creating, updating, and viewing Prior Authorization requests.
- appeals: Schemas for appeal generation and management.
- dashboard: Schemas for analytics, metrics, and impact reporting.
- audit: Schemas for event-sourced audit logs.
"""

from pydantic import BaseModel, ConfigDict

__version__ = "1.0.0"
__author__ = "Prior Auth Pro Team"


class BaseSchema(BaseModel):
    """
    Base Pydantic schema for all API request and response models.
    
    Configuration:
    - from_attributes: Enables reading data directly from SQLAlchemy 2.0 ORM models.
    - populate_by_name: Allows population by field name or alias.
    - str_strip_whitespace: Automatically strips leading/trailing whitespace from strings.
    """
    model_config = ConfigDict(
        from_attributes=True,
        populate_by_name=True,
        str_strip_whitespace=True,
    )

__all__ = ["BaseSchema"]