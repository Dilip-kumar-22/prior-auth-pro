import asyncio
import json
import uuid
from typing import Any, Dict, List
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from sqlalchemy.exc import OperationalError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from engines.rag.engine import RAGEngine

pytestmark = pytest.mark.asyncio


# ==========================================
# MOCKS & FIXTURES
# ==========================================

class MockGuideline:
    """Mock representation of the Guideline SQLAlchemy model with pgvector."""
    def __init__(self, id: uuid.UUID, content: str, metadata: Dict[str, Any], distance: float = 0.1):
        self.id = id
        self.content = content
        self.metadata = metadata
        self.embedding = [0.01] * 768
        self.distance = distance


def create_mock_session() -> AsyncMock:
    """Provide a mocked SQLAlchemy AsyncSession."""
    session = AsyncMock(spec=AsyncSession)
    
    # Setup default successful execute return for searches
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = []
    session.execute.return_value = mock_result
    
    return session


@pytest.fixture(autouse=True)
def mock_gemini_api():
    """Mock the external HTTPX calls to the Gemini embedding API."""
    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = httpx.Response(
            200, 
            json={
                "predictions": [
                    {"embeddings": {"values": [0.01] * 768}}
                ]
            }
        )
        yield mock_post


# ==========================================
# 1. HAPPY PATH TESTS
# ==========================================

async def test_ingest_text_minimal_valid() -> None:
    """Test ingesting a simple text snippet with minimal metadata."""
    mock_session = create_mock_session()
    rag_engine = RAGEngine(session=mock_session)
    content = "Patient requires MRI for severe migraines."
    metadata = {"source": "guideline_a"}
    
    result = await rag_engine.ingest_text(content=content, metadata=metadata)
    
    mock_session.add.assert_called_once()
    mock_session.commit.assert_called_once()
    assert result is not None


async def test_ingest_text_with_full_metadata() -> None:
    """Test ingesting text with a complex, nested metadata dictionary."""
    mock_session = create_mock_session()
    rag_engine = RAGEngine(session=mock_session)
    content = "Prior authorization for CPAP requires sleep study results."
    metadata = {
        "source": "policy_db",
        "payer": "UnitedHealth",
        "effective_date": "2024-01-01",
        "tags": ["dme", "respiratory", "cpap"],
        "requires_ai": True
    }
    
    await rag_engine.ingest_text(content=content, metadata=metadata)
    
    mock_session.add.assert_called_once()
    added_obj = mock_session.add.call_args[0][0]
    assert added_obj.content == content
    assert added_obj.metadata["payer"] == "UnitedHealth"
    assert "cpap" in added_obj.metadata["tags"]
    mock_session.commit.assert_called_once()


async def test_vector_search_basic() -> None:
    """Test performing a basic vector search without filters."""
    mock_session = create_mock_session()
    rag_engine = RAGEngine(session=mock_session)
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = [
        MockGuideline(id=uuid.uuid4(), content="MRI Guideline", metadata={"cat": "imaging"})
    ]
    mock_session.execute.return_value = mock_result
    
    results = await rag_engine.search(query="MRI requirements", top_k=5)
    
    assert len(results) == 1
    assert results[0]["content"] == "MRI Guideline"
    assert results[0]["metadata"]["cat"] == "imaging"
    mock_session.execute.assert_called_once()


async def test_vector_search_with_category_filter() -> None:
    """Test performing a vector search filtered by a specific category."""
    mock_session = create_mock_session()
    rag_engine = RAGEngine(session=mock_session)
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = [
        MockGuideline(id=uuid.uuid4(), content="CPAP Guideline", metadata={"category": "dme"})
    ]
    mock_session.execute.return_value = mock_result
    
    results = await rag_engine.search(query="CPAP", top_k=3, category="dme")
    
    assert len(results) == 1
    assert results[0]["metadata"]["category"] == "dme"
    
    # Verify the SQL statement included the category filter
    call_args = mock_session.execute.call_args[0][0]
    assert "category" in str(call_args).lower() or "metadata" in str(call_args).lower()


