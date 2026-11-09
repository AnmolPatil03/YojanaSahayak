"""Structured JSON logging with request ids and PII masking."""

from __future__ import annotations

import contextvars
import json
import logging
import re
import sys
from datetime import UTC, datetime

request_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "request_id", default=None
)

_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_PHONE = re.compile(r"(?<!\d)(?:\+?91[\s-]?)?[6-9]\d{9}(?!\d)")
_AADHAAR = re.compile(r"(?<!\d)\d{4}[\s-]?\d{4}[\s-]?\d{4}(?!\d)")
_KEY = re.compile(r"\b(sk|gsk|ghp|github_pat|AIza)[-_A-Za-z0-9]{12,}")
_PROFILE_FIELDS = re.compile(
    r"(\"?(?:age|annual_family_income|income|social_category|caste|gender|disability|"
    r"state|occupation|education_level|residence)\"?\s*[:=]\s*)(\"[^\"]*\"|[^,}\s]+)",
    re.I,
)


def mask_pii(text: str) -> str:
    """Mask emails, phone and Aadhaar-like numbers, API keys and profile values."""
    text = _KEY.sub("[key]", text)
    text = _EMAIL.sub("[email]", text)
    text = _AADHAAR.sub("[id]", text)
    text = _PHONE.sub("[phone]", text)
    return _PROFILE_FIELDS.sub(lambda m: f"{m.group(1)}[masked]", text)


class PiiMaskingFilter(logging.Filter):
    """Applies `mask_pii` to every record before it is formatted."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:
            return True
        record.msg = mask_pii(message)
        record.args = None
        return True


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "ts": datetime.fromtimestamp(record.created, tz=UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        request_id = request_id_var.get()
        if request_id:
            payload["request_id"] = request_id
        for key in ("method", "path", "status", "duration_ms"):
            value = getattr(record, key, None)
            if value is not None:
                payload[key] = value
        if record.exc_info:
            payload["exc"] = mask_pii(self.formatException(record.exc_info))
        return json.dumps(payload, ensure_ascii=False)


def configure_logging(level: str = "INFO", *, json_output: bool = True) -> None:
    """Install a single stderr handler with masking; safe to call more than once."""
    root = logging.getLogger()
    root.setLevel(level.upper())
    for handler in list(root.handlers):
        if getattr(handler, "_yojana", False):
            root.removeHandler(handler)
    handler = logging.StreamHandler(sys.stderr)
    handler._yojana = True  # type: ignore[attr-defined]
    handler.addFilter(PiiMaskingFilter())
    handler.setFormatter(
        JsonFormatter() if json_output else logging.Formatter("%(levelname)s %(name)s: %(message)s")
    )
    root.addHandler(handler)
    for noisy in ("httpx", "httpcore", "urllib3", "sentence_transformers", "filelock"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
