"""Gemini client used by the worker's clinical-reasoning tasks.

The brief's three behaviours that matter:

1.  Structured output: we POST to Gemini's REST endpoint with a
    ``response_schema`` derived from the requested Pydantic model and parse
    the returned JSON back into that model.
2.  Retry on transient outage: 503 / 429 / network errors get retried up to
    ``MAX_ATTEMPTS_PER_MODEL`` times with exponential backoff (2s, 4s, 8s).
3.  Fallback chain: when a model exhausts its retries, walk through
    ``FALLBACK_CHAIN`` (Pro → Pro → Flash → Flash) until one succeeds, or
    raise ``GeminiAllModelsFailedError`` if every step in the chain fails.

We deliberately avoid the ``google-generativeai`` SDK; the existing baseline
(``engines/rag/engine.py``) talks to the REST API with httpx, and we follow
that pattern to keep dependencies tight.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from typing import Any, Optional, Type, TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from worker.schemas import (
    AppealContext,
    AppealLetter,
    AuthDecision,
    ClinicalContext,
)

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)


# ── Retry / fallback configuration ────────────────────────────────────────────

# Per the M1 brief: gemini-3.1-pro → 2.5-pro → 3-flash → 2.5-flash.
FALLBACK_CHAIN: list[str] = [
    "gemini-3.1-pro",
    "gemini-2.5-pro",
    "gemini-3-flash",
    "gemini-2.5-flash",
]

MAX_ATTEMPTS_PER_MODEL: int = 3
BACKOFF_SECONDS: list[int] = [2, 4, 8]  # used at attempts 1, 2, 3 -> sleeps 2s, 4s

GEMINI_API_BASE: str = "https://generativelanguage.googleapis.com/v1beta"
RETRYABLE_STATUS_CODES: set[int] = {429, 500, 502, 503, 504}


# ── Errors ────────────────────────────────────────────────────────────────────


class GeminiAllModelsFailedError(RuntimeError):
    """Raised when every model in the fallback chain has exhausted its retries."""


# ── Prompts (M2 will externalise these to jinja2 templates) ───────────────────


AUTH_DECISION_PROMPT_TEMPLATE = """You are a board-certified physician reviewer for a US health insurer's
prior-authorisation department. Determine whether the requested service is
medically necessary based on the patient's clinical context and the relevant
payer guidelines below.

