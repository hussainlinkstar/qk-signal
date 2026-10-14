from __future__ import annotations

import base64
import ipaddress
import mimetypes
import socket
from io import BytesIO
from urllib.parse import urlparse


_MAX_REMOTE_ASSET_BYTES = 5 * 1024 * 1024
_PRIVATE_HOSTNAMES = {"localhost", "backend", "frontend"}


def _clean_base64_payload(value: str) -> str:
    return "".join(str(value or "").strip().split())


def _decode_base64_payload(value: str) -> bytes | None:
    cleaned = _clean_base64_payload(value)
    if not cleaned:
        return None

    padding = "=" * ((4 - (len(cleaned) % 4)) % 4)
    payload = (cleaned + padding).encode("ascii", "ignore")
    try:
        return base64.b64decode(payload, altchars=b"-_", validate=False)
    except Exception:
        return None


def _guess_mime_type(payload: bytes, source_hint: str | None = None, *, default: str) -> str:
    trimmed = payload.lstrip()
    lowered_hint = str(source_hint or "").lower()

    if trimmed.startswith(b"<svg") or trimmed.startswith(b"<?xml") and b"<svg" in trimmed[:256]:
        return "image/svg+xml"
    if payload.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if payload.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if payload.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if payload.startswith(b"RIFF") and payload[8:12] == b"WEBP":
        return "image/webp"

    guessed, _ = mimetypes.guess_type(lowered_hint)
    return guessed or default


def _build_data_uri(payload: bytes, mime_type: str) -> str:
    encoded = base64.b64encode(payload).decode("ascii")
    return f"data:{mime_type};base64,{encoded}"


def _is_public_hostname(hostname: str) -> bool:
    normalized = str(hostname or "").strip().rstrip(".").lower()
    if not normalized or normalized in _PRIVATE_HOSTNAMES:
        return False

    try:
        parsed_ip = ipaddress.ip_address(normalized)
    except ValueError:
        parsed_ip = None

    if parsed_ip is not None:
        return not (
            parsed_ip.is_private
            or parsed_ip.is_loopback
            or parsed_ip.is_link_local
            or parsed_ip.is_multicast
            or parsed_ip.is_reserved
            or parsed_ip.is_unspecified
        )

    try:
        resolved = socket.getaddrinfo(normalized, 443, type=socket.SOCK_STREAM)
    except OSError:
        return False

    public_addresses = 0
    for _, _, _, _, sockaddr in resolved:
        address = sockaddr[0]
        try:
            parsed = ipaddress.ip_address(address)
        except ValueError:
            return False
        if (
            parsed.is_private
            or parsed.is_loopback
            or parsed.is_link_local
            or parsed.is_multicast
            or parsed.is_reserved
            or parsed.is_unspecified
        ):
            return False
        public_addresses += 1
    return public_addresses > 0


def _is_safe_remote_asset_url(value: str) -> bool:
    parsed = urlparse(value)
    if parsed.scheme != "https":
        return False
    if parsed.username or parsed.password or not parsed.hostname:
        return False
    try:
        port = parsed.port
    except ValueError:
        return False
    if port not in (None, 443):
        return False
    return _is_public_hostname(parsed.hostname)


def coerce_base64_image_data_uri(
    value: str | None, *, default_mime: str = "image/png"
) -> str | None:
    if not value:
        return None

    normalized = str(value).strip()
    if normalized.startswith("data:"):
        return normalized

    payload = _decode_base64_payload(normalized)
    if payload is None:
        return None
    return _build_data_uri(payload, _guess_mime_type(payload, default=default_mime))


def resolve_asset_data_uri(source: str | None, *, default_mime: str = "image/png") -> str | None:
    if not source:
        return None

    normalized = str(source).strip()
    if not normalized:
        return None
    if normalized.startswith("data:"):
        return normalized
    if normalized.startswith("gs://") or normalized.startswith("local://"):
        from services.s3_storage_service import get_storage_service

        payload = get_storage_service().download_file(storage_uri=normalized)
        if not payload:
            return None
        return _build_data_uri(
            payload,
            _guess_mime_type(payload, normalized, default=default_mime),
        )
    if normalized.startswith("http://") or normalized.startswith("https://"):
        if not _is_safe_remote_asset_url(normalized):
            return None
        try:
            from services.url_validation import safe_sync_fetch

            response = safe_sync_fetch(
                normalized,
                method="GET",
                timeout=10.0,
                headers={"User-Agent": "Qiko Signal PDF Renderer/1.0"},
            )
        except Exception:
            return None
        if len(response.content) > _MAX_REMOTE_ASSET_BYTES:
            return None

        content_type = response.headers.get("content-type") or ""
        mime_type = content_type.split(";", 1)[0].strip()
        if not mime_type:
            mime_type = _guess_mime_type(response.content, normalized, default=default_mime)
        if mime_type != "image/svg+xml" and not mime_type.startswith("image/"):
            mime_type = _guess_mime_type(response.content, normalized, default=default_mime)
        if mime_type != "image/svg+xml" and not mime_type.startswith("image/"):
            return None
        return _build_data_uri(response.content, mime_type)

    payload = _decode_base64_payload(normalized)
    if payload is None:
        return None
    return _build_data_uri(payload, _guess_mime_type(payload, normalized, default=default_mime))


def read_image_bytes(data_uri: str | None) -> BytesIO | None:
    if not data_uri or not str(data_uri).startswith("data:"):
        return None
    try:
        _, encoded = str(data_uri).split(",", 1)
    except ValueError:
        return None
    payload = _decode_base64_payload(encoded)
    if payload is None:
        return None
    return BytesIO(payload)
