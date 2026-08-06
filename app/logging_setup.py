import json
import logging
import os
import sys
from datetime import datetime
from pathlib import Path
from app.settings import settings


class SensitiveFilter(logging.Filter):
    """Filter out sensitive info like API keys from log records."""

    def filter(self, record: logging.LogRecord) -> bool:
        api_key = settings.ai_api_key
        if api_key and len(api_key) > 4:
            msg = record.getMessage()
            if api_key in msg:
                record.msg = msg.replace(api_key, "***REDACTED_API_KEY***")
                record.args = ()
        return True


class JsonFormatter(logging.Formatter):
    """Format logs as JSON lines."""

    def format(self, record: logging.LogRecord) -> str:
        log_entry = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "level": record.levelname,
            "pipeline_step": getattr(record, "pipeline_step", "general"),
            "provider_id": getattr(record, "provider_id", None),
            "source_url": getattr(record, "source_url", None),
            "error_type": getattr(record, "error_type", None),
            "error_message": record.getMessage(),
        }
        return json.dumps(log_entry, ensure_ascii=False)


def setup_logging() -> logging.Logger:
    """Setup logger with console and file handlers."""
    settings.ensure_directories()
    logger = logging.getLogger("bestai_parser")
    logger.setLevel(logging.INFO)

    if logger.handlers:
        return logger

    sensitive_filter = SensitiveFilter()

    # File Handler
    log_file_path = Path(settings.log_dir) / "app.log"
    file_handler = logging.FileHandler(log_file_path, encoding="utf-8")
    file_handler.setFormatter(JsonFormatter())
    file_handler.addFilter(sensitive_filter)
    logger.addHandler(file_handler)

    # Console Handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(logging.Formatter("[%(levelname)s] %(message)s"))
    console_handler.addFilter(sensitive_filter)
    logger.addHandler(console_handler)

    return logger


logger = setup_logging()
