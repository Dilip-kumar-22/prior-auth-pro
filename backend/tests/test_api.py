import asyncio
import json
from typing import Any, Dict, List
from unittest.mock import patch

import httpx
import pytest
from fastapi import FastAPI

# Assuming the main FastAPI application is importable from api.main
from api.main import app

# Apply pytest.mark.asyncio to all test functions in this module
pytestmark = pytest.mark.asyncio


# ==========================================
# FIXTURES
# ==========================================

@pytest.fixture
async def async_client() -> httpx.AsyncClient:
    """
    Provide an asynchronous test client for the FastAPI application.
    Uses ASGITransport to communicate directly with the app without a running server.
    """
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client


# ==========================================
# 1. HEALTH CHECK — HAPPY PATH & METHODS
# ==========================================

async def test_health_check_happy_path_returns_200(async_client: httpx.AsyncClient) -> None:
    """Test that the health check endpoint returns a 200 OK with expected payload."""
    response = await async_client.get("/health")
    
    assert response.status_code == 200
    data = response.json()
    assert "status" in data
    assert data["status"] in ["ok", "healthy", "up"]


async def test_health_check_post_method_returns_405(async_client: httpx.AsyncClient) -> None:
    """Test that sending a POST request to the health check endpoint returns 405 Method Not Allowed."""
    response = await async_client.post("/health", json={"test": "data"})
    
    assert response.status_code == 405
    assert response.json()["detail"] == "Method Not Allowed"


async def test_health_check_put_method_returns_405(async_client: httpx.AsyncClient) -> None:
    """Test that sending a PUT request to the health check endpoint returns 405 Method Not Allowed."""
    response = await async_client.put("/health", json={"test": "data"})
    
    assert response.status_code == 405
    assert response.json()["detail"] == "Method Not Allowed"


async def test_health_check_delete_method_returns_405(async_client: httpx.AsyncClient) -> None:
    """Test that sending a DELETE request to the health check endpoint returns 405 Method Not Allowed."""
    response = await async_client.delete("/health")
    
    assert response.status_code == 405
    assert response.json()["detail"] == "Method Not Allowed"


async def test_health_check_patch_method_returns_405(async_client: httpx.AsyncClient) -> None:
    """Test that sending a PATCH request to the health check endpoint returns 405 Method Not Allowed."""
    response = await async_client.patch("/health", json={"test": "data"})
    
    assert response.status_code == 405
    assert response.json()["detail"] == "Method Not Allowed"


async def test_health_check_head_method_returns_200(async_client: httpx.AsyncClient) -> None:
    """Test that sending a HEAD request to the health check endpoint returns 200 OK without body."""
    response = await async_client.head("/health")
    
    assert response.status_code == 200
    assert response.text == ""


async def test_health_check_options_method_returns_200(async_client: httpx.AsyncClient) -> None:
    """Test that sending an OPTIONS request to the health check endpoint returns 200 OK (CORS preflight)."""
    response = await async_client.options("/health")
    
    assert response.status_code == 200


# ==========================================
# 2. HEALTH CHECK — SECURITY & INJECTION
# ==========================================

async def test_health_check_with_sql_injection_in_query_returns_200(async_client: httpx.AsyncClient) -> None:
    """Test that SQL injection payloads in query parameters are safely ignored by the health check."""
    sqli_payloads = [
        "'; DROP TABLE users;--",
        "' OR '1'='1",
        "1; UPDATE users SET role='admin'",
        "\" OR \"1\"=\"1\"",
        "' UNION SELECT 1,2,3--"
    ]
    for sqli_payload in sqli_payloads:
        response = await async_client.get(f"/health?q={sqli_payload}")
        
        assert response.status_code == 200
        assert response.json().get("status") in ["ok", "healthy", "up"]


async def test_health_check_with_sql_injection_in_headers_returns_200(async_client: httpx.AsyncClient) -> None:
    """Test that SQL injection payloads in headers are safely ignored by the health check."""
    sqli_payloads = [
        "'; DROP TABLE users;--",
        "' OR '1'='1",
        "1; UPDATE users SET role='admin'"
    ]
    for sqli_payload in sqli_payloads:
        headers = {"X-Custom-Header": sqli_payload}
        response = await async_client.get("/health", headers=headers)
        
        assert response.status_code == 200


async def test_health_check_with_xss_in_query_returns_200(async_client: httpx.AsyncClient) -> None:
    """Test that XSS payloads in query parameters are safely ignored by the health check."""
    xss_payloads = [
        "<script>alert('xss')</script>",
        "<img src=x onerror=alert(1)>",
        "javascript:alert(1)"
    ]
    for xss_payload in xss_payloads:
        response = await async_client.get(f"/health?ref={xss_payload}")
        
        assert response.status_code == 200


