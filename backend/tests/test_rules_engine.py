import asyncio
import uuid
from typing import Any, Dict, List
from unittest.mock import patch

import pytest

from engines.rules.engine import RulesEngine
from models.auth_request import AuthRequest

pytestmark = pytest.mark.asyncio

# ==========================================
# FIXTURES
# ==========================================

def get_mock_policies() -> List[Dict[str, Any]]:
    """Provide a set of mock payer policies for testing the rules engine."""
    return [
        {
            "payer_name": "UnitedHealth",
            "policy_code": "UH-MED-001",
            "service_category": "medication",
            "cpt_codes": ["J3490"],
            "icd10_required": ["E11.9"],
            "documentation_required": ["clinical_notes"],
            "auto_approve_criteria": {
                "qualifying_diagnoses": ["E11.9"],
            },
            "auto_deny_criteria": {
                "excluded_service_codes": ["J9999"],
                "contraindicated_diagnoses": ["K85.9"]
            },
            "requires_ai_review": True
        },
        {
            "payer_name": "Aetna",
            "policy_code": "AET-IMG-001",
            "service_category": "imaging",
            "cpt_codes": ["70551"],
            "icd10_required": ["G43.001"],
            "documentation_required": ["mri_history"],
            "auto_approve_criteria": {
                "qualifying_diagnoses": ["G43.001"],
            },
            "auto_deny_criteria": {
                "excluded_service_codes": ["70553"],
                "contraindicated_diagnoses": []
            },
            "requires_ai_review": False
        },
        {
            "payer_name": "Cigna",
            "policy_code": "CIG-PROC-001",
            "service_category": "procedure",
            "cpt_codes": ["27447"],
            "icd10_required": ["M17.11"],
            "documentation_required": ["xray_results", "physical_therapy_notes"],
            "auto_approve_criteria": {
                "qualifying_diagnoses": [],
            },
            "auto_deny_criteria": {
                "excluded_service_codes": [],
                "contraindicated_diagnoses": ["E66.01"]
            },
            "requires_ai_review": True
        }
    ]


def get_rules_engine() -> RulesEngine:
    """Provide a RulesEngine instance with mocked policies to avoid file I/O."""
    with patch.object(RulesEngine, '__init__', lambda self: None):
        engine = RulesEngine()
        engine.policies = get_mock_policies()
        return engine


@pytest.fixture
def sample_auth_request() -> AuthRequest:
    """Provide a standard AuthRequest instance for testing."""
    return AuthRequest(
        id=uuid.uuid4(),
        patient_id="pat-123",
        auth_type="medication",
        service_requested="J3490",
        diagnosis_codes=["E11.9"],
        payer_id="UnitedHealth",
        plan_id="UH-Gold",
        priority="standard",
        fhir_bundle={"resourceType": "Bundle", "entry": []}
    )


# ==========================================
# 1. HAPPY PATH TESTS
# ==========================================

async def test_auto_approve_scenario(sample_auth_request: AuthRequest) -> None:
    """Test that a request meeting auto-approve criteria is approved."""
    rules_engine = get_rules_engine()
    result = await rules_engine.evaluate(sample_auth_request)
    
    assert result["decision"] == "approve"
    assert result["matched_policy"] == "UH-MED-001"
    assert "reason" in result
    assert result["requires_ai"] is False


async def test_auto_deny_scenario(sample_auth_request: AuthRequest) -> None:
    """Test that a request meeting auto-deny criteria is denied immediately."""
    rules_engine = get_rules_engine()
    sample_auth_request.service_requested = "J9999"
    
    result = await rules_engine.evaluate(sample_auth_request)
    
    assert result["decision"] == "deny"
    assert result["matched_policy"] == "UH-MED-001"
    assert "reason" in result
    assert result["requires_ai"] is False


async def test_ai_review_scenario(sample_auth_request: AuthRequest) -> None:
    """Test that a request not meeting auto-approve/deny but requiring AI review is flagged."""
    rules_engine = get_rules_engine()
    sample_auth_request.payer_id = "Cigna"
    sample_auth_request.auth_type = "procedure"
    sample_auth_request.service_requested = "27447"
    sample_auth_request.diagnosis_codes = ["M17.11"]
    
    result = await rules_engine.evaluate(sample_auth_request)
    
    assert result["decision"] == "review"
    assert result["matched_policy"] == "CIG-PROC-001"
    assert result["requires_ai"] is True


async def test_auto_deny_contraindicated_diagnosis(sample_auth_request: AuthRequest) -> None:
    """Test that a contraindicated diagnosis triggers an auto-deny."""
    rules_engine = get_rules_engine()
    sample_auth_request.diagnosis_codes = ["K85.9"]
    
    result = await rules_engine.evaluate(sample_auth_request)
    
    assert result["decision"] == "deny"
    assert result["matched_policy"] == "UH-MED-001"


async def test_auto_approve_imaging_scenario(sample_auth_request: AuthRequest) -> None:
    """Test auto-approve for an imaging request."""
    rules_engine = get_rules_engine()
    sample_auth_request.payer_id = "Aetna"
    sample_auth_request.auth_type = "imaging"
    sample_auth_request.service_requested = "70551"
    sample_auth_request.diagnosis_codes = ["G43.001"]
    
    result = await rules_engine.evaluate(sample_auth_request)
    
    assert result["decision"] == "approve"
    assert result["matched_policy"] == "AET-IMG-001"


# ==========================================
# 2. VALIDATION & EDGE CASES
# ==========================================

async def test_evaluate_missing_payer_returns_review(sample_auth_request: AuthRequest) -> None:
    """Test that an unknown payer falls back to manual/AI review."""
    rules_engine = get_rules_engine()
    sample_auth_request.payer_id = "UnknownPayer"
    
    result = await rules_engine.evaluate(sample_auth_request)
    
    assert result["decision"] == "review"
    assert result["matched_policy"] is None
    assert result["requires_ai"] is True


async def test_evaluate_missing_service_code_returns_review(sample_auth_request: AuthRequest) -> None:
    """Test that an unknown service code falls back to review."""
    rules_engine = get_rules_engine()
    sample_auth_request.service_requested = "UNKNOWN-CODE"
    
    result = await rules_engine.evaluate(sample_auth_request)
    
    assert result["decision"] == "review"
    assert result["matched_policy"] is None


async def test_evaluate_empty_diagnosis_codes_returns_review(sample_auth_request: AuthRequest) -> None:
    """Test that empty diagnosis codes cannot auto-approve and fall back to review."""
    rules_engine = get_rules_engine()
    sample_auth_request.diagnosis_codes = []
    
    result = await rules_engine.evaluate(sample_auth_request)
    
    assert result["decision"] == "review"


async def test_evaluate_null_diagnosis_codes_handled_gracefully(sample_auth_request: AuthRequest) -> None:
    """Test that None for diagnosis codes is handled without crashing."""
    rules_engine = get_rules_engine()
    sample_auth_request.diagnosis_codes = None
    
    result = await rules_engine.evaluate(sample_auth_request)
    
    assert result["decision"] == "review"


async def test_evaluate_multiple_diagnoses_one_auto_deny(sample_auth_request: AuthRequest) -> None:
    """Test that if any diagnosis is contraindicated, the request is denied."""
    rules_engine = get_rules_engine()
    sample_auth_request.diagnosis_codes = ["E11.9", "K85.9"]  # One approve, one deny
    
    result = await rules_engine.evaluate(sample_auth_request)
    
    assert result["decision"] == "deny"  # Deny takes precedence


async def test_evaluate_multiple_diagnoses_one_auto_approve(sample_auth_request: AuthRequest) -> None:
    """Test that if one diagnosis qualifies and none contraindicate, it is approved."""
    rules_engine = get_rules_engine()
    sample_auth_request.diagnosis_codes = ["M10.9", "E11.9"]  # One neutral, one approve
    
    result = await rules_engine.evaluate(sample_auth_request)
    
    assert result["decision"] == "approve"


