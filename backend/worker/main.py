import logging
import os
from typing import Any, Dict

from arq.connections import RedisSettings

from models.database import engine
from worker.tasks import generate_appeal_task, process_auth_request_task

logger = logging.getLogger(__name__)


async def startup(ctx: Dict[str, Any]) -> None:
    """
    ARQ worker startup function.
    
    Initializes database connections, external service configurations,
    and populates the worker context required by the background tasks.
    
    Args:
        ctx (Dict[str, Any]): The ARQ worker context dictionary.
    """
    logger.info("Starting up ARQ worker...")
    
    # Load FHIR configuration into context for tasks to use via client_from_session
    ctx["fhir_base_url"] = os.environ.get("FHIR_BASE_URL", "http://localhost:8080/fhir")
    ctx["fhir_token"] = os.environ.get("FHIR_TOKEN")
    
    try:
        ctx["fhir_timeout"] = float(os.environ.get("FHIR_TIMEOUT", "30.0"))
    except ValueError:
        ctx["fhir_timeout"] = 30.0
        
    # Store the SQLAlchemy async engine in the context
    ctx["db_engine"] = engine
    
    logger.info("ARQ worker startup complete. Context initialized.")


async def shutdown(ctx: Dict[str, Any]) -> None:
    """
    ARQ worker shutdown function.
    
    Gracefully closes database connections and cleans up resources
    to prevent connection leaks.
    
    Args:
        ctx (Dict[str, Any]): The ARQ worker context dictionary.
    """
    logger.info("Shutting down ARQ worker...")
    
    db_engine = ctx.get("db_engine")
    if db_engine:
        try:
            await db_engine.dispose()
            logger.info("Database engine disposed successfully.")
        except Exception as e:
            logger.error(f"Error disposing database engine: {str(e)}")
            
    logger.info("ARQ worker shutdown complete.")


class WorkerSettings:
    """
    Configuration class for the ARQ worker.
    
    Defines the Redis connection, startup/shutdown lifecycle hooks, 
    and the list of background tasks available for processing.
    """
    
    redis_settings = RedisSettings.from_dsn(
        os.environ.get("REDIS_URL", "redis://localhost:6379")
    )
    
    functions = [
        process_auth_request_task,
        generate_appeal_task
    ]
    
    on_startup = startup
    on_shutdown = shutdown
    
    max_jobs = int(os.environ.get("ARQ_MAX_JOBS", "10"))
    job_timeout = int(os.environ.get("ARQ_JOB_TIMEOUT", "300"))
    keep_result = int(os.environ.get("ARQ_KEEP_RESULT", "3600"))
    max_tries = int(os.environ.get("ARQ_MAX_TRIES", "3"))