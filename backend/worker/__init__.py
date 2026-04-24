"""
Async Worker package initialization.

This package contains the background job processing logic for the Prior Auth Pro system.
It utilizes ARQ (Async Redis Queue) and Redis to handle long-running AI pipeline tasks
such as data extraction, classification, rules evaluation, RAG lookups, and clinical reasoning
without blocking the main FastAPI application thread.

Modules:
- tasks: Defines the async functions executed by the worker.
- settings: Configuration for the ARQ Worker instance.
"""

__version__ = "1.0.0"
__author__ = "Prior Auth Pro Team"

__all__ = []