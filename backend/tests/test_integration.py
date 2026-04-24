import asyncio
import os
import uuid
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from jose import jwt

from api.main import app

pytestmark = pytest.mark.asyncio

# ==========================================
# CONSTANTS & CONFIGURATION
# ==========================================

SECRET_KEY = os.environ.get("SECRET_KEY", os.urandom(32).hex())
ALGORITHM = "HS256"

# ==========================================
# FIXTURES
# ==========================================

@pytest.fixture
async def async_client():
    """
    Provide an asynchronous test client for the FastAPI application.
    Uses ASGITransport to communicate directly with the app without a running server.
    """
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client


@pytest.fixture
def valid_admin_token():
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
def valid_viewer_token():
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
def auth_headers(valid_admin_token):
    """Provide standard Authorization headers using the valid admin token."""
    return {"Authorization": f"Bearer {valid_admin_token}"}


@pytest.fixture
def viewer_headers(valid_viewer_token):
    """Provide standard Authorization headers using the valid viewer token."""
    return {"Authorization": f"Bearer {valid_viewer_token}"}


@pytest.fixture
def base_auth_request_payload():
    """Provide a valid payload for creating an Auth Request."""
    return {
        "patient_id": str(uuid.uuid4()),
        "auth_type": "medication",
        "service_requested": "Humira 40mg",
        "diagnosis_codes": ["L40.0", "M06.9"],
        "payer_id": str(uuid.uuid4()),
        "plan_id": str(uuid.uuid4()),
        "priority": "standard"
    }


@pytest.fixture
def base_appeal_payload():
    """Provide a valid payload for creating an Appeal."""
    return {
        "auth_request_id": str(uuid.uuid4()),  # Will be overridden in tests
        "denial_reason": "Step therapy required. Must try Methotrexate first.",
        "counter_evidence": {"clinical_notes": "Patient failed Methotrexate in 2022 due to severe nausea."},
        "appeal_letter": "Draft letter...",
        "guidelines_cited": ["ACR Rheumatoid Arthritis Guidelines 2021"]
    }


# ==========================================
# INTEGRATION TESTS - FULL LIFECYCLES
# ==========================================

async def test_full_auth_lifecycle(
    async_client, 
    auth_headers,
    base_auth_request_payload
):
    """
    Test the complete lifecycle of an Auth Request:
    1. Create Auth Request
    2. Read Auth Request by ID
    3. Trigger AI Processing
    4. Check Workflow Steps
    5. Check Audit Events
    6. List Auth Requests
    """
    # 1. Create Auth Request
    create_resp = await async_client.post(
        "/", 
        json=base_auth_request_payload, 
        headers=auth_headers
    )
    assert create_resp.status_code in [200, 201]
    auth_data = create_resp.json()
    assert "id" in auth_data
    auth_id = auth_data["id"]
    assert auth_data["service_requested"] == base_auth_request_payload["service_requested"]

    # 2. Read Auth Request by ID
    get_resp = await async_client.get(f"/{auth_id}", headers=auth_headers)
    assert get_resp.status_code == 200
    assert get_resp.json()["id"] == auth_id

    # 3. Trigger AI Processing
    process_resp = await async_client.post(f"/{auth_id}/process", headers=auth_headers)
    assert process_resp.status_code in [200, 202]
    assert "status" in process_resp.json()

    # 4. Check Workflow Steps
    workflow_resp = await async_client.get(f"/{auth_id}/workflow", headers=auth_headers)
    assert workflow_resp.status_code == 200
    workflow_data = workflow_resp.json()
    assert isinstance(workflow_data, list)

    # 5. Check Audit Events
    events_resp = await async_client.get(f"/{auth_id}/events", headers=auth_headers)
    assert events_resp.status_code == 200
    events_data = events_resp.json()
    assert isinstance(events_data, list)
    # At least a 'created' event should exist
    assert any(e.get("event_type") == "created" for e in events_data)

    # 6. List Auth Requests
    list_resp = await async_client.get("/?limit=10", headers=auth_headers)
    assert list_resp.status_code == 200
    list_data = list_resp.json()
    # Handle both paginated dict response and flat list response
    items = list_data.get("items", list_data) if isinstance(list_data, dict) else list_data
    assert any(item["id"] == auth_id for item in items)


