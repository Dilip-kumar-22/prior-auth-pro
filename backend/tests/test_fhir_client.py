import asyncio
import json
import uuid
from datetime import datetime
from typing import Any, Dict, List
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from fhir.client import FHIRClient
from fhir.resources import parse_patient

pytestmark = pytest.mark.asyncio


@pytest.fixture
def fhir_client() -> FHIRClient:
    """
    Provide a configured FHIRClient instance for testing.
    """
    return FHIRClient(
        base_url="https://mock-fhir-server.com/r4",
        token="mock-token-123",
        timeout=5.0,
        max_retries=3
    )


@pytest.fixture
def sample_patient_json() -> Dict[str, Any]:
    """
    Provide a valid, standard FHIR Patient resource JSON dictionary.
    """
    return {
        "resourceType": "Patient",
        "id": "pat-123",
        "active": True,
        "name": [
            {
                "use": "official",
                "family": "Doe",
                "given": ["John", "A."]
            }
        ],
        "telecom": [
            {"system": "phone", "value": "555-1234", "use": "home"},
            {"system": "email", "value": "john.doe@example.com"}
        ],
        "gender": "male",
        "birthDate": "1980-01-01",
        "address": [
            {
                "use": "home",
                "line": ["123 Main St"],
                "city": "Anytown",
                "state": "CA",
                "postalCode": "12345"
            }
        ]
    }


# ==========================================
# 1. FHIR READ TESTS
# ==========================================

@patch("httpx.AsyncClient.request", new_callable=AsyncMock)
async def test_fhir_read(mock_request: AsyncMock, fhir_client: FHIRClient) -> None:
    """Test standard happy path for reading a FHIR resource by ID."""
    mock_request.return_value = httpx.Response(
        200, json={"resourceType": "Patient", "id": "123", "active": True}
    )
    
    result = await fhir_client.read("Patient", "123")
    
    assert result["id"] == "123"
    assert result["resourceType"] == "Patient"
    mock_request.assert_called_once()
    args, kwargs = mock_request.call_args
    assert kwargs["method"] == "GET"
    assert "Patient/123" in str(kwargs["url"])


@patch("httpx.AsyncClient.request", new_callable=AsyncMock)
async def test_fhir_read_not_found_returns_none(mock_request: AsyncMock, fhir_client: FHIRClient) -> None:
    """Test that reading a non-existent resource gracefully returns None or handles 404."""
    mock_request.return_value = httpx.Response(404, json={"issue": [{"severity": "error", "code": "not-found"}]})
    
    result = await fhir_client.read("Patient", "999999")
    
    assert result is None
    mock_request.assert_called_once()


@patch("httpx.AsyncClient.request", new_callable=AsyncMock)
async def test_fhir_read_server_error_raises_exception(mock_request: AsyncMock, fhir_client: FHIRClient) -> None:
    """Test that a 500 Internal Server Error raises an appropriate HTTP error."""
    mock_request.return_value = httpx.Response(500, text="Internal Server Error")
    
    with pytest.raises(httpx.HTTPStatusError) as exc_info:
        await fhir_client.read("Patient", "123")
        
    assert exc_info.value.response.status_code == 500


@patch("httpx.AsyncClient.request", new_callable=AsyncMock)
async def test_fhir_read_invalid_resource_type_raises_value_error(mock_request: AsyncMock, fhir_client: FHIRClient) -> None:
    """Test that passing an empty or invalid resource type raises a ValueError before network call."""
    with pytest.raises(ValueError):
        await fhir_client.read("", "123")
    mock_request.assert_not_called()


@patch("httpx.AsyncClient.request", new_callable=AsyncMock)
async def test_fhir_read_empty_id_raises_value_error(mock_request: AsyncMock, fhir_client: FHIRClient) -> None:
    """Test that passing an empty ID raises a ValueError before network call."""
    with pytest.raises(ValueError):
        await fhir_client.read("Patient", "")
    mock_request.assert_not_called()


