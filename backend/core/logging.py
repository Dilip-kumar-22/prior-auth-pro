import logging
import json
import sys
from datetime import datetime, timezone
from typing import Any, Dict, List

from core.config import get_settings

SENSITIVE_KEYS: List[str] = [
    "password",
    "secret",
    "token",
    "authorization",
    "api_key",
    "ssn",
    "patient_ssn",
    "credit_card",
    "cvv"
]

class JSONLogFormatter(logging.Formatter):
    """
    Custom formatter to output logs as JSON strings.
    Ensures sensitive data is masked and exceptions are properly serialized.
    """

    def _mask_sensitive_data(self, data: Any) -> Any:
        """
        Recursively mask sensitive keys in dictionaries and lists.
        
        Args:
            data (Any): The data payload to sanitize.
            
        Returns:
            Any: The sanitized data payload.
        """
        if isinstance(data, dict):
            masked_data = {}
            for key, value in data.items():
                if any(sensitive_key in str(key).lower() for sensitive_key in SENSITIVE_KEYS):
                    masked_data[key] = "***MASKED***"
                else:
                    masked_data[key] = self._mask_sensitive_data(value)
            return masked_data
        elif isinstance(data, list):
            return [self._mask_sensitive_data(item) for item in data]
        return data

    def format(self, record: logging.LogRecord) -> str:
        """
        Format the log record as a JSON string.
        
        Args:
            record (logging.LogRecord): The log record to format.
            
        Returns:
            str: The JSON-formatted log string.
        """
        log_obj: Dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }

        standard_attrs = {
            "args", "asctime", "created", "exc_info", "exc_text", "filename",
            "funcName", "levelname", "levelno", "lineno", "module",
            "msecs", "message", "msg", "name", "pathname", "process",
            "processName", "relativeCreated", "stack_info", "thread", "threadName",
            "taskName", "color_message"
        }
        
        extra_data = {k: v for k, v in record.__dict__.items() if k not in standard_attrs}
        if extra_data:
            log_obj["extra"] = self._mask_sensitive_data(extra_data)

        if record.exc_info:
            log_obj["exception"] = self.formatException(record.exc_info)
        elif record.exc_text:
            log_obj["exception"] = record.exc_text

        return json.dumps(log_obj, default=str)

def setup_logging() -> None:
    """
    Configure the root logger and standard library loggers to use JSON formatting.
    Sets the log level based on the application settings and ensures no sensitive
    data is leaked into the logs.
    """
    settings = get_settings()
    log_level_str = settings.LOG_LEVEL.upper()
    log_level = getattr(logging, log_level_str, logging.INFO)

    json_handler = logging.StreamHandler(sys.stdout)
    json_handler.setFormatter(JSONLogFormatter())

    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)
    
    for handler in list(root_logger.handlers):
        root_logger.removeHandler(handler)
        
    root_logger.addHandler(json_handler)

    third_party_loggers = [
        "uvicorn",
        "uvicorn.access",
        "uvicorn.error",
        "fastapi",
        "sqlalchemy.engine",
        "sqlalchemy.pool",
        "httpx",
        "arq",
        "alembic"
    ]

    for logger_name in third_party_loggers:
        logger = logging.getLogger(logger_name)
        logger.handlers = []
        logger.propagate = True
        
        if logger_name in ("sqlalchemy.engine", "sqlalchemy.pool", "httpx") and log_level != logging.DEBUG:
            logger.setLevel(logging.WARNING)
        else:
            logger.setLevel(log_level)

def get_logger(name: str) -> logging.Logger:
    """
    Retrieve a logger instance by name.
    
    Args:
        name (str): The name of the logger, typically __name__.
        
    Returns:
        logging.Logger: The configured logger instance.
    """
    return logging.getLogger(name)