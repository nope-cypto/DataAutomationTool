from __future__ import annotations

import re


SENSITIVE_PATTERNS = [
    re.compile(r"authorization\s*[:=]\s*[^;\r\n]+", re.IGNORECASE),
    re.compile(r"cookie\s*[:=]\s*[^;\r\n]+", re.IGNORECASE),
    re.compile(r"(?:jwt|token|password)\s*[:=]\s*[^;\r\n]+", re.IGNORECASE),
    re.compile(r"(?:keyword|asin)s?\s*[:=]\s*[^;\r\n]+", re.IGNORECASE),
]


def sanitize_log_message(message: str) -> str:
    sanitized = message
    for pattern in SENSITIVE_PATTERNS:
        sanitized = pattern.sub("[REDACTED]", sanitized)
    return sanitized