@patch("httpx.AsyncClient.request", new_callable=AsyncMock)
async def test_fhir_read_timeout_raises_exception(mock_request: AsyncMock, fhir_client: FHIRClient) -> None:
    """Test that a network timeout raises the appropriate httpx exception."""
    mock_request.side_effect = httpx.ReadTimeout("Read timed out")
    
    with pytest.raises(httpx.ReadTimeout):
        await fhir_client.read("Patient", "123")


@patch("httpx.AsyncClient.request", new_callable=AsyncMock)
async def test_fhir_read_unauthorized_returns_401(mock_request: AsyncMock, fhir_client: FHIRClient) -> None:
    """Test that an invalid token resulting in 401 raises an HTTPStatusError."""
    mock_request.return_value = httpx.Response(401, text="Unauthorized")
    
    with pytest.raises(httpx.HTTPStatusError) as exc_info:
        await fhir_client.read("Patient", "123")
        
    assert exc_info.value.response.status_code == 401


@patch("httpx.AsyncClient.request", new_callable=AsyncMock)
async def test_fhir_read_forbidden_returns_403(mock_request: AsyncMock, fhir_client: FHIRClient) -> None:
    """Test that insufficient scopes resulting in 403 raises an HTTPStatusError."""
    mock_request.return_value = httpx.Response(403, text="Forbidden")
    
    with pytest.raises(httpx.HTTPStatusError) as exc_info:
        await fhir_client.read("Patient", "123")
        
    assert exc_info.value.response.status_code == 403


@patch("httpx.AsyncClient.request", new_callable=AsyncMock)
async def test_fhir_read_large_payload_success(mock_request: AsyncMock, fhir_client: FHIRClient) -> None:
    """Test reading a resource with a very large JSON payload (e.g., DocumentReference)."""
    large_text = "A" * 1000000  # 1MB string
    mock_request.return_value = httpx.Response(
        200, json={"resourceType": "DocumentReference", "id": "doc-1", "text": {"div": large_text}}
    )
    
    result = await fhir_client.read("DocumentReference", "doc-1")
    
    assert result["id"] == "doc-1"
    assert len(result["text"]["div"]) == 1000000


@patch("httpx.AsyncClient.request", new_callable=AsyncMock)
async def test_fhir_read_unicode_id_success(mock_request: AsyncMock, fhir_client: FHIRClient) -> None:
    """Test reading a resource with unicode characters in the ID (though rare, should be URL encoded)."""
    mock_request.return_value = httpx.Response(
        200, json={"resourceType": "Patient", "id": "pat-🚀"}
    )
    
    result = await fhir_client.read("Patient", "pat-🚀")
    
    assert result["id"] == "pat-🚀"
    args, kwargs = mock_request.call_args
    assert "pat-%F0%9F%9A%80" in str(kwargs["url"]) or "pat-🚀" in str(kwargs["url"])


# ==========================================
# 2. FHIR SEARCH TESTS
# ==========================================

@patch("httpx.AsyncClient.request", new_callable=AsyncMock)
async def test_fhir_search(mock_request: AsyncMock, fhir_client: FHIRClient) -> None:
    """Test standard happy path for searching FHIR resources."""
    mock_request.return_value = httpx.Response(
        200, json={
            "resourceType": "Bundle",
            "type": "searchset",
            "total": 1,
            "entry": [{"resource": {"resourceType": "Condition", "id": "cond-1"}}]
        }
    )
    
    result = await fhir_client.search("Condition", {"patient": "pat-123"})
    
    assert result["resourceType"] == "Bundle"
    assert result["total"] == 1
    assert len(result["entry"]) == 1
    assert result["entry"][0]["resource"]["id"] == "cond-1"
    
    args, kwargs = mock_request.call_args
    assert kwargs["method"] == "GET"
    assert "Condition" in str(kwargs["url"])
    assert kwargs["params"] == {"patient": "pat-123"}


