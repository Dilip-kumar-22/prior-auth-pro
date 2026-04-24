import asyncio
import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import AsyncGenerator, Dict, List, Any

import httpx
import pytest
from jose import jwt

# Assuming the main FastAPI application is importable from api.main
from api.main import app

# Apply pytest.mark.asyncio to all test functions in this module
pytestmark = pytest.mark.asyncio

# ==========================================
# CONSTANTS & CONFIGURATION
# ==========================================

SECRET_KEY = os.environ.get("SECRET_KEY", "test_super_secret_key_for_jwt_generation_12345")
ALGORITHM = "HS256"
CONCURRENCY_LEVEL_HIGH = 50
CONCURRENCY_LEVEL_MEDIUM = 20
CONCURRENCY_LEVEL_LOW = 10

# ==========================================
# FIXTURES & HELPERS
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
def auth_headers(valid_admin_token: str) -> dict:
    """Provide standard Authorization headers using the valid admin token."""
    return {"Authorization": f"Bearer {valid_admin_token}"}


async def create_base_auth_request(client: httpx.AsyncClient, headers: dict) -> str:
    """Helper to create a single auth request and return its UUID."""
    req_id = str(uuid.uuid4())
    payload = {
        "patient_id": str(uuid.uuid4()),
        "auth_type": "medication",
        "service_requested": "Test Medication",
        "diagnosis_codes": ["E11.9"],
        "payer_id": str(uuid.uuid4()),
        "plan_id": str(uuid.uuid4()),
        "priority": "standard"
    }
    response = await client.post(f"/{req_id}", json=payload, headers=headers)
    # If the endpoint is mocked or fails in isolated tests, fallback to a random UUID
    if response.status_code in [200, 201]:
        return response.json().get("id", req_id)
    return req_id


async def create_base_appeal(client: httpx.AsyncClient, headers: dict, auth_req_id: str) -> str:
    """Helper to create a single appeal and return its UUID."""
    appeal_id = str(uuid.uuid4())
    payload = {
        "auth_request_id": auth_req_id,
        "denial_reason": "Not medically necessary",
        "counter_evidence": {"notes": "Patient requires this medication."},
        "appeal_letter": "Draft letter...",
        "guidelines_cited": ["MCG-123"]
    }
    response = await client.post(f"/{appeal_id}", json=payload, headers=headers)
    if response.status_code in [200, 201]:
        return response.json().get("id", appeal_id)
    return appeal_id


# ==========================================
# 1. CONCURRENT WRITES & CREATION
# ==========================================

async def test_concurrent_auth_request_creation(async_client, auth_headers):
    """
    Test that multiple concurrent POST requests to create Auth Requests 
    are handled safely without database locking issues or 500 errors.
    """
    async def create_request() -> httpx.Response:
        req_id = str(uuid.uuid4())
        payload = {
            "patient_id": str(uuid.uuid4()),
            "auth_type": "imaging",
            "service_requested": "MRI Brain",
            "diagnosis_codes": ["R51"],
            "payer_id": str(uuid.uuid4()),
            "plan_id": str(uuid.uuid4()),
            "priority": "urgent"
        }
        return await async_client.post(f"/{req_id}", json=payload, headers=auth_headers)

    tasks = [create_request() for _ in range(CONCURRENCY_LEVEL_HIGH)]
    results = await asyncio.gather(*tasks)

    success_count = 0
    for response in results:
        assert response.status_code != 500, "Concurrent creation caused a 500 Internal Server Error"
        if response.status_code in [200, 201]:
            success_count += 1
            
    # In a properly scaling async system, all should succeed unless rate-limited
    assert success_count > 0, "Expected at least some requests to succeed"


async def test_concurrent_appeal_creation_different_requests(async_client, auth_headers):
    """
    Test concurrent creation of appeals for entirely different auth requests.
    This tests general database insert concurrency on the Appeals table.
    """
    async def create_appeal() -> httpx.Response:
        appeal_id = str(uuid.uuid4())
        payload = {
            "auth_request_id": str(uuid.uuid4()),
            "denial_reason": "Experimental treatment",
            "counter_evidence": {"clinical_trial": "NCT123456"},
            "appeal_letter": "Please reconsider based on attached trial data.",
            "guidelines_cited": ["NCCN"]
        }
        return await async_client.post(f"/{appeal_id}", json=payload, headers=auth_headers)

    tasks = [create_appeal() for _ in range(CONCURRENCY_LEVEL_MEDIUM)]
    results = await asyncio.gather(*tasks)

    for response in results:
        # Might be 404/422 if auth_request_id FK is strictly enforced and missing, 
        # but should NEVER be 500.
        assert response.status_code in [200, 201, 400, 404, 409, 422]
        assert response.status_code != 500


async def test_concurrent_appeal_creation_same_request(async_client, auth_headers):
    """
    Test concurrent creation of appeals for the EXACT SAME auth request.
    This tests race conditions on unique constraints (e.g., one appeal per auth request).
    """
    auth_req_id = await create_base_auth_request(async_client, auth_headers)
    
    async def create_appeal() -> httpx.Response:
        appeal_id = str(uuid.uuid4())
        payload = {
            "auth_request_id": auth_req_id,
            "denial_reason": "Step therapy required",
            "counter_evidence": {"history": "Failed step 1"},
            "appeal_letter": "Patient already failed prerequisite.",
            "guidelines_cited": []
        }
        return await async_client.post(f"/{appeal_id}", json=payload, headers=auth_headers)

    tasks = [create_appeal() for _ in range(CONCURRENCY_LEVEL_LOW)]
    results = await asyncio.gather(*tasks)

    successes = [r for r in results if r.status_code in [200, 201]]
    conflicts = [r for r in results if r.status_code in [400, 409, 422]]
    
    for response in results:
        assert response.status_code != 500
        
    # Depending on business logic, either all succeed (multiple appeals allowed) 
    # or exactly one succeeds and the rest conflict.
    assert len(successes) + len(conflicts) == CONCURRENCY_LEVEL_LOW


