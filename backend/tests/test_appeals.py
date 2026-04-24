import asyncio
import uuid
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from models.appeal import Appeal
from models.auth_request import AuthRequest

pytestmark = pytest.mark.asyncio


# ==========================================
# 1. HAPPY PATH TESTS
# ==========================================

async def test_create_appeal_minimal_valid_request(async_client: AsyncClient, sample_auth_request: AuthRequest) -> None:
    """Test creating an appeal with only the required fields."""
    payload = {
        "auth_request_id": str(sample_auth_request.id),
        "denial_reason": "Service not medically necessary based on submitted documentation."
    }
    response = await async_client.post("/appeals", json=payload)
    assert response.status_code == 201
    data = response.json()
    assert data["auth_request_id"] == str(sample_auth_request.id)
    assert data["denial_reason"] == payload["denial_reason"]
    assert "id" in data
    assert data["status"] in ["draft", "submitted", "under_review", "resolved"]


async def test_create_appeal_all_optional_fields(async_client: AsyncClient, sample_auth_request: AuthRequest) -> None:
    """Test creating an appeal with all optional fields provided."""
    payload = {
        "auth_request_id": str(sample_auth_request.id),
        "denial_reason": "Experimental treatment.",
        "counter_evidence": {"clinical_notes": "Patient failed 6 months of conservative therapy."},
        "appeal_letter": "To whom it may concern, I am appealing the denial...",
        "guidelines_cited": [{"id": "g-123", "text": "Guideline A"}],
        "status": "draft",
        "outcome": "null"
    }
    response = await async_client.post("/appeals", json=payload)
    assert response.status_code == 201
    data = response.json()
    assert data["counter_evidence"] == payload["counter_evidence"]
    assert data["appeal_letter"] == payload["appeal_letter"]
    assert data["guidelines_cited"] == payload["guidelines_cited"]
    assert data["status"] == "draft"
    assert data["outcome"] == "null"


async def test_list_appeals_returns_200(async_client: AsyncClient, sample_appeal: Appeal) -> None:
    """Test listing appeals returns a 200 OK with a list of appeals."""
    response = await async_client.get("/appeals")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) >= 1
    assert data[0]["id"] == str(sample_appeal.id)


async def test_get_appeal_by_id_returns_200(async_client: AsyncClient, sample_appeal: Appeal) -> None:
    """Test retrieving a specific appeal by its ID."""
    response = await async_client.get(f"/appeals/{sample_appeal.id}")
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == str(sample_appeal.id)
    assert data["auth_request_id"] == str(sample_appeal.auth_request_id)
    assert data["denial_reason"] == sample_appeal.denial_reason


# ==========================================
# 2. VALIDATION TESTS
# ==========================================

async def test_create_appeal_missing_auth_request_id_returns_422(async_client: AsyncClient) -> None:
    """Test creating an appeal without the required auth_request_id."""
    payload = {
        "denial_reason": "Missing auth ID."
    }
    response = await async_client.post("/appeals", json=payload)
    assert response.status_code == 422
    assert "auth_request_id" in response.json()["detail"][0]["loc"]


async def test_create_appeal_missing_denial_reason_returns_422(async_client: AsyncClient, sample_auth_request: AuthRequest) -> None:
    """Test creating an appeal without the required denial_reason."""
    payload = {
        "auth_request_id": str(sample_auth_request.id)
    }
    response = await async_client.post("/appeals", json=payload)
    assert response.status_code == 422
    assert "denial_reason" in response.json()["detail"][0]["loc"]


async def test_create_appeal_invalid_uuid_returns_422(async_client: AsyncClient) -> None:
    """Test creating an appeal with an invalid UUID format for auth_request_id."""
    payload = {
        "auth_request_id": "not-a-uuid",
        "denial_reason": "Invalid UUID."
    }
    response = await async_client.post("/appeals", json=payload)
    assert response.status_code == 422
    assert "auth_request_id" in response.json()["detail"][0]["loc"]


async def test_create_appeal_invalid_status_enum_returns_422(async_client: AsyncClient, sample_auth_request: AuthRequest) -> None:
    """Test creating an appeal with an invalid status enum value."""
    payload = {
        "auth_request_id": str(sample_auth_request.id),
        "denial_reason": "Invalid status.",
        "status": "invalid_status"
    }
    response = await async_client.post("/appeals", json=payload)
    assert response.status_code == 422
    assert "status" in response.json()["detail"][0]["loc"]


