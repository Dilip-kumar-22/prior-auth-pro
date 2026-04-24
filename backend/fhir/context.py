import os
from typing import Any, AsyncGenerator, Mapping, Optional, Union

from fastapi import Request

from fhir.client import FHIRClient


def client_from_session(state: Union[Mapping[str, Any], Any]) -> FHIRClient:
    """
    Builds and returns a FHIRClient instance from the provided session state.
    
    This function is designed to work with both dictionary-like states (e.g., ARQ worker 
    context) and object-like states (e.g., FastAPI request.app.state). It falls 
    back to environment variables if specific configuration is not found in the state.

    Args:
        state (Union[Mapping[str, Any], Any]): The session state containing 
            configuration variables such as 'fhir_base_url', 'fhir_token', and 'fhir_timeout'.

    Returns:
        FHIRClient: A configured instance of the async FHIR client.
    """
    def _get_val(key: str, default: Any = None) -> Any:
        if isinstance(state, Mapping):
            return state.get(key, default)
        return getattr(state, key, default)

    base_url = _get_val("fhir_base_url") or os.environ.get("FHIR_BASE_URL", "http://localhost:8080/fhir")
    token = _get_val("fhir_token") or os.environ.get("FHIR_TOKEN")
    
    raw_timeout = _get_val("fhir_timeout") or os.environ.get("FHIR_TIMEOUT", "30.0")
    try:
        timeout = float(raw_timeout)
    except (ValueError, TypeError):
        timeout = 30.0

    return FHIRClient(base_url=base_url, token=token, timeout=timeout)


async def get_fhir_client(request: Request) -> AsyncGenerator[FHIRClient, None]:
    """
    FastAPI dependency for injecting a FHIRClient into route handlers.
    
    Extracts configuration from the FastAPI application state and ensures
    the client's underlying HTTP connections are properly closed after the 
    request completes.

    Args:
        request (Request): The incoming FastAPI request.

    Yields:
        FHIRClient: An active FHIR client instance ready for use.
    """
    app_state = getattr(request.app.state, "fhir_config", {})
    client = client_from_session(app_state)
    
    try:
        yield client
    finally:
        await client.close()