"""
FHIR Client module for Prior Authorization AI Agent.

This package provides an asynchronous FHIR R4 REST client using httpx,
resource parsers for extracting structured clinical data from raw FHIR JSON,
and context management for dependency injection within the FastAPI application.

Modules:
- client: Async FHIR R4 REST client for interacting with external FHIR servers.
- resources: Parsers and extractors for FHIR resources (Patient, Condition, etc.).
- context: Context builders and dependency injection utilities.
"""

__version__ = "1.0.0"
__author__ = "Prior Auth Pro Team"