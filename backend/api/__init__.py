"""
API module for Prior Authorization AI Agent.

This package contains the FastAPI application, REST API routes,
WebSocket handlers for real-time updates, and Pydantic schemas
for request and response validation.

Modules:
- main: FastAPI application factory and configuration.
- routes: API endpoints for auth requests, appeals, dashboard, and audit.
- schemas: Pydantic v2 models for data validation.
- websocket: Real-time event broadcasting.
"""

__version__ = "1.0.0"
__author__ = "Prior Auth Pro Team"