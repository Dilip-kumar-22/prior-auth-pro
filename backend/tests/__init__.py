"""
Test suite package initialization for Prior Auth Pro.

This package contains all the automated tests for the Prior Authorization AI Agent backend.
It includes unit tests, integration tests, security tests, and performance tests.
The tests are designed to be run with pytest and utilize pytest-asyncio for asynchronous
testing of FastAPI endpoints, SQLAlchemy models, and external service clients (FHIR, Gemini).

Test Categories:
- Unit Tests: Test individual functions, models, and utility classes in isolation.
- Integration Tests: Test API endpoints, database interactions, and full workflows.
- Security Tests: Test for vulnerabilities like SQL Injection, XSS, and broken access control.
- Concurrency Tests: Test race conditions and parallel access scenarios.
"""

__version__ = "1.0.0"
__author__ = "Prior Auth Pro Team"