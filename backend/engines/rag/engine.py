import logging
import os
import uuid
from typing import Any, Dict, List, Optional

import httpx
from pgvector.sqlalchemy import Vector
from sqlalchemy import Column, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from models.database import Base

logger = logging.getLogger(__name__)


class Guideline(Base):
    """
    SQLAlchemy model for storing clinical guidelines and their vector embeddings.
    """
    __tablename__ = "guidelines"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    content = Column(Text, nullable=False)
    metadata_payload = Column("metadata", JSONB, nullable=False, default=dict)
    category = Column(String, nullable=True, index=True)
    embedding = Column(Vector(768), nullable=False)


class RAGEngine:
    """
    Retrieval-Augmented Generation (RAG) Engine using pgvector and Gemini text-embedding-004.
    """

    def __init__(self, session: AsyncSession) -> None:
        """
        Initialize the RAGEngine.

        Args:
            session (AsyncSession): SQLAlchemy async session for database operations.
        """
        self.session = session
        self.api_key = os.environ.get("GEMINI_API_KEY")
        self.model_name = "models/text-embedding-004"
        self.api_url = f"https://generativelanguage.googleapis.com/v1beta/{self.model_name}:embedContent"

    async def get_embedding(self, text: str) -> List[float]:
        """
        Generate a vector embedding for the given text using Gemini text-embedding-004.
        
        Args:
            text (str): The text to embed.
            
        Returns:
            List[float]: A 768-dimensional vector embedding.
            
        Raises:
            ValueError: If GEMINI_API_KEY is not set.
            httpx.HTTPError: If the API request fails.
        """
        if not self.api_key:
            raise ValueError("GEMINI_API_KEY environment variable is not set.")
            
        async with httpx.AsyncClient() as client:
            payload = {
                "model": self.model_name,
                "content": {
                    "parts": [{"text": text}]
                }
            }
            headers = {"Content-Type": "application/json"}
            params = {"key": self.api_key}
            
            try:
                response = await client.post(
                    self.api_url,
                    json=payload,
                    headers=headers,
                    params=params,
                    timeout=15.0
                )
                response.raise_for_status()
                data = response.json()
                return data["embedding"]["values"]
            except httpx.HTTPStatusError as e:
                logger.error(f"Gemini API HTTP error: {e.response.status_code} - {e.response.text}")
                raise
            except httpx.RequestError as e:
                logger.error(f"Gemini API request failed: {str(e)}")
                raise

    async def ingest_text(self, content: str, metadata: Dict[str, Any]) -> None:
        """
        Embed and store a text chunk with its metadata in the vector database.
        
        Args:
            content (str): The text content to ingest.
            metadata (Dict[str, Any]): Associated metadata (e.g., source, category).
            
        Raises:
            Exception: If database insertion fails.
        """
        embedding = await self.get_embedding(content)
        category = metadata.get("category")
        
        guideline = Guideline(
            content=content,
            metadata_payload=metadata,
            category=category,
            embedding=embedding
        )
        
        try:
            self.session.add(guideline)
            await self.session.commit()
        except Exception as e:
            await self.session.rollback()
            logger.error(f"Failed to ingest text into vector database: {str(e)}")
            raise

    async def search(self, query: str, top_k: int = 5, category: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Search for the most relevant guidelines using vector similarity.
        
        Args:
            query (str): The search query.
            top_k (int): Number of results to return. Default is 5.
            category (Optional[str]): Optional category filter.
            
        Returns:
            List[Dict[str, Any]]: List of matching guidelines with their distances.
            
        Raises:
            Exception: If the database query fails.
        """
        query_embedding = await self.get_embedding(query)
        
        distance_col = Guideline.embedding.cosine_distance(query_embedding).label("distance")
        stmt = select(Guideline, distance_col).order_by(distance_col).limit(top_k)
        
        if category:
            stmt = stmt.where(Guideline.category == category)
            
        try:
            result = await self.session.execute(stmt)
            rows = result.all()
            
            return [
                {
                    "id": str(row.Guideline.id),
                    "content": row.Guideline.content,
                    "metadata": row.Guideline.metadata_payload,
                    "category": row.Guideline.category,
                    "distance": float(row.distance)
                }
                for row in rows
            ]
        except Exception as e:
            logger.error(f"Failed to search guidelines in vector database: {str(e)}")
            raise