async def test_create_appeal_invalid_outcome_enum_returns_422(async_client: AsyncClient, sample_auth_request: AuthRequest) -> None:
    """Test creating an appeal with an invalid outcome enum value."""
    payload = {
        "auth_request_id": str(sample_auth_request.id),
        "denial_reason": "Invalid outcome.",
        "outcome": "invalid_outcome"
    }
    response = await async_client.post("/appeals", json=payload)
    assert response.status_code == 422
    assert "outcome" in response.json()["detail"][0]["loc"]


async def test_create_appeal_null_denial_reason_returns_422(async_client: AsyncClient, sample_auth_request: AuthRequest) -> None:
    """Test creating an appeal with a null denial_reason."""
    payload = {
        "auth_request_id": str(sample_auth_request.id),
        "denial_reason": None
    }
    response = await async_client.post("/appeals", json=payload)
    assert response.status_code == 422
    assert "denial_reason" in response.json()["detail"][0]["loc"]


async def test_create_appeal_wrong_type_counter_evidence_returns_422(async_client: AsyncClient, sample_auth_request: AuthRequest) -> None:
    """Test creating an appeal with a string instead of a dict for counter_evidence."""
    payload = {
        "auth_request_id": str(sample_auth_request.id),
        "denial_reason": "Wrong type.",
        "counter_evidence": "This should be an object/dict, not a string."
    }
    response = await async_client.post("/appeals", json=payload)
    assert response.status_code == 422
    assert "counter_evidence" in response.json()["detail"][0]["loc"]


async def test_list_appeals_invalid_skip_returns_422(async_client: AsyncClient) -> None:
    """Test listing appeals with a non-integer skip value."""
    response = await async_client.get("/appeals?skip=not-an-int")
    assert response.status_code == 422
    assert "skip" in response.json()["detail"][0]["loc"]


async def test_create_appeal_missing_body_returns_422(async_client: AsyncClient) -> None:
    """Test creating an appeal with no request body."""
    response = await async_client.post("/appeals")
    assert response.status_code == 422
    assert "body" in response.json()["detail"][0]["loc"]


async def test_create_appeal_invalid_json_returns_422(async_client: AsyncClient) -> None:
    """Test creating an appeal with malformed JSON."""
    response = await async_client.post("/appeals", content="invalid json", headers={"Content-Type": "application/json"})
    assert response.status_code == 422


# ==========================================
# 3. NOT FOUND TESTS
# ==========================================

async def test_create_appeal_non_existent_auth_request_returns_404(async_client: AsyncClient) -> None:
    """Test creating an appeal for an auth request that does not exist."""
    payload = {
        "auth_request_id": str(uuid.uuid4()),
        "denial_reason": "Auth request does not exist."
    }
    response = await async_client.post("/appeals", json=payload)
    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()


async def test_get_appeal_non_existent_id_returns_404(async_client: AsyncClient) -> None:
    """Test retrieving an appeal that does not exist."""
    response = await async_client.get(f"/appeals/{uuid.uuid4()}")
    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()


async def test_generate_appeal_non_existent_id_returns_404(async_client: AsyncClient) -> None:
    """Test triggering AI generation for an appeal that does not exist."""
    response = await async_client.post(f"/appeals/{uuid.uuid4()}/generate")
    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()


# ==========================================
# 4. BOUNDARY VALUES & DUPLICATES
# ==========================================

async def test_create_appeal_empty_counter_evidence_dict_returns_201(async_client: AsyncClient, sample_auth_request: AuthRequest) -> None:
    """Test creating an appeal with an empty dictionary for counter_evidence."""
    payload = {
        "auth_request_id": str(sample_auth_request.id),
        "denial_reason": "Empty dict.",
        "counter_evidence": {}
    }
    response = await async_client.post("/appeals", json=payload)
    assert response.status_code == 201
    assert response.json()["counter_evidence"] == {}