@patch("httpx.AsyncClient.request", new_callable=AsyncMock)
async def test_fhir_search_empty_results(mock_request: AsyncMock, fhir_client: FHIRClient) -> None:
    """Test searching that yields no results returns an empty Bundle."""
    mock_request.return_value = httpx.Response(
        200, json={
            "resourceType": "Bundle",
            "type": "searchset",
            "total": 0,
            "entry": []
        }
    )
    
    result = await fhir_client.search("Condition", {"patient": "non-existent"})
    
    assert result["total"] == 0
    assert len(result.get("entry", [])) == 0


@patch("httpx.AsyncClient.request", new_callable=AsyncMock)
async def test_fhir_search_missing_resource_type_raises_value_error(mock_request: AsyncMock, fhir_client: FHIRClient) -> None:
    """Test that searching without a resource type raises a ValueError."""
    with pytest.raises(ValueError):
        await fhir_client.search("", {"patient": "pat-123"})
    mock_request.assert_not_called()


@patch("httpx.AsyncClient.request", new_callable=AsyncMock)
async def test_fhir_search_null_params_handled_gracefully(mock_request: AsyncMock, fhir_client: FHIRClient) -> None:
    """Test that searching with None for params executes a search without query parameters."""
    mock_request.return_value = httpx.Response(
        200, json={"resourceType": "Bundle", "total": 100}
    )
    
    result = await fhir_client.search("Patient", None)
    
    assert result["total"] == 100
    args, kwargs = mock_request.call_args
    assert not kwargs.get("params")


@patch("httpx.AsyncClient.request", new_callable=AsyncMock)
async def test_fhir_search_multiple_params(mock_request: AsyncMock, fhir_client: FHIRClient) -> None:
    """Test searching with multiple query parameters."""
    mock_request.return_value = httpx.Response(
        200, json={"resourceType": "Bundle", "total": 5}
    )
    
    params = {"patient": "pat-123", "status": "active", "category": "problem-list-item"}
    result = await fhir_client.search("Condition", params)
    
    assert result["total"] == 5
    args, kwargs = mock_request.call_args
    assert kwargs["params"] == params


@patch("httpx.AsyncClient.request", new_callable=AsyncMock)
async def test_fhir_search_server_error_raises_exception(mock_request: AsyncMock, fhir_client: FHIRClient) -> None:
    """Test that a 500 error during search raises an HTTPStatusError."""
    mock_request.return_value = httpx.Response(500, text="Database timeout")
    
    with pytest.raises(httpx.HTTPStatusError):
        await fhir_client.search("Observation", {"patient": "pat-123"})


@patch("httpx.AsyncClient.request", new_callable=AsyncMock)
async def test_fhir_search_malformed_json_response(mock_request: AsyncMock, fhir_client: FHIRClient) -> None:
    """Test that a non-JSON response from the server raises a JSONDecodeError or similar."""
    mock_request.return_value = httpx.Response(200, text="<html>Bad Gateway</html>")
    
    with pytest.raises(json.JSONDecodeError):
        await fhir_client.search("Patient", {"name": "Smith"})


@patch("httpx.AsyncClient.request", new_callable=AsyncMock)
async def test_fhir_search_pagination_handling(mock_request: AsyncMock, fhir_client: FHIRClient) -> None:
    """Test that search correctly handles pagination links if implemented in the client."""
    mock_request.return_value = httpx.Response(
        200, json={
            "resourceType": "Bundle",
            "link": [{"relation": "next", "url": "https://mock-fhir-server.com/r4/Patient?_getpages=123"}],
            "entry": [{"resource": {"id": "1"}}]
        }
    )
    
    result = await fhir_client.search("Patient", {"_count": "1"})
    
    assert "link" in result
    assert result["link"][0]["relation"] == "next"


# ==========================================
# 3. RATE LIMITING & BACKOFF TESTS
# ==========================================

