import io
import logging
import re
from typing import Any

# Regex patterns matching API keys and secret header representations
SECRET_PATTERNS = [
    # Google AI Studio / Gemini keys
    re.compile(r"AIza[0-9A-Za-z_-]{35}"),
    # Anthropic keys
    re.compile(r"sk-ant-[A-Za-z0-9_-]{20,}"),
    # OpenAI and generic API keys (sk-...)
    re.compile(r"sk-[A-Za-z0-9_-]{20,}"),
    # Bearer tokens in headers
    re.compile(r"(Bearer\s+)[A-Za-z0-9_\-\.]{20,}", re.IGNORECASE),
    # Key headers in dict/text formats: 'X-Provider-Key': '...', 'authorization': '...'
    re.compile(r"(['\"]?(?:x-provider-key|x-goog-api-key|x-api-key|authorization)['\"]?\s*[:=]\s*['\"]?)([^'\",\s]+)", re.IGNORECASE),
]

REDACTED_SUB = "[REDACTED_KEY]"


def scrub_secrets(text: str) -> str:
    """Scrub known secret formats and key patterns from text."""
    if not isinstance(text, str):
        return text

    scrubbed = text
    for pattern in SECRET_PATTERNS:
        # If the pattern has capturing groups, preserve header prefix and redact value
        if pattern.groups == 2:
            scrubbed = pattern.sub(r"\1" + REDACTED_SUB, scrubbed)
        elif pattern.groups == 1:
            scrubbed = pattern.sub(r"\1" + REDACTED_SUB, scrubbed)
        else:
            scrubbed = pattern.sub(REDACTED_SUB, scrubbed)
    return scrubbed


def _scrub_obj(obj: Any) -> Any:
    """Recursively scrub strings inside container objects."""
    if isinstance(obj, str):
        return scrub_secrets(obj)
    if isinstance(obj, dict):
        return {k: _scrub_obj(v) for k, v in obj.items()}
    if isinstance(obj, tuple):
        return tuple(_scrub_obj(x) for x in obj)
    if isinstance(obj, list):
        return [_scrub_obj(x) for x in obj]
    return obj


class RedactionFilter(logging.Filter):
    """
    Guarantees that X-Provider-Key and anything key-shaped is scrubbed from every log record.
    Evaluates formatted message to prevent template formatting mismatch while scrubbing secrets.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            # Format message with args first, then scrub secrets from final string
            formatted = record.getMessage()
            record.msg = scrub_secrets(formatted)
            record.args = ()
        except Exception:
            if isinstance(record.msg, str):
                record.msg = scrub_secrets(record.msg)
            if record.args:
                record.args = _scrub_obj(record.args)

        if record.exc_text:
            record.exc_text = scrub_secrets(record.exc_text)

        return True


def setup_redaction_logging() -> None:
    """Configure standard logging with redaction filter on all handlers."""
    redaction_filter = RedactionFilter()

    # Apply to root logger and its handlers
    root_logger = logging.getLogger()
    root_logger.addFilter(redaction_filter)
    for handler in root_logger.handlers:
        handler.addFilter(redaction_filter)

    # Apply to uvicorn loggers
    for logger_name in ("uvicorn", "uvicorn.access", "uvicorn.error"):
        l = logging.getLogger(logger_name)
        l.addFilter(redaction_filter)
        for h in l.handlers:
            h.addFilter(redaction_filter)


def verify_redaction_filter() -> bool:
    """
    Self-check proving that the redaction filter successfully masks test keys and headers.
    Returns True if verification passes, raises AssertionError otherwise.
    """
    test_stream = io.StringIO()
    handler = logging.StreamHandler(test_stream)
    filter_instance = RedactionFilter()
    handler.addFilter(filter_instance)
    handler.setFormatter(logging.Formatter("%(message)s"))

    test_logger = logging.getLogger("redaction_test_logger")
    test_logger.setLevel(logging.INFO)
    test_logger.addHandler(handler)
    test_logger.propagate = False

    fake_gemini_key = "AIzaSy" + "D" * 33
    fake_openai_key = "sk-" + "A" * 32
    fake_anthropic_key = "sk-ant-" + "B" * 32

    # Emit test log records
    test_logger.info("Testing key transit: X-Provider-Key: %s", fake_gemini_key)
    test_logger.info("Headers dict: %s", {"X-Provider-Key": fake_openai_key, "other": "ok"})
    test_logger.info("Raw Anthropic key in text: %s", fake_anthropic_key)

    output = test_stream.getvalue()

    # Assert none of the raw keys appear in output
    assert fake_gemini_key not in output, "Gemini key leaked in log output!"
    assert fake_openai_key not in output, "OpenAI key leaked in log output!"
    assert fake_anthropic_key not in output, "Anthropic key leaked in log output!"
    assert REDACTED_SUB in output, "Redacted substitution missing from log output!"

    return True