async def test_create_appeal_empty_guidelines_list_returns_201(async_client: AsyncClient, sample_auth_request: AuthRequest) -> None:
    """Test creating an appeal with an empty list for guidelines_cited."""
    payload = {
        "auth_request_id": str(sample_auth_request.id),
        "denial_reason": "Empty list.",
        "guidelines_cited": []
    }
    response = await async_client.post("/appeals", json=payload)
    assert response.status_code == 201
    assert response.json()["guidelines_cited"] == []


async def test_list_appeals_limit_100_returns_200(async_client: AsyncClient) -> None:
    """Test listing appeals with the maximum allowed limit."""
    response = await async_client.get("/appeals?limit=100")
    assert response.status_code == 200
    assert isinstance(response.json(), list)


async def test_list_appeals_limit_101_returns_422(async_client: AsyncClient) -> None:
    """Test listing appeals with a limit exceeding the maximum allowed."""
    response = await async_client.get("/appeals?limit=101")
    assert response.status_code == 422
    assert "limit" in response.json()["detail"][0]["loc"]


async def test_list_appeals_limit_0_returns_422(async_client: AsyncClient) -> None:
    """Test listing appeals with a limit of zero."""
    response = await async_client.get("/appeals?limit=0")
    assert response.status_code == 422
    assert "limit" in response.json()["detail"][0]["loc"]


async def test_list_appeals_skip_negative_returns_422(async_client: AsyncClient) -> None:
    """Test listing appeals with a negative skip value."""
    response = await async_client.get("/appeals?skip=-1")
    assert response.status_code == 422
    assert "skip" in response.json()["detail"][0]["loc"]


async def test_create_multiple_appeals_for_same_auth_request_returns_201(async_client: AsyncClient, sample_auth_request: AuthRequest) -> None:
    """Test that multiple appeals can be created for the same authorization request."""
    payload1 = {
        "auth_request_id": str(sample_auth_request.id),
        "denial_reason": "First appeal"
    }
    payload2 = {
        "auth_request_id": str(sample_auth_request.id),
        "denial_reason": "Second appeal"
    }
    resp1 = await async_client.post("/appeals", json=payload1)
    resp2 = await async_client.post("/appeals", json=payload2)
    
    assert resp1.status_code == 201
    assert resp2.status_code == 201
    assert resp1.json()["id"] != resp2.json()["id"]


async def test_create_appeal_large_payload_returns_201(async_client: AsyncClient, sample_auth_request: AuthRequest) -> None:
    """Test creating an appeal with a very large denial reason string (10KB)."""
    payload = {
        "auth_request_id": str(sample_auth_request.id),
        "denial_reason": "A" * 10000
    }
    response = await async_client.post("/appeals", json=payload)
    assert response.status_code == 201
    assert len(response.json()["denial_reason"]) == 10000


# ==========================================
# 5. SECURITY — SQL INJECTION TESTS
# ==========================================

async def test_create_appeal_sqli_in_denial_reason_returns_201(async_client: AsyncClient, sample_auth_request: AuthRequest) -> None:
    """Test that SQL injection payloads in denial_reason are safely stored as literal strings."""
    payloads = [
        "admin' OR '1'='1",
        "'; DROP TABLE appeals;--",
        "admin\" OR \"1\"=\"1\"",
        "' UNION SELECT 1,2,3--",
        "1; UPDATE appeals SET status='resolved'"
    ]
    for sqli_payload in payloads:
        payload = {
            "auth_request_id": str(sample_auth_request.id),
            "denial_reason": sqli_payload
        }
        response = await async_client.post("/appeals", json=payload)
        assert response.status_code == 201
        assert response.json()["denial_reason"] == sqli_payload


async def test_get_appeal_sqli_in_id_returns_404(async_client: AsyncClient) -> None:
    """Test that SQL injection payloads in the path parameter are rejected by validation."""
    response = await async_client.get("/appeals/1; DROP TABLE appeals;--")
    assert response.status_code == 404


async def test_list_appeals_sqli_in_auth_request_id_returns_422(async_client: AsyncClient) -> None:
    """Test that SQL injection payloads in query parameters are rejected by validation."""
    response = await async_client.get("/appeals?auth_request_id=1' OR '1'='1")
    assert response.status_code == 422
    assert "auth_request_id" in response.json()["detail"][0]["loc"]


