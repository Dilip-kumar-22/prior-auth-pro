"""ARQ background tasks for the prior-authorisation pipeline.

Two entrypoints, both registered in ``worker.main.WorkerSettings.functions``:

- ``process_auth_request_task(ctx, auth_request_id)`` — runs the full pipeline
  for one ``AuthRequest``: FHIR extract → classify → rules → (optional RAG +
  Gemini) → persist decision. Each phase appends an ``AuthEvent`` row so the
  dashboard's audit trail is complete.

- ``generate_appeal_task(ctx, appeal_id)`` — generates a Markdown appeal
  letter via Gemini for a denied request, persists it on the ``Appeal`` row.

Both tasks are idempotent: re-running with the same id short-circuits when a
prior successful run is detected.

Context dict shape (populated by ``worker.main.startup``):

    ctx["db_engine"]       AsyncEngine
    ctx["session_factory"] async_sessionmaker (added if missing)
    ctx["fhir_base_url"]   str
    ctx["fhir_token"]      Optional[str]
    ctx["fhir_timeout"]    float
"""
from __future__ import annotations

import logging
import time
import traceback
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from engines.rag.engine import RAGEngine
from engines.rules.engine import RulesEngine
from fhir.context import client_from_session
from models.appeal import Appeal, AppealStatus
from models.auth_request import AuthEvent, AuthRequest, EventType
from worker.llm_client import generate_appeal_letter, generate_auth_decision
from worker.schemas import AppealContext, AuthDecision, ClinicalContext

logger = logging.getLogger(__name__)


# ── Internal helpers ──────────────────────────────────────────────────────────


def _to_uuid(value: Any) -> uuid.UUID:
    """Accept either a UUID or a string-of-UUID (ARQ serialises ids as strings)."""
    if isinstance(value, uuid.UUID):
        return value
    return uuid.UUID(str(value))


def _session_factory(ctx: dict[str, Any]) -> async_sessionmaker[AsyncSession]:
    """Get or build a session factory bound to the engine in ctx."""
    factory = ctx.get("session_factory")
    if factory is None:
        engine = ctx.get("db_engine")
        if engine is None:
            raise RuntimeError(
                "ARQ ctx is missing both 'session_factory' and 'db_engine'; "
                "worker.main.startup must populate one of these."
            )
        factory = async_sessionmaker(
            bind=engine, class_=AsyncSession, expire_on_commit=False
        )
        ctx["session_factory"] = factory
    return factory


async def _emit_event(
    session: AsyncSession,
    *,
    auth_request_id: uuid.UUID,
    event_type: EventType,
    payload: Optional[dict[str, Any]] = None,
    agent_name: Optional[str] = None,
    model_used: Optional[str] = None,
    confidence_score: Optional[float] = None,
    latency_ms: Optional[int] = None,
) -> AuthEvent:
    """Append an AuthEvent row for the audit trail and flush it."""
    event = AuthEvent(
        id=uuid.uuid4(),
        auth_request_id=auth_request_id,
        event_type=event_type,
        agent_name=agent_name,
        model_used=model_used,
        payload=payload or {},
        confidence_score=confidence_score,
        latency_ms=latency_ms,
        timestamp=datetime.now(timezone.utc),
    )
    session.add(event)
    await session.flush()
    return event


