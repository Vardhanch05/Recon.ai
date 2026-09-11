
import logging
import json
import sys
import os
from datetime import datetime, timezone
from typing import Any, Dict


class JSONFormatter(logging.Formatter):
    """
    JSON log formatter for production log aggregators.
    Formats logs as single-line JSON objects with timestamps, level, logger name,
    message, and any contextual extra fields.
    """
    def format(self, record: logging.LogRecord) -> str:
        log_obj: Dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "lineno": record.lineno,
        }
        if record.exc_info:
            log_obj["exception"] = self.formatException(record.exc_info)
        
        # Include custom extra fields if provided
        for key, val in record.__dict__.items():
            if key not in ("name", "msg", "args", "levelname", "levelno", "pathname",
                           "filename", "module", "exc_info", "exc_text", "stack_info",
                           "lineno", "funcName", "created", "msecs", "relativeCreated",
                           "thread", "threadName", "processName", "process", "message"):
                log_obj[key] = val

        return json.dumps(log_obj)


def setup_logging(environment: str = "development") -> logging.Logger:
    """
    Configures root and application loggers.
    Uses JSONFormatter for production and readable formatted logs for development.
    """
    log_level_str = os.getenv("LOG_LEVEL", "INFO").upper()
    log_level = getattr(logging, log_level_str, logging.INFO)

    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)

    # Clear existing handlers to prevent duplicate lines
    if root_logger.hasHandlers():
        root_logger.handlers.clear()

    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(log_level)

    if environment.lower() == "production":
        handler.setFormatter(JSONFormatter())
    else:
        dev_formatter = logging.Formatter(
            fmt="%(asctime)s [%(levelname)s] [%(name)s:%(lineno)d] %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S"
        )
        handler.setFormatter(dev_formatter)

    root_logger.addHandler(handler)

    # Configure app logger
    logger = logging.getLogger("recon_ai")
    logger.setLevel(log_level)
    return logger
