import logging
from typing import Any, Dict, Optional

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from core.logging import get_logger

logger = get_logger(__name__)


class PriorAuthException(Exception):
    """
    Base exception class for the Prior Authorization AI Agent.
    All custom exceptions should inherit from this class to ensure
    consistent error handling and API responses.
    """

    def __init__(
        self,
        message: str,
        status_code: int = 500,
        error_code: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        Initialize the base PriorAuthException.

        Args:
            message (str): Human-readable error message.
            status_code (int): HTTP status code to return. Defaults to 500.
            error_code (Optional[str]): Application-specific error code. Defaults to "INTERNAL_SERVER_ERROR".
            details (Optional[Dict[str, Any]]): Additional context or metadata about the error.
        """
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.error_code = error_code or "INTERNAL_SERVER_ERROR"
        self.details = details or {}


class ResourceNotFoundException(PriorAuthException):
    """
    Exception raised when a requested resource (e.g., AuthRequest, Patient, Policy)
    cannot be found in the database or external system.
    """

    def __init__(self, resource_type: str, resource_id: str) -> None:
        """
        Initialize the ResourceNotFoundException.

        Args:
            resource_type (str): The type of resource that was not found (e.g., "AuthRequest").
            resource_id (str): The unique identifier that was queried.
        """
        message = f"{resource_type} with ID '{resource_id}' was not found."
        super().__init__(
            message=message,
            status_code=404,
            error_code="RESOURCE_NOT_FOUND",
            details={
                "resource_type": resource_type,
                "resource_id": resource_id,
            },
        )


class FHIRIntegrationException(PriorAuthException):
    """
    Exception raised when an interaction with the external FHIR server fails.
    This could be due to network issues, invalid payloads, or server errors.
    """

    def __init__(
        self,
        message: str,
        status_code: int = 502,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        Initialize the FHIRIntegrationException.

        Args:
            message (str): Description of the FHIR integration failure.
            status_code (int): HTTP status code. Defaults to 502 (Bad Gateway).
            details (Optional[Dict[str, Any]]): Additional context, such as the FHIR resource or endpoint.
        """
        super().__init__(
            message=message,
            status_code=status_code,
            error_code="FHIR_INTEGRATION_ERROR",
            details=details,
        )


async def prior_auth_exception_handler(
    request: Request, exc: PriorAuthException
) -> JSONResponse:
    """
    Global exception handler for PriorAuthException and its subclasses.
    Logs the error and returns a standardized JSON response to the client.

    Args:
        request (Request): The incoming FastAPI request.
        exc (PriorAuthException): The raised custom exception.

    Returns:
        JSONResponse: A formatted JSON response containing the error details.
    """
    logger.error(
        f"PriorAuthException caught: {exc.message}",
        extra={
            "error_code": exc.error_code,
            "status_code": exc.status_code,
            "details": exc.details,
            "path": request.url.path,
            "method": request.method,
        },
    )

    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": {
                "code": exc.error_code,
                "message": exc.message,
                "details": exc.details,
                "path": request.url.path,
            }
        },
    )


def setup_exception_handlers(app: FastAPI) -> None:
    """
    Register custom exception handlers with the FastAPI application.

    Args:
        app (FastAPI): The FastAPI application instance.
    """
    app.add_exception_handler(PriorAuthException, prior_auth_exception_handler)