import asyncio
import os
import uuid
from datetime import datetime, timezone
from typing import Any, AsyncGenerator, Dict, Generator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import JSON, String, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# Default to in-memory SQLite for tests so the suite runs without Docker /
# Postgres locally. Override with TEST_DATABASE_URL=postgresql+asyncpg://...
# to run the same tests against a real Postgres + pgvector container.
TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "sqlite+aiosqlite:///:memory:",
)
_USING_SQLITE = TEST_DATABASE_URL.startswith("sqlite")

# When running on SQLite we register compile-impls for the Postgres-only
# types (UUID, JSONB, Vector) so the test suite can use a zero-dep in-memory
# SQLite database. Override with TEST_DATABASE_URL=postgresql+asyncpg://...
# to run the same tests against real Postgres + pgvector.
if _USING_SQLITE:
    import pgvector.sqlalchemy
    from sqlalchemy.dialects.postgresql import JSONB, UUID
    from sqlalchemy.ext.compiler import compiles

    @compiles(UUID, "sqlite")
    def _compile_uuid_sqlite(type_, compiler, **kw):  # noqa: ARG001
        return "VARCHAR(36)"

    @compiles(JSONB, "sqlite")
    def _compile_jsonb_sqlite(type_, compiler, **kw):  # noqa: ARG001
        return "JSON"

    @compiles(pgvector.sqlalchemy.Vector, "sqlite")
    def _compile_vector_sqlite(type_, compiler, **kw):  # noqa: ARG001
        return "JSON"

from api.main import app as fastapi_app  # noqa: E402
from models.appeal import Appeal  # noqa: E402
from models.auth_request import AuthEvent, AuthRequest  # noqa: E402
from models.database import Base, get_db  # noqa: E402
from models.payer_policy import PayerPolicy  # noqa: E402
from models.workflow import WorkflowStep  # noqa: E402


@pytest.fixture(scope="session")
def event_loop() -> Generator[asyncio.AbstractEventLoop, None, None]:
    """
    Create an instance of the default event loop for the test session.
    """
    policy = asyncio.get_event_loop_policy()
    loop = policy.new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture(scope="session")
async def test_db_engine() -> AsyncGenerator[Any, None]:
    """
    Create an async SQLAlchemy engine for the test database.
    Sets up the pgvector extension (Postgres only) and creates all tables.
    """
    engine = create_async_engine(TEST_DATABASE_URL, echo=False)

    async with engine.begin() as conn:
        if not _USING_SQLITE:
            try:
                await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector;"))
            except Exception:
                pass

        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)

    yield engine

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)

    await engine.dispose()


@pytest_asyncio.fixture
async def test_db_session(test_db_engine: Any) -> AsyncGenerator[AsyncSession, None]:
    """
    Provide an async database session for a test.
    Rolls back any transactions after the test completes to maintain isolation.
    """
    TestingSessionLocal = async_sessionmaker(
        bind=test_db_engine, 
        class_=AsyncSession, 
        expire_on_commit=False
    )
    
    async with TestingSessionLocal() as session:
        yield session
        await session.rollback()


class MockRedisPipeline:
    """Mock Redis pipeline for rate limiting tests."""
    def incr(self, key: str) -> None:
        pass

    def expire(self, key: str, time: int) -> None:
        pass

    async def execute(self) -> None:
        pass


class MockRedisPool:
    """Mock ARQ Redis pool for background task tests."""
    async def enqueue_job(self, function: str, *args: Any, **kwargs: Any) -> None:
        pass

    async def close(self) -> None:
        pass

    async def get(self, key: str) -> Any:
        return None

    def pipeline(self) -> MockRedisPipeline:
        return MockRedisPipeline()


@pytest.fixture
def mock_redis() -> MockRedisPool:
    """
    Provide a mock Redis pool to bypass actual Redis connections during testing.
    """
    return MockRedisPool()


@pytest_asyncio.fixture
async def app(test_db_session: AsyncSession, mock_redis: MockRedisPool) -> AsyncGenerator[Any, None]:
    """
    Provide the FastAPI application instance with overridden dependencies.
    """
    fastapi_app.dependency_overrides[get_db] = lambda: test_db_session
    fastapi_app.state.redis_pool = mock_redis
    
    yield fastapi_app
    
    fastapi_app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def async_client(app: Any) -> AsyncGenerator[AsyncClient, None]:
    """
    Provide an async HTTP client for testing FastAPI endpoints.
    """
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client