# ==========================================
# 6. SECURITY — XSS TESTS
# ==========================================

async def test_create_appeal_xss_in_denial_reason_returns_201(async_client: AsyncClient, sample_auth_request: AuthRequest) -> None:
    """Test that XSS payloads in denial_reason are safely stored as literal strings."""
    payloads = [
        "<script>alert('xss')</script>",
        "<img src=x onerror=alert(1)>",
        "javascript:alert(1)"
    ]
    for xss_payload in payloads:
        payload = {
            "auth_request_id": str(sample_auth_request.id),
            "denial_reason": xss_payload
        }
        response = await async_client.post("/appeals", json=payload)
        assert response.status_code == 201
        assert response.json()["denial_reason"] == xss_payload


# ==========================================
# 7. UNICODE & ENCODING TESTS
# ==========================================

async def test_create_appeal_unicode_emoji_returns_201(async_client: AsyncClient, sample_auth_request: AuthRequest) -> None:
    """Test creating an appeal with emojis in the denial reason."""
    payload = {
        "auth_request_id": str(sample_auth_request.id),
        "denial_reason": "Denied 🚀 🛑"
    }
    response = await async_client.post("/appeals", json=payload)
    assert response.status_code == 201
    assert response.json()["denial_reason"] == "Denied 🚀 🛑"


async def test_create_appeal_cjk_characters_returns_201(async_client: AsyncClient, sample_auth_request: AuthRequest) -> None:
    """Test creating an appeal with CJK characters in the denial reason."""
    payload = {
        "auth_request_id": str(sample_auth_request.id),
        "denial_reason": "拒绝原因"
    }
    response = await async_client.post("/appeals", json=payload)
    assert response.status_code == 201
    assert response.json()["denial_reason"] == "拒绝原因"


async def test_create_appeal_rtl_arabic_returns_201(async_client: AsyncClient, sample_auth_request: AuthRequest) -> None:
    """Test creating an appeal with RTL Arabic text in the denial reason."""
    payload = {
        "auth_request_id": str(sample_auth_request.id),
        "denial_reason": "سبب الرفض"
    }
    response = await async_client.post("/appeals", json=payload)
    assert response.status_code == 201
    assert response.json()["denial_reason"] == "سبب الرفض"


async def test_create_appeal_null_bytes_returns_422_or_500(async_client: AsyncClient, sample_auth_request: AuthRequest) -> None:
    """Test creating an appeal with null bytes in the string. Should be rejected."""
    payload = {
        "auth_request_id": str(sample_auth_request.id),
        "denial_reason": "null\x00byte"
    }
    response = await async_client.post("/appeals", json=payload)
    assert response.status_code in [400, 422, 500]
    assert response.status_code != 201


# ==========================================
# 8. CONCURRENT ACCESS TESTS
# ==========================================

async def test_create_appeal_concurrent_requests_returns_201(async_client: AsyncClient, sample_auth_request: AuthRequest) -> None:
    """Test creating multiple appeals concurrently for the same auth request."""
    payload = {
        "auth_request_id": str(sample_auth_request.id),
        "denial_reason": "Concurrent test"
    }
    
    tasks = [async_client.post("/appeals", json=payload) for _ in range(5)]
    responses = await asyncio.gather(*tasks)
    
    for response in responses:
        assert response.status_code == 201
        assert response.json()["denial_reason"] == "Concurrent test"


# ==========================================
# 9. PAGINATION TESTS
# ==========================================

async def test_list_appeals_pagination_first_page_returns_200(async_client: AsyncClient, sample_appeal: Appeal) -> None:
    """Test listing appeals with pagination parameters for the first page."""
    response = await async_client.get("/appeals?skip=0&limit=10")
    assert response.status_code == 200
    data = response.json()
    assert len(data) >= 1
    assert data[0]["id"] == str(sample_appeal.id)


async def test_list_appeals_pagination_second_page_returns_200(async_client: AsyncClient, sample_appeal: Appeal) -> None:
    """Test listing appeals with pagination parameters for the second page."""
    response = await async_client.get("/appeals?skip=10&limit=10")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)