def _extract_clinical_context(bundle: Optional[dict[str, Any]]) -> ClinicalContext:
    """Build a ClinicalContext from a FHIR Bundle using the existing parsers in
    ``fhir.resources``. Returns a mostly-empty context if the bundle is None.

    A first-pass extractor that's good enough for the rules + RAG paths. The
    Module 2 ExtractionAgent will replace this with an LLM-backed version.
    """
    from fhir.resources import (
        parse_condition,
        parse_medication_request,
        parse_observation,
        parse_patient,
    )

    if not bundle:
        return ClinicalContext()

    patient = parse_patient(bundle)
    conditions = parse_condition(bundle)
    medications = parse_medication_request(bundle)
    observations = parse_observation(bundle)

    age: Optional[int] = None
    birth_date = patient.get("birth_date")
    if birth_date:
        try:
            year = int(str(birth_date).split("-", 1)[0])
            age = max(0, datetime.now(timezone.utc).year - year)
        except (ValueError, IndexError):
            age = None

    diagnoses = [c.get("code") for c in conditions if c.get("code")]
    meds = [
        m.get("medication_display") or m.get("medication_code")
        for m in medications
        if m.get("medication_display") or m.get("medication_code")
    ]
    lab_lines = []
    for o in observations:
        disp = o.get("display") or o.get("code")
        val = o.get("value")
        if disp and val is not None:
            unit = o.get("unit") or ""
            lab_lines.append(f"{disp}: {val}{(' ' + unit) if unit else ''}")

    narrative_parts = []
    if patient.get("gender") and age is not None:
        narrative_parts.append(f"{age}{patient.get('gender', '')[:1].upper()}")
    if diagnoses:
        narrative_parts.append("with " + ", ".join(diagnoses[:3]))
    if meds:
        narrative_parts.append("on " + ", ".join(meds[:3]))
    narrative = ". ".join(p for p in narrative_parts if p)

    return ClinicalContext(
        patient_age=age,
        patient_sex=patient.get("gender"),
        primary_diagnosis_icd10=diagnoses[:1],
        secondary_diagnoses_icd10=diagnoses[1:],
        relevant_medications=[m for m in meds if m],
        failed_prior_therapies=[],
        lab_results_summary="; ".join(lab_lines) if lab_lines else None,
        clinical_narrative=narrative,
    )


def _verdict_to_status(verdict: str) -> str:
    return {
        "approve": "approved",
        "deny": "denied",
        "pend": "pending_documentation",
        "review": "needs_review",
    }.get(verdict, verdict)


async def _existing_decision_event(
    session: AsyncSession, auth_request_id: uuid.UUID
) -> Optional[AuthEvent]:
    """Idempotency check: has this request already had a decision made?"""
    res = await session.execute(
        select(AuthEvent)
        .where(AuthEvent.auth_request_id == auth_request_id)
        .where(AuthEvent.event_type == EventType.decision_made)
        .order_by(AuthEvent.timestamp.desc())
        .limit(1)
    )
    return res.scalar_one_or_none()


# ── Task: process_auth_request_task ───────────────────────────────────────────


async def process_auth_request_task(
    ctx: dict[str, Any], auth_request_id: Any
) -> dict[str, Any]:
    """ARQ task: run the full PA pipeline for one AuthRequest."""
    start = time.time()
    request_uuid = _to_uuid(auth_request_id)
    factory = _session_factory(ctx)

    async with factory() as session:
        # ── Idempotency ──────────────────────────────────────────────────────
        existing = await _existing_decision_event(session, request_uuid)
        if existing is not None:
            logger.info(
                "process_auth_request_task: idempotent skip for %s "
                "(prior decision_made event at %s)",
                request_uuid,
                existing.timestamp,
            )
            payload = existing.payload or {}
            return {
                "status": _verdict_to_status(payload.get("verdict", "review")),
                "auth_request_id": str(request_uuid),
                "verdict": payload.get("verdict"),
                "idempotent": True,
                "latency_ms": int((time.time() - start) * 1000),
            }

        # ── Load the request ─────────────────────────────────────────────────
        req = (
            await session.execute(
                select(AuthRequest).where(AuthRequest.id == request_uuid)
            )
        ).scalar_one_or_none()
        if req is None:
            raise ValueError(f"AuthRequest {request_uuid} not found")

        try:
            return await _run_pipeline(ctx, session, req, start)
        except Exception as exc:
            # Best-effort: record the error event on a fresh session so even a
            # rolled-back primary session doesn't lose the audit trail.
            logger.exception(
                "process_auth_request_task failed for %s: %s", request_uuid, exc
            )
            await session.rollback()
            await _record_error_event(factory, request_uuid, exc)
            raise


