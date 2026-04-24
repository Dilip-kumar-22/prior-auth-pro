"""
RAG Engine package initialization.

This package contains the Retrieval-Augmented Generation (RAG) engine for the Prior Auth Pro system.
It utilizes pgvector for vector similarity search and Gemini text-embedding-004 for generating
embeddings of clinical guidelines.

Modules:
- engine: Contains the RAGEngine class for searching and retrieving clinical guidelines.
- ingest: Utilities for chunking text and ingesting markdown guidelines into the vector database.
"""

__version__ = "1.0.0"
__author__ = "Prior Auth Pro Team"

__all__ = []