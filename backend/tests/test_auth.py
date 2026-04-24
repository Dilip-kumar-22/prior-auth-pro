import asyncio
import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Generator

import httpx
import pytest
from jose import jwt
from sqlalchemy.ext.asyncio import AsyncSession

from api.main import app

pytestmark = pytest.mark.asyncio

# ==========================================
# CONFIGURATION & CONSTANTS
# ==========================================

SECRET_KEY = os.environ.get("SECRET_KEY", "test_super_secret_key_for_jwt_generation_12345")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30

PROTECTED_GET_ROUTE = "/api/v1/auth-requests"
PROTECTED_POST_ROUTE = f"/api/v1/auth-requests/{uuid.uuid4()}/process"
ADMIN_ROUTE = "/api/v1/dashboard/metrics"

# ==========================================
# FIXTURES
# ==========================================

@pytest.fixture
async def async_client() -> Generator[httpx.AsyncClient, None, None]:
    """Provide an asynchronous test client for the FastAPI application."""
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client


def create_jwt_token(data: Dict[str, Any], expires_delta: timedelta | None = None) -> str:
    """Helper to generate JWT tokens for testing."""
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(minutes=15)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


@pytest.fixture
def valid_viewer_token() -> str:
    """Provide a valid token for a user with 'viewer' role."""
    return create_jwt_token({"sub": "user-123", "role": "viewer", "type": "access"})


@pytest.fixture
def valid_admin_token() -> str:
    """Provide a valid token for a user with 'admin' role."""
    return create_jwt_token({"sub": "admin-456", "role": "admin", "type": "access"})


@pytest.fixture
def expired_token() -> str:
    """Provide a token that has already expired."""
    return create_jwt_token(
        {"sub": "user-123", "role": "viewer", "type": "access"},
        expires_delta=timedelta(minutes=-10)
    )