async def test_list_appeals_pagination_empty_page_returns_200(async_client: AsyncClient) -> None:
    """Test listing appeals with a skip value far beyond the total count returns an empty list."""
    response = await async_client.get("/appeals?skip=999999&limit=10")
    assert response.status_code == 200
    assert response.json() == []


async def test_list_appeals_filter_by_auth_request_id_returns_200(async_client: AsyncClient, sample_appeal: Appeal) -> None:
    """Test filtering the appeals list by a specific auth_request_id."""
    response = await async_client.get(f"/appeals?auth_request_id={sample_appeal.auth_request_id}")
    assert response.status_code == 200
    data = response.json()
    assert len(data) >= 1
    assert data[0]["auth_request_id"] == str(sample_appeal.auth_request_id)


async def test_list_appeals_filter_by_non_existent_auth_request_id_returns_empty_list(async_client: AsyncClient) -> None:
    """Test filtering the appeals list by an auth_request_id that has no appeals."""
    response = await async_client.get(f"/appeals?auth_request_id={uuid.uuid4()}")
    assert response.status_code == 200
    assert response.json() == []


# ==========================================
# 10. STATE TRANSITIONS & INTEGRATION TESTS
# ==========================================

async def test_generate_appeal_triggers_arq_and_updates_status_returns_202(async_client: AsyncClient, sample_appeal: Appeal) -> None:
    """Test triggering AI appeal generation enqueues the task and updates the status."""
    response = await async_client.post(f"/appeals/{sample_appeal.id}/generate")
    assert response.status_code == 202
    data = response.json()
    assert data["message"] == "AI appeal generation successfully triggered."
    assert data["appeal_id"] == str(sample_appeal.id)
    assert data["status"] == "queued"
    
    get_response = await async_client.get(f"/appeals/{sample_appeal.id}")
    assert get_response.status_code == 200
    assert get_response.json()["status"] == "under_review"


async def test_generate_appeal_missing_redis_pool_returns_503(async_client: AsyncClient, sample_appeal: Appeal, app: Any) -> None:
    """Test triggering AI appeal generation when the Redis pool is unavailable."""
    redis_pool = getattr(app.state, "redis_pool", None)
    app.state.redis_pool = None
    
    try:
        response = await async_client.post(f"/appeals/{sample_appeal.id}/generate")
        assert response.status_code == 503
        assert "unavailable" in response.json()["detail"].lower()
    finally:
        app.state.redis_pool = redis_pool


async def test_full_appeal_lifecycle_integration(async_client: AsyncClient, sample_auth_request: AuthRequest) -> None:
    """Test the full lifecycle of an appeal: creation, retrieval, and AI generation trigger."""
    payload = {
        "auth_request_id": str(sample_auth_request.id),
        "denial_reason": "Integration test denial."
    }
    create_resp = await async_client.post("/appeals", json=payload)
    assert create_resp.status_code == 201
    appeal_id = create_resp.json()["id"]
    
    get_resp = await async_client.get(f"/appeals/{appeal_id}")
    assert get_resp.status_code == 200
    assert get_resp.json()["status"] == "draft"
    
    gen_resp = await async_client.post(f"/appeals/{appeal_id}/generate")
    assert gen_resp.status_code == 202
    
    verify_resp = await async_client.get(f"/appeals/{appeal_id}")
    assert verify_resp.status_code == 200
    assert verify_resp.json()["status"] == "under_review"


async def test_generate_appeal_already_resolved_returns_202(async_client: AsyncClient, sample_appeal: Appeal, test_db_session: AsyncSession) -> None:
    """Test triggering AI appeal generation on an already resolved appeal."""
    sample_appeal.status = "resolved"
    await test_db_session.commit()
    
    response = await async_client.post(f"/appeals/{sample_appeal.id}/generate")
    assert response.status_code == 202
    assert response.json()["status"] == "queued"


async def test_get_appeal_invalid_uuid_returns_404(async_client: AsyncClient) -> None:
    """Test retrieving an appeal with an invalid UUID format."""
    response = await async_client.get("/appeals/not-a-uuid")
    assert response.status_code == 404


async def test_generate_appeal_invalid_uuid_returns_404(async_client: AsyncClient) -> None:
    """Test triggering AI appeal generation with an invalid UUID format."""
    response = await async_client.post("/appeals/not-a-uuid/generate")
    assert response.status_code == 404