async def _run_pipeline(
    ctx: dict[str, Any],
    session: AsyncSession,
    req: AuthRequest,
    start: float,
) -> dict[str, Any]:
    request_uuid = req.id

    # ── FHIR extract → ClinicalContext ───────────────────────────────────────
    fhir_bundle = req.fhir_bundle
    if fhir_bundle is None:
        # Fall back to fetching from FHIR server using the pat ref.
        fhir_client = client_from_session(ctx)
        try:
            fhir_bundle = await fhir_client.search(
                "Patient", {"_id": req.patient_id}
            )
        finally:
            close = getattr(fhir_client, "close", None)
            if close is not None:
                try:
                    await close()
                except Exception:  # pragma: no cover - defensive
                    pass

    clinical = _extract_clinical_context(fhir_bundle)
    await _emit_event(
        session,
        auth_request_id=request_uuid,
        event_type=EventType.data_extracted,
        agent_name="extractor",
        payload={
            "primary_diagnosis_icd10": clinical.primary_diagnosis_icd10,
            "patient_age": clinical.patient_age,
            "n_medications": len(clinical.relevant_medications),
        },
    )

    # ── Classification (lightweight — uses auth_type) ────────────────────────
    await _emit_event(
        session,
        auth_request_id=request_uuid,
        event_type=EventType.classified,
        agent_name="classifier",
        payload={
            "service_category": req.auth_type
            if isinstance(req.auth_type, str)
            else req.auth_type.value,
            "service_requested": req.service_requested,
        },
    )

    # ── Rules engine ─────────────────────────────────────────────────────────
    rules_engine = RulesEngine()
    rules_input = {
        "service_requested": req.service_requested,
        "service_category": req.auth_type
        if isinstance(req.auth_type, str)
        else req.auth_type.value,
        "diagnosis_codes": [c.get("code") for c in (req.diagnosis_codes or [])],
        "payer_id": req.payer_id,
        "plan_id": req.plan_id,
    }
    rules_result: dict[str, Any] = rules_engine.evaluate(rules_input)
    rules_decision = (rules_result or {}).get("decision", "review")
    rules_event_type = (
        EventType.rule_matched
        if rules_decision in ("approve", "deny")
        else EventType.rule_no_match
    )
    await _emit_event(
        session,
        auth_request_id=request_uuid,
        event_type=rules_event_type,
        agent_name="rules_engine",
        payload=rules_result,
    )

    # ── Auto-decide branches ─────────────────────────────────────────────────
    if rules_decision == "approve":
        return await _finalise_decision(
            session,
            request_uuid,
            verdict="approve",
            reasoning=rules_result.get("reason", "Auto-approved per payer policy."),
            confidence=1.0,
            cited_guidelines=[rules_result.get("matched_policy")] if rules_result.get("matched_policy") else [],
            extra_payload={"matched_policy": rules_result.get("matched_policy")},
            agent_name="rules_engine",
            model_used=None,
            start=start,
        )
    if rules_decision == "deny":
        return await _finalise_decision(
            session,
            request_uuid,
            verdict="deny",
            reasoning=rules_result.get("reason", "Auto-denied per payer policy."),
            confidence=1.0,
            cited_guidelines=[rules_result.get("matched_policy")] if rules_result.get("matched_policy") else [],
            extra_payload={"matched_policy": rules_result.get("matched_policy")},
            agent_name="rules_engine",
            model_used=None,
            start=start,
        )

    # ── AI review path: RAG → Gemini ─────────────────────────────────────────
    rag = RAGEngine(session)
    query = clinical.clinical_narrative or req.service_requested
    guidelines = await rag.search(query, top_k=5)
    await _emit_event(
        session,
        auth_request_id=request_uuid,
        event_type=EventType.rag_queried,
        agent_name="rag_engine",
        payload={
            "top_k": 5,
            "n_results": len(guidelines),
            "scores": [g.get("distance") for g in guidelines if "distance" in g],
        },
    )

    decision: AuthDecision = await generate_auth_decision(clinical, guidelines)

    return await _finalise_decision(
        session,
        request_uuid,
        verdict=decision.decision,
        reasoning=decision.reasoning,
        confidence=decision.confidence,
        cited_guidelines=decision.cited_guidelines,
        extra_payload={
            "key_factors": decision.key_factors,
            "required_documentation_missing": decision.required_documentation_missing,
        },
        agent_name="ai_reviewer",
        model_used="gemini-3.1-pro",
        start=start,
    )


async def _finalise_decision(
    session: AsyncSession,
    request_uuid: uuid.UUID,
    *,
    verdict: str,
    reasoning: str,
    confidence: float,
    cited_guidelines: list[Any],
    extra_payload: dict[str, Any],
    agent_name: str,
    model_used: Optional[str],
    start: float,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "verdict": verdict,
        "reasoning": reasoning,
        "confidence": confidence,
        "cited_guidelines": [c for c in cited_guidelines if c],
    }
    payload.update(extra_payload or {})

    await _emit_event(
        session,
        auth_request_id=request_uuid,
        event_type=EventType.decision_made,
        agent_name=agent_name,
        model_used=model_used,
        payload=payload,
        confidence_score=confidence,
        latency_ms=int((time.time() - start) * 1000),
    )
    await session.commit()

    return {
        "status": _verdict_to_status(verdict),
        "auth_request_id": str(request_uuid),
        "verdict": verdict,
        "confidence": confidence,
        "latency_ms": int((time.time() - start) * 1000),
        "idempotent": False,
    }