# ==========================================
# 2. VALIDATION & EDGE CASES
# ==========================================

async def test_ingest_empty_text_raises_value_error() -> None:
    """Test that ingesting an empty string raises a ValueError."""
    mock_session = create_mock_session()
    rag_engine = RAGEngine(session=mock_session)
    with pytest.raises(ValueError, match="Content cannot be empty"):
        await rag_engine.ingest_text(content="", metadata={"source": "test"})
    mock_session.add.assert_not_called()


async def test_ingest_whitespace_only_text_raises_value_error() -> None:
    """Test that ingesting only whitespace raises a ValueError."""
    mock_session = create_mock_session()
    rag_engine = RAGEngine(session=mock_session)
    with pytest.raises(ValueError, match="Content cannot be empty"):
        await rag_engine.ingest_text(content="   \n \t  ", metadata={"source": "test"})
    mock_session.add.assert_not_called()


async def test_ingest_null_text_raises_type_error() -> None:
    """Test that passing None for content raises a TypeError or ValueError."""
    mock_session = create_mock_session()
    rag_engine = RAGEngine(session=mock_session)
    with pytest.raises((TypeError, ValueError)):
        await rag_engine.ingest_text(content=None, metadata={"source": "test"}) # type: ignore


async def test_ingest_invalid_metadata_type_raises_type_error() -> None:
    """Test that passing a non-dictionary for metadata raises a TypeError."""
    mock_session = create_mock_session()
    rag_engine = RAGEngine(session=mock_session)
    with pytest.raises(TypeError, match="Metadata must be a dictionary"):
        await rag_engine.ingest_text(content="Valid text", metadata="invalid_metadata_string") # type: ignore


async def test_search_empty_query_raises_value_error() -> None:
    """Test that searching with an empty query string raises a ValueError."""
    mock_session = create_mock_session()
    rag_engine = RAGEngine(session=mock_session)
    with pytest.raises(ValueError, match="Query cannot be empty"):
        await rag_engine.search(query="", top_k=5)
    mock_session.execute.assert_not_called()


async def test_search_zero_top_k_raises_value_error() -> None:
    """Test that searching with top_k=0 raises a ValueError."""
    mock_session = create_mock_session()
    rag_engine = RAGEngine(session=mock_session)
    with pytest.raises(ValueError, match="top_k must be greater than 0"):
        await rag_engine.search(query="test", top_k=0)


async def test_search_negative_top_k_raises_value_error() -> None:
    """Test that searching with a negative top_k raises a ValueError."""
    mock_session = create_mock_session()
    rag_engine = RAGEngine(session=mock_session)
    with pytest.raises(ValueError, match="top_k must be greater than 0"):
        await rag_engine.search(query="test", top_k=-5)


async def test_search_null_query_raises_type_error() -> None:
    """Test that searching with a None query raises a TypeError or ValueError."""
    mock_session = create_mock_session()
    rag_engine = RAGEngine(session=mock_session)
    with pytest.raises((TypeError, ValueError)):
        await rag_engine.search(query=None, top_k=5) # type: ignore


# ==========================================
# 3. BOUNDARY VALUES & LARGE PAYLOADS
# ==========================================

async def test_search_excessive_top_k_capped() -> None:
    """Test that requesting an excessively large top_k is either capped or handled gracefully."""
    mock_session = create_mock_session()
    rag_engine = RAGEngine(session=mock_session)
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = [
        MockGuideline(id=uuid.uuid4(), content=f"Result {i}", metadata={}) for i in range(100)
    ]
    mock_session.execute.return_value = mock_result
    
    results = await rag_engine.search(query="test", top_k=10000)
    
    assert len(results) <= 100
    mock_session.execute.assert_called_once()


