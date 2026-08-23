import json
import logging
import re
from datetime import UTC, datetime
from typing import Any

from app.core.config import get_settings

EMAIL_PATTERN = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
BEARER_PATTERN = re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]+")
SECRET_PATTERN = re.compile(
    r"(?i)\b(password|secret|token|api[_-]?key)\s*[:=]\s*[^\s,;]+"
)
SAFE_EXTRA_FIELDS = (
    "event",
    "correlation_id",
    "http_method",
    "route",
    "status_code",
    "duration_ms",
    "resource_id",
    "worker_id",
    "job_count",
    "attempt",
    "exception_type",
)


def redact_log_value(value: str) -> str:
    value = EMAIL_PATTERN.sub("[redacted-email]", value)
    value = BEARER_PATTERN.sub("Bearer [redacted]", value)
    return SECRET_PATTERN.sub(lambda match: f"{match.group(1)}=[redacted]", value)


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": redact_log_value(record.getMessage()),
        }
        for field in SAFE_EXTRA_FIELDS:
            value = getattr(record, field, None)
            if value is not None:
                payload[field] = redact_log_value(value) if isinstance(value, str) else value
        if record.exc_info and record.exc_info[0] is not None:
            payload["exception_type"] = record.exc_info[0].__name__
        return json.dumps(payload, ensure_ascii=True)


def configure_logging() -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    logging.basicConfig(
        level=getattr(logging, get_settings().log_level),
        handlers=[handler],
        force=True,
    )