async def test_evaluate_missing_fhir_bundle_handled_gracefully(sample_auth_request: AuthRequest) -> None:
    """Test that a missing FHIR bundle does not crash the engine."""
    rules_engine = get_rules_engine()
    sample_auth_request.fhir_bundle = None
    
    result = await rules_engine.evaluate(sample_auth_request)
    
    assert result["decision"] in ["approve", "deny", "review"]


async def test_evaluate_invalid_auth_type(sample_auth_request: AuthRequest) -> None:
    """Test that an invalid auth type falls back to review."""
    rules_engine = get_rules_engine()
    sample_auth_request.auth_type = "invalid_type"
    
    result = await rules_engine.evaluate(sample_auth_request)
    
    assert result["decision"] == "review"


# ==========================================
# 3. BOUNDARY VALUES
# ==========================================

async def test_evaluate_max_length_service_code(sample_auth_request: AuthRequest) -> None:
    """Test evaluating a service code at the maximum reasonable length."""
    rules_engine = get_rules_engine()
    sample_auth_request.service_requested = "A" * 50
    
    result = await rules_engine.evaluate(sample_auth_request)
    
    assert result["decision"] == "review"


async def test_evaluate_huge_diagnosis_list(sample_auth_request: AuthRequest) -> None:
    """Test evaluating a request with a massive list of diagnosis codes."""
    rules_engine = get_rules_engine()
    sample_auth_request.diagnosis_codes = [f"E{i}.9" for i in range(1000)]
    sample_auth_request.diagnosis_codes.append("E11.9")  # Include the qualifying one
    
    result = await rules_engine.evaluate(sample_auth_request)
    
    assert result["decision"] == "approve"


async def test_evaluate_empty_service_code(sample_auth_request: AuthRequest) -> None:
    """Test evaluating a request with an empty string for service code."""
    rules_engine = get_rules_engine()
    sample_auth_request.service_requested = ""
    
    result = await rules_engine.evaluate(sample_auth_request)
    
    assert result["decision"] == "review"


async def test_evaluate_case_insensitivity_service_code(sample_auth_request: AuthRequest) -> None:
    """Test that service code matching is case-insensitive."""
    rules_engine = get_rules_engine()
    sample_auth_request.service_requested = "j3490"  # Lowercase
    
    result = await rules_engine.evaluate(sample_auth_request)
    
    assert result["decision"] == "approve"


async def test_evaluate_case_insensitivity_diagnosis_code(sample_auth_request: AuthRequest) -> None:
    """Test that diagnosis code matching is case-insensitive."""
    rules_engine = get_rules_engine()
    sample_auth_request.diagnosis_codes = ["e11.9"]  # Lowercase
    
    result = await rules_engine.evaluate(sample_auth_request)
    
    assert result["decision"] == "approve"


# ==========================================
# 4. SECURITY — INJECTION TESTS
# ==========================================

async def test_evaluate_sqli_in_service_code(sample_auth_request: AuthRequest) -> None:
    """Test that SQL injection payloads in service_requested are safely handled (no match)."""
    payloads = [
        "J3490' OR '1'='1",
        "'; DROP TABLE payer_policy;--",
        "\" OR \"1\"=\"1\"",
        "' UNION SELECT 1,2,3--",
        "1; UPDATE payer_policy SET requires_ai_review=false"
    ]
    for sqli_payload in payloads:
        rules_engine = get_rules_engine()
        sample_auth_request.service_requested = sqli_payload
        
        result = await rules_engine.evaluate(sample_auth_request)
        
        assert result["decision"] == "review"
        assert result["matched_policy"] is None


async def test_evaluate_sqli_in_diagnosis_codes(sample_auth_request: AuthRequest) -> None:
    """Test that SQL injection payloads in diagnosis_codes are safely handled."""
    payloads = [
        "E11.9' OR '1'='1",
        "'; DROP TABLE auth_request;--",
    ]
    for sqli_payload in payloads:
        rules_engine = get_rules_engine()
        sample_auth_request.diagnosis_codes = [sqli_payload]
        
        result = await rules_engine.evaluate(sample_auth_request)
        
        assert result["decision"] == "review"


