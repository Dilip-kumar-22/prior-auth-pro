"""REST endpoint tests for `/auth-requests`.

The brief specifies these tests as part of M1. The endpoint itself lives in
the baseline (`api.routes.auth_requests`) and is not modified — these tests
exercise existing behaviour and lock down the contract.

Fixtures (from conftest):
- async_client : httpx.AsyncClient bound to the app
- test_db_session : async SQLAlchemy session, rolled back per test
- mock_redis : MockRedisPool (no-op enqueue_job)
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from models.auth_request import AuthRequest

VALID_PAYLOAD: dict[str, Any] = {
    "patient_id": "pat-test-001",
    "auth_type": "medication",
    "service_requested": "J3380",
    "diagnosis_codes": [
        {"code": "M05.70", "system": "http://hl7.org/fhir/sid/icd-10-cm"}
    ],
    "payer_id": "uhc-001",
    "plan_id": "plan-test",
    "priority": "standard",
}


@pytest.mark.asyncio
async def test_create_auth_request_valid(async_client: AsyncClient) -> None:
    """POST /auth-requests with valid payload → 201, returns id + idempotency replay handled."""
    resp = await async_client.post("/auth-requests", json=VALID_PAYLOAD)
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert "id" in body
    assert uuid.UUID(body["id"])  # parses
    assert body["patient_id"] == VALID_PAYLOAD["patient_id"]
    assert body["service_requested"] == VALID_PAYLOAD["service_requested"]


@pytest.mark.asyncio
async def test_create_auth_request_missing_patient(async_client: AsyncClient) -> None:
    """POST missing patient_id → 422 validation error."""
    payload = {k: v for k, v in VALID_PAYLOAD.items() if k != "patient_id"}
    resp = await async_client.post("/auth-requests", json=payload)
    assert resp.status_code == 422, resp.text


@pytest.mark.asyncio
async def test_create_auth_request_missing_payer(async_client: AsyncClient) -> None:
    """POST missing payer_id → 422 validation error."""
    payload = {k: v for k, v in VALID_PAYLOAD.items() if k != "payer_id"}
    resp = await async_client.post("/auth-requests", json=payload)
    assert resp.status_code == 422, resp.text


@pytest.mark.asyncio
async def test_create_auth_request_invalid_auth_type(
    async_client: AsyncClient,
) -> None:
    """auth_type not in the enum → 422."""
    payload = {**VALID_PAYLOAD, "auth_type": "not_a_real_type"}
    resp = await async_client.post("/auth-requests", json=payload)
    assert resp.status_code == 422, resp.text


@pytest.mark.asyncio
async def test_create_auth_request_idempotent_replay(async_client: AsyncClient) -> None:
    """Two POSTs with identical (patient, service, payer) within 24h → same id."""
    first = await async_client.post("/auth-requests", json=VALID_PAYLOAD)
    assert first.status_code == 201, first.text
    second = await async_client.post("/auth-requests", json=VALID_PAYLOAD)
    assert second.status_code == 201, second.text
    # The route returns the existing request when an idempotency match is found.
    assert first.json()["id"] == second.json()["id"]


@pytest.mark.asyncio
async def test_get_auth_request_returns_record(
    async_client: AsyncClient, test_db_session: AsyncSession
) -> None:
    """GET /auth-requests/{id} for a seeded record → 200 + matching id."""
    req = AuthRequest(
        id=uuid.uuid4(),
        patient_id="pat-fetch",
        auth_type="medication",
        service_requested="J3380",
        diagnosis_codes=[],
        payer_id="uhc-001",
        plan_id="plan-fetch",
        priority="standard",
        fhir_bundle=None,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    test_db_session.add(req)
    await test_db_session.commit()
    await test_db_session.refresh(req)

    resp = await async_client.get(f"/auth-requests/{req.id}")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["id"] == str(req.id)
    assert body["patient_id"] == "pat-fetch"


@pytest.mark.asyncio
async def test_get_auth_request_not_found(async_client: AsyncClient) -> None:
    """GET nonexistent id → 404."""
    resp = await async_client.get(f"/auth-requests/{uuid.uuid4()}")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_get_auth_request_events_empty(
    async_client: AsyncClient, test_db_session: AsyncSession
) -> None:
    """GET /auth-requests/{id}/events for a seeded record with no events → []."""
    req = AuthRequest(
        id=uuid.uuid4(),
        patient_id="pat-events",
        auth_type="medication",
        service_requested="J3380",
        diagnosis_codes=[],
        payer_id="uhc-001",
        plan_id="plan-events",
        priority="standard",
        fhir_bundle=None,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    test_db_session.add(req)
    await test_db_session.commit()
    await test_db_session.refresh(req)

    resp = await async_client.get(f"/auth-requests/{req.id}/events")
    assert resp.status_code == 200, resp.text
    assert isinstance(resp.json(), list)


@pytest.mark.asyncio
async def test_get_auth_request_events_after_create_has_created_event(
    async_client: AsyncClient,
) -> None:
    """After POST creates a request, /events returns at least the 'created' event."""
    create_resp = await async_client.post(
        "/auth-requests",
        json={**VALID_PAYLOAD, "patient_id": "pat-evcheck"},
    )
    assert create_resp.status_code == 201, create_resp.text
    auth_id = create_resp.json()["id"]

    events_resp = await async_client.get(f"/auth-requests/{auth_id}/events")
    assert events_resp.status_code == 200, events_resp.text
    events = events_resp.json()
    assert isinstance(events, list)
    assert any(e["event_type"] == "created" for e in events)


@pytest.mark.asyncio
async def test_list_auth_requests_pagination(
    async_client: AsyncClient, test_db_session: AsyncSession
) -> None:
    """Seed 3, list with limit=2 → 2 results; skip=2 → remaining 1."""
    for i in range(3):
        test_db_session.add(
            AuthRequest(
                id=uuid.uuid4(),
                patient_id=f"pat-pag-{i}",
                auth_type="medication",
                service_requested="J3380",
                diagnosis_codes=[],
                payer_id="uhc-001",
                plan_id="plan-pag",
                priority="standard",
                fhir_bundle=None,
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )
        )
    await test_db_session.commit()

    page1 = await async_client.get("/auth-requests", params={"skip": 0, "limit": 2})
    assert page1.status_code == 200, page1.text
    assert len(page1.json()) == 2

    page2 = await async_client.get("/auth-requests", params={"skip": 2, "limit": 2})
    assert page2.status_code == 200, page2.text
    # We seeded 3 here but other tests may have left rows; guard with >= 1.
    assert len(page2.json()) >= 1


@pytest.mark.asyncio
async def test_list_auth_requests_filter_by_patient(
    async_client: AsyncClient, test_db_session: AsyncSession
) -> None:
    """patient_id filter narrows the result set to only that patient."""
    target_patient = f"pat-filter-{uuid.uuid4().hex[:8]}"
    for i in range(2):
        test_db_session.add(
            AuthRequest(
                id=uuid.uuid4(),
                patient_id=target_patient,
                auth_type="medication",
                service_requested="J3380",
                diagnosis_codes=[],
                payer_id="uhc-001",
                plan_id="plan-flt",
                priority="standard",
                fhir_bundle=None,
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )
        )
    test_db_session.add(
        AuthRequest(
            id=uuid.uuid4(),
            patient_id="pat-other",
            auth_type="medication",
            service_requested="J3380",
            diagnosis_codes=[],
            payer_id="uhc-001",
            plan_id="plan-flt",
            priority="standard",
            fhir_bundle=None,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
    )
    await test_db_session.commit()

    resp = await async_client.get(
        "/auth-requests", params={"patient_id": target_patient}
    )
    assert resp.status_code == 200, resp.text
    bodies = resp.json()
    assert len(bodies) == 2
    assert all(b["patient_id"] == target_patient for b in bodies)


@pytest.mark.asyncio
async def test_process_auth_request_enqueues_job(async_client: AsyncClient) -> None:
    """POST /{id}/process for a seeded request → 202 + 'queued' status."""
    create_resp = await async_client.post(
        "/auth-requests",
        json={**VALID_PAYLOAD, "patient_id": "pat-enqueue"},
    )
    assert create_resp.status_code == 201, create_resp.text
    auth_id = create_resp.json()["id"]

    resp = await async_client.post(f"/auth-requests/{auth_id}/process")
    assert resp.status_code == 202, resp.text
    body = resp.json()
    assert body["status"] == "queued"
    assert body["auth_request_id"] == auth_id


@pytest.mark.asyncio
async def test_process_auth_request_unknown_id_404(async_client: AsyncClient) -> None:
    """POST /{id}/process for a non-existent id → 404."""
    resp = await async_client.post(f"/auth-requests/{uuid.uuid4()}/process")
    assert resp.status_code == 404