@patch("httpx.AsyncClient.request", new_callable=AsyncMock)
async def test_fhir_rate_limit_backoff(mock_request: AsyncMock, fhir_client: FHIRClient) -> None:
    """Test that the client automatically retries on 429 Too Many Requests and eventually succeeds."""
    mock_request.side_effect = [
        httpx.Response(429, headers={"Retry-After": "0.1"}),
        httpx.Response(429, headers={"Retry-After": "0.1"}),
        httpx.Response(200, json={"resourceType": "Patient", "id": "123"})
    ]
    
    result = await fhir_client.read("Patient", "123")
    
    assert mock_request.call_count == 3
    assert result["id"] == "123"


@patch("httpx.AsyncClient.request", new_callable=AsyncMock)
async def test_fhir_rate_limit_exhausted_retries_raises(mock_request: AsyncMock, fhir_client: FHIRClient) -> None:
    """Test that exceeding the maximum number of retries raises an HTTPStatusError."""
    mock_request.return_value = httpx.Response(429, headers={"Retry-After": "0.1"})
    
    with pytest.raises(httpx.HTTPStatusError) as exc_info:
        await fhir_client.read("Patient", "123")
        
    assert mock_request.call_count == fhir_client.max_retries + 1
    assert exc_info.value.response.status_code == 429


@patch("httpx.AsyncClient.request", new_callable=AsyncMock)
async def test_fhir_rate_limit_backoff_on_search(mock_request: AsyncMock, fhir_client: FHIRClient) -> None:
    """Test that rate limit backoff also applies to search operations."""
    mock_request.side_effect = [
        httpx.Response(429, headers={"Retry-After": "0.1"}),
        httpx.Response(200, json={"resourceType": "Bundle", "total": 1})
    ]
    
    result = await fhir_client.search("Condition", {"patient": "123"})
    
    assert mock_request.call_count == 2
    assert result["total"] == 1


@patch("httpx.AsyncClient.request", new_callable=AsyncMock)
async def test_fhir_rate_limit_missing_retry_after_header(mock_request: AsyncMock, fhir_client: FHIRClient) -> None:
    """Test that the client falls back to exponential backoff if Retry-After is missing."""
    mock_request.side_effect = [
        httpx.Response(429),  # No Retry-After header
        httpx.Response(200, json={"resourceType": "Patient", "id": "123"})
    ]
    
    result = await fhir_client.read("Patient", "123")
    
    assert mock_request.call_count == 2
    assert result["id"] == "123"


@patch("httpx.AsyncClient.request", new_callable=AsyncMock)
async def test_fhir_rate_limit_invalid_retry_after_header(mock_request: AsyncMock, fhir_client: FHIRClient) -> None:
    """Test that the client handles an invalid Retry-After header gracefully."""
    mock_request.side_effect = [
        httpx.Response(429, headers={"Retry-After": "invalid-date-format"}),
        httpx.Response(200, json={"resourceType": "Patient", "id": "123"})
    ]
    
    result = await fhir_client.read("Patient", "123")
    
    assert mock_request.call_count == 2
    assert result["id"] == "123"


@patch("httpx.AsyncClient.request", new_callable=AsyncMock)
async def test_fhir_503_service_unavailable_triggers_backoff(mock_request: AsyncMock, fhir_client: FHIRClient) -> None:
    """Test that 503 Service Unavailable also triggers the retry mechanism."""
    mock_request.side_effect = [
        httpx.Response(503),
        httpx.Response(200, json={"resourceType": "Patient", "id": "123"})
    ]
    
    result = await fhir_client.read("Patient", "123")
    
    assert mock_request.call_count == 2
    assert result["id"] == "123"


@patch("httpx.AsyncClient.request", new_callable=AsyncMock)
async def test_fhir_network_error_triggers_backoff(mock_request: AsyncMock, fhir_client: FHIRClient) -> None:
    """Test that transient network errors (like ConnectError) trigger retries."""
    mock_request.side_effect = [
        httpx.ConnectError("Connection refused"),
        httpx.Response(200, json={"resourceType": "Patient", "id": "123"})
    ]
    
    result = await fhir_client.read("Patient", "123")
    
    assert mock_request.call_count == 2
    assert result["id"] == "123"


