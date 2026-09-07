from __future__ import annotations

from collections.abc import Mapping
import hashlib
import json
import re
import shlex
from urllib.parse import urlsplit

from .log_sanitizer import sanitize_log_message


SESSION_HEADER = "x-data-automation-session"
SENSITIVE_STATE_KEYS = {
    "authorization",
    "cookie",
    "curl",
    "curltext",
    "jwt",
    "password",
    "request",
    "requesttext",
    "token",
}
BUSINESS_COLLECTION_KEYS = {"asins", "entities", "files", "items", "keywords", "searchterms", "seeds"}


class SessionAuthError(RuntimeError):
    """Raised when a local worker request does not carry the launch secret."""


def require_session(headers: Mapping[str, str], expected_secret: str) -> None:
    normalized = {key.lower(): value for key, value in headers.items()}
    if not expected_secret or normalized.get(SESSION_HEADER) != expected_secret:
        raise SessionAuthError("invalid worker session")


def _body_shape(value: object, prefix: str = "") -> list[str]:
    if isinstance(value, dict):
        result: list[str] = []
        for key in sorted(value):
            child = f"{prefix}.{key}" if prefix else str(key)
            result.append(child)
            result.extend(_body_shape(value[key], child))
        return result
    if isinstance(value, list):
        return [f"{prefix}[]"] + (_body_shape(value[0], f"{prefix}[]") if value else [])
    return []


def _strip_shell_quotes(value: str) -> str:
    text = str(value).strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in {"'", '"'}:
        return text[1:-1]
    return text


def credential_free_curl_fingerprint(curl_text: str) -> str:
    tokens = shlex.split(str(curl_text), posix=False)
    normalized_tokens = [_strip_shell_quotes(token) for token in tokens]
    url = next((token for token in normalized_tokens[1:] if token.lower().startswith(("http://", "https://"))), "")
    parsed = urlsplit(url)
    query_keys = sorted({part.split("=", 1)[0] for part in parsed.query.split("&") if part})
    method = "GET"
    content_type = ""
    body_shape: list[str] = []
    for index, token in enumerate(normalized_tokens):
        lowered = token.lower()
        if lowered in {"-x", "--request"} and index + 1 < len(normalized_tokens):
            method = normalized_tokens[index + 1].upper()
        if lowered in {"-h", "--header"} and index + 1 < len(normalized_tokens):
            header = normalized_tokens[index + 1]
            if header.lower().startswith("content-type:"):
                content_type = header.split(":", 1)[1].strip().lower()
        if lowered in {"--data", "--data-raw", "--data-binary"} and index + 1 < len(normalized_tokens):
            if method == "GET":
                method = "POST"
            try:
                body_shape = sorted(_body_shape(json.loads(normalized_tokens[index + 1])))
            except (json.JSONDecodeError, TypeError):
                body_shape = ["opaque-body"]
    canonical = {
        "method": method,
        "host": parsed.netloc.lower(),
        "path": parsed.path,
        "queryKeys": query_keys,
        "contentType": content_type,
        "bodyKeys": body_shape,
    }
    return hashlib.sha256(json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def sanitize_sensitive_text(message: str) -> str:
    text = str(message)
    if re.search(r"(^|\s)curl(?:\.exe)?\s", text, re.IGNORECASE):
        return "[REDACTED_CURL]"
    return sanitize_log_message(text)


def sanitize_persisted_job_inputs(inputs: Mapping[str, object]) -> dict[str, object]:
    sanitized: dict[str, object] = {}
    for key, value in inputs.items():
        compact_key = re.sub(r"[^a-z0-9]", "", str(key).lower())
        if compact_key in BUSINESS_COLLECTION_KEYS and isinstance(value, (list, tuple, set)):
            sanitized[f"{key}Count"] = len(value)
        elif compact_key in SENSITIVE_STATE_KEYS:
            sanitized[str(key)] = "[REDACTED]"
        elif isinstance(value, Mapping):
            sanitized[str(key)] = sanitize_persisted_job_inputs(value)
        elif isinstance(value, str):
            sanitized[str(key)] = sanitize_sensitive_text(value)
        else:
            sanitized[str(key)] = value
    return sanitized
