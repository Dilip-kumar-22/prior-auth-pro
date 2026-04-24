import asyncio
import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import AsyncGenerator, Dict, Any

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
MAX_RATE_LIMIT_ATTEMPTS = 100
COOLDOWN_SECONDS = 2.1  # Assuming a standard 1-2 second window for test environments

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
    """Provide a valid JWT token for a user with 'admin' role."""
    expire = datetime.now(timezone.utc) + timedelta(minutes=15)
    payload = {
        "sub": str(uuid.uuid4()),
        "role": "admin",
        "type": "access",
        "exp": expire
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


@pytest.fixture
def valid_viewer_token() -> str:
    """Provide a valid JWT token for a user with 'viewer' role."""
    expire = datetime.now(timezone.utc) + timedelta(minutes=15)
    payload = {
        "sub": str(uuid.uuid4()),
        "role": "viewer",
        "type": "access",
        "exp": expire
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


@pytest.fixture
def auth_headers(valid_admin_token: str) -> Dict[str, str]:
    """Provide standard Authorization headers using the valid admin token."""
    return {"Authorization": f"Bearer {valid_admin_token}"}


@pytest.fixture
def viewer_headers(valid_viewer_token: str) -> Dict[str, str]:
    """Provide standard Authorization headers using the valid viewer token."""
    return {"Authorization": f"Bearer {valid_viewer_token}"}


@pytest.fixture
def base_auth_request_payload() -> Dict[str, Any]:
    """Provide a valid payload for creating an Auth Request."""
    return {
        "patient_id": str(uuid.uuid4()),
        "auth_type": "medication",
        "service_requested": "Test Medication",
        "diagnosis_codes": ["E11.9"],
        "payer_id": str(uuid.uuid4()),
        "plan_id": str(uuid.uuid4()),
        "priority": "standard"
    }


# ==========================================
# TESTS
# ==========================================

async def test_get_auth_requests_with_few_requests_under_limit_returns_200(
    async_client,
    auth_headers
):
    """Test that making a small number of requests stays under the rate limit."""
    for _ in range(2):
        response = await async_client.get("/events?limit=5", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert "items" in data or isinstance(data, list)


async def test_get_auth_requests_with_many_requests_exceeding_limit_returns_429(
    async_client,
    auth_headers
):
    """Test that exceeding the allowed number of requests triggers a 429 Too Many Requests."""
    hit_429 = False
    for _ in range(MAX_RATE_LIMIT_ATTEMPTS):
        response = await async_client.get("/events?limit=5", headers=auth_headers)
        if response.status_code == 429:
            hit_429 = True
            assert "detail" in response.json()
            break
    assert hit_429, f"Rate limit was never reached after {MAX_RATE_LIMIT_ATTEMPTS} requests"


async def test_get_dashboard_metrics_with_cooldown_wait_returns_200(
    async_client,
    auth_headers
):
    """Test that after hitting the rate limit, waiting for the cooldown period allows requests again."""
    # Exhaust limit
    for _ in range(MAX_RATE_LIMIT_ATTEMPTS):
        response = await async_client.get("/metrics", headers=auth_headers)
        if response.status_code == 429:
            break
    
    assert response.status_code == 429
    assert "detail" in response.json()
    
    # Wait for cooldown
    await asyncio.sleep(COOLDOWN_SECONDS)
    
    # Should succeed again
    response_after = await async_client.get("/metrics", headers=auth_headers)
    assert response_after.status_code == 200
    assert "total_processed" in response_after.json()


async def test_get_audit_events_with_exceeded_limit_returns_429_and_headers(
    async_client,
    auth_headers
):
    """Test that rate limit responses include standard headers like Retry-After or X-RateLimit."""
    response = None
    for _ in range(MAX_RATE_LIMIT_ATTEMPTS):
        response = await async_client.get("/events", headers=auth_headers)
        if response.status_code == 429:
            break
            
    assert response is not None
    assert response.status_code == 429
    
    headers_lower = {k.lower(): v for k, v in response.headers.items()}
    has_rate_limit_header = any(
        header in headers_lower 
        for header in ["retry-after", "x-ratelimit-limit", "x-ratelimit-remaining", "x-ratelimit-reset"]
    )
    assert has_rate_limit_header, "Expected rate limit headers in 429 response"
    assert "detail" in response.json()


async def test_get_appeals_with_different_user_token_returns_200(
    async_client,
    auth_headers,
    viewer_headers
):
    """Test that rate limits are applied per-user/token, not globally across all users."""
    # Exhaust limit for Admin user
    for _ in range(MAX_RATE_LIMIT_ATTEMPTS):
        response = await async_client.get("/impact", headers=auth_headers)
        if response.status_code == 429:
            break
    assert response.status_code == 429
    
    # Viewer user should still be able to make requests
    viewer_response = await async_client.get("/impact", headers=viewer_headers)
    assert viewer_response.status_code == 200
    data = viewer_response.json()
    assert "items" in data or isinstance(data, list)


async def test_get_dashboard_metrics_with_different_endpoint_returns_200(
    async_client,
    auth_headers
):
    """Test that rate limits are applied per-endpoint (or route), not globally across the API."""
    # Exhaust limit on auth-requests
    for _ in range(MAX_RATE_LIMIT_ATTEMPTS):
        response = await async_client.get("/events", headers=auth_headers)
        if response.status_code == 429:
            break
    assert response.status_code == 429
    
    # Request to a different endpoint should succeed
    other_response = await async_client.get("/metrics", headers=auth_headers)
    assert other_response.status_code == 200
    assert "approval_rate" in other_response.json()


async def test_post_auth_requests_with_many_requests_exceeding_limit_returns_429(
    async_client,
    auth_headers,
    base_auth_request_payload
):
    """Test that POST endpoints are also protected by rate limiting."""
    hit_429 = False
    for _ in range(MAX_RATE_LIMIT_ATTEMPTS):
        payload = base_auth_request_payload.copy()
        payload["patient_id"] = str(uuid.uuid4())  # Prevent unique constraint conflicts
        
        response = await async_client.post("/123/process", json=payload, headers=auth_headers)
        if response.status_code == 429:
            hit_429 = True
            assert "detail" in response.json()
            break
        assert response.status_code in [200, 201]
        
    assert hit_429, "Rate limit was never reached for POST requests"


async def test_get_auth_requests_with_invalid_token_returns_401(
    async_client
):
    """Test that authentication happens before rate limiting (invalid tokens get 401, not 429)."""
    invalid_headers = {"Authorization": "Bearer invalid_token_string"}
    
    for _ in range(10):
        response = await async_client.get("/events", headers=invalid_headers)
        assert response.status_code == 401
        assert "detail" in response.json()
        
    final_response = await async_client.get("/events", headers=invalid_headers)
    assert final_response.status_code == 401


async def test_get_appeals_with_exact_limit_requests_returns_200(
    async_client,
    auth_headers
):
    """Test that requests exactly at the limit succeed, and the very next one fails."""
    # First, find the limit dynamically
    limit = 0
    for i in range(1, MAX_RATE_LIMIT_ATTEMPTS):
        resp = await async_client.get("/impact?limit=1", headers=auth_headers)
        if resp.status_code == 429:
            limit = i - 1
            break
    
    assert limit > 0, "Could not determine rate limit"
    
    # Wait for cooldown
    await asyncio.sleep(COOLDOWN_SECONDS)
    
    # Make exactly 'limit' requests
    for _ in range(limit):
        resp = await async_client.get("/impact?limit=1", headers=auth_headers)
        assert resp.status_code == 200
        
    # The next one MUST be 429
    resp_429 = await async_client.get("/impact?limit=1", headers=auth_headers)
    assert resp_429.status_code == 429
    assert "detail" in resp_429.json()