async def test_evaluate_xss_in_payer_id(sample_auth_request: AuthRequest) -> None:
    """Test that XSS payloads in payer_id do not cause issues and result in no match."""
    payloads = [
        "<script>alert('xss')</script>",
        "<img src=x onerror=alert(1)>",
        "javascript:alert(1)"
    ]
    for xss_payload in payloads:
        rules_engine = get_rules_engine()
        sample_auth_request.payer_id = xss_payload
        
        result = await rules_engine.evaluate(sample_auth_request)
        
        assert result["decision"] == "review"


# ==========================================
# 5. UNICODE & ENCODING TESTS
# ==========================================

async def test_evaluate_unicode_emoji_in_service_code(sample_auth_request: AuthRequest) -> None:
    """Test evaluating a service code containing emojis."""
    rules_engine = get_rules_engine()
    sample_auth_request.service_requested = "J3490🚀"
    
    result = await rules_engine.evaluate(sample_auth_request)
    
    assert result["decision"] == "review"


async def test_evaluate_cjk_characters_in_payer_id(sample_auth_request: AuthRequest) -> None:
    """Test evaluating a payer ID with CJK characters."""
    rules_engine = get_rules_engine()
    sample_auth_request.payer_id = "联合健康"
    
    result = await rules_engine.evaluate(sample_auth_request)
    
    assert result["decision"] == "review"


async def test_evaluate_rtl_arabic_in_diagnosis(sample_auth_request: AuthRequest) -> None:
    """Test evaluating a diagnosis code with RTL Arabic text."""
    rules_engine = get_rules_engine()
    sample_auth_request.diagnosis_codes = ["تشخيص"]
    
    result = await rules_engine.evaluate(sample_auth_request)
    
    assert result["decision"] == "review"


async def test_evaluate_null_bytes_in_service_code(sample_auth_request: AuthRequest) -> None:
    """Test evaluating a service code with null bytes."""
    rules_engine = get_rules_engine()
    sample_auth_request.service_requested = "J3490\x00"
    
    result = await rules_engine.evaluate(sample_auth_request)
    
    assert result["decision"] == "review"


# ==========================================
# 6. CONCURRENT ACCESS TESTS
# ==========================================

async def test_evaluate_concurrent_requests() -> None:
    """Test that the rules engine can evaluate multiple requests concurrently without state leakage."""
    rules_engine = get_rules_engine()
    requests = []
    for i in range(100):
        req = AuthRequest(
            id=uuid.uuid4(),
            patient_id=f"pat-{i}",
            auth_type="medication",
            service_requested="J3490" if i % 2 == 0 else "J9999",
            diagnosis_codes=["E11.9"] if i % 2 == 0 else ["K85.9"],
            payer_id="UnitedHealth",
            plan_id="UH-Gold",
            priority="standard",
            fhir_bundle={}
        )
        requests.append(req)
        
    tasks = [rules_engine.evaluate(req) for req in requests]
    results = await asyncio.gather(*tasks)
    
    assert len(results) == 100
    approves = [r for r in results if r["decision"] == "approve"]
    denies = [r for r in results if r["decision"] == "deny"]
    
    assert len(approves) == 50
    assert len(denies) == 50


# ==========================================
# 7. COMPLEX RULE INTERACTIONS
# ==========================================

async def test_evaluate_policy_without_auto_approve_criteria(sample_auth_request: AuthRequest) -> None:
    """Test evaluation when the matched policy lacks auto-approve criteria entirely."""
    rules_engine = get_rules_engine()
    sample_auth_request.payer_id = "Cigna"
    sample_auth_request.auth_type = "procedure"
    sample_auth_request.service_requested = "27447"
    sample_auth_request.diagnosis_codes = ["M17.11"]
    
    result = await rules_engine.evaluate(sample_auth_request)
    
    assert result["decision"] == "review"
    assert result["matched_policy"] == "CIG-PROC-001"