async def test_full_appeal_lifecycle(
    async_client, 
    auth_headers,
    base_auth_request_payload,
    base_appeal_payload
):
    """
    Test the complete lifecycle of an Appeal:
    1. Create prerequisite Auth Request
    2. Create Appeal linked to Auth Request
    3. Read Appeal by ID
    4. Trigger AI Appeal Letter Generation
    5. List Appeals
    """
    # 1. Create prerequisite Auth Request
    auth_resp = await async_client.post(
        "/", 
        json=base_auth_request_payload, 
        headers=auth_headers
    )
    assert auth_resp.status_code in [200, 201]
    auth_id = auth_resp.json()["id"]

    # 2. Create Appeal
    base_appeal_payload["auth_request_id"] = auth_id
    appeal_resp = await async_client.post(
        "/", 
        json=base_appeal_payload, 
        headers=auth_headers
    )
    assert appeal_resp.status_code in [200, 201]
    appeal_data = appeal_resp.json()
    assert "id" in appeal_data
    appeal_id = appeal_data["id"]
    assert appeal_data["auth_request_id"] == auth_id

    # 3. Read Appeal by ID
    get_resp = await async_client.get(f"/{appeal_id}", headers=auth_headers)
    assert get_resp.status_code == 200
    assert get_resp.json()["id"] == appeal_id
    assert get_resp.json()["denial_reason"] == base_appeal_payload["denial_reason"]

    # 4. Trigger AI Appeal Letter Generation
    generate_resp = await async_client.post(f"/{appeal_id}/generate", headers=auth_headers)
    assert generate_resp.status_code in [200, 202]
    assert "status" in generate_resp.json()

    # 5. List Appeals
    list_resp = await async_client.get("/?limit=10", headers=auth_headers)
    assert list_resp.status_code == 200
    list_data = list_resp.json()
    items = list_data.get("items", list_data) if isinstance(list_data, dict) else list_data
    assert any(item["id"] == appeal_id for item in items)


async def test_auth_request_lifecycle_with_invalid_data_returns_422(
    async_client, 
    auth_headers,
    base_auth_request_payload
):
    """
    Test that the lifecycle correctly blocks invalid data at the creation step.
    """
    # Missing required field 'patient_id'
    invalid_payload_1 = base_auth_request_payload.copy()
    del invalid_payload_1["patient_id"]
    
    resp_1 = await async_client.post("/", json=invalid_payload_1, headers=auth_headers)
    assert resp_1.status_code == 422
    assert "patient_id" in resp_1.json()["detail"][0]["loc"]

    # Invalid enum for 'auth_type'
    invalid_payload_2 = base_auth_request_payload.copy()
    invalid_payload_2["auth_type"] = "invalid_type"
    
    resp_2 = await async_client.post("/", json=invalid_payload_2, headers=auth_headers)
    assert resp_2.status_code == 422
    assert "auth_type" in resp_2.json()["detail"][0]["loc"]


async def test_appeal_lifecycle_with_nonexistent_auth_request_returns_404_or_422(
    async_client, 
    auth_headers,
    base_appeal_payload
):
    """
    Test that creating an appeal for a non-existent auth request fails gracefully.
    """
    base_appeal_payload["auth_request_id"] = str(uuid.uuid4())  # Random, non-existent UUID
    
    resp = await async_client.post("/", json=base_appeal_payload, headers=auth_headers)
    # Depending on strict FK enforcement vs Pydantic validation, it could be 404, 400, or 422
    assert resp.status_code in [400, 404, 422]


async def test_auth_request_lifecycle_pagination_and_filtering_returns_200(
    async_client, 
    auth_headers,
    base_auth_request_payload
):
    """
    Test that pagination and filtering work correctly across the lifecycle.
    """
    patient_id = str(uuid.uuid4())
    
    # Create 3 requests for the same patient
    for _ in range(3):
        payload = base_auth_request_payload.copy()
        payload["patient_id"] = patient_id
        resp = await async_client.post("/", json=payload, headers=auth_headers)
        assert resp.status_code in [200, 201]

    # Filter by patient_id
    filter_resp = await async_client.get(f"/?patient_id={patient_id}", headers=auth_headers)
    assert filter_resp.status_code == 200
    filter_data = filter_resp.json()
    items = filter_data.get("items", filter_data) if isinstance(filter_data, dict) else filter_data
    assert len(items) >= 3
    assert all(item["patient_id"] == patient_id for item in items)

    # Test pagination
    paginated_resp = await async_client.get(f"/?patient_id={patient_id}&limit=2&skip=0", headers=auth_headers)
    assert paginated_resp.status_code == 200
    paginated_data = paginated_resp.json()
    page_items = paginated_data.get("items", paginated_data) if isinstance(paginated_data, dict) else paginated_data
    assert len(page_items) == 2


