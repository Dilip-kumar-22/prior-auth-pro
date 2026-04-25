"""Tests for `worker.llm_client.GeminiClient` retry + fallback behaviour.

Per M1 brief: zero real Gemini API calls during the test run. We patch the
internal `_post_generate_content` method (the single httpx call site) and
control the simulated success/503/429 sequence from there.
"""
from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from worker.llm_client import (
    FALLBACK_CHAIN,
    GeminiAllModelsFailedError,
    GeminiClient,
    generate_appeal_letter,
    generate_auth_decision,
)
from worker.schemas import (
    AppealContext,
    AppealLetter,
    AuthDecision,
    ClinicalContext,
)


def _http_503() -> httpx.HTTPStatusError:
    """Build a httpx.HTTPStatusError that looks like a 503 from Gemini."""
    request = httpx.Request("POST", "https://example/test")
    response = httpx.Response(
        status_code=503,
        request=request,
        content=b'{"error": {"message": "Service Unavailable"}}',
    )
    return httpx.HTTPStatusError("503", request=request, response=response)


def _http_429() -> httpx.HTTPStatusError:
    request = httpx.Request("POST", "https://example/test")
    response = httpx.Response(
        status_code=429,
        request=request,
        content=b'{"error": {"message": "Too Many Requests"}}',
    )
    return httpx.HTTPStatusError("429", request=request, response=response)


def _canned_decision_json() -> dict[str, Any]:
    return {
        "decision": "approve",
        "reasoning": "Patient meets all coverage criteria for this medication.",
        "confidence": 0.92,
        "key_factors": ["RA diagnosis confirmed", "Failed methotrexate trial"],
        "cited_guidelines": ["UH-MED-001"],
        "required_documentation_missing": [],
    }


def _canned_letter_json() -> dict[str, Any]:
    return {
        "introduction": "I am writing to appeal the denial of prior authorization.",
        "clinical_justification": "The patient has a documented diagnosis with failed conservative therapy.",
        "policy_citations": "Per the payer's medical policy section 4.3, this service is covered.",
        "conclusion": "I respectfully request reconsideration of this denial.",
    }


@pytest.mark.asyncio
async def test_generate_structured_returns_parsed_model_on_first_try():
    """Happy path: one successful call returns a validated AuthDecision."""
    client = GeminiClient(api_key="test-key", model="gemini-3.1-pro")

    with patch.object(
        client,
        "_post_generate_content",
        new=AsyncMock(return_value=_canned_decision_json()),
    ) as mock_post:
        result = await client.generate_structured("test prompt", AuthDecision)

    assert isinstance(result, AuthDecision)
    assert result.decision == "approve"
    assert result.confidence == 0.92
    assert mock_post.await_count == 1


@pytest.mark.asyncio
async def test_generate_structured_retries_on_503_with_backoff():
    """503 retried up to 3 times with exponential backoff, then succeeds."""
    client = GeminiClient(api_key="test-key", model="gemini-3.1-pro")

    side_effects = [_http_503(), _http_503(), _canned_decision_json()]

    with patch.object(
        client, "_post_generate_content", new=AsyncMock(side_effect=side_effects)
    ) as mock_post:
        with patch("worker.llm_client.asyncio.sleep", new=AsyncMock()) as mock_sleep:
            result = await client.generate_structured("test prompt", AuthDecision)

    assert isinstance(result, AuthDecision)
    assert mock_post.await_count == 3
    # Two backoff sleeps (2s and 4s)
    assert mock_sleep.await_count == 2
    backoffs = [c.args[0] for c in mock_sleep.await_args_list]
    assert backoffs == [2, 4]


@pytest.mark.asyncio
async def test_generate_structured_falls_back_through_model_chain_on_persistent_503():
    """After exhausting retries on a model, fall back to the next model in chain."""
    client = GeminiClient(api_key="test-key", model="gemini-3.1-pro")

    # Pro, 2.5-pro, 3-flash all 503 (3 attempts each = 9 fails).
    # Then 2.5-flash succeeds.
    side_effects = [_http_503()] * 9 + [_canned_decision_json()]

    with patch.object(
        client, "_post_generate_content", new=AsyncMock(side_effect=side_effects)
    ) as mock_post:
        with patch("worker.llm_client.asyncio.sleep", new=AsyncMock()):
            result = await client.generate_structured("test prompt", AuthDecision)

    assert isinstance(result, AuthDecision)
    # 3 attempts × 4 models = 12 max; we hit on the 10th (4th model, attempt 1)
    assert mock_post.await_count == 10
    # Verify the fallback walked the chain in order
    models_used = [c.kwargs.get("model") or c.args[0] for c in mock_post.call_args_list]
    assert models_used[0] == FALLBACK_CHAIN[0]
    assert models_used[3] == FALLBACK_CHAIN[1]
    assert models_used[6] == FALLBACK_CHAIN[2]
    assert models_used[9] == FALLBACK_CHAIN[3]