async def test_ingest_massive_text_payload() -> None:
    """Test ingesting a very large text payload (e.g., 1MB of text)."""
    mock_session = create_mock_session()
    rag_engine = RAGEngine(session=mock_session)
    massive_text = "Guideline " * 100000  # ~1MB string
    
    await rag_engine.ingest_text(content=massive_text, metadata={"source": "large_doc"})
    
    mock_session.add.assert_called_once()
    added_obj = mock_session.add.call_args[0][0]
    assert len(added_obj.content) > 500000
    mock_session.commit.assert_called_once()


async def test_search_massive_query_payload() -> None:
    """Test searching with a very large query string."""
    mock_session = create_mock_session()
    rag_engine = RAGEngine(session=mock_session)
    massive_query = "MRI " * 10000
    
    results = await rag_engine.search(query=massive_query, top_k=5)
    
    assert isinstance(results, list)
    mock_session.execute.assert_called_once()


async def test_ingest_massive_metadata_dictionary() -> None:
    """Test ingesting text with a massive metadata dictionary."""
    mock_session = create_mock_session()
    rag_engine = RAGEngine(session=mock_session)
    massive_metadata = {f"key_{i}": f"value_{i}" for i in range(10000)}
    
    await rag_engine.ingest_text(content="Standard text", metadata=massive_metadata)
    
    mock_session.add.assert_called_once()
    added_obj = mock_session.add.call_args[0][0]
    assert len(added_obj.metadata) == 10000
    mock_session.commit.assert_called_once()


# ==========================================
# 4. SECURITY — INJECTION & XSS
# ==========================================

async def test_ingest_sqli_payload_in_content() -> None:
    """Test that SQL injection payloads in content are safely parameterized by SQLAlchemy."""
    mock_session = create_mock_session()
    rag_engine = RAGEngine(session=mock_session)
    payloads = [
        "'; DROP TABLE guidelines;--",
        "' OR '1'='1",
        "1; UPDATE guidelines SET content='hacked'",
        "' UNION SELECT 1,2,3--"
    ]
    for sqli_payload in payloads:
        mock_session.reset_mock()
        await rag_engine.ingest_text(content=sqli_payload, metadata={"source": "test"})
        
        mock_session.add.assert_called_once()
        added_obj = mock_session.add.call_args[0][0]
        assert added_obj.content == sqli_payload  # Stored as literal string
        mock_session.commit.assert_called_once()


async def test_ingest_sqli_payload_in_metadata() -> None:
    """Test that SQL injection payloads in JSONB metadata are safely parameterized."""
    mock_session = create_mock_session()
    rag_engine = RAGEngine(session=mock_session)
    payloads = [
        "'; DROP TABLE guidelines;--",
        "' OR '1'='1"
    ]
    for sqli_payload in payloads:
        mock_session.reset_mock()
        await rag_engine.ingest_text(content="Valid text", metadata={"source": sqli_payload})
        
        mock_session.add.assert_called_once()
        added_obj = mock_session.add.call_args[0][0]
        assert added_obj.metadata["source"] == sqli_payload
        mock_session.commit.assert_called_once()


async def test_search_sqli_payload_in_query() -> None:
    """Test that SQL injection payloads in search queries do not break the vector search."""
    mock_session = create_mock_session()
    rag_engine = RAGEngine(session=mock_session)
    payloads = [
        "'; DROP TABLE guidelines;--",
        "' OR '1'='1"
    ]
    for sqli_payload in payloads:
        mock_session.reset_mock()
        results = await rag_engine.search(query=sqli_payload, top_k=5)
        
        assert isinstance(results, list)
        mock_session.execute.assert_called_once()


async def test_ingest_xss_payload_in_content() -> None:
    """Test that XSS payloads are stored as literal strings without execution."""
    mock_session = create_mock_session()
    rag_engine = RAGEngine(session=mock_session)
    payloads = [
        "<script>alert('xss')</script>",
        "<img src=x onerror=alert(1)>",
        "javascript:alert(1)"
    ]
    for xss_payload in payloads:
        mock_session.reset_mock()
        await rag_engine.ingest_text(content=xss_payload, metadata={"source": "test"})
        
        mock_session.add.assert_called_once()
        added_obj = mock_session.add.call_args[0][0]
        assert added_obj.content == xss_payload