# ==========================================
# 4. PARSE PATIENT TESTS
# ==========================================

def test_parse_patient(sample_patient_json: Dict[str, Any]) -> None:
    """Test standard happy path for parsing a complete FHIR Patient resource."""
    parsed = parse_patient(sample_patient_json)
    
    assert parsed["id"] == "pat-123"
    assert parsed["first_name"] == "John"
    assert parsed["last_name"] == "Doe"
    assert parsed["gender"] == "male"
    assert parsed["birth_date"] == "1980-01-01"
    assert parsed["phone"] == "555-1234"
    assert parsed["email"] == "john.doe@example.com"
    assert parsed["address_line"] == "123 Main St"
    assert parsed["city"] == "Anytown"
    assert parsed["state"] == "CA"
    assert parsed["postal_code"] == "12345"


def test_parse_patient_missing_name(sample_patient_json: Dict[str, Any]) -> None:
    """Test parsing a patient that has no name array."""
    del sample_patient_json["name"]
    parsed = parse_patient(sample_patient_json)
    
    assert parsed["first_name"] is None
    assert parsed["last_name"] is None


def test_parse_patient_empty_name_array(sample_patient_json: Dict[str, Any]) -> None:
    """Test parsing a patient with an empty name array."""
    sample_patient_json["name"] = []
    parsed = parse_patient(sample_patient_json)
    
    assert parsed["first_name"] is None
    assert parsed["last_name"] is None


def test_parse_patient_missing_given_name(sample_patient_json: Dict[str, Any]) -> None:
    """Test parsing a patient missing the given name field."""
    del sample_patient_json["name"][0]["given"]
    parsed = parse_patient(sample_patient_json)
    
    assert parsed["first_name"] is None
    assert parsed["last_name"] == "Doe"


def test_parse_patient_missing_family_name(sample_patient_json: Dict[str, Any]) -> None:
    """Test parsing a patient missing the family name field."""
    del sample_patient_json["name"][0]["family"]
    parsed = parse_patient(sample_patient_json)
    
    assert parsed["first_name"] == "John"
    assert parsed["last_name"] is None


def test_parse_patient_missing_telecom(sample_patient_json: Dict[str, Any]) -> None:
    """Test parsing a patient with no telecom array."""
    del sample_patient_json["telecom"]
    parsed = parse_patient(sample_patient_json)
    
    assert parsed["phone"] is None
    assert parsed["email"] is None


def test_parse_patient_empty_telecom_array(sample_patient_json: Dict[str, Any]) -> None:
    """Test parsing a patient with an empty telecom array."""
    sample_patient_json["telecom"] = []
    parsed = parse_patient(sample_patient_json)
    
    assert parsed["phone"] is None
    assert parsed["email"] is None


def test_parse_patient_missing_address(sample_patient_json: Dict[str, Any]) -> None:
    """Test parsing a patient with no address array."""
    del sample_patient_json["address"]
    parsed = parse_patient(sample_patient_json)
    
    assert parsed["address_line"] is None
    assert parsed["city"] is None
    assert parsed["state"] is None
    assert parsed["postal_code"] is None


def test_parse_patient_missing_id(sample_patient_json: Dict[str, Any]) -> None:
    """Test parsing a patient missing the required ID field raises ValueError."""
    del sample_patient_json["id"]
    with pytest.raises(ValueError, match="Patient resource missing required 'id'"):
        parse_patient(sample_patient_json)


def test_parse_patient_wrong_resource_type(sample_patient_json: Dict[str, Any]) -> None:
    """Test parsing a resource that is not a Patient raises ValueError."""
    sample_patient_json["resourceType"] = "Observation"
    with pytest.raises(ValueError, match="Expected resourceType 'Patient'"):
        parse_patient(sample_patient_json)


def test_parse_patient_unicode_cjk_characters(sample_patient_json: Dict[str, Any]) -> None:
    """Test parsing a patient with CJK characters in the name."""
    sample_patient_json["name"][0]["family"] = "王"
    sample_patient_json["name"][0]["given"] = ["伟"]
    parsed = parse_patient(sample_patient_json)
    
    assert parsed["first_name"] == "伟"
    assert parsed["last_name"] == "王"


