import io
import json
import logging
from typing import BinaryIO

logger = logging.getLogger("runtime.file_validator")


MAGIC_SIGNATURES = {
    "application/pdf": [b"%PDF-", b"%PDF"],
    "image/png": [b"\x89PNG\r\n\x1a\n"],
    "image/jpeg": [b"\xff\xd8\xff"],
}


class FileValidationError(Exception):
    """Raised when an uploaded file violates limits or fails magic byte verification."""

    def __init__(self, message_ar: str, code: str = "invalid_file") -> None:
        super().__init__(message_ar)
        self.message_ar = message_ar
        self.code = code


def verify_file_content(
    file_bytes: bytes,
    claimed_mime: str,
    allowed_types: list[str],
) -> str:
    """
    Verifies that the uploaded file matches an allowed MIME type and its real magic byte signature.
    Never relies solely on client-supplied Content-Type or file extension.
    Returns the verified MIME type.
    """
    if claimed_mime not in allowed_types:
        raise FileValidationError(
            f"نوع الملف '{claimed_mime}' غير مسموح به لهذا الوكيل.",
            code="unsupported_file_type",
        )

    # Check magic signatures where applicable
    if claimed_mime in MAGIC_SIGNATURES:
        signatures = MAGIC_SIGNATURES[claimed_mime]
        matched = any(file_bytes.startswith(sig) for sig in signatures)
        if not matched:
            raise FileValidationError(
                f"محتوى الملف لا يطابق توقيع النوع المصرح به ({claimed_mime}).",
                code="file_signature_mismatch",
            )
        return claimed_mime

    # Plain text / CSV validation
    if claimed_mime in ("text/plain", "text/csv"):
        if b"\x00" in file_bytes[:1024]:
            raise FileValidationError("الملف النصي يحتوي على بايتات ثنائية غير صالحة.", code="invalid_text_file")
        try:
            file_bytes.decode("utf-8")
        except UnicodeDecodeError:
            raise FileValidationError("الملف النصي يجب أن يكون بترميز UTF-8 صالح.", code="invalid_encoding")
        return claimed_mime

    # JSON validation
    if claimed_mime == "application/json":
        try:
            json.loads(file_bytes.decode("utf-8"))
        except Exception:
            raise FileValidationError("ملف JSON غير صالح.", code="invalid_json_file")
        return claimed_mime

    raise FileValidationError(f"نوع الملف غير مدعوم للتحقق الآمن: {claimed_mime}", code="unsupported_file_type")


def sanitize_filename(filename: str) -> str:
    """
    Sanitizes filename to prevent directory traversal or shell meta-characters.
    """
    import os
    import re

    base = os.path.basename(filename)
    # Remove all dangerous characters, keep only alphanumerics, dots, hyphens, underscores
    sanitized = re.sub(r"[^a-zA-Z0-9._-]", "_", base)
    if not sanitized or sanitized.startswith("."):
        sanitized = f"upload_{sanitized}".lstrip(".")
    return sanitized[:128]