async def _record_error_event(
    factory: async_sessionmaker[AsyncSession],
    request_uuid: uuid.UUID,
    exc: BaseException,
) -> None:
    """Persist an error AuthEvent on a fresh session (the primary one may be rolled back)."""
    try:
        async with factory() as session:
            await _emit_event(
                session,
                auth_request_id=request_uuid,
                event_type=EventType.flagged_for_review,
                agent_name="error_handler",
                payload={
                    "error": repr(exc),
                    "traceback": traceback.format_exc(),
                },
            )
            await session.commit()
    except Exception:  # pragma: no cover - swallowing to ensure original raises
        logger.exception("Failed to persist error event for %s", request_uuid)


# ── Task: generate_appeal_task ────────────────────────────────────────────────


async def generate_appeal_task(
    ctx: dict[str, Any], appeal_id: Any
) -> dict[str, Any]:
    """ARQ task: generate a Markdown appeal letter for a denied AuthRequest."""
    start = time.time()
    appeal_uuid = _to_uuid(appeal_id)
    factory = _session_factory(ctx)

    async with factory() as session:
        appeal = (
            await session.execute(select(Appeal).where(Appeal.id == appeal_uuid))
        ).scalar_one_or_none()
        if appeal is None:
            raise ValueError(f"Appeal {appeal_uuid} not found")

        # Idempotency: if the letter is already written, return cached result.
        if appeal.appeal_letter and len(appeal.appeal_letter.strip()) > 0:
            logger.info(
                "generate_appeal_task: idempotent skip for %s (letter already populated)",
                appeal_uuid,
            )
            return {
                "status": "generated",
                "appeal_id": str(appeal_uuid),
                "letter_length": len(appeal.appeal_letter),
                "idempotent": True,
                "latency_ms": int((time.time() - start) * 1000),
            }

        # Reconstruct AppealContext from the appeal + linked AuthRequest + decision_made event.
        req = (
            await session.execute(
                select(AuthRequest).where(AuthRequest.id == appeal.auth_request_id)
            )
        ).scalar_one_or_none()
        if req is None:
            raise ValueError(
                f"Appeal {appeal_uuid} references missing AuthRequest {appeal.auth_request_id}"
            )

        decision_event = await _existing_decision_event(session, req.id)
        decision_payload = (decision_event.payload or {}) if decision_event else {}

        clinical = _extract_clinical_context(req.fhir_bundle)
        clinical_summary = (
            clinical.clinical_narrative
            or decision_payload.get("reasoning")
            or "Clinical context unavailable."
        )

        policy_citations = [str(c) for c in (appeal.guidelines_cited or [])]
        # If guidelines_cited holds dicts (per fixture), prefer their text.
        if appeal.guidelines_cited and isinstance(appeal.guidelines_cited[0], dict):
            policy_citations = [
                str(g.get("text") or g.get("id") or g)
                for g in appeal.guidelines_cited
            ]

        ctx_obj = AppealContext(
            denial_reason=appeal.denial_reason,
            clinical_summary=clinical_summary,
            policy_citations=policy_citations,
            patient_age=clinical.patient_age,
            primary_diagnosis_icd10=clinical.primary_diagnosis_icd10[0]
            if clinical.primary_diagnosis_icd10
            else None,
        )

        letter = await generate_appeal_letter(ctx_obj)
        rendered = (
            f"{letter.introduction}\n\n"
            f"{letter.clinical_justification}\n\n"
            f"{letter.policy_citations}\n\n"
            f"{letter.conclusion}"
        )

        appeal.appeal_letter = rendered
        # Bump status to submitted (the closest enum value to "generated and ready").
        # Caller can revert to 'draft' if they want clinician review before submission.
        appeal.status = AppealStatus.submitted
        await session.commit()

        return {
            "status": "generated",
            "appeal_id": str(appeal_uuid),
            "letter_length": len(rendered),
            "idempotent": False,
            "latency_ms": int((time.time() - start) * 1000),
        }