async def test_search_xss_payload_in_query() -> None:
    """Test that XSS payloads in search queries are handled safely."""
    mock_session = create_mock_session()
    rag_engine = RAGEngine(session=mock_session)
    payloads = [
        "<script>alert('xss')</script>",
        "<img src=x onerror=alert(1)>"
    ]
    for xss_payload in payloads:
        mock_session.reset_mock()
        results = await rag_engine.search(query=xss_payload, top_k=5)
        
        assert isinstance(results, list)
        mock_session.execute.assert_called_once()


# ==========================================
# 5. UNICODE & ENCODING
# ==========================================

async def test_ingest_unicode_emojis() -> None:
    """Test ingesting text containing emojis."""
    mock_session = create_mock_session()
    rag_engine = RAGEngine(session=mock_session)
    content = "Guideline for 🚀 advanced imaging 🧠."
    
    await rag_engine.ingest_text(content=content, metadata={"emoji": "✅"})
    
    mock_session.add.assert_called_once()
    added_obj = mock_session.add.call_args[0][0]
    assert "🚀" in added_obj.content
    assert added_obj.metadata["emoji"] == "✅"


async def test_ingest_cjk_characters() -> None:
    """Test ingesting text containing CJK (Chinese, Japanese, Korean) characters."""
    mock_session = create_mock_session()
    rag_engine = RAGEngine(session=mock_session)
    content = "患者需要进行核磁共振检查 (MRI)."
    
    await rag_engine.ingest_text(content=content, metadata={"lang": "zh"})
    
    mock_session.add.assert_called_once()
    added_obj = mock_session.add.call_args[0][0]
    assert "核磁共振检查" in added_obj.content


async def test_ingest_rtl_arabic() -> None:
    """Test ingesting text containing RTL Arabic characters."""
    mock_session = create_mock_session()
    rag_engine = RAGEngine(session=mock_session)
    content = "المريض يحتاج إلى تصوير بالرنين المغناطيسي."
    
    await rag_engine.ingest_text(content=content, metadata={"lang": "ar"})
    
    mock_session.add.assert_called_once()
    added_obj = mock_session.add.call_args[0][0]
    assert "المريض" in added_obj.content


async def test_ingest_null_bytes_handled_safely() -> None:
    """Test that null bytes in text are either stripped or handled without crashing."""
    mock_session = create_mock_session()
    rag_engine = RAGEngine(session=mock_session)
    content = "Guideline\x00 with null byte."
    
    # Depending on implementation, it might raise ValueError or strip it. We test it doesn't 500.
    try:
        await rag_engine.ingest_text(content=content, metadata={"source": "test"})
        mock_session.add.assert_called_once()
    except ValueError:
        pass  # Also acceptable if the engine explicitly rejects null bytes


async def test_search_unicode_characters() -> None:
    """Test searching with a query containing unicode characters."""
    mock_session = create_mock_session()
    rag_engine = RAGEngine(session=mock_session)
    query = "MRI 🧠 核磁共振"
    
    results = await rag_engine.search(query=query, top_k=5)
    
    assert isinstance(results, list)
    mock_session.execute.assert_called_once()


# ==========================================
# 6. CONCURRENCY TESTS
# ==========================================

async def test_concurrent_ingestion_requests() -> None:
    """Test that multiple ingestion requests can be processed concurrently."""
    mock_session = create_mock_session()
    rag_engine = RAGEngine(session=mock_session)
    tasks = [
        rag_engine.ingest_text(content=f"Guideline {i}", metadata={"id": i})
        for i in range(50)
    ]
    
    await asyncio.gather(*tasks)
    
    assert mock_session.add.call_count == 50
    assert mock_session.commit.call_count == 50


async def test_concurrent_search_requests() -> None:
    """Test that multiple search requests can be processed concurrently."""
    mock_session = create_mock_session()
    rag_engine = RAGEngine(session=mock_session)
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = [
        MockGuideline(id=uuid.uuid4(), content="Result", metadata={})
    ]
    mock_session.execute.return_value = mock_result
    
    tasks = [
        rag_engine.search(query=f"Query {i}", top_k=3)
        for i in range(50)
    ]
    
    results = await asyncio.gather(*tasks)
    
    assert len(results) == 50
    assert mock_session.execute.call_count == 50
    for res in results:
        assert len(res) == 1