async def test_evaluate_policy_without_auto_deny_criteria(sample_auth_request: AuthRequest) -> None:
    """Test evaluation when the matched policy lacks auto-deny criteria entirely."""
    rules_engine = get_rules_engine()
    sample_auth_request.payer_id = "Aetna"
    sample_auth_request.auth_type = "imaging"
    sample_auth_request.service_requested = "70551"
    sample_auth_request.diagnosis_codes = ["UNKNOWN"]
    
    result = await rules_engine.evaluate(sample_auth_request)
    
    assert result["decision"] == "review"
    assert result["matched_policy"] == "AET-IMG-001"


async def test_evaluate_requires_ai_review_flag_respected(sample_auth_request: AuthRequest) -> None:
    """Test that the requires_ai_review flag from the policy is correctly propagated."""
    rules_engine = get_rules_engine()
    sample_auth_request.payer_id = "Aetna"
    sample_auth_request.auth_type = "imaging"
    sample_auth_request.service_requested = "70551"
    sample_auth_request.diagnosis_codes = ["UNKNOWN"]
    
    result = await rules_engine.evaluate(sample_auth_request)
    
    assert result["decision"] == "review"
    assert result["requires_ai"] is False


async def test_evaluate_malformed_policy_data_handled_gracefully(sample_auth_request: AuthRequest) -> None:
    """Test that if a policy is missing expected keys, the engine doesn't crash."""
    rules_engine = get_rules_engine()
    rules_engine.policies.append({
        "payer_name": "BadPayer",
        "policy_code": "BAD-001",
        "cpt_codes": ["12345"]
    })
    
    sample_auth_request.payer_id = "BadPayer"
    sample_auth_request.service_requested = "12345"
    
    result = await rules_engine.evaluate(sample_auth_request)
    
    assert result["decision"] == "review"
    assert result["matched_policy"] == "BAD-001"


async def test_evaluate_multiple_matching_policies_picks_first(sample_auth_request: AuthRequest) -> None:
    """Test that if multiple policies match the payer and service code, it handles it deterministically."""
    rules_engine = get_rules_engine()
    rules_engine.policies.append({
        "payer_name": "UnitedHealth",
        "policy_code": "UH-MED-002",
        "service_category": "medication",
        "cpt_codes": ["J3490"],
        "auto_approve_criteria": {"qualifying_diagnoses": ["Z99.9"]},
        "auto_deny_criteria": {"excluded_service_codes": []},
        "requires_ai_review": True
    })
    
    sample_auth_request.diagnosis_codes = ["E11.9"]
    
    result = await rules_engine.evaluate(sample_auth_request)
    
    assert result["decision"] == "approve"
    assert result["matched_policy"] == "UH-MED-001"


async def test_evaluate_whitespace_in_service_code(sample_auth_request: AuthRequest) -> None:
    """Test that leading/trailing whitespace in service code is stripped/handled."""
    rules_engine = get_rules_engine()
    sample_auth_request.service_requested = "  J3490  "
    
    result = await rules_engine.evaluate(sample_auth_request)
    
    assert result["decision"] == "approve"


async def test_evaluate_whitespace_in_diagnosis_codes(sample_auth_request: AuthRequest) -> None:
    """Test that leading/trailing whitespace in diagnosis codes is stripped/handled."""
    rules_engine = get_rules_engine()
    sample_auth_request.diagnosis_codes = ["  E11.9  "]
    
    result = await rules_engine.evaluate(sample_auth_request)
    
    assert result["decision"] == "approve"


async def test_evaluate_no_policies_loaded(sample_auth_request: AuthRequest) -> None:
    """Test evaluation when the engine has no policies loaded."""
    rules_engine = get_rules_engine()
    rules_engine.policies = []
    
    result = await rules_engine.evaluate(sample_auth_request)
    
    assert result["decision"] == "review"
    assert result["matched_policy"] is None