async def test_health_check_with_xss_in_headers_returns_200(async_client: httpx.AsyncClient) -> None:
    """Test that XSS payloads in headers are safely ignored by the health check."""
    xss_payloads = [
        "<script>alert('xss')</script>",
        "<img src=x onerror=alert(1)>"
    ]
    for xss_payload in xss_payloads:
        headers = {"User-Agent": xss_payload}
        response = await async_client.get("/health", headers=headers)
        
        assert response.status_code == 200


# ==========================================
# 3. HEALTH CHECK — BOUNDARIES, UNICODE, LARGE PAYLOADS
# ==========================================

async def test_health_check_with_massive_query_string_returns_200_or_414(async_client: httpx.AsyncClient) -> None:
    """Test health check with an extremely long query string."""
    massive_query = "a" * 10000
    response = await async_client.get(f"/health?data={massive_query}")
    
    # Depending on server config, it might accept it (200) or reject URI too long (414)
    # The key is that it doesn't crash (500)
    assert response.status_code in [200, 414]


async def test_health_check_with_massive_header_returns_200_or_431(async_client: httpx.AsyncClient) -> None:
    """Test health check with an extremely long header value."""
    massive_header = "a" * 10000
    headers = {"X-Massive-Header": massive_header}
    response = await async_client.get("/health", headers=headers)
    
    # Depending on server config, it might accept it (200) or reject headers too large (431)
    assert response.status_code in [200, 431]


async def test_health_check_with_body_payload_ignored_returns_200(async_client: httpx.AsyncClient) -> None:
    """Test that sending a body payload with a GET request to health check is safely ignored."""
    # httpx AsyncClient requires using request() directly to send body with GET
    response = await async_client.request("GET", "/health", json={"unexpected": "payload"})
    
    assert response.status_code == 200


async def test_health_check_unicode_query_parameters_returns_200(async_client: httpx.AsyncClient) -> None:
    """Test health check with unicode characters in query parameters."""
    response = await async_client.get("/health?emoji=🚀&cjk=测试&rtl=مرحبا")
    
    assert response.status_code == 200


async def test_health_check_unicode_headers_returns_200(async_client: httpx.AsyncClient) -> None:
    """Test health check with unicode characters in headers (encoded properly)."""
    # HTTP headers should technically be ASCII/Latin-1, but testing framework handling
    headers = {"X-Unicode-Header": "🚀测试مرحبا".encode("utf-8").decode("latin-1")}
    response = await async_client.get("/health", headers=headers)
    
    assert response.status_code == 200


async def test_health_check_null_bytes_in_query_returns_400_or_ignored(async_client: httpx.AsyncClient) -> None:
    """Test health check with null bytes in query string."""
    response = await async_client.get("/health?q=test\x00byte")
    
    # FastAPI/Starlette usually handles null bytes gracefully or rejects them as bad requests
    assert response.status_code in [200, 400]


# ==========================================
# 4. HEALTH CHECK — CONCURRENCY & RATE LIMITING
# ==========================================

async def test_health_check_concurrent_access_returns_200(async_client: httpx.AsyncClient) -> None:
    """Test that the health check endpoint can handle many concurrent requests."""
    tasks = [async_client.get("/health") for _ in range(100)]
    results = await asyncio.gather(*tasks)
    
    for response in results:
        assert response.status_code == 200
        assert response.json().get("status") in ["ok", "healthy", "up"]


async def test_health_check_idempotency(async_client: httpx.AsyncClient) -> None:
    """Test that repeated calls to the health check endpoint return consistent results."""
    response1 = await async_client.get("/health")
    response2 = await async_client.get("/health")
    response3 = await async_client.get("/health")
    
    assert response1.status_code == 200
    assert response2.status_code == 200
    assert response3.status_code == 200
    assert response1.json() == response2.json() == response3.json()


# ==========================================
# 5. CORS — PREFLIGHT & ACTUAL REQUESTS
# ==========================================

async def test_cors_preflight_allowed_origin_returns_headers(async_client: httpx.AsyncClient) -> None:
    """Test that an OPTIONS preflight request from an allowed origin returns correct CORS headers."""
    allowed_origins = ["http://localhost:3000", "https://dashboard.prior-auth-pro.com"]
    origin = allowed_origins[0]
    headers = {
        "Origin": origin,
        "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "Authorization, Content-Type"
    }
    
    response = await async_client.options("/events", headers=headers)
    
    assert response.status_code == 200
    assert response.headers.get("access-control-allow-origin") == origin
    assert "POST" in response.headers.get("access-control-allow-methods", "")
    assert "authorization" in response.headers.get("access-control-allow-headers", "").lower()