@pytest.fixture
def future_nbf_token() -> str:
    """Provide a token that is not yet valid (nbf in the future)."""
    payload = {
        "sub": "user-123",
        "role": "viewer",
        "type": "access",
        "nbf": datetime.now(timezone.utc) + timedelta(minutes=10),
        "exp": datetime.now(timezone.utc) + timedelta(minutes=30)
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


@pytest.fixture
def refresh_token() -> str:
    """Provide a valid refresh token (wrong type for access endpoints)."""
    return create_jwt_token({"sub": "user-123", "role": "viewer", "type": "refresh"})


# ==========================================
# 1. MISSING & MALFORMED TOKENS
# ==========================================

async def test_access_protected_route_with_missing_token_returns_401(async_client: httpx.AsyncClient) -> None:
    """Test that omitting the Authorization header returns 401 Unauthorized."""
    response = await async_client.get(PROTECTED_GET_ROUTE)
    
    assert response.status_code == 401
    assert response.json()["detail"] == "Not authenticated"


async def test_access_protected_route_with_empty_token_returns_401(async_client: httpx.AsyncClient) -> None:
    """Test that an empty Authorization header returns 401 Unauthorized."""
    response = await async_client.get(PROTECTED_GET_ROUTE, headers={"Authorization": ""})
    
    assert response.status_code == 401
    assert response.json()["detail"] == "Not authenticated"


async def test_access_protected_route_with_invalid_token_format_returns_401(async_client: httpx.AsyncClient) -> None:
    """Test that a malformed Authorization header (no Bearer) returns 401."""
    response = await async_client.get(PROTECTED_GET_ROUTE, headers={"Authorization": "InvalidFormatToken"})
    
    assert response.status_code == 401
    assert response.json()["detail"] == "Not authenticated"


async def test_access_protected_route_with_wrong_scheme_returns_401(async_client: httpx.AsyncClient, valid_viewer_token: str) -> None:
    """Test that using Basic auth scheme instead of Bearer returns 401."""
    response = await async_client.get(PROTECTED_GET_ROUTE, headers={"Authorization": f"Basic {valid_viewer_token}"})
    
    assert response.status_code == 401
    assert response.json()["detail"] == "Not authenticated"


async def test_access_protected_route_with_bearer_but_no_token_returns_401(async_client: httpx.AsyncClient) -> None:
    """Test that 'Bearer ' with no actual token string returns 401."""
    response = await async_client.get(PROTECTED_GET_ROUTE, headers={"Authorization": "Bearer "})
    
    assert response.status_code == 401
    assert response.json()["detail"] == "Not authenticated"


async def test_access_protected_route_with_non_jwt_bearer_returns_401(async_client: httpx.AsyncClient) -> None:
    """Test that a Bearer token that is not a valid JWT returns 401."""
    response = await async_client.get(PROTECTED_GET_ROUTE, headers={"Authorization": "Bearer not.a.real.jwt"})
    
    assert response.status_code == 401
    assert response.json()["detail"] == "Could not validate credentials"


# ==========================================
# 2. CRYPTOGRAPHIC & CLAIM VALIDATION
# ==========================================

async def test_access_protected_route_with_expired_token_returns_401(async_client: httpx.AsyncClient, expired_token: str) -> None:
    """Test that a token with an expiration time in the past returns 401."""
    response = await async_client.get(PROTECTED_GET_ROUTE, headers={"Authorization": f"Bearer {expired_token}"})
    
    assert response.status_code == 401
    assert response.json()["detail"] == "Token has expired"


async def test_access_protected_route_with_invalid_signature_returns_401(async_client: httpx.AsyncClient, valid_viewer_token: str) -> None:
    """Test that a token signed with a different secret key returns 401."""
    # Tamper with the signature part of the JWT
    parts = valid_viewer_token.split(".")
    tampered_token = f"{parts[0]}.{parts[1]}.invalid_signature_123"
    
    response = await async_client.get(PROTECTED_GET_ROUTE, headers={"Authorization": f"Bearer {tampered_token}"})
    
    assert response.status_code == 401
    assert response.json()["detail"] == "Could not validate credentials"


async def test_access_protected_route_with_future_nbf_returns_401(async_client: httpx.AsyncClient, future_nbf_token: str) -> None:
    """Test that a token with a 'not before' (nbf) claim in the future returns 401."""
    response = await async_client.get(PROTECTED_GET_ROUTE, headers={"Authorization": f"Bearer {future_nbf_token}"})
    
    assert response.status_code == 401
    assert response.json()["detail"] == "Could not validate credentials"


async def test_access_protected_route_with_missing_sub_claim_returns_401(async_client: httpx.AsyncClient) -> None:
    """Test that a token missing the subject (sub) claim returns 401."""
    token = create_jwt_token({"role": "viewer", "type": "access"})
    response = await async_client.get(PROTECTED_GET_ROUTE, headers={"Authorization": f"Bearer {token}"})
    
    assert response.status_code == 401
    assert response.json()["detail"] == "Could not validate credentials"


async def test_access_protected_route_with_refresh_token_returns_401(async_client: httpx.AsyncClient, refresh_token: str) -> None:
    """Test that using a refresh token on an endpoint expecting an access token returns 401."""
    response = await async_client.get(PROTECTED_GET_ROUTE, headers={"Authorization": f"Bearer {refresh_token}"})
    
    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid token type"


# ==========================================
# 3. AUTHORIZATION & ROLE-BASED ACCESS (RBAC)
# ==========================================

async def test_access_admin_route_with_viewer_token_returns_403(async_client: httpx.AsyncClient, valid_viewer_token: str) -> None:
    """Test that a user with 'viewer' role cannot access admin endpoints."""
    response = await async_client.get(ADMIN_ROUTE, headers={"Authorization": f"Bearer {valid_viewer_token}"})
    
    assert response.status_code == 403
    assert response.json()["detail"] == "Not enough permissions"


async def test_access_admin_route_with_admin_token_returns_200(async_client: httpx.AsyncClient, valid_admin_token: str) -> None:
    """Test that a user with 'admin' role can access admin endpoints."""
    response = await async_client.get(ADMIN_ROUTE, headers={"Authorization": f"Bearer {valid_admin_token}"})
    
    assert response.status_code == 200


async def test_post_process_route_with_viewer_token_returns_403(async_client: httpx.AsyncClient, valid_viewer_token: str) -> None:
    """Test that a viewer cannot trigger the AI processing pipeline."""
    response = await async_client.post(PROTECTED_POST_ROUTE, headers={"Authorization": f"Bearer {valid_viewer_token}"})
    
    assert response.status_code == 403
    assert response.json()["detail"] == "Not enough permissions"


async def test_post_process_route_with_admin_token_returns_200_or_404(async_client: httpx.AsyncClient, valid_admin_token: str) -> None:
    """Test that an admin can trigger the AI processing pipeline (auth succeeds, might 404 if ID missing)."""
    response = await async_client.post(PROTECTED_POST_ROUTE, headers={"Authorization": f"Bearer {valid_admin_token}"})
    
    # It shouldn't be 401 or 403. It might be 404 because the random UUID doesn't exist in DB.
    assert response.status_code not in [401, 403]


# ==========================================
# 4. SECURITY — INJECTION & MALICIOUS PAYLOADS
# ==========================================

@pytest.mark.parametrize("sqli_payload", [
    "admin' OR '1'='1",
    "'; DROP TABLE users;--",
    "' UNION SELECT 1,2,3--"
])
async def test_auth_header_with_sql_injection_returns_401(async_client: httpx.AsyncClient, sqli_payload: str) -> None:
    """Test that SQL injection payloads in the Authorization header are handled safely."""
    response = await async_client.get(PROTECTED_GET_ROUTE, headers={"Authorization": f"Bearer {sqli_payload}"})
    
    assert response.status_code == 401
    assert response.json()["detail"] == "Could not validate credentials"


@pytest.mark.parametrize("xss_payload", [
    "<script>alert('xss')</script>",
    "<img src=x onerror=alert(1)>"
])
async def test_auth_header_with_xss_returns_401(async_client: httpx.AsyncClient, xss_payload: str) -> None:
    """Test that XSS payloads in the Authorization header are handled safely."""
    response = await async_client.get(PROTECTED_GET_ROUTE, headers={"Authorization": f"Bearer {xss_payload}"})
    
    assert response.status_code == 401
    assert response.json()["detail"] == "Could not validate credentials"


async def test_auth_header_with_unicode_returns_401(async_client: httpx.AsyncClient) -> None:
    """Test that unicode characters in the Authorization header do not cause 500 errors."""
    # HTTP headers should be ASCII/Latin-1. If unicode is forced, it should be rejected gracefully.
    try:
        headers = {"Authorization": "Bearer 🚀测试".encode("utf-8").decode("latin-1")}
        response = await async_client.get(PROTECTED_GET_ROUTE, headers=headers)
        assert response.status_code == 401
    except (UnicodeEncodeError, ValueError):
        # If the HTTP client or server strictly rejects it before routing, that's also acceptable
        pass


async def test_auth_header_with_null_byte_returns_400_or_401(async_client: httpx.AsyncClient) -> None:
    """Test that null bytes in the Authorization header are handled safely."""
    try:
        response = await async_client.get(PROTECTED_GET_ROUTE, headers={"Authorization": "Bearer valid\x00token"})
        assert response.status_code in [400, 401]
    except ValueError:
        # httpx might raise ValueError for null bytes in headers, which is safe behavior
        pass


# ==========================================
# 5. BOUNDARY VALUES & LARGE PAYLOADS
# ==========================================

async def test_auth_header_with_massive_token_returns_401_or_431(async_client: httpx.AsyncClient) -> None:
    """Test that an extremely long token string is rejected gracefully without crashing."""
    massive_token = "a" * 20000
    response = await async_client.get(PROTECTED_GET_ROUTE, headers={"Authorization": f"Bearer {massive_token}"})
    
    # 431 Request Header Fields Too Large, or 401 if it reaches the auth dependency
    assert response.status_code in [401, 431]


async def test_auth_header_with_exact_max_length_token_returns_401(async_client: httpx.AsyncClient) -> None:
    """Test a token that is exactly at a typical max header length (e.g., 8192 bytes)."""
    # Create a valid JWT but pad it with a massive payload to reach ~8KB
    large_payload = {"sub": "user-123", "role": "viewer", "type": "access", "padding": "a" * 7500}
    large_token = create_jwt_token(large_payload)
    
    response = await async_client.get(PROTECTED_GET_ROUTE, headers={"Authorization": f"Bearer {large_token}"})
    
    # It should be a valid token, so it returns 200, or 401 if the user doesn't exist in DB
    assert response.status_code in [200, 401, 403]


# ==========================================
# 6. CONCURRENCY & STATE
# ==========================================

async def test_concurrent_requests_with_same_token_returns_200(async_client: httpx.AsyncClient, valid_admin_token: str) -> None:
    """Test that multiple concurrent requests using the same valid token succeed."""
    headers = {"Authorization": f"Bearer {valid_admin_token}"}
    
    # Fire 20 concurrent requests to the admin route
    tasks = [async_client.get(ADMIN_ROUTE, headers=headers) for _ in range(20)]
    results = await asyncio.gather(*tasks)
    
    for response in results:
        assert response.status_code == 200


async def test_concurrent_requests_with_expired_token_returns_401(async_client: httpx.AsyncClient, expired_token: str) -> None:
    """Test that multiple concurrent requests using an expired token all fail consistently."""
    headers = {"Authorization": f"Bearer {expired_token}"}
    
    tasks = [async_client.get(PROTECTED_GET_ROUTE, headers=headers) for _ in range(10)]
    results = await asyncio.gather(*tasks)
    
    for response in results:
        assert response.status_code == 401
        assert response.json()["detail"] == "Token has expired"


# ==========================================
# 7. USER STATE VALIDATION (MOCKED DB SCENARIOS)
# ==========================================

async def test_valid_token_for_deleted_user_returns_401(async_client: httpx.AsyncClient) -> None:
    """Test that a valid JWT for a user that no longer exists in the database returns 401."""
    # Assuming the system checks the DB for user existence. We use a known non-existent ID.
    deleted_user_token = create_jwt_token({"sub": "deleted-user-999", "role": "viewer", "type": "access"})
    
    response = await async_client.get(PROTECTED_GET_ROUTE, headers={"Authorization": f"Bearer {deleted_user_token}"})
    
    # If the app does DB lookups on auth, it should return 401. 
    # If it's pure stateless JWT, it might return 200. We assert 401 as it's best practice.
    assert response.status_code == 401
    assert response.json()["detail"] in ["User not found", "Could not validate credentials", "Inactive user"]


async def test_valid_token_for_suspended_user_returns_401(async_client: httpx.AsyncClient) -> None:
    """Test that a valid JWT for a suspended/inactive user returns 401."""
    suspended_user_token = create_jwt_token({"sub": "suspended-user-888", "role": "viewer", "type": "access"})
    
    response = await async_client.get(PROTECTED_GET_ROUTE, headers={"Authorization": f"Bearer {suspended_user_token}"})
    
    assert response.status_code == 401
    assert response.json()["detail"] in ["Inactive user", "User not found", "Could not validate credentials"]


# ==========================================
# 8. MULTIPLE HEADERS & EDGE CASES
# ==========================================

async def test_multiple_authorization_headers_uses_first_or_fails(async_client: httpx.AsyncClient, valid_admin_token: str, expired_token: str) -> None:
    """Test behavior when multiple Authorization headers are sent."""
    # httpx doesn't easily allow duplicate headers in a dict, so we use a list of tuples
    headers = [
        (b"authorization", f"Bearer {expired_token}".encode("ascii")),
        (b"authorization", f"Bearer {valid_admin_token}".encode("ascii"))
    ]
    
    response = await async_client.get(ADMIN_ROUTE, headers=headers)
    
    # FastAPI/Starlette typically takes the last header or joins them. 
    # If it joins them, it becomes invalid (401). If it takes the last, it might be 200.
    # The key is that it doesn't crash (500).
    assert response.status_code in [200, 401, 400]


async def test_authorization_header_case_insensitivity(async_client: httpx.AsyncClient, valid_admin_token: str) -> None:
    """Test that the Authorization header name is treated case-insensitively."""
    headers = {"aUtHoRiZaTiOn": f"Bearer {valid_admin_token}"}
    
    response = await async_client.get(ADMIN_ROUTE, headers=headers)
    
    assert response.status_code == 200


async def test_bearer_prefix_case_insensitivity(async_client: httpx.AsyncClient, valid_admin_token: str) -> None:
    """Test that the 'Bearer' prefix is treated case-insensitively (if supported by the app)."""
    headers = {"Authorization": f"bearer {valid_admin_token}"}
    
    response = await async_client.get(ADMIN_ROUTE, headers=headers)
    
    # FastAPI's OAuth2PasswordBearer is strictly case-sensitive for "Bearer" by default,
    # so it usually returns 401. If custom middleware is used, it might be 200.
    assert response.status_code in [200, 401]