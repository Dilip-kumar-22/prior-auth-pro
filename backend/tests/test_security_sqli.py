import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import AsyncGenerator, Dict, List

import httpx
import pytest
from jose import jwt

from api.main import app

pytestmark = pytest.mark.asyncio

# ==========================================
# CONSTANTS & CONFIGURATION
# ==========================================

SECRET_KEY = os.environ.get("SECRET_KEY", "test_super_secret_key_for_jwt_generation_12345")
ALGORITHM = "HS256"

# 5 distinct SQL Injection payloads to test against each endpoint
SQLI_PAYLOADS: List[str] = [
    "admin' OR '1'='1",
    "'; DROP TABLE users;--",
    "admin\" OR \"1\"=\"1\"",
    "' UNION SELECT 1,2,3--",
    "1; UPDATE users SET role='admin'"
]

# ==========================================
# FIXTURES
# ==========================================

@pytest.fixture
async def async_client() -> AsyncGenerator[httpx.AsyncClient, None]:
    """
    Provide an asynchronous test client for the FastAPI application.
    Uses ASGITransport to communicate directly with the app without a running server.
    """
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client


@pytest.fixture
def valid_admin_token() -> str:
    """Provide a valid JWT token for a user with 'admin' role to bypass auth blocks."""
    expire = datetime.now(timezone.utc) + timedelta(minutes=15)
    payload = {
        "sub": str(uuid.uuid4()),
        "role": "admin",
        "type": "access",
        "exp": expire
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


@pytest.fixture
def auth_headers(valid_admin_token: str) -> Dict[str, str]:
    """Provide standard Authorization headers using the valid admin token."""
    return {"Authorization": f"Bearer {valid_admin_token}"}


# ==========================================
# 1. AUTH REQUEST LIST ENDPOINT (GET)
# ==========================================

@pytest.mark.parametrize("sqli_payload", SQLI_PAYLOADS)
async def test_sqli_auth_request_list_patient_id(
    async_client: httpx.AsyncClient, 
    auth_headers: Dict[str, str], 
    sqli_payload: str
) -> None:
    """
    Test that SQL injection payloads in the 'patient_id' query parameter 
    for the Auth Request list endpoint are safely handled (422 or 404, never 500).
    """
    response = await async_client.get(
        f"/api/v1/auth-requests?patient_id={sqli_payload}", 
        headers=auth_headers
    )
    
    # Pydantic should catch invalid UUIDs (422), or if it's a string field, 
    # SQLAlchemy should parameterize it resulting in no matches (200 empty list or 404).
    assert response.status_code in [200, 400, 404, 422]
    assert response.status_code != 500, f"SQLi payload '{sqli_payload}' caused a 500 Internal Server Error"


@pytest.mark.parametrize("sqli_payload", SQLI_PAYLOADS)
async def test_sqli_auth_request_list_priority(
    async_client: httpx.AsyncClient, 
    auth_headers: Dict[str, str], 
    sqli_payload: str
) -> None:
    """
    Test that SQL injection payloads in the 'priority' query parameter 
    (an ENUM field) are safely handled.
    """
    response = await async_client.get(
        f"/api/v1/auth-requests?priority={sqli_payload}", 
        headers=auth_headers
    )
    
    # Pydantic should reject invalid enum values with 422
    assert response.status_code in [400, 422]
    assert response.status_code != 500, f"SQLi payload '{sqli_payload}' caused a 500 Internal Server Error"


@pytest.mark.parametrize("sqli_payload", SQLI_PAYLOADS)
async def test_sqli_auth_request_list(
    async_client: httpx.AsyncClient, 
    auth_headers: Dict[str, str], 
    sqli_payload: str
) -> None:
    """
    Test that SQL injection payloads in general search/filter query parameters 
    are safely handled by the list endpoint.
    """
    response = await async_client.get(
        f"/api/v1/auth-requests?search={sqli_payload}&sort_by={sqli_payload}", 
        headers=auth_headers
    )
    
    assert response.status_code in [200, 400, 404, 422]
    assert response.status_code != 500, f"SQLi payload '{sqli_payload}' caused a 500 Internal Server Error"


# ==========================================
# 2. APPEAL GET ENDPOINT (GET)
# ==========================================

@pytest.mark.parametrize("sqli_payload", SQLI_PAYLOADS)
async def test_sqli_appeal_get(
    async_client: httpx.AsyncClient, 
    auth_headers: Dict[str, str], 
    sqli_payload: str
) -> None:
    """
    Test that SQL injection payloads in the path parameter 'id' for the 
    Appeal GET endpoint are safely handled.
    """
    response = await async_client.get(
        f"/api/v1/appeals/{sqli_payload}", 
        headers=auth_headers
    )
    
    # Path parameter 'id' is expected to be a UUID. Pydantic/FastAPI should return 422.
    # If defined as string, SQLAlchemy will parameterize and return 404.
    assert response.status_code in [400, 404, 422]
    assert response.status_code != 500, f"SQLi payload '{sqli_payload}' caused a 500 Internal Server Error"


# ==========================================
# 3. AUTH REQUEST GET ENDPOINT (GET)
# ==========================================

@pytest.mark.parametrize("sqli_payload", SQLI_PAYLOADS)
async def test_sqli_auth_request_get_id(
    async_client: httpx.AsyncClient, 
    auth_headers: Dict[str, str], 
    sqli_payload: str
) -> None:
    """
    Test that SQL injection payloads in the path parameter 'id' for the 
    Auth Request GET endpoint are safely handled.
    """
    response = await async_client.get(
        f"/api/v1/auth-requests/{sqli_payload}", 
        headers=auth_headers
    )
    
    assert response.status_code in [400, 404, 422]
    assert response.status_code != 500, f"SQLi payload '{sqli_payload}' caused a 500 Internal Server Error"


@pytest.mark.parametrize("sqli_payload", SQLI_PAYLOADS)
async def test_sqli_auth_request_get_events(
    async_client: httpx.AsyncClient, 
    auth_headers: Dict[str, str], 
    sqli_payload: str
) -> None:
    """
    Test that SQL injection payloads in the path parameter 'id' for the 
    Auth Request Events GET endpoint are safely handled.
    """
    response = await async_client.get(
        f"/api/v1/auth-requests/{sqli_payload}/events", 
        headers=auth_headers
    )
    
    assert response.status_code in [400, 404, 422]
    assert response.status_code != 500, f"SQLi payload '{sqli_payload}' caused a 500 Internal Server Error"


# ==========================================
# 4. AUTH REQUEST CREATE ENDPOINT (POST)
# ==========================================

@pytest.mark.parametrize("sqli_payload", SQLI_PAYLOADS)
async def test_sqli_auth_request_create_body(
    async_client: httpx.AsyncClient, 
    auth_headers: Dict[str, str], 
    sqli_payload: str
) -> None:
    """
    Test that SQL injection payloads in the JSON body for creating an 
    Auth Request are safely handled (parameterized by SQLAlchemy or rejected by Pydantic).
    """
    payload = {
        "patient_id": sqli_payload,
        "auth_type": "medication",
        "service_requested": sqli_payload,
        "diagnosis_codes": [sqli_payload, "E11.9"],
        "payer_id": str(uuid.uuid4()),
        "plan_id": str(uuid.uuid4()),
        "priority": "standard"
    }
    
    response = await async_client.post(
        "/api/v1/auth-requests", 
        json=payload, 
        headers=auth_headers
    )
    
    # If patient_id is a UUID, Pydantic returns 422.
    # If it's a string, SQLAlchemy parameterizes it and it might succeed (201) 
    # or fail due to foreign key constraints (400/404/422).
    assert response.status_code in [200, 201, 400, 404, 409, 422]
    assert response.status_code != 500, f"SQLi payload '{sqli_payload}' caused a 500 Internal Server Error"


# ==========================================
# 5. APPEAL CREATE ENDPOINT (POST)
# ==========================================

@pytest.mark.parametrize("sqli_payload", SQLI_PAYLOADS)
async def test_sqli_appeal_create_body(
    async_client: httpx.AsyncClient, 
    auth_headers: Dict[str, str], 
    sqli_payload: str
) -> None:
    """
    Test that SQL injection payloads in the JSON body for creating an 
    Appeal are safely handled. Text fields should store the payload literally.
    """
    payload = {
        "auth_request_id": str(uuid.uuid4()),
        "denial_reason": sqli_payload,
        "counter_evidence": {"notes": sqli_payload},
        "appeal_letter": sqli_payload,
        "guidelines_cited": [sqli_payload]
    }
    
    response = await async_client.post(
        "/api/v1/appeals", 
        json=payload, 
        headers=auth_headers
    )
    
    # Text fields storing SQLi payloads should succeed (201) because SQLAlchemy 
    # safely parameterizes strings, preventing execution. If auth_request_id FK fails, 400/404/422.
    assert response.status_code in [200, 201, 400, 404, 422]
    assert response.status_code != 500, f"SQLi payload '{sqli_payload}' caused a 500 Internal Server Error"
    
    # If it succeeded, verify the payload was stored as literal text, not executed
    if response.status_code in [200, 201]:
        data = response.json()
        assert data["denial_reason"] == sqli_payload
        assert data["appeal_letter"] == sqli_payload