class MockFHIRClient:
    """Mock FHIR client to bypass actual HTTP requests to a FHIR server."""
    async def read(self, resource_type: str, id: str) -> Dict[str, Any]:
        return {
            "resourceType": resource_type,
            "id": id,
            "status": "active"
        }
        
    async def search(self, resource_type: str, params: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "resourceType": "Bundle",
            "type": "searchset",
            "total": 1,
            "entry": [
                {
                    "resource": {
                        "resourceType": resource_type,
                        "id": str(uuid.uuid4())
                    }
                }
            ]
        }


@pytest.fixture
def mock_fhir_server(monkeypatch: pytest.MonkeyPatch) -> MockFHIRClient:
    """
    Patch the FHIR client factory to return a mock client.
    """
    client = MockFHIRClient()
    monkeypatch.setattr("fhir.context.client_from_session", lambda state: client)
    return client


@pytest_asyncio.fixture
async def sample_auth_request(test_db_session: AsyncSession) -> AuthRequest:
    """
    Create and persist a sample AuthRequest in the test database.
    """
    req = AuthRequest(
        id=uuid.uuid4(),
        patient_id="pat-12345",
        auth_type="medication",
        service_requested="J3380",
        diagnosis_codes=[{"code": "M05.70", "system": "http://hl7.org/fhir/sid/icd-10-cm"}],
        payer_id="uhc-001",
        plan_id="plan-xyz",
        priority="standard",
        fhir_bundle={"resourceType": "Bundle", "entry": []},
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc)
    )
    test_db_session.add(req)
    await test_db_session.commit()
    await test_db_session.refresh(req)
    return req


@pytest_asyncio.fixture
async def sample_auth_event(test_db_session: AsyncSession, sample_auth_request: AuthRequest) -> AuthEvent:
    """
    Create and persist a sample AuthEvent linked to the sample AuthRequest.
    """
    event = AuthEvent(
        id=uuid.uuid4(),
        auth_request_id=sample_auth_request.id,
        event_type="created",
        agent_name="api_system",
        model_used=None,
        payload={"message": "Authorization request received and created."},
        confidence_score=1.0,
        latency_ms=0,
        timestamp=datetime.now(timezone.utc)
    )
    test_db_session.add(event)
    await test_db_session.commit()
    await test_db_session.refresh(event)
    return event


@pytest_asyncio.fixture
async def sample_appeal(test_db_session: AsyncSession, sample_auth_request: AuthRequest) -> Appeal:
    """
    Create and persist a sample Appeal linked to the sample AuthRequest.
    """
    appeal = Appeal(
        id=uuid.uuid4(),
        auth_request_id=sample_auth_request.id,
        denial_reason="Service not deemed medically necessary based on submitted documentation.",
        counter_evidence={"clinical_notes": "Patient failed 6 months of conservative therapy."},
        appeal_letter="Dear Medical Director, I am writing to appeal the denial...",
        guidelines_cited=[{"id": "g-123", "text": "Aetna Clinical Policy Bulletin 0001"}],
        status="draft",
        outcome="null",
        created_at=datetime.now(timezone.utc)
    )
    test_db_session.add(appeal)
    await test_db_session.commit()
    await test_db_session.refresh(appeal)
    return appeal


@pytest_asyncio.fixture
async def sample_workflow_step(test_db_session: AsyncSession, sample_auth_request: AuthRequest) -> WorkflowStep:
    """
    Create and persist a sample WorkflowStep linked to the sample AuthRequest.
    """
    step = WorkflowStep(
        id=uuid.uuid4(),
        auth_request_id=sample_auth_request.id,
        step_type="extraction",
        status="completed",
        agent_name="extraction_agent",
        started_at=datetime.now(timezone.utc),
        completed_at=datetime.now(timezone.utc),
        input_hash="hash_input_123",
        output_hash="hash_output_456",
        retry_count=0
    )
    test_db_session.add(step)
    await test_db_session.commit()
    await test_db_session.refresh(step)
    return step


@pytest_asyncio.fixture
async def sample_payer_policy(test_db_session: AsyncSession) -> PayerPolicy:
    """
    Create and persist a sample PayerPolicy in the test database.
    """
    policy = PayerPolicy(
        id=uuid.uuid4(),
        payer_name="UnitedHealth",
        policy_code="UH-MED-001-TEST",
        service_category="medication",
        cpt_codes=["J3380", "J0129"],
        icd10_required=["M05.70", "M06.9"],
        documentation_required=["clinical_notes", "lab_results"],
        auto_approve_criteria={"qualifying_diagnoses": ["M05.70"]},
        auto_deny_criteria={"excluded_service_codes": ["J3381"]},
        requires_ai_review=True,
        effective_date=datetime(2023, 1, 1, tzinfo=timezone.utc),
        expiry_date=datetime(2025, 12, 31, tzinfo=timezone.utc)
    )
    test_db_session.add(policy)
    await test_db_session.commit()
    await test_db_session.refresh(policy)
    return policy