@pytest.mark.asyncio
async def test_generate_structured_raises_when_all_models_fail():
    """If every model exhausts retries, raise GeminiAllModelsFailedError."""
    client = GeminiClient(api_key="test-key", model="gemini-3.1-pro")

    # 4 models × 3 attempts = 12 failures
    side_effects = [_http_503()] * 12

    with patch.object(
        client, "_post_generate_content", new=AsyncMock(side_effect=side_effects)
    ):
        with patch("worker.llm_client.asyncio.sleep", new=AsyncMock()):
            with pytest.raises(GeminiAllModelsFailedError):
                await client.generate_structured("test prompt", AuthDecision)


@pytest.mark.asyncio
async def test_generate_structured_treats_429_same_as_503():
    """Rate-limit (429) triggers same retry+fallback as 503."""
    client = GeminiClient(api_key="test-key", model="gemini-3.1-pro")

    side_effects = [_http_429(), _canned_decision_json()]

    with patch.object(
        client, "_post_generate_content", new=AsyncMock(side_effect=side_effects)
    ) as mock_post:
        with patch("worker.llm_client.asyncio.sleep", new=AsyncMock()):
            result = await client.generate_structured("test prompt", AuthDecision)

    assert isinstance(result, AuthDecision)
    assert mock_post.await_count == 2


@pytest.mark.asyncio
async def test_generate_structured_does_not_retry_other_http_errors():
    """A 400 (bad request) is not retryable — propagate immediately."""
    client = GeminiClient(api_key="test-key", model="gemini-3.1-pro")

    request = httpx.Request("POST", "https://example/test")
    response = httpx.Response(
        status_code=400,
        request=request,
        content=b'{"error": {"message": "Bad Request"}}',
    )
    bad_request = httpx.HTTPStatusError("400", request=request, response=response)

    with patch.object(
        client,
        "_post_generate_content",
        new=AsyncMock(side_effect=bad_request),
    ) as mock_post:
        with pytest.raises(httpx.HTTPStatusError):
            await client.generate_structured("test prompt", AuthDecision)

    assert mock_post.await_count == 1


@pytest.mark.asyncio
async def test_generate_text_returns_string():
    """generate_text returns the text payload as a string."""
    client = GeminiClient(api_key="test-key", model="gemini-3.1-pro")

    with patch.object(
        client,
        "_post_generate_content",
        new=AsyncMock(return_value="Plain text response."),
    ):
        result = await client.generate_text("test prompt")

    assert result == "Plain text response."


@pytest.mark.asyncio
async def test_generate_auth_decision_helper_returns_auth_decision(monkeypatch):
    """The module-level helper builds the prompt and calls generate_structured."""
    captured = {}

    async def fake_generate_structured(self, prompt, schema, **kwargs):
        captured["prompt"] = prompt
        captured["schema"] = schema
        return AuthDecision(**_canned_decision_json())

    monkeypatch.setattr(GeminiClient, "generate_structured", fake_generate_structured)
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")

    clinical = ClinicalContext(
        patient_age=58,
        patient_sex="female",
        primary_diagnosis_icd10=["M05.70"],
        clinical_narrative="58F with seropositive RA, failed methotrexate.",
    )
    guidelines = [{"policy_code": "UH-MED-001", "text": "Coverage criteria..."}]

    decision = await generate_auth_decision(clinical, guidelines)

    assert isinstance(decision, AuthDecision)
    assert decision.decision == "approve"
    assert "M05.70" in captured["prompt"]
    assert "UH-MED-001" in captured["prompt"]
    assert captured["schema"] is AuthDecision


@pytest.mark.asyncio
async def test_generate_appeal_letter_helper_returns_appeal_letter(monkeypatch):
    """The appeal helper builds the prompt and calls generate_structured."""
    captured = {}

    async def fake_generate_structured(self, prompt, schema, **kwargs):
        captured["prompt"] = prompt
        captured["schema"] = schema
        return AppealLetter(**_canned_letter_json())

    monkeypatch.setattr(GeminiClient, "generate_structured", fake_generate_structured)
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")

    ctx = AppealContext(
        denial_reason="Insufficient documentation of conservative therapy.",
        clinical_summary="62yo male with chronic knee pain, failed PT and NSAIDs.",
        policy_citations=["BCBS-ORTHO-2024-007"],
        patient_age=62,
        primary_diagnosis_icd10="M17.11",
    )

    letter = await generate_appeal_letter(ctx)

    assert isinstance(letter, AppealLetter)
    assert "Insufficient documentation" in captured["prompt"]
    assert "BCBS-ORTHO-2024-007" in captured["prompt"]
    assert captured["schema"] is AppealLetter


def test_fallback_chain_is_pro_to_flash():
    """The brief mandates this exact fallback order."""
    assert FALLBACK_CHAIN == [
        "gemini-3.1-pro",
        "gemini-2.5-pro",
        "gemini-3-flash",
        "gemini-2.5-flash",
    ]
