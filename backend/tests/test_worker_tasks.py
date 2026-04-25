"""Integration tests for the two ARQ background tasks in worker.tasks.

These tests run the tasks against the real test database (via test_db_session)
but mock all external services: Gemini via worker.llm_client.generate_*, the
FHIR client via fhir.context.client_from_session, and the RAG engine via the
RAGEngine.search() method.

The brief requires zero real Gemini calls during tests; we enforce that by
patching the module-level helpers and asserting their call counts.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, AsyncGenerator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from models.appeal import Appeal
from models.auth_request import AuthEvent, AuthRequest, EventType
from worker.schemas import AppealLetter, AuthDecision


# ── Helpers / fixtures ────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def task_session_factory(test_db_engine: Any) -> AsyncGenerator[Any, None]:
    """Session factory the worker tasks use internally — they create their own
    session per task so we cannot share the test_db_session.
    """
    factory = async_sessionmaker(
        bind=test_db_engine, class_=AsyncSession, expire_on_commit=False
    )
    yield factory


@pytest_asyncio.fixture
async def worker_ctx(test_db_engine: Any, task_session_factory: Any) -> dict[str, Any]:
    """Minimal ARQ ctx dict matching what worker.main.startup populates."""
    return {
        "db_engine": test_db_engine,
        "session_factory": task_session_factory,
        "fhir_base_url": "http://mock-fhir/fhir",
        "fhir_token": None,
        "fhir_timeout": 30.0,
    }


def _mk_canned_decision(verdict: str = "approve", confidence: float = 0.88) -> AuthDecision:
    return AuthDecision(
        decision=verdict,
        reasoning="Canned decision for test purposes — clinical evidence supports the determination.",
        confidence=confidence,
        key_factors=["test factor 1", "test factor 2"],
        cited_guidelines=["UH-MED-001"],
        required_documentation_missing=[],
    )


def _mk_canned_letter() -> AppealLetter:
    return AppealLetter(
        introduction="I am writing to appeal the denial of prior authorization.",
        clinical_justification="The patient meets coverage criteria as documented.",
        policy_citations="Per policy section 4.3, this service is covered.",
        conclusion="I respectfully request reconsideration.",
    )


async def _seed_request(
    session: AsyncSession,
    *,
    service_requested: str = "J3380",
    diagnosis_codes: list[dict[str, Any]] | None = None,
    payer_id: str = "uhc-001",
) -> AuthRequest:
    diagnosis_codes = diagnosis_codes or [
        {"code": "M05.70", "system": "http://hl7.org/fhir/sid/icd-10-cm"}
    ]
    req = AuthRequest(
        id=uuid.uuid4(),
        patient_id="pat-test",
        auth_type="medication",
        service_requested=service_requested,
        diagnosis_codes=diagnosis_codes,
        payer_id=payer_id,
        plan_id="plan-test",
        priority="standard",
        fhir_bundle={
            "resourceType": "Bundle",
            "type": "collection",
            "entry": [
                {
                    "resource": {
                        "resourceType": "Patient",
                        "id": "pat-test",
                        "gender": "female",
                        "birthDate": "1965-03-12",
                    }
                },
                {
                    "resource": {
                        "resourceType": "Condition",
                        "id": "cond-1",
                        "code": {
                            "coding": [
                                {
                                    "system": "http://hl7.org/fhir/sid/icd-10-cm",
                                    "code": "M05.70",
                                    "display": "Rheumatoid arthritis",
                                }
                            ]
                        },
                        "clinicalStatus": {"coding": [{"code": "active"}]},
                    }
                },
            ],
        },
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    session.add(req)
    await session.commit()
    await session.refresh(req)
    return req


async def _events_for(session: AsyncSession, auth_request_id: uuid.UUID) -> list[AuthEvent]:
    res = await session.execute(
        select(AuthEvent).where(AuthEvent.auth_request_id == auth_request_id).order_by(AuthEvent.timestamp)
    )
    return list(res.scalars().all())


# ── process_auth_request_task ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_process_auth_request_auto_approve(
    worker_ctx: dict[str, Any], test_db_session: AsyncSession
) -> None:
    """Rules engine auto-approves → Gemini NEVER called, decision_made event recorded."""
    from worker import tasks

    req = await _seed_request(test_db_session)

    # Force rules engine to auto-approve.
    fake_rules = MagicMock()
    fake_rules.evaluate.return_value = {
        "decision": "approve",
        "matched_policy": "UH-MED-001",
        "reason": "Auto-approved per UH-MED-001",
        "requires_ai": False,
    }

    with patch("worker.tasks.RulesEngine", return_value=fake_rules), \
         patch("worker.tasks.generate_auth_decision", new=AsyncMock()) as mock_gemini, \
         patch("worker.tasks.RAGEngine") as mock_rag_class:
        result = await tasks.process_auth_request_task(worker_ctx, str(req.id))

    assert result["status"] == "approved"
    assert mock_gemini.await_count == 0  # Gemini NOT called
    mock_rag_class.assert_not_called()  # RAG NOT used

    events = await _events_for(test_db_session, req.id)
    types = [e.event_type for e in events]
    assert EventType.classified in types
    assert EventType.rule_matched in types
    assert EventType.decision_made in types

    decision_event = next(e for e in events if e.event_type == EventType.decision_made)
    assert decision_event.payload["verdict"] == "approve"
    assert decision_event.payload["matched_policy"] == "UH-MED-001"


@pytest.mark.asyncio
async def test_process_auth_request_auto_deny(
    worker_ctx: dict[str, Any], test_db_session: AsyncSession
) -> None:
    """Rules engine auto-denies → Gemini NEVER called, decision_made with deny."""
    from worker import tasks

    req = await _seed_request(test_db_session, service_requested="J3381")

    fake_rules = MagicMock()
    fake_rules.evaluate.return_value = {
        "decision": "deny",
        "matched_policy": "UH-MED-001",
        "reason": "Excluded service code",
        "requires_ai": False,
    }

    with patch("worker.tasks.RulesEngine", return_value=fake_rules), \
         patch("worker.tasks.generate_auth_decision", new=AsyncMock()) as mock_gemini:
        result = await tasks.process_auth_request_task(worker_ctx, str(req.id))

    assert result["status"] == "denied"
    assert mock_gemini.await_count == 0

    events = await _events_for(test_db_session, req.id)
    decision_event = next(e for e in events if e.event_type == EventType.decision_made)
    assert decision_event.payload["verdict"] == "deny"


@pytest.mark.asyncio
async def test_process_auth_request_ai_review_approve(
    worker_ctx: dict[str, Any], test_db_session: AsyncSession
) -> None:
    """Rules → review → RAG → Gemini approve. Full AI path exercised."""
    from worker import tasks

    req = await _seed_request(test_db_session)

    fake_rules = MagicMock()
    fake_rules.evaluate.return_value = {
        "decision": "review",
        "matched_policy": "UH-MED-001",
        "reason": "Requires AI review",
        "requires_ai": True,
    }

    fake_rag = MagicMock()
    fake_rag.search = AsyncMock(return_value=[
        {"id": "g1", "policy_code": "UH-MED-001", "content": "guideline text", "distance": 0.12},
    ])

    canned = _mk_canned_decision(verdict="approve", confidence=0.91)

    with patch("worker.tasks.RulesEngine", return_value=fake_rules), \
         patch("worker.tasks.RAGEngine", return_value=fake_rag), \
         patch("worker.tasks.generate_auth_decision", new=AsyncMock(return_value=canned)) as mock_gemini:
        result = await tasks.process_auth_request_task(worker_ctx, str(req.id))

    assert result["status"] == "approved"
    assert mock_gemini.await_count == 1
    assert fake_rag.search.await_count == 1

    events = await _events_for(test_db_session, req.id)
    types = [e.event_type for e in events]
    assert EventType.rag_queried in types
    assert EventType.decision_made in types

    decision_event = next(e for e in events if e.event_type == EventType.decision_made)
    assert decision_event.payload["verdict"] == "approve"
    assert decision_event.payload["confidence"] == pytest.approx(0.91)


@pytest.mark.asyncio
async def test_process_auth_request_ai_review_deny(
    worker_ctx: dict[str, Any], test_db_session: AsyncSession
) -> None:
    """Same as above but Gemini returns deny."""
    from worker import tasks

    req = await _seed_request(test_db_session)

    fake_rules = MagicMock()
    fake_rules.evaluate.return_value = {
        "decision": "review",
        "requires_ai": True,
        "matched_policy": None,
        "reason": "AI required",
    }
    fake_rag = MagicMock()
    fake_rag.search = AsyncMock(return_value=[])
    canned = _mk_canned_decision(verdict="deny", confidence=0.78)

    with patch("worker.tasks.RulesEngine", return_value=fake_rules), \
         patch("worker.tasks.RAGEngine", return_value=fake_rag), \
         patch("worker.tasks.generate_auth_decision", new=AsyncMock(return_value=canned)):
        result = await tasks.process_auth_request_task(worker_ctx, str(req.id))

    assert result["status"] == "denied"

    events = await _events_for(test_db_session, req.id)
    decision_event = next(e for e in events if e.event_type == EventType.decision_made)
    assert decision_event.payload["verdict"] == "deny"


@pytest.mark.asyncio
async def test_process_auth_request_idempotency(
    worker_ctx: dict[str, Any], test_db_session: AsyncSession
) -> None:
    """Running the task twice with the same id → second run returns cached result,
    Gemini called at most once across both runs.
    """
    from worker import tasks

    req = await _seed_request(test_db_session)

    fake_rules = MagicMock()
    fake_rules.evaluate.return_value = {
        "decision": "review",
        "requires_ai": True,
        "matched_policy": None,
        "reason": "AI required",
    }
    fake_rag = MagicMock()
    fake_rag.search = AsyncMock(return_value=[])
    canned = _mk_canned_decision(verdict="approve", confidence=0.85)

    with patch("worker.tasks.RulesEngine", return_value=fake_rules), \
         patch("worker.tasks.RAGEngine", return_value=fake_rag), \
         patch("worker.tasks.generate_auth_decision", new=AsyncMock(return_value=canned)) as mock_gemini:

        first = await tasks.process_auth_request_task(worker_ctx, str(req.id))
        second = await tasks.process_auth_request_task(worker_ctx, str(req.id))

    assert first["status"] == "approved"
    assert second["status"] == "approved"
    assert second.get("idempotent") is True
    assert mock_gemini.await_count == 1  # second run skipped Gemini

    events = await _events_for(test_db_session, req.id)
    decision_events = [e for e in events if e.event_type == EventType.decision_made]
    assert len(decision_events) == 1  # no duplicate decision events


@pytest.mark.asyncio
async def test_process_auth_request_error_recorded(
    worker_ctx: dict[str, Any], test_db_session: AsyncSession
) -> None:
    """Rules engine raises mid-flow → flagged_for_review event recorded, exception re-raised."""
    from worker import tasks

    req = await _seed_request(test_db_session)

    fake_rules = MagicMock()
    fake_rules.evaluate.side_effect = RuntimeError("synthetic rules failure")

    with patch("worker.tasks.RulesEngine", return_value=fake_rules):
        with pytest.raises(RuntimeError, match="synthetic rules failure"):
            await tasks.process_auth_request_task(worker_ctx, str(req.id))

    events = await _events_for(test_db_session, req.id)
    error_events = [
        e for e in events
        if e.event_type == EventType.flagged_for_review
        and (e.payload or {}).get("error") is not None
    ]
    assert len(error_events) >= 1
    assert "synthetic rules failure" in error_events[-1].payload["error"]


# ── generate_appeal_task ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_generate_appeal_produces_valid_markdown(
    worker_ctx: dict[str, Any], test_db_session: AsyncSession
) -> None:
    """Mock Gemini → letter rendered to markdown with all 4 sections."""
    from worker import tasks

    req = await _seed_request(test_db_session)
    appeal = Appeal(
        id=uuid.uuid4(),
        auth_request_id=req.id,
        denial_reason="Insufficient documentation of conservative therapy.",
        counter_evidence=[],
        appeal_letter=None,
        guidelines_cited=[{"id": "g1", "text": "Aetna Clinical Policy Bulletin 0001"}],
        status="draft",
        outcome=None,
        created_at=datetime.now(timezone.utc),
    )
    test_db_session.add(appeal)
    await test_db_session.commit()
    await test_db_session.refresh(appeal)

    canned_letter = _mk_canned_letter()

    with patch("worker.tasks.generate_appeal_letter", new=AsyncMock(return_value=canned_letter)) as mock_g:
        result = await tasks.generate_appeal_task(worker_ctx, str(appeal.id))

    assert result["status"] == "generated"
    assert mock_g.await_count == 1

    await test_db_session.refresh(appeal)
    assert appeal.appeal_letter is not None
    assert canned_letter.introduction in appeal.appeal_letter
    assert canned_letter.clinical_justification in appeal.appeal_letter
    assert canned_letter.policy_citations in appeal.appeal_letter
    assert canned_letter.conclusion in appeal.appeal_letter
    # Sections separated by blank lines
    assert "\n\n" in appeal.appeal_letter


@pytest.mark.asyncio
async def test_generate_appeal_idempotency(
    worker_ctx: dict[str, Any], test_db_session: AsyncSession
) -> None:
    """Running twice → Gemini called once, second run returns cached result."""
    from worker import tasks

    req = await _seed_request(test_db_session)
    appeal = Appeal(
        id=uuid.uuid4(),
        auth_request_id=req.id,
        denial_reason="Insufficient documentation.",
        counter_evidence=[],
        appeal_letter=None,
        guidelines_cited=[],
        status="draft",
        outcome=None,
        created_at=datetime.now(timezone.utc),
    )
    test_db_session.add(appeal)
    await test_db_session.commit()
    await test_db_session.refresh(appeal)

    canned_letter = _mk_canned_letter()

    with patch("worker.tasks.generate_appeal_letter", new=AsyncMock(return_value=canned_letter)) as mock_g:
        first = await tasks.generate_appeal_task(worker_ctx, str(appeal.id))
        second = await tasks.generate_appeal_task(worker_ctx, str(appeal.id))

    assert first["status"] == "generated"
    assert second["status"] == "generated"
    assert second.get("idempotent") is True
    assert mock_g.await_count == 1
