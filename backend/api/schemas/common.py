import enum
from typing import Generic, List, TypeVar

from pydantic import BaseModel, ConfigDict, Field

T = TypeVar("T")


class AuthTypeEnum(str, enum.Enum):
    """
    Enumeration for types of authorization requests.
    Used for request validation and response serialization.
    Matches the database AuthType enum.
    """
    medication = "medication"
    imaging = "imaging"
    procedure = "procedure"
    dme = "dme"


class PriorityEnum(str, enum.Enum):
    """
    Enumeration for priority levels of authorization requests.
    Used for request validation and response serialization.
    Matches the database PriorityLevel enum.
    """
    urgent = "urgent"
    standard = "standard"


class PaginatedResponse(BaseModel, Generic[T]):
    """
    Generic Pydantic schema for paginated API responses.
    Can be parameterized with any other Pydantic model to represent the items list.
    
    Example:
        response: PaginatedResponse[AuthRequestResponse]
    """
    items: List[T] = Field(
        ..., 
        description="List of items for the current page"
    )
    total: int = Field(
        ..., 
        ge=0, 
        description="Total number of items across all pages"
    )
    page: int = Field(
        ..., 
        ge=1, 
        description="Current page number (1-indexed)"
    )
    size: int = Field(
        ..., 
        ge=1, 
        description="Number of items per page"
    )
    pages: int = Field(
        ..., 
        ge=0, 
        description="Total number of pages available"
    )

    model_config = ConfigDict(
        from_attributes=True,
        populate_by_name=True,
        str_strip_whitespace=True,
    )