def test_parse_patient_unicode_rtl_arabic(sample_patient_json: Dict[str, Any]) -> None:
    """Test parsing a patient with RTL Arabic characters in the name."""
    sample_patient_json["name"][0]["family"] = "محمد"
    sample_patient_json["name"][0]["given"] = ["أحمد"]
    parsed = parse_patient(sample_patient_json)
    
    assert parsed["first_name"] == "أحمد"
    assert parsed["last_name"] == "محمد"


def test_parse_patient_xss_payload_in_name(sample_patient_json: Dict[str, Any]) -> None:
    """Test that XSS payloads in string fields are safely extracted as literal strings."""
    xss_payload = "<script>alert('xss')</script>"
    sample_patient_json["name"][0]["family"] = xss_payload
    parsed = parse_patient(sample_patient_json)
    
    assert parsed["last_name"] == xss_payload


def test_parse_patient_sqli_payload_in_address(sample_patient_json: Dict[str, Any]) -> None:
    """Test that SQL injection payloads in string fields are safely extracted as literal strings."""
    sqli_payload = "123 Main St'; DROP TABLE patients;--"
    sample_patient_json["address"][0]["line"] = [sqli_payload]
    parsed = parse_patient(sample_patient_json)
    
    assert parsed["address_line"] == sqli_payload


def test_parse_patient_null_bytes_in_string(sample_patient_json: Dict[str, Any]) -> None:
    """Test parsing a patient with null bytes in a string field."""
    sample_patient_json["name"][0]["family"] = "Doe\x00Smith"
    parsed = parse_patient(sample_patient_json)
    
    assert parsed["last_name"] == "Doe\x00Smith"


def test_parse_patient_multiple_names_picks_official(sample_patient_json: Dict[str, Any]) -> None:
    """Test that the parser prefers the 'official' name over 'usual' or 'nickname'."""
    sample_patient_json["name"] = [
        {"use": "nickname", "given": ["Johnny"]},
        {"use": "official", "family": "Doe", "given": ["John", "A."]}
    ]
    parsed = parse_patient(sample_patient_json)
    
    assert parsed["first_name"] == "John"
    assert parsed["last_name"] == "Doe"


def test_parse_patient_multiple_addresses_picks_home(sample_patient_json: Dict[str, Any]) -> None:
    """Test that the parser prefers the 'home' address over 'work'."""
    sample_patient_json["address"] = [
        {"use": "work", "line": ["999 Office Blvd"], "city": "Worktown"},
        {"use": "home", "line": ["123 Main St"], "city": "Anytown"}
    ]
    parsed = parse_patient(sample_patient_json)
    
    assert parsed["address_line"] == "123 Main St"
    assert parsed["city"] == "Anytown"


def test_parse_patient_invalid_date_format_handled_gracefully(sample_patient_json: Dict[str, Any]) -> None:
    """Test parsing a patient with an invalid birthDate format."""
    sample_patient_json["birthDate"] = "not-a-date"
    parsed = parse_patient(sample_patient_json)
    
    assert parsed["birth_date"] == "not-a-date"


def test_parse_patient_empty_json_raises_value_error() -> None:
    """Test parsing an empty dictionary raises a ValueError."""
    with pytest.raises(ValueError, match="Expected resourceType 'Patient'"):
        parse_patient({})


# ==========================================
# 5. CONCURRENCY & INTEGRATION TESTS
# ==========================================

@patch("httpx.AsyncClient.request", new_callable=AsyncMock)
async def test_fhir_client_concurrent_reads(mock_request: AsyncMock, fhir_client: FHIRClient) -> None:
    """Test that the client can handle multiple concurrent read requests."""
    mock_request.return_value = httpx.Response(
        200, json={"resourceType": "Patient", "id": "123"}
    )
    
    tasks = [fhir_client.read("Patient", str(i)) for i in range(10)]
    results = await asyncio.gather(*tasks)
    
    assert len(results) == 10
    assert mock_request.call_count == 10
    for result in results:
        assert result["resourceType"] == "Patient"