CLINICAL CONTEXT (extracted from the patient's FHIR record):
{clinical_block}

RELEVANT PAYER GUIDELINES (top {n_guidelines} matches from policy library):
{guidelines_block}

Return a JSON object matching this schema exactly:
- decision: one of "approve", "deny", "pend" (use "pend" when documentation is missing)
- reasoning: 3-5 sentences plainly explaining the determination
- confidence: float 0.0-1.0
- key_factors: list of 2-5 short bullet phrases
- cited_guidelines: list of policy codes you referenced
- required_documentation_missing: list of any missing documents (empty if none)

Be conservative — when in doubt, prefer "pend" with a clear list of missing
documentation rather than approving or denying outright.
"""


APPEAL_LETTER_PROMPT_TEMPLATE = """You are an experienced physician writing a formal appeal letter to a US
health insurer that has denied a prior-authorisation request. The letter
must be persuasive, fact-based, and grounded in the patient's clinical
record and the payer's own coverage policies.

DENIAL REASON:
{denial_reason}

CLINICAL SUMMARY:
{clinical_summary}

PAYER POLICY CITATIONS:
{policy_citations_block}

PATIENT FACTS:
- Age: {patient_age}
- Primary diagnosis (ICD-10): {primary_diagnosis_icd10}

Write the letter as a JSON object with these four paragraphs:
- introduction: salutation + statement of purpose (2-3 sentences)
- clinical_justification: paragraph linking patient facts to coverage criteria
- policy_citations: paragraph quoting / paraphrasing the payer's own policy
- conclusion: respectful request for reconsideration + closing (2-3 sentences)

Each paragraph must be plain prose — no bullet lists, no headers.
"""


# ── Pydantic-to-JSON-Schema helper ────────────────────────────────────────────


def _pydantic_to_response_schema(model_cls: Type[BaseModel]) -> dict[str, Any]:
    """Convert a Pydantic v2 model to the subset of JSON Schema that Gemini's
    ``response_schema`` field accepts.

    Gemini's structured output supports a restricted form of JSON Schema —
    notably it does NOT support ``$ref``, ``$defs``, or ``allOf``/``anyOf`` of
    arbitrary shapes. We strip those out and rely on validation against the
    pydantic model after parsing.
    """
    schema = model_cls.model_json_schema()
    schema.pop("$defs", None)
    schema.pop("definitions", None)
    return schema


# ── Client ────────────────────────────────────────────────────────────────────


class GeminiClient:
    """Thin async wrapper around Gemini's REST ``:generateContent`` endpoint."""

    def __init__(
        self,
        api_key: str,
        model: str = "gemini-3.1-pro",
        timeout: float = 60.0,
    ) -> None:
        if not api_key:
            raise ValueError("api_key is required (set GEMINI_API_KEY in env)")
        self.api_key = api_key
        self.model = model
        self.timeout = timeout

    # ── Public API ────────────────────────────────────────────────────────────

    async def generate_structured(
        self,
        prompt: str,
        schema: Type[T],
        max_tokens: int = 4096,
        temperature: float = 0.2,
    ) -> T:
        """Generate a response constrained to ``schema`` and return a parsed instance."""
        payload = self._build_payload(
            prompt=prompt,
            response_schema=_pydantic_to_response_schema(schema),
            max_tokens=max_tokens,
            temperature=temperature,
        )
        raw = await self._call_with_fallback(payload)
        if isinstance(raw, dict):
            data = raw
        elif isinstance(raw, str):
            data = json.loads(raw)
        else:
            raise TypeError(f"Unexpected payload type: {type(raw).__name__}")

        try:
            return schema.model_validate(data)
        except ValidationError as e:
            logger.error(
                "Gemini returned a payload that did not validate against %s: %s",
                schema.__name__,
                e,
            )
            raise

    async def generate_text(
        self,
        prompt: str,
        max_tokens: int = 2048,
        temperature: float = 0.3,
    ) -> str:
        """Generate unstructured text and return as a string."""
        payload = self._build_payload(
            prompt=prompt,
            response_schema=None,
            max_tokens=max_tokens,
            temperature=temperature,
        )
        raw = await self._call_with_fallback(payload)
        if isinstance(raw, str):
            return raw
        if isinstance(raw, dict) and "text" in raw:
            return str(raw["text"])
        return json.dumps(raw)

    # ── Internal: payload + REST ──────────────────────────────────────────────

    def _build_payload(
        self,
        *,
        prompt: str,
        response_schema: Optional[dict[str, Any]],
        max_tokens: int,
        temperature: float,
    ) -> dict[str, Any]:
        generation_config: dict[str, Any] = {
            "temperature": temperature,
            "maxOutputTokens": max_tokens,
        }
        if response_schema is not None:
            generation_config["responseMimeType"] = "application/json"
            generation_config["responseSchema"] = response_schema

        return {
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": generation_config,
        }

    async def _call_with_fallback(self, payload: dict[str, Any]) -> Any:
        """Walk the fallback chain, retrying on each model before giving up."""
        first_idx = (
            FALLBACK_CHAIN.index(self.model)
            if self.model in FALLBACK_CHAIN
            else 0
        )
        chain = FALLBACK_CHAIN[first_idx:]

        last_error: Optional[BaseException] = None
        for chain_pos, model in enumerate(chain):
            for attempt in range(1, MAX_ATTEMPTS_PER_MODEL + 1):
                start = time.time()
                try:
                    result = await self._post_generate_content(model=model, payload=payload)
                except httpx.HTTPStatusError as e:
                    if e.response.status_code in RETRYABLE_STATUS_CODES:
                        last_error = e
                        elapsed_ms = int((time.time() - start) * 1000)
                        logger.warning(
                            "Gemini %s attempt %d/%d returned %d (%dms); retrying",
                            model,
                            attempt,
                            MAX_ATTEMPTS_PER_MODEL,
                            e.response.status_code,
                            elapsed_ms,
                        )
                        if attempt < MAX_ATTEMPTS_PER_MODEL:
                            await asyncio.sleep(BACKOFF_SECONDS[attempt - 1])
                            continue
                        # Out of retries on this model — fall through to next.
                        if chain_pos < len(chain) - 1:
                            logger.warning(
                                "Gemini %s exhausted retries; falling back to %s",
                                model,
                                chain[chain_pos + 1],
                            )
                        break
                    # Non-retryable HTTP error — propagate.
                    raise
                except httpx.RequestError as e:
                    last_error = e
                    elapsed_ms = int((time.time() - start) * 1000)
                    logger.warning(
                        "Gemini %s attempt %d/%d network error (%dms): %s",
                        model,
                        attempt,
                        MAX_ATTEMPTS_PER_MODEL,
                        elapsed_ms,
                        e,
                    )
                    if attempt < MAX_ATTEMPTS_PER_MODEL:
                        await asyncio.sleep(BACKOFF_SECONDS[attempt - 1])
                        continue
                    if chain_pos < len(chain) - 1:
                        logger.warning(
                            "Gemini %s exhausted retries; falling back to %s",
                            model,
                            chain[chain_pos + 1],
                        )
                    break
                else:
                    elapsed_ms = int((time.time() - start) * 1000)
                    logger.info(
                        "Gemini %s succeeded on attempt %d (%dms)",
                        model,
                        attempt,
                        elapsed_ms,
                    )
                    return result

        raise GeminiAllModelsFailedError(
            f"All models in fallback chain failed: {chain}"
        ) from last_error

    async def _post_generate_content(
        self,
        *,
        model: str,
        payload: dict[str, Any],
    ) -> Any:
        """Single POST to Gemini's :generateContent endpoint.

        Returns the parsed text part of the first candidate. Tests patch this
        method to inject canned responses or simulate transient failures.
        """
        url = f"{GEMINI_API_BASE}/models/{model}:generateContent"
        params = {"key": self.api_key}

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(url, params=params, json=payload)
            resp.raise_for_status()
            data = resp.json()

        candidates = data.get("candidates", [])
        if not candidates:
            return ""
        parts = candidates[0].get("content", {}).get("parts", [])
        if not parts:
            return ""
        text = parts[0].get("text", "")

        # If we asked for JSON, try to parse — caller may want dict directly.
        if payload.get("generationConfig", {}).get("responseMimeType") == "application/json":
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                # Fall back to returning the raw string; caller decides.
                return text
        return text


# ── Module-level helpers (called from worker.tasks) ───────────────────────────


def _format_clinical_block(clinical: ClinicalContext) -> str:
    parts = [
        f"- Age: {clinical.patient_age if clinical.patient_age is not None else 'unknown'}",
        f"- Sex: {clinical.patient_sex or 'unknown'}",
        f"- Primary diagnoses (ICD-10): {', '.join(clinical.primary_diagnosis_icd10) or 'none recorded'}",
        f"- Secondary diagnoses (ICD-10): {', '.join(clinical.secondary_diagnoses_icd10) or 'none'}",
        f"- Active medications: {', '.join(clinical.relevant_medications) or 'none recorded'}",
        f"- Failed prior therapies: {', '.join(clinical.failed_prior_therapies) or 'none recorded'}",
        f"- Lab summary: {clinical.lab_results_summary or 'none provided'}",
    ]
    if clinical.clinical_narrative:
        parts.append(f"- Narrative: {clinical.clinical_narrative}")
    return "\n".join(parts)


def _format_guidelines_block(guidelines: list[dict[str, Any]]) -> str:
    if not guidelines:
        return "No guidelines retrieved."
    lines = []
    for i, g in enumerate(guidelines, start=1):
        code = g.get("policy_code") or g.get("id") or f"guideline-{i}"
        text = g.get("text") or g.get("content") or g.get("body") or ""
        lines.append(f"[{code}] {text}".strip())
    return "\n".join(lines)


def _format_policy_citations_block(citations: list[str]) -> str:
    if not citations:
        return "No policy citations available."
    return "\n".join(f"- {c}" for c in citations)


def _build_client(model: str = "gemini-3.1-pro") -> GeminiClient:
    api_key = os.environ.get("GEMINI_API_KEY", "")
    return GeminiClient(api_key=api_key, model=model)


async def generate_auth_decision(
    clinical: ClinicalContext,
    relevant_guidelines: list[dict[str, Any]],
    *,
    client: Optional[GeminiClient] = None,
) -> AuthDecision:
    """Build the auth-decision prompt and ask Gemini for a structured AuthDecision."""
    prompt = AUTH_DECISION_PROMPT_TEMPLATE.format(
        clinical_block=_format_clinical_block(clinical),
        n_guidelines=len(relevant_guidelines),
        guidelines_block=_format_guidelines_block(relevant_guidelines),
    )
    c = client or _build_client()
    return await c.generate_structured(prompt, AuthDecision)


async def generate_appeal_letter(
    ctx: AppealContext,
    *,
    client: Optional[GeminiClient] = None,
) -> AppealLetter:
    """Build the appeal-letter prompt and ask Gemini for a structured AppealLetter."""
    prompt = APPEAL_LETTER_PROMPT_TEMPLATE.format(
        denial_reason=ctx.denial_reason,
        clinical_summary=ctx.clinical_summary,
        policy_citations_block=_format_policy_citations_block(ctx.policy_citations),
        patient_age=ctx.patient_age if ctx.patient_age is not None else "unknown",
        primary_diagnosis_icd10=ctx.primary_diagnosis_icd10 or "unknown",
    )
    c = client or _build_client()
    return await c.generate_structured(prompt, AppealLetter)