async def test_cors_preflight_disallowed_origin_omits_headers(async_client: httpx.AsyncClient) -> None:
    """Test that an OPTIONS preflight request from a disallowed origin omits CORS headers."""
    headers = {
        "Origin": "http://malicious-site.com",
        "Access-Control-Request-Method": "GET"
    }
    
    response = await async_client.options("/health", headers=headers)
    
    # FastAPI CORSMiddleware returns 400 for disallowed origins in preflight
    # or simply omits the access-control-allow-origin header depending on strictness
    if response.status_code == 200:
        assert "access-control-allow-origin" not in response.headers
    else:
        assert response.status_code == 400


async def test_cors_actual_request_allowed_origin_returns_headers(async_client: httpx.AsyncClient) -> None:
    """Test that an actual GET request from an allowed origin includes the allow-origin header."""
    allowed_origins = ["http://localhost:3000", "https://dashboard.prior-auth-pro.com"]
    origin = allowed_origins[0]
    headers = {"Origin": origin}
    
    response = await async_client.get("/health", headers=headers)
    
    assert response.status_code == 200
    assert response.headers.get("access-control-allow-origin") == origin


async def test_cors_actual_request_disallowed_origin_omits_headers(async_client: httpx.AsyncClient) -> None:
    """Test that an actual GET request from a disallowed origin omits the allow-origin header."""
    headers = {"Origin": "http://evil.com"}
    
    response = await async_client.get("/health", headers=headers)
    
    assert response.status_code == 200  # The request succeeds, but browser will block it
    assert "access-control-allow-origin" not in response.headers


async def test_cors_preflight_missing_origin_handled_gracefully(async_client: httpx.AsyncClient) -> None:
    """Test that an OPTIONS request without an Origin header is handled gracefully."""
    headers = {
        "Access-Control-Request-Method": "GET"
    }
    
    response = await async_client.options("/health", headers=headers)
    
    assert response.status_code == 200
    assert "access-control-allow-origin" not in response.headers


async def test_cors_preflight_credentials_supported(async_client: httpx.AsyncClient) -> None:
    """Test that CORS configuration supports credentials (cookies/auth headers) if configured."""
    allowed_origins = ["http://localhost:3000", "https://dashboard.prior-auth-pro.com"]
    origin = allowed_origins[0]
    headers = {
        "Origin": origin,
        "Access-Control-Request-Method": "GET"
    }
    
    response = await async_client.options("/health", headers=headers)
    
    assert response.status_code == 200
    # If allow_credentials=True in CORSMiddleware, this header must be "true"
    allow_creds = response.headers.get("access-control-allow-credentials")
    if allow_creds:
        assert allow_creds == "true"


async def test_cors_wildcard_origin_not_used_in_production(async_client: httpx.AsyncClient) -> None:
    """Test that the application does not return a wildcard '*' for allowed origins to ensure security."""
    allowed_origins = ["http://localhost:3000", "https://dashboard.prior-auth-pro.com"]
    origin = allowed_origins[0]
    headers = {"Origin": origin}
    
    response = await async_client.get("/health", headers=headers)
    
    assert response.status_code == 200
    allow_origin = response.headers.get("access-control-allow-origin")
    assert allow_origin != "*"
    assert allow_origin == origin


# ==========================================
# 6. CORS — SECURITY & EDGE CASES
# ==========================================

async def test_cors_with_sql_injection_in_origin_omits_headers(async_client: httpx.AsyncClient) -> None:
    """Test that SQL injection payloads in the Origin header do not reflect and omit CORS headers."""
    sqli_payloads = [
        "'; DROP TABLE users;--",
        "' OR '1'='1"
    ]
    for sqli_payload in sqli_payloads:
        headers = {"Origin": sqli_payload}
        
        response = await async_client.get("/health", headers=headers)
        
        assert response.status_code == 200
        assert "access-control-allow-origin" not in response.headers


async def test_cors_with_xss_in_origin_omits_headers(async_client: httpx.AsyncClient) -> None:
    """Test that XSS payloads in the Origin header do not reflect and omit CORS headers."""
    xss_payloads = [
        "<script>alert('xss')</script>",
        "http://localhost:3000<script>alert(1)</script>"
    ]
    for xss_payload in xss_payloads:
        headers = {"Origin": xss_payload}
        
        response = await async_client.get("/health", headers=headers)
        
        assert response.status_code == 200
        assert "access-control-allow-origin" not in response.headers


async def test_cors_with_unicode_in_origin_omits_headers(async_client: httpx.AsyncClient) -> None:
    """Test that unicode characters in the Origin header are handled safely."""
    # Origins should be ASCII (punycode for IDNs), so raw unicode should be rejected/omitted
    headers = {"Origin": "http://测试.com".encode("utf-8").decode("latin-1")}
    
    response = await async_client.get("/health", headers=headers)
    
    assert response.status_code == 200
    assert "access-control-allow-origin" not in response.headers