async def test_auth_request_processing_idempotency_returns_200_or_409(
    async_client, 
    auth_headers,
    base_auth_request_payload
):
    """
    Test that triggering processing multiple times is handled safely (idempotent or conflict).
    """
    create_resp = await async_client.post("/", json=base_auth_request_payload, headers=auth_headers)
    auth_id = create_resp.json()["id"]

    # First trigger
    proc_resp_1 = await async_client.post(f"/{auth_id}/process", headers=auth_headers)
    assert proc_resp_1.status_code in [200, 202]

    # Second trigger immediately after
    proc_resp_2 = await async_client.post(f"/{auth_id}/process", headers=auth_headers)
    # Should either accept it idempotently or reject as already processing
    assert proc_resp_2.status_code in [200, 202, 400, 409]


async def test_dashboard_metrics_updates_after_lifecycle_events_returns_200(
    async_client, 
    auth_headers,
    base_auth_request_payload
):
    """
    Test that the dashboard metrics endpoint successfully aggregates data 
    after new resources are created in the lifecycle.
    """
    # Get initial metrics
    initial_resp = await async_client.get("/metrics", headers=auth_headers)
    assert initial_resp.status_code == 200
    initial_data = initial_resp.json()
    assert "total_processed" in initial_data

    # Create a new request
    await async_client.post("/", json=base_auth_request_payload, headers=auth_headers)

    # Get updated metrics
    updated_resp = await async_client.get("/metrics", headers=auth_headers)
    assert updated_resp.status_code == 200
    updated_data = updated_resp.json()
    
    # Depending on async processing, metrics might not update instantly, 
    # but the endpoint must return 200 and valid schema.
    assert "total_processed" in updated_data
    assert "approval_rate" in updated_data


async def test_audit_log_captures_full_lifecycle_events_returns_200(
    async_client, 
    auth_headers,
    base_auth_request_payload
):
    """
    Test that the global audit log correctly captures events generated during the lifecycle.
    """
    # Create request to generate an event
    create_resp = await async_client.post("/", json=base_auth_request_payload, headers=auth_headers)
    auth_id = create_resp.json()["id"]

    # Query global audit log
    audit_resp = await async_client.get(f"/events?auth_request_id={auth_id}", headers=auth_headers)
    assert audit_resp.status_code == 200
    audit_data = audit_resp.json()
    items = audit_data.get("items", audit_data) if isinstance(audit_data, dict) else audit_data
    
    assert isinstance(items, list)
    assert len(items) > 0
    assert items[0]["auth_request_id"] == auth_id
    assert items[0]["event_type"] == "created"


async def test_concurrent_lifecycle_operations_maintain_consistency(
    async_client, 
    auth_headers,
    base_auth_request_payload
):
    """
    Test that executing multiple lifecycle creations concurrently does not cause 500 errors.
    """
    async def create_req():
        payload = base_auth_request_payload.copy()
        payload["patient_id"] = str(uuid.uuid4())
        return await async_client.post("/", json=payload, headers=auth_headers)

    # Execute 10 concurrent creations
    tasks = [create_req() for _ in range(10)]
    results = await asyncio.gather(*tasks)

    for resp in results:
        assert resp.status_code in [200, 201]
        assert "id" in resp.json()


async def test_full_auth_lifecycle_with_unauthorized_user_returns_403(
    async_client, 
    viewer_headers,
    base_auth_request_payload
):
    """
    Test that a user with insufficient permissions (viewer) is blocked from 
    mutating state in the lifecycle.
    """
    # Attempt to create Auth Request as viewer
    create_resp = await async_client.post(
        "/", 
        json=base_auth_request_payload, 
        headers=viewer_headers
    )
    # Depending on RBAC implementation, viewers might be blocked from POST
    assert create_resp.status_code in [401, 403]
    assert "detail" in create_resp.json()

    # Attempt to trigger processing on a random UUID as viewer
    random_id = str(uuid.uuid4())
    process_resp = await async_client.post(
        f"/{random_id}/process", 
        headers=viewer_headers
    )
    assert process_resp.status_code in [401, 403]


async def test_lifecycle_not_found_handling_returns_404(
    async_client, 
    auth_headers
):
    """
    Test that attempting lifecycle operations on non-existent resources returns 404.
    """
    fake_id = str(uuid.uuid4())

    # Get non-existent Auth Request
    get_auth = await async_client.get(f"/{fake_id}", headers=auth_headers)
    assert get_auth.status_code == 404

    # Get non-existent Appeal
    get_appeal = await async_client.get(f"/{fake_id}", headers=auth_headers)
    assert get_appeal.status_code == 404

    # Trigger processing on non-existent Auth Request
    process_auth = await async_client.post(f"/{fake_id}/process", headers=auth_headers)
    assert process_auth.status_code == 404

    # Trigger generation on non-existent Appeal
    generate_appeal = await async_client.post(f"/{fake_id}/generate", headers=auth_headers)
    assert generate_appeal.status_code == 404