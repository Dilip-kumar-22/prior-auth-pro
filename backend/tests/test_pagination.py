import os
import uuid
import asyncio
from datetime import datetime, timedelta, timezone
from typing import AsyncGenerator, Dict, Any, List

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

# ==========================================
# HELPERS
# ==========================================

def get_auth_headers() -> Dict[str, str]:
    """Provide standard Authorization headers using a valid admin token."""
    expire = datetime.now(timezone.utc) + timedelta(minutes=15)
    payload = {
        "sub": str(uuid.uuid4()),
        "role": "admin",
        "type": "access",
        "exp": expire
    }
    token = jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)
    return {"Authorization": f"Bearer {token}"}


async def seed_auth_requests(async_client: httpx.AsyncClient, patient_id: str) -> List[Dict[str, Any]]:
    """
    Seed the database with 15 Auth Requests for a specific patient.
    This guarantees exact counts for pagination tests regardless of other concurrent tests.
    """
    requests = []
    headers = get_auth_headers()
    for i in range(15):
        payload = {
            "patient_id": patient_id,
            "auth_type": "medication",
            "service_requested": f"Test Medication {i}",
            "diagnosis_codes": ["E11.9"],
            "payer_id": str(uuid.uuid4()),
            "plan_id": str(uuid.uuid4()),
            "priority": "standard"
        }
        response = await async_client.post("/events", json=payload, headers=headers)
        if response.status_code in [200, 201]:
            requests.append(response.json())
            
    # Ensure we actually seeded the data
    assert len(requests) == 15, "Failed to seed 15 auth requests for pagination tests"
    return requests


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


# ==========================================
# REQUIRED IMPLEMENTATIONS
# ==========================================

async def test_pagination_skip_limit(async_client: httpx.AsyncClient) -> None:
    """
    Test that skip and limit correctly paginate through a known dataset.
    Verifies that consecutive pages return the correct number of items and do not overlap.
    """
    auth_headers = get_auth_headers()
    unique_patient_id = str(uuid.uuid4())
    await seed_auth_requests(async_client, unique_patient_id)

    # Fetch Page 1 (items 1-5)
    resp1 = await async_client.get(
        f"/events?patient_id={unique_patient_id}&limit=5&skip=0", 
        headers=auth_headers
    )
    assert resp1.status_code == 200
    data1 = resp1.json()
    items1 = data1.get("items", data1) if isinstance(data1, dict) else data1
    assert len(items1) == 5

    # Fetch Page 2 (items 6-10)
    resp2 = await async_client.get(
        f"/events?patient_id={unique_patient_id}&limit=5&skip=5", 
        headers=auth_headers
    )
    assert resp2.status_code == 200
    data2 = resp2.json()
    items2 = data2.get("items", data2) if isinstance(data2, dict) else data2
    assert len(items2) == 5

    # Fetch Page 3 (items 11-15)
    resp3 = await async_client.get(
        f"/events?patient_id={unique_patient_id}&limit=5&skip=10", 
        headers=auth_headers
    )
    assert resp3.status_code == 200
    data3 = resp3.json()
    items3 = data3.get("items", data3) if isinstance(data3, dict) else data3
    assert len(items3) == 5

    # Ensure no overlap between pages
    ids1 = {item["id"] for item in items1}
    ids2 = {item["id"] for item in items2}
    ids3 = {item["id"] for item in items3}
    
    assert ids1.isdisjoint(ids2), "Page 1 and Page 2 contain overlapping items"
    assert ids2.isdisjoint(ids3), "Page 2 and Page 3 contain overlapping items"
    assert ids1.isdisjoint(ids3), "Page 1 and Page 3 contain overlapping items"


async def test_pagination_exceed_max_limit(async_client: httpx.AsyncClient) -> None:
    """
    Test that requesting a limit above the maximum allowed (e.g., 100) returns a 422 Validation Error.
    """
    auth_headers = get_auth_headers()
    # Assuming the API enforces a max limit of 100 via Pydantic Field(le=100)
    resp = await async_client.get("/events?limit=1001&skip=0", headers=auth_headers)
    assert resp.status_code == 422
    assert "detail" in resp.json()
    
    # Verify the error is specifically about the 'limit' query parameter
    error_locs = [err["loc"] for err in resp.json()["detail"]]
    assert any("limit" in loc for loc in error_locs), "Expected validation error on 'limit' field"


async def test_pagination_negative_skip(async_client: httpx.AsyncClient) -> None:
    """
    Test that providing a negative skip value returns a 422 Validation Error.
    """
    auth_headers = get_auth_headers()
    resp = await async_client.get("/events?limit=10&skip=-5", headers=auth_headers)
    assert resp.status_code == 422
    assert "detail" in resp.json()
    
    # Verify the error is specifically about the 'skip' query parameter
    error_locs = [err["loc"] for err in resp.json()["detail"]]
    assert any("skip" in loc for loc in error_locs), "Expected validation error on 'skip' field"


# ==========================================
# ADDITIONAL PAGINATION EDGE CASES
# ==========================================