async def test_cors_with_massive_origin_string_omits_headers(async_client: httpx.AsyncClient) -> None:
    """Test that an extremely long Origin header is handled safely without crashing."""
    massive_origin = "http://" + ("a" * 5000) + ".com"
    headers = {"Origin": massive_origin}
    
    response = await async_client.get("/health", headers=headers)
    
    assert response.status_code in [200, 431]
    if response.status_code == 200:
        assert "access-control-allow-origin" not in response.headers


async def test_cors_case_sensitivity_in_origin(async_client: httpx.AsyncClient) -> None:
    """Test that Origin matching is exact and case-sensitive (or handled correctly per spec)."""
    allowed_origins = ["http://localhost:3000", "https://dashboard.prior-auth-pro.com"]
    origin = allowed_origins[0].upper()  # e.g., HTTP://LOCALHOST:3000
    headers = {"Origin": origin}
    
    response = await async_client.get("/health", headers=headers)
    
    assert response.status_code == 200
    # Browsers send lowercase origins. If uppercase is sent, it shouldn't match the exact lowercase config.
    assert "access-control-allow-origin" not in response.headers


# ==========================================
# 7. GENERAL API — 404, 405, AND GLOBAL HANDLERS
# ==========================================

async def test_api_unknown_route_returns_404(async_client: httpx.AsyncClient) -> None:
    """Test that requesting a non-existent route returns a standard 404 Not Found."""
    response = await async_client.get("/this-route-does-not-exist")
    
    assert response.status_code == 404
    assert response.json()["detail"] == "Not Found"


async def test_api_unknown_route_with_sqli_returns_404(async_client: httpx.AsyncClient) -> None:
    """Test that SQL injection payloads in the URL path do not cause 500s and return 404."""
    sqli_payloads = [
        "'; DROP TABLE users;--",
        "' OR '1'='1"
    ]
    for sqli_payload in sqli_payloads:
        response = await async_client.get(f"/{sqli_payload}")
        
        assert response.status_code == 404
        assert response.json()["detail"] == "Not Found"


async def test_api_unknown_route_with_xss_returns_404(async_client: httpx.AsyncClient) -> None:
    """Test that XSS payloads in the URL path do not cause 500s and return 404."""
    xss_payloads = [
        "<script>alert('xss')</script>",
        "%3Cscript%3Ealert('xss')%3C%2Fscript%3E"
    ]
    for xss_payload in xss_payloads:
        response = await async_client.get(f"/{xss_payload}")
        
        assert response.status_code == 404
        assert response.json()["detail"] == "Not Found"


async def test_api_unknown_route_with_unicode_returns_404(async_client: httpx.AsyncClient) -> None:
    """Test that unicode characters in the URL path return 404 Not Found."""
    response = await async_client.get("/🚀测试")
    
    assert response.status_code == 404
    assert response.json()["detail"] == "Not Found"


async def test_api_unknown_route_with_massive_path_returns_404_or_414(async_client: httpx.AsyncClient) -> None:
    """Test that an extremely long URL path is handled safely."""
    massive_path = "/" + ("a" * 10000)
    response = await async_client.get(massive_path)
    
    assert response.status_code in [404, 414]


async def test_api_trailing_slash_redirect_or_404(async_client: httpx.AsyncClient) -> None:
    """Test behavior of trailing slashes on known endpoints."""
    # FastAPI typically redirects (307) to the non-trailing slash version if configured,
    # or returns 404 if strict routing is enabled.
    response = await async_client.get("/health/")
    
    assert response.status_code in [200, 307, 404]
    if response.status_code == 307:
        assert response.headers["location"] == "/health"


async def test_api_malformed_json_returns_422_or_400(async_client: httpx.AsyncClient) -> None:
    """Test that sending malformed JSON to an endpoint expecting a body is handled gracefully."""
    # We use a known endpoint that expects a body, or just test the global exception handler
    # Since we don't know exact endpoints here, we'll send it to a hypothetical POST endpoint
    # If it doesn't exist, it returns 404. If it does, it should return 422/400.
    headers = {"Content-Type": "application/json"}
    response = await async_client.post("/events", content="{malformed_json:", headers=headers)
    
    # 404 if route doesn't exist, 400/422 if it does and catches the bad JSON
    assert response.status_code in [400, 404, 422]


async def test_api_unsupported_media_type_returns_415_or_422(async_client: httpx.AsyncClient) -> None:
    """Test that sending an unsupported Content-Type is handled gracefully."""
    headers = {"Content-Type": "application/xml"}
    response = await async_client.post("/events", content="<xml></xml>", headers=headers)
    
    # 404 if route doesn't exist, 415/422 if it does and rejects XML
    assert response.status_code in [404, 415, 422]