import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from pgvector.sqlalchemy import Vector
from sqlalchemy import DateTime, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base


class Guideline(Base):
    """
    SQLAlchemy model representing a clinical guideline or policy document chunk.
    Uses pgvector for storing text embeddings to enable RAG (Retrieval-Augmented Generation)
    searches during the AI reasoning and appeal generation processes.
    """
    __tablename__ = "guidelines"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True
    )
    
    content: Mapped[str] = mapped_column(
        Text, nullable=False
    )
    
    # Named document_metadata to avoid conflict with SQLAlchemy's internal Base.metadata
    document_metadata: Mapped[Dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict
    )
    
    # Gemini text-embedding-004 outputs 768-dimensional vectors
    embedding: Mapped[List[float]] = mapped_column(
        Vector(768), nullable=False
    )
    
    category: Mapped[Optional[str]] = mapped_column(
        String, index=True, nullable=True
    )
    
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )