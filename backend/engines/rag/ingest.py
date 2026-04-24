import logging
from pathlib import Path
from typing import List

from sqlalchemy.ext.asyncio import AsyncSession

from engines.rag.engine import RAGEngine

logger = logging.getLogger(__name__)


def chunk_text(text: str, chunk_size: int = 500, overlap: int = 100) -> List[str]:
    """
    Splits text into smaller chunks with a specified overlap.
    
    Args:
        text (str): The text to be chunked.
        chunk_size (int): The maximum size of each chunk in characters.
        overlap (int): The number of overlapping characters between consecutive chunks.
        
    Returns:
        List[str]: A list of text chunks.
        
    Raises:
        ValueError: If chunk_size is less than or equal to 0, or if overlap is 
                    greater than or equal to chunk_size.
    """
    if not text:
        return []
        
    if chunk_size <= 0:
        raise ValueError("chunk_size must be greater than 0")
        
    if overlap >= chunk_size:
        raise ValueError("overlap must be less than chunk_size")
        
    chunks = []
    start = 0
    text_len = len(text)
    
    while start < text_len:
        end = start + chunk_size
        chunks.append(text[start:end])
        if end >= text_len:
            break
        start += (chunk_size - overlap)
        
    return chunks


async def ingest_all_guidelines(session: AsyncSession, guidelines_dir: str = "guidelines") -> None:
    """
    Reads markdown files from the guidelines directory, chunks the text,
    and ingests them into the vector database using the RAGEngine.
    
    Args:
        session (AsyncSession): SQLAlchemy async session for database operations.
        guidelines_dir (str): Path to the directory containing markdown guidelines.
                              Defaults to "guidelines".
    """
    base_path = Path(__file__).resolve().parent.parent.parent
    target_dir = base_path / guidelines_dir if not Path(guidelines_dir).is_absolute() else Path(guidelines_dir)
    
    if not target_dir.exists() or not target_dir.is_dir():
        logger.warning(f"Guidelines directory {target_dir} does not exist or is not a directory.")
        return
        
    rag_engine = RAGEngine(session)
    
    for file_path in target_dir.rglob("*.md"):
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read()
                
            if not content.strip():
                logger.debug(f"Skipping empty file: {file_path.name}")
                continue
                
            # Derive category from the parent directory name if it's not the base guidelines dir
            category = file_path.parent.name if file_path.parent != target_dir else "general"
            
            chunks = chunk_text(content, chunk_size=500, overlap=100)
            
            for i, chunk in enumerate(chunks):
                metadata = {
                    "source_file": file_path.name,
                    "chunk_index": i,
                    "total_chunks": len(chunks),
                    "category": category
                }
                await rag_engine.ingest_text(chunk, metadata)
                
            logger.info(f"Successfully ingested {len(chunks)} chunks from {file_path.name}")
            
        except Exception as e:
            logger.error(f"Failed to ingest guideline file {file_path}: {str(e)}")