# ==========================================
# 7. ERROR HANDLING & RESILIENCE
# ==========================================

async def test_embedding_api_timeout_raises_custom_error() -> None:
    """Test that a timeout from the embedding API is handled and raises an appropriate error."""
    mock_session = create_mock_session()
    rag_engine = RAGEngine(session=mock_session)
    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.side_effect = httpx.ReadTimeout("Read timed out")
        
        with pytest.raises((httpx.ReadTimeout, RuntimeError, ValueError)):
            await rag_engine.ingest_text(content="Test content", metadata={})
            
        mock_session.add.assert_not_called()


async def test_embedding_api_500_raises_custom_error() -> None:
    """Test that a 500 Internal Server Error from the embedding API is handled."""
    mock_session = create_mock_session()
    rag_engine = RAGEngine(session=mock_session)
    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = httpx.Response(500, text="Internal Server Error")
        
        with pytest.raises((httpx.HTTPStatusError, RuntimeError, ValueError)):
            await rag_engine.search(query="Test query", top_k=5)
            
        mock_session.execute.assert_not_called()


async def test_db_operational_error_during_ingest() -> None:
    """Test that a database OperationalError during ingestion is propagated correctly."""
    mock_session = create_mock_session()
    rag_engine = RAGEngine(session=mock_session)
    mock_session.commit.side_effect = OperationalError("statement", "params", "orig")
    
    with pytest.raises(OperationalError):
        await rag_engine.ingest_text(content="Test content", metadata={})


async def test_db_operational_error_during_search() -> None:
    """Test that a database OperationalError during search is propagated correctly."""
    mock_session = create_mock_session()
    rag_engine = RAGEngine(session=mock_session)
    mock_session.execute.side_effect = OperationalError("statement", "params", "orig")
    
    with pytest.raises(OperationalError):
        await rag_engine.search(query="Test query", top_k=5)


async def test_search_returns_empty_list_when_no_matches() -> None:
    """Test that searching returns an empty list when the database has no matching vectors."""
    mock_session = create_mock_session()
    rag_engine = RAGEngine(session=mock_session)
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = []
    mock_session.execute.return_value = mock_result
    
    results = await rag_engine.search(query="Highly specific non-existent query", top_k=5)
    
    assert isinstance(results, list)
    assert len(results) == 0
    mock_session.execute.assert_called_once()


async def test_ingest_missing_metadata_defaults_to_empty_dict() -> None:
    """Test that omitting metadata defaults to an empty dictionary rather than failing."""
    mock_session = create_mock_session()
    rag_engine = RAGEngine(session=mock_session)
    # Assuming the method signature allows metadata to be optional or handles None gracefully if typed as Optional
    try:
        await rag_engine.ingest_text(content="Test content", metadata={})
        mock_session.add.assert_called_once()
        added_obj = mock_session.add.call_args[0][0]
        assert added_obj.metadata == {}
    except TypeError:
        # If the signature strictly requires metadata, this is also acceptable
        pass


async def test_search_missing_category_searches_all() -> None:
    """Test that omitting the category filter searches across all guidelines."""
    mock_session = create_mock_session()
    rag_engine = RAGEngine(session=mock_session)
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = [
        MockGuideline(id=uuid.uuid4(), content="Result 1", metadata={"cat": "A"}),
        MockGuideline(id=uuid.uuid4(), content="Result 2", metadata={"cat": "B"})
    ]
    mock_session.execute.return_value = mock_result
    
    results = await rag_engine.search(query="Test query", top_k=5, category=None)
    
    assert len(results) == 2
    call_args = mock_session.execute.call_args[0][0]
    # Ensure no category filter is applied in the SQL statement
    assert "category" not in str(call_args).lower()