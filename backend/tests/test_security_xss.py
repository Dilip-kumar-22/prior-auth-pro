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

XSS_PAYLOADS: List[str] = [
    "<script>alert('xss')</script>",
    "<img src=x onerror=alert(1)>",
    "javascript:alert(1)",
    "'\"><svg/onload=alert(1)>",
    "<iframe src=\"javascript:alert(1)\"></iframe>"
]

UNICODE_PAYLOADS: List[str] = [
    "Task 🚀 Launch",  # Emojis
    "任务管理系统",      # CJK characters
    "مشروع جديد",      # RTL Arabic text
    "Zażółć gęślą jaźń", # Polish diacritics
    "ñáéíóúü"          # Spanish accents
]

NULL_BYTE_PAYLOADS: List[str] = [
    "test\x00byte",
    "\x00",
    "null\u0000byte"
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
# 1. XSS TESTS — AUTH REQUESTS
# ==========================================

@pytest.mark.parametrize("xss_payload", XSS_PAYLOADS)
async def test_xss_payload_in_diagnosis(
    async_client: httpx.AsyncClient, 
    auth_headers: Dict[str, str], 
    xss_payload: str
) -> None:
    """
    Test that XSS payloads in the diagnosis_codes JSONB field are safely handled.
    They should either be stored as literal text (201) or rejected by validation (422).
    """
    payload = {
        "patient_id": str(uuid.uuid4()),
        "auth_type": "medication",
        "service_requested": "MRI Brain",
        "diagnosis_codes": [xss_payload, "E11.9"],
        "payer_id": str(uuid.uuid4()),
        "plan_id": str(uuid.uuid4()),
        "priority": "standard"
    }
    
    response = await async_client.post(
        "/api/v1/auth-requests", 
        json=payload, 
        headers=auth_headers
    )
    
    assert response.status_code in [200, 201, 400, 422]
    assert response.status_code != 500, f"XSS payload '{xss_payload}' caused a 500 Internal Server Error"
    
    if response.status_code in [200, 201]:
        data = response.json()
        assert xss_payload in data["diagnosis_codes"]


@pytest.mark.parametrize("xss_payload", XSS_PAYLOADS)
async def test_xss_in_auth_request_service_requested(
    async_client: httpx.AsyncClient, 
    auth_headers: Dict[str, str], 
    xss_payload: str
) -> None:
    """
    Test that XSS payloads in the service_requested text field are safely handled.
    """
    payload = {
        "patient_id": str(uuid.uuid4()),
        "auth_type": "imaging",
        "service_requested": xss_payload,
        "diagnosis_codes": ["R51"],
        "payer_id": str(uuid.uuid4()),
        "plan_id": str(uuid.uuid4()),
        "priority": "urgent"
    }
    
    response = await async_client.post(
        "/api/v1/auth-requests", 
        json=payload, 
        headers=auth_headers
    )
    
    assert response.status_code in [200, 201, 400, 422]
    assert response.status_code != 500
    
    if response.status_code in [200, 201]:
        data = response.json()
        assert data["service_requested"] == xss_payload


@pytest.mark.parametrize("xss_payload", XSS_PAYLOADS)
async def test_xss_in_auth_request_priority(
    async_client: httpx.AsyncClient, 
    auth_headers: Dict[str, str], 
    xss_payload: str
) -> None:
    """
    Test that XSS payloads in an ENUM field (priority) are strictly rejected with 422.
    """
    payload = {
        "patient_id": str(uuid.uuid4()),
        "auth_type": "medication",
        "service_requested": "Aspirin",
        "diagnosis_codes": ["I10"],
        "payer_id": str(uuid.uuid4()),
        "plan_id": str(uuid.uuid4()),
        "priority": xss_payload
    }
    
    response = await async_client.post(
        "/api/v1/auth-requests", 
        json=payload, 
        headers=auth_headers
    )
    
    assert response.status_code == 422
    assert "priority" in response.json()["detail"][0]["loc"]


# ==========================================
# 2. XSS TESTS — APPEALS
# ==========================================

@pytest.mark.parametrize("xss_payload", XSS_PAYLOADS)
async def test_xss_in_appeal_denial_reason(
    async_client: httpx.AsyncClient, 
    auth_headers: Dict[str, str], 
    xss_payload: str
) -> None:
    """
    Test that XSS payloads in the denial_reason text field are safely handled.
    """
    payload = {
        "auth_request_id": str(uuid.uuid4()),
        "denial_reason": xss_payload,
        "counter_evidence": {"notes": "Valid notes"},
        "appeal_letter": "Valid letter",
        "guidelines_cited": ["MCG-123"]
    }
    
    response = await async_client.post(
        "/api/v1/appeals", 
        json=payload, 
        headers=auth_headers
    )
    
    assert response.status_code in [200, 201, 400, 404, 422]
    assert response.status_code != 500
    
    if response.status_code in [200, 201]:
        data = response.json()
        assert data["denial_reason"] == xss_payload


@pytest.mark.parametrize("xss_payload", XSS_PAYLOADS)
async def test_xss_in_appeal_letter(
    async_client: httpx.AsyncClient, 
    auth_headers: Dict[str, str], 
    xss_payload: str
) -> None:
    """
    Test that XSS payloads in the appeal_letter text field are safely handled.
    """
    payload = {
        "auth_request_id": str(uuid.uuid4()),
        "denial_reason": "Not medically necessary",
        "counter_evidence": {"notes": "Valid notes"},
        "appeal_letter": xss_payload,
        "guidelines_cited": ["MCG-123"]
    }
    
    response = await async_client.post(
        "/api/v1/appeals", 
        json=payload, 
        headers=auth_headers
    )
    
    assert response.status_code in [200, 201, 400, 404, 422]
    assert response.status_code != 500
    
    if response.status_code in [200, 201]:
        data = response.json()
        assert data["appeal_letter"] == xss_payload


# ==========================================
# 3. XSS TESTS — QUERY & PATH PARAMETERS
# ==========================================

@pytest.mark.parametrize("xss_payload", XSS_PAYLOADS)
async def test_xss_in_query_parameters(
    async_client: httpx.AsyncClient, 
    auth_headers: Dict[str, str], 
    xss_payload: str
) -> None:
    """
    Test that XSS payloads in query parameters do not cause 500 errors and are handled safely.
    """
    response = await async_client.get(
        f"/api/v1/auth-requests?search={xss_payload}&patient_id={xss_payload}", 
        headers=auth_headers
    )
    
    assert response.status_code in [200, 400, 422]
    assert response.status_code != 500


@pytest.mark.parametrize("xss_payload", XSS_PAYLOADS)
async def test_xss_in_path_parameters(
    async_client: httpx.AsyncClient, 
    auth_headers: Dict[str, str], 
    xss_payload: str
) -> None:
    """
    Test that XSS payloads in path parameters (expecting UUIDs) are rejected with 422 or 404.
    """
    response = await async_client.get(
        f"/api/v1/auth-requests/{xss_payload}", 
        headers=auth_headers
    )
    
    assert response.status_code in [400, 404, 422]
    assert response.status_code != 500


# ==========================================
# 4. UNICODE & ENCODING TESTS
# ==========================================

@pytest.mark.parametrize("unicode_payload", UNICODE_PAYLOADS)
async def test_unicode_patient_name(
    async_client: httpx.AsyncClient, 
    auth_headers: Dict[str, str], 
    unicode_payload: str
) -> None:
    """
    Test that Unicode characters in string fields (like patient_id if treated as string, 
    or a hypothetical patient_name field) are safely handled and preserved.
    """
    payload = {
        "patient_id": unicode_payload,  # If strict UUID, this will 422. If string, it should 201.
        "auth_type": "procedure",
        "service_requested": "Knee Replacement",
        "diagnosis_codes": ["M17.11"],
        "payer_id": str(uuid.uuid4()),
        "plan_id": str(uuid.uuid4()),
        "priority": "standard"
    }
    
    response = await async_client.post(
        "/api/v1/auth-requests", 
        json=payload, 
        headers=auth_headers
    )
    
    assert response.status_code in [200, 201, 400, 422]
    assert response.status_code != 500
    
    if response.status_code in [200, 201]:
        data = response.json()
        assert data["patient_id"] == unicode_payload


@pytest.mark.parametrize("unicode_payload", UNICODE_PAYLOADS)
async def test_unicode_in_auth_request_service(
    async_client: httpx.AsyncClient, 
    auth_headers: Dict[str, str], 
    unicode_payload: str
) -> None:
    """
    Test that Unicode characters in the service_requested field are preserved correctly.
    """
    payload = {
        "patient_id": str(uuid.uuid4()),
        "auth_type": "dme",
        "service_requested": unicode_payload,
        "diagnosis_codes": ["G47.33"],
        "payer_id": str(uuid.uuid4()),
        "plan_id": str(uuid.uuid4()),
        "priority": "standard"
    }
    
    response = await async_client.post(
        "/api/v1/auth-requests", 
        json=payload, 
        headers=auth_headers
    )
    
    assert response.status_code in [200, 201, 400, 422]
    assert response.status_code != 500
    
    if response.status_code in [200, 201]:
        data = response.json()
        assert data["service_requested"] == unicode_payload


@pytest.mark.parametrize("unicode_payload", UNICODE_PAYLOADS)
async def test_unicode_in_appeal_letter(
    async_client: httpx.AsyncClient, 
    auth_headers: Dict[str, str], 
    unicode_payload: str
) -> None:
    """
    Test that Unicode characters in the appeal_letter field are preserved correctly.
    """
    payload = {
        "auth_request_id": str(uuid.uuid4()),
        "denial_reason": "Lack of documentation",
        "counter_evidence": {"notes": "Attached"},
        "appeal_letter": unicode_payload,
        "guidelines_cited": ["MCG-456"]
    }
    
    response = await async_client.post(
        "/api/v1/appeals", 
        json=payload, 
        headers=auth_headers
    )
    
    assert response.status_code in [200, 201, 400, 404, 422]
    assert response.status_code != 500
    
    if response.status_code in [200, 201]:
        data = response.json()
        assert data["appeal_letter"] == unicode_payload


@pytest.mark.parametrize("unicode_payload", UNICODE_PAYLOADS)
async def test_cjk_characters_in_diagnosis_codes(
    async_client: httpx.AsyncClient, 
    auth_headers: Dict[str, str], 
    unicode_payload: str
) -> None:
    """
    Test that CJK and other Unicode characters in JSONB arrays are preserved correctly.
    """
    payload = {
        "patient_id": str(uuid.uuid4()),
        "auth_type": "medication",
        "service_requested": "Insulin",
        "diagnosis_codes": [unicode_payload, "E11.9"],
        "payer_id": str(uuid.uuid4()),
        "plan_id": str(uuid.uuid4()),
        "priority": "standard"
    }
    
    response = await async_client.post(
        "/api/v1/auth-requests", 
        json=payload, 
        headers=auth_headers
    )
    
    assert response.status_code in [200, 201, 400, 422]
    assert response.status_code != 500
    
    if response.status_code in [200, 201]:
        data = response.json()
        assert unicode_payload in data["diagnosis_codes"]


@pytest.mark.parametrize("unicode_payload", UNICODE_PAYLOADS)
async def test_rtl_arabic_in_counter_evidence(
    async_client: httpx.AsyncClient, 
    auth_headers: Dict[str, str], 
    unicode_payload: str
) -> None:
    """
    Test that RTL Arabic and other Unicode characters in JSONB objects are preserved correctly.
    """
    payload = {
        "auth_request_id": str(uuid.uuid4()),
        "denial_reason": "Experimental",
        "counter_evidence": {"physician_notes": unicode_payload},
        "appeal_letter": "Standard letter",
        "guidelines_cited": ["NCCN"]
    }
    
    response = await async_client.post(
        "/api/v1/appeals", 
        json=payload, 
        headers=auth_headers
    )
    
    assert response.status_code in [200, 201, 400, 404, 422]
    assert response.status_code != 500
    
    if response.status_code in [200, 201]:
        data = response.json()
        assert data["counter_evidence"]["physician_notes"] == unicode_payload


@pytest.mark.parametrize("unicode_payload", UNICODE_PAYLOADS)
async def test_unicode_in_query_parameters(
    async_client: httpx.AsyncClient, 
    auth_headers: Dict[str, str], 
    unicode_payload: str
) -> None:
    """
    Test that Unicode characters in query parameters are handled safely.
    """
    response = await async_client.get(
        f"/api/v1/auth-requests?search={unicode_payload}", 
        headers=auth_headers
    )
    
    assert response.status_code in [200, 400, 422]
    assert response.status_code != 500


# ==========================================
# 5. NULL BYTE TESTS
# ==========================================

@pytest.mark.parametrize("null_byte_payload", NULL_BYTE_PAYLOADS)
async def test_null_byte_in_auth_request_body(
    async_client: httpx.AsyncClient, 
    auth_headers: Dict[str, str], 
    null_byte_payload: str
) -> None:
    """
    Test that null bytes in request bodies are rejected cleanly (usually 422 by Pydantic/FastAPI)
    and do not cause 500 Internal Server Errors at the database level.
    """
    payload = {
        "patient_id": str(uuid.uuid4()),
        "auth_type": "medication",
        "service_requested": null_byte_payload,
        "diagnosis_codes": ["I10"],
        "payer_id": str(uuid.uuid4()),
        "plan_id": str(uuid.uuid4()),
        "priority": "standard"
    }
    
    response = await async_client.post(
        "/api/v1/auth-requests", 
        json=payload, 
        headers=auth_headers
    )
    
    # Pydantic v2 strictly rejects null bytes in strings by default
    assert response.status_code in [400, 422]
    assert response.status_code != 500
    
    if response.status_code == 422:
        assert "service_requested" in response.json()["detail"][0]["loc"]


@pytest.mark.parametrize("null_byte_payload", NULL_BYTE_PAYLOADS)
async def test_null_byte_in_appeal_body(
    async_client: httpx.AsyncClient, 
    auth_headers: Dict[str, str], 
    null_byte_payload: str
) -> None:
    """
    Test that null bytes in appeal request bodies are rejected cleanly.
    """
    payload = {
        "auth_request_id": str(uuid.uuid4()),
        "denial_reason": null_byte_payload,
        "counter_evidence": {"notes": "Valid"},
        "appeal_letter": "Valid",
        "guidelines_cited": ["MCG-123"]
    }
    
    response = await async_client.post(
        "/api/v1/appeals", 
        json=payload, 
        headers=auth_headers
    )
    
    assert response.status_code in [400, 422]
    assert response.status_code != 500
    
    if response.status_code == 422:
        assert "denial_reason" in response.json()["detail"][0]["loc"]