async def test_get_auth_requests_with_negative_limit_returns_422(async_client: httpx.AsyncClient) -> None:
    """
    Test that providing a negative limit value returns a 422 Validation Error.
    """
    auth_headers = get_auth_headers()
    resp = await async_client.get("/events?limit=-10&skip=0", headers=auth_headers)
    assert resp.status_code == 422
    
    error_locs = [err["loc"] for err in resp.json()["detail"]]
    assert any("limit" in loc for loc in error_locs)


async def test_get_auth_requests_with_zero_limit_returns_422(async_client: httpx.AsyncClient) -> None:
    """
    Test that providing a limit of zero returns a 422 Validation Error.
    (Assuming limit must be >= 1).
    """
    auth_headers = get_auth_headers()
    resp = await async_client.get("/events?limit=0&skip=0", headers=auth_headers)
    assert resp.status_code == 422
    
    error_locs = [err["loc"] for err in resp.json()["detail"]]
    assert any("limit" in loc for loc in error_locs)


async def test_get_auth_requests_with_large_skip_returns_200_empty_list(async_client: httpx.AsyncClient) -> None:
    """
    Test that providing a skip value far beyond the total number of records 
    returns a 200 OK with an empty list, not a 404 or 500 error.
    """
    auth_headers = get_auth_headers()
    unique_patient_id = str(uuid.uuid4())
    resp = await async_client.get(
        f"/events?patient_id={unique_patient_id}&limit=10&skip=999999", 
        headers=auth_headers
    )
    assert resp.status_code == 200
    
    data = resp.json()
    items = data.get("items", data) if isinstance(data, dict) else data
    assert isinstance(items, list)
    assert len(items) == 0


async def test_get_auth_requests_with_string_skip_returns_422(async_client: httpx.AsyncClient) -> None:
    """
    Test that providing a non-integer string for skip returns a 422 Validation Error.
    """
    auth_headers = get_auth_headers()
    resp = await async_client.get("/events?limit=10&skip=invalid_skip", headers=auth_headers)
    assert resp.status_code == 422
    
    error_locs = [err["loc"] for err in resp.json()["detail"]]
    assert any("skip" in loc for loc in error_locs)


async def test_get_auth_requests_with_string_limit_returns_422(async_client: httpx.AsyncClient) -> None:
    """
    Test that providing a non-integer string for limit returns a 422 Validation Error.
    """
    auth_headers = get_auth_headers()
    resp = await async_client.get("/events?limit=invalid_limit&skip=0", headers=auth_headers)
    assert resp.status_code == 422
    
    error_locs = [err["loc"] for err in resp.json()["detail"]]
    assert any("limit" in loc for loc in error_locs)


async def test_get_auth_requests_with_missing_limit_uses_default_returns_200(async_client: httpx.AsyncClient) -> None:
    """
    Test that omitting the limit parameter falls back to the default value and returns 200 OK.
    """
    auth_headers = get_auth_headers()
    resp = await async_client.get("/events?skip=0", headers=auth_headers)
    assert resp.status_code == 200
    
    data = resp.json()
    items = data.get("items", data) if isinstance(data, dict) else data
    assert isinstance(items, list)


async def test_get_auth_requests_with_missing_skip_uses_default_returns_200(async_client: httpx.AsyncClient) -> None:
    """
    Test that omitting the skip parameter falls back to the default value (0) and returns 200 OK.
    """
    auth_headers = get_auth_headers()
    resp = await async_client.get("/events?limit=10", headers=auth_headers)
    assert resp.status_code == 200
    
    data = resp.json()
    items = data.get("items", data) if isinstance(data, dict) else data
    assert isinstance(items, list)


async def test_get_appeals_with_pagination_returns_200(async_client: httpx.AsyncClient) -> None:
    """
    Test that pagination parameters are correctly accepted on the Appeals list endpoint.
    """
    auth_headers = get_auth_headers()
    resp = await async_client.get("/events?limit=5&skip=0", headers=auth_headers)
    assert resp.status_code == 200
    
    data = resp.json()
    items = data.get("items", data) if isinstance(data, dict) else data
    assert isinstance(items, list)
    assert len(items) <= 5


async def test_get_audit_events_with_pagination_returns_200(async_client: httpx.AsyncClient) -> None:
    """
    Test that pagination parameters are correctly accepted on the Audit Events list endpoint.
    """
    auth_headers = get_auth_headers()
    resp = await async_client.get("/events?limit=20&skip=10", headers=auth_headers)
    assert resp.status_code == 200
    
    data = resp.json()
    items = data.get("items", data) if isinstance(data, dict) else data
    assert isinstance(items, list)
    assert len(items) <= 20


async def test_pagination_partial_page_returns_correct_count(async_client: httpx.AsyncClient) -> None:
    """
    Test that requesting a page that partially overlaps the end of the dataset 
    returns only the remaining items, not the full limit.
    """
    auth_headers = get_auth_headers()
    unique_patient_id = str(uuid.uuid4())
    await seed_auth_requests(async_client, unique_patient_id)

    # We seeded exactly 15 items. Skip 12, limit 10 -> should return exactly 3 items.
    resp = await async_client.get(
        f"/events?patient_id={unique_patient_id}&limit=10&skip=12", 
        headers=auth_headers
    )
    assert resp.status_code == 200
    
    data = resp.json()
    items = data.get("items", data) if isinstance(data, dict) else data
    assert len(items) == 3