import base64
import binascii
import re


_BASE64_DATA_URL_MARKER = ";base64,"


def normalize_screenshot_base64(payload: str) -> str:
    """Normalize screenshot payloads into canonical standard base64.

    Accepts raw base64 and ``data:*;base64,...`` payloads, strips whitespace,
    converts URL-safe characters to standard base64 alphabet, adds missing
    padding, then performs strict decoding/encoding to return canonical base64.
    """

    if not isinstance(payload, str):
        raise ValueError("Screenshot payload must be a string")

    normalized_payload = payload.strip()
    if normalized_payload.startswith("data:") and _BASE64_DATA_URL_MARKER in normalized_payload:
        normalized_payload = normalized_payload.split(",", 1)[1]

    normalized_payload = re.sub(r"\s+", "", normalized_payload)
    normalized_payload = normalized_payload.replace("-", "+").replace("_", "/")

    padding = (-len(normalized_payload)) % 4
    if padding:
        normalized_payload += "=" * padding

    try:
        decoded = base64.b64decode(normalized_payload, validate=True)
    except binascii.Error as exc:
        raise ValueError("Invalid screenshot payload") from exc

    return base64.b64encode(decoded).decode("ascii")