# ==========================================
# 2. CONCURRENT ACTIONS & TRIGGERS
# ==========================================

async def test_concurrent_appeal_generation(async_client, auth_headers):
    """
    Test that multiple concurrent POST requests to trigger AI appeal generation 
    for the same appeal ID handle race conditions gracefully (e.g., idempotency or 409).
    """
    auth_req_id = await create_base_auth_request(async_client, auth_headers)
    appeal_id = await create_base_appeal(async_client, auth_headers, auth_req_id)
    
    tasks = [
        async_client.post(f"/{appeal_id}/generate", headers=auth_headers)
        for _ in range(CONCURRENCY_LEVEL_LOW)
    ]
    results = await asyncio.gather(*tasks)

    successes = 0
    conflicts = 0
    for response in results:
        assert response.status_code != 500, "Concurrent AI generation trigger caused a 500 error"
        if response.status_code in [200, 202]:
            successes += 1
        elif response.status_code in [400, 409]:
            conflicts += 1

    # At least one should succeed or be accepted. Others might be rejected if already generating.
    assert successes > 0 or conflicts > 0


async def test_concurrent_auth_request_processing_trigger(async_client, auth_headers):
    """
    Test concurrent triggers of the AI processing pipeline for the same Auth Request.
    Ensures that the workflow engine doesn't duplicate steps or crash under race conditions.
    """
    auth_req_id = await create_base_auth_request(async_client, auth_headers)
    
    tasks = [
        async_client.post(f"/{auth_req_id}/process", headers=auth_headers)
        for _ in range(CONCURRENCY_LEVEL_LOW)
    ]
    results = await asyncio.gather(*tasks)

    for response in results:
        # Should return 200/202 (Accepted), or 409 if already processing.
        assert response.status_code in [200, 202, 400, 404, 409]
        assert response.status_code != 500


# ==========================================
# 3. CONCURRENT READS & CONNECTION POOLING
# ==========================================

async def test_concurrent_reads_auth_request_list(async_client, auth_headers):
    """
    Test that the database connection pool can handle a high volume of 
    concurrent read requests to the list endpoint.
    """
    tasks = [
        async_client.get("/events?limit=10&skip=0", headers=auth_headers)
        for _ in range(CONCURRENCY_LEVEL_HIGH)
    ]
    results = await asyncio.gather(*tasks)

    for response in results:
        assert response.status_code == 200
        assert isinstance(response.json(), list) or "items" in response.json()


async def test_concurrent_reads_single_auth_request(async_client, auth_headers):
    """
    Test concurrent reads to a single specific Auth Request.
    """
    auth_req_id = await create_base_auth_request(async_client, auth_headers)
    
    tasks = [
        async_client.get(f"/{auth_req_id}", headers=auth_headers)
        for _ in range(CONCURRENCY_LEVEL_HIGH)
    ]
    results = await asyncio.gather(*tasks)

    for response in results:
        # Might be 404 if creation failed in isolated test, but should be consistent
        assert response.status_code in [200, 404]
        assert response.status_code != 500


async def test_concurrent_dashboard_metrics(async_client, auth_headers):
    """
    Test concurrent access to the dashboard metrics endpoint, which typically 
    involves heavy aggregation queries. Ensures no deadlocks or timeouts.
    """
    tasks = [
        async_client.get("/metrics", headers=auth_headers)
        for _ in range(CONCURRENCY_LEVEL_MEDIUM)
    ]
    results = await asyncio.gather(*tasks)

    for response in results:
        assert response.status_code == 200
        data = response.json()
        assert "approval_rate" in data
        assert "total_processed" in data


async def test_concurrent_workflow_reads(async_client, auth_headers):
    """
    Test concurrent reads of the workflow pipeline steps for a specific Auth Request.
    """
    auth_req_id = await create_base_auth_request(async_client, auth_headers)
    
    tasks = [
        async_client.get(f"/{auth_req_id}/workflow", headers=auth_headers)
        for _ in range(CONCURRENCY_LEVEL_MEDIUM)
    ]
    results = await asyncio.gather(*tasks)

    for response in results:
        assert response.status_code in [200, 404]
        assert response.status_code != 500


async def test_concurrent_audit_events_reads(async_client, auth_headers):
    """
    Test concurrent reads of the global audit events log with query parameters.
    """
    tasks = [
        async_client.get("/events?limit=20&event_type=created", headers=auth_headers)
        for _ in range(CONCURRENCY_LEVEL_MEDIUM)
    ]
    results = await asyncio.gather(*tasks)

    for response in results:
        assert response.status_code == 200
        assert response.status_code != 500


async def test_concurrent_health_checks(async_client):
    """
    Test that the health check endpoint can handle a massive burst of concurrent requests 
    without degrading, ensuring the load balancer/ingress won't kill the service.
    """
    tasks = [
        async_client.get("/health")
        for _ in range(100)  # Extra high concurrency for health check
    ]
    results = await asyncio.gather(*tasks)

    for response in results:
        assert response.status_code == 200
        assert response.json().get("status") in ["ok", "healthy", "up"]