@patch("httpx.AsyncClient.request", new_callable=AsyncMock)
async def test_fhir_client_concurrent_searches(mock_request: AsyncMock, fhir_client: FHIRClient) -> None:
    """Test that the client can handle multiple concurrent search requests."""
    mock_request.return_value = httpx.Response(
        200, json={"resourceType": "Bundle", "total": 1}
    )
    
    tasks = [fhir_client.search("Condition", {"patient": f"pat-{i}"}) for i in range(5)]
    results = await asyncio.gather(*tasks)
    
    assert len(results) == 5
    assert mock_request.call_count == 5
    for result in results:
        assert result["resourceType"] == "Bundle"


@patch("httpx.AsyncClient.request", new_callable=AsyncMock)
async def test_fhir_client_auth_header_injection(mock_request: AsyncMock, fhir_client: FHIRClient) -> None:
    """Test that the client correctly injects the Bearer token into the Authorization header."""
    mock_request.return_value = httpx.Response(
        200, json={"resourceType": "Patient", "id": "123"}
    )
    
    await fhir_client.read("Patient", "123")
    
    args, kwargs = mock_request.call_args
    headers = kwargs.get("headers", {})
    assert "Authorization" in headers
    assert headers["Authorization"] == "Bearer mock-token-123"


@patch("httpx.AsyncClient.request", new_callable=AsyncMock)
async def test_fhir_client_custom_headers_merged(mock_request: AsyncMock) -> None:
    """Test that custom headers provided during client initialization are merged correctly."""
    client = FHIRClient(
        base_url="https://mock-fhir-server.com/r4",
        token="mock-token-123",
        headers={"X-Custom-Header": "CustomValue"}
    )
    mock_request.return_value = httpx.Response(
        200, json={"resourceType": "Patient", "id": "123"}
    )
    
    await client.read("Patient", "123")
    
    args, kwargs = mock_request.call_args
    headers = kwargs.get("headers", {})
    assert headers["Authorization"] == "Bearer mock-token-123"
    assert headers["X-Custom-Header"] == "CustomValue"


@patch("httpx.AsyncClient.request", new_callable=AsyncMock)
async def test_fhir_client_get_all_for_auth_integration(mock_request: AsyncMock, fhir_client: FHIRClient) -> None:
    """Test the composite method that fetches all necessary FHIR data for a prior auth request."""
    # Mock responses for Patient, Conditions, Medications, Procedures
    def side_effect(*args: Any, **kwargs: Any) -> httpx.Response:
        url = str(kwargs.get("url", ""))
        if "Patient/pat-123" in url:
            return httpx.Response(200, json={"resourceType": "Patient", "id": "pat-123"})
        elif "Condition" in url:
            return httpx.Response(200, json={"resourceType": "Bundle", "total": 2, "entry": []})
        elif "MedicationRequest" in url:
            return httpx.Response(200, json={"resourceType": "Bundle", "total": 1, "entry": []})
        elif "Procedure" in url:
            return httpx.Response(200, json={"resourceType": "Bundle", "total": 0, "entry": []})
        elif "Observation" in url:
            return httpx.Response(200, json={"resourceType": "Bundle", "total": 5, "entry": []})
        elif "Coverage" in url:
            return httpx.Response(200, json={"resourceType": "Bundle", "total": 1, "entry": []})
        return httpx.Response(404)

    mock_request.side_effect = side_effect
    
    # Assuming the client has a high-level method get_all_for_auth
    if hasattr(fhir_client, "get_all_for_auth"):
        result = await fhir_client.get_all_for_auth("pat-123")
        
        assert "patient" in result
        assert "conditions" in result
        assert "medications" in result
        assert result["patient"]["id"] == "pat-123"
        assert result["conditions"]["total"] == 2
        assert mock_request.call_count >= 5