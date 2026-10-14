import ipaddress
import logging
import os
import socket
from fnmatch import fnmatch
from typing import Any, NamedTuple
from urllib.parse import urljoin, urlparse

import httpx
from pydantic import HttpUrl, TypeAdapter, ValidationError

logger = logging.getLogger(__name__)

_HTTP_URL_ADAPTER = TypeAdapter(HttpUrl)
_MAX_REDIRECTS = 5
_DEFAULT_TIMEOUT = 15.0
_MAX_RESPONSE_BYTES = 10 * 1024 * 1024  # 10 MB
_DEFAULT_USER_AGENT = "Qiko Signal/1.0"
_MAX_PINNED_IPS = 4


class SSRFBlockedError(ValueError):
    """The request was blocked by SSRF protection policy."""


class ResponseTooLargeError(ValueError):
    """The response body exceeds the configured maximum size."""


class ValidatedTarget(NamedTuple):
    """A URL that passed SSRF validation, plus the addresses it resolved to.

    *ips* carries the addresses that were checked against the forbidden ranges.
    Requests are issued against those addresses instead of the hostname, so a
    DNS-rebinding domain cannot swap in a private address between the check and
    the socket connect (SIGV2-1247). It is empty when the hostname could not be
    resolved locally, and holds the single literal address when the URL already
    targets an IP.
    """

    url: str
    host: str
    ips: tuple[str, ...]


def normalize_and_validate_url(raw_url: str) -> str:
    return validate_url_target(raw_url).url


def validate_url_target(raw_url: str) -> ValidatedTarget:
    trimmed = (raw_url or "").strip()
    if not trimmed:
        raise ValueError("URL is required.")

    if not trimmed.startswith(("http://", "https://")):
        raise ValueError("Invalid URL format. URL must start with http:// or https://.")

    try:
        normalized_url = str(_HTTP_URL_ADAPTER.validate_python(trimmed))
    except ValidationError as exc:
        raise ValueError("Invalid URL format.") from exc

    parsed = urlparse(normalized_url)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("Only http(s) URLs are allowed.")
    if not parsed.netloc:
        raise ValueError("Please provide a valid URL.")

    host = (parsed.hostname or "").strip().lower().rstrip(".")
    if not host:
        raise ValueError("Please provide a valid URL.")
    if any(char.isspace() for char in host):
        raise ValueError("Please provide a valid URL.")

    validated_ips = _validate_host(host)

    normalized = parsed.geturl()
    if parsed.path == "/" and not parsed.params and not parsed.query and not parsed.fragment:
        normalized = f"{parsed.scheme}://{parsed.netloc}"
    return ValidatedTarget(url=normalized, host=host, ips=validated_ips)


def validate_target_host(target: str) -> None:
    value = (target or "").strip()
    if not value:
        raise ValueError("URL or domain is required.")

    parsed = urlparse(value if value.startswith(("http://", "https://")) else f"https://{value}")
    host = (parsed.hostname or parsed.netloc or parsed.path or "").strip().lower().rstrip(".")
    if not host:
        raise ValueError("A valid URL or domain is required.")

    _validate_host(host)


def _load_policy_entries(env_name: str) -> list[str]:
    raw = os.getenv(env_name, "")
    return [item.strip().lower() for item in raw.split(",") if item.strip()]


def _validate_host(host: str) -> tuple[str, ...]:
    """Validate *host* against SSRF policy and return the approved addresses.

    The hostname is resolved exactly once; the returned addresses are the ones
    that were checked, so callers can connect to them directly instead of
    re-resolving the hostname.
    """
    if host == "localhost" or host.endswith(".localhost"):
        raise ValueError("Localhost targets are not allowed.")

    if host in {"[::1]", "::1"}:
        raise ValueError("Loopback targets are not allowed.")

    ip_obj = _parse_ip(host)
    if ip_obj and _is_forbidden_ip(ip_obj):
        raise ValueError("Private or reserved network targets are not allowed.")

    validated_ips: tuple[str, ...] = (str(ip_obj),) if ip_obj else ()
    if ip_obj is None:
        resolved_ips = _resolve_host_ips(host)
        if any(_is_forbidden_ip(resolved_ip) for resolved_ip in resolved_ips):
            raise ValueError("Private or reserved network targets are not allowed.")
        validated_ips = tuple(str(resolved_ip) for resolved_ip in resolved_ips)

    deny_entries = _load_policy_entries("URL_VALIDATION_DENYLIST")
    if deny_entries and _matches_policy(host, ip_obj, deny_entries):
        raise ValueError("Target is blocked by URL denylist policy.")

    allow_entries = _load_policy_entries("URL_VALIDATION_ALLOWLIST")
    if allow_entries and not _matches_policy(host, ip_obj, allow_entries):
        raise ValueError("Target is not permitted by URL allowlist policy.")

    return validated_ips


def _parse_ip(host: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    value = host
    if value.startswith("[") and value.endswith("]"):
        value = value[1:-1]
    try:
        return ipaddress.ip_address(value)
    except ValueError:
        return None


def _is_forbidden_ip(ip_obj: ipaddress._BaseAddress) -> bool:
    return any(
        [
            ip_obj.is_private,
            ip_obj.is_loopback,
            ip_obj.is_link_local,
            ip_obj.is_reserved,
            ip_obj.is_multicast,
            ip_obj.is_unspecified,
        ]
    )


def _matches_policy(host: str, ip_obj: ipaddress._BaseAddress | None, entries: list[str]) -> bool:
    for entry in entries:
        try:
            network = ipaddress.ip_network(entry, strict=False)
            if ip_obj and ip_obj in network:
                return True
            continue
        except ValueError:
            pass

        if host == entry or host.endswith(f".{entry}") or fnmatch(host, entry):
            return True
    return False


def _resolve_host_ips(host: str) -> tuple[ipaddress.IPv4Address | ipaddress.IPv6Address, ...]:
    try:
        address_info = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    except OSError:
        return ()

    resolved: list[ipaddress.IPv4Address | ipaddress.IPv6Address] = []
    seen: set[str] = set()
    for family, _socktype, _proto, _canonname, sockaddr in address_info:
        if family not in {socket.AF_INET, socket.AF_INET6}:
            continue
        raw_ip = sockaddr[0]
        try:
            ip_obj = ipaddress.ip_address(raw_ip)
        except ValueError:
            continue
        normalized = str(ip_obj)
        if normalized in seen:
            continue
        seen.add(normalized)
        resolved.append(ip_obj)
    return tuple(resolved)


def resolve_redirect_target(current_url: str, location: str | None) -> str:
    return validate_redirect_target(current_url, location).url


def validate_redirect_target(current_url: str, location: str | None) -> ValidatedTarget:
    if not location:
        raise ValueError("Redirect response is missing a Location header.")
    return validate_url_target(urljoin(current_url, location))


# ---------------------------------------------------------------------------
# Validated-IP pinning
# ---------------------------------------------------------------------------


class _ConnectAttempt(NamedTuple):
    url: str
    headers: dict[str, str]
    extensions: dict[str, Any]


def _connect_attempts(
    target: ValidatedTarget,
    headers: dict[str, str] | None = None,
) -> list[_ConnectAttempt]:
    """Build the connect candidates for an already validated target.

    Every candidate points at an address that validation approved, carries the
    original ``Host`` header and sets ``sni_hostname`` so TLS still presents and
    verifies the real hostname rather than the pinned address. Candidates are
    tried in resolver order, which preserves the multi-address fallback the
    socket layer used to provide.
    """
    request_headers = dict(headers or {})
    parsed = httpx.URL(target.url)
    pinned_ips = [ip for ip in target.ips if ip != parsed.host][:_MAX_PINNED_IPS]

    if not pinned_ips:
        # Either the URL already targets the validated literal address, or the
        # hostname did not resolve locally and there is nothing to pin.
        if not target.ips:
            logger.debug(
                "No resolved address to pin for %s; connecting by hostname.",
                target.host,
            )
        return [_ConnectAttempt(target.url, request_headers, {})]

    if "host" not in {key.lower() for key in request_headers}:
        request_headers["Host"] = parsed.netloc.decode("ascii")

    return [
        _ConnectAttempt(
            url=str(parsed.copy_with(host=pinned_ip)),
            headers=dict(request_headers),
            extensions={"sni_hostname": target.host},
        )
        for pinned_ip in pinned_ips
    ]


async def _request_pinned_async(
    client: httpx.AsyncClient,
    *,
    method: str,
    target: ValidatedTarget,
    headers: dict[str, str] | None = None,
    **kwargs: Any,
) -> httpx.Response:
    attempts = _connect_attempts(target, headers)
    last_error: httpx.ConnectError | httpx.ConnectTimeout | None = None
    for attempt in attempts:
        try:
            return await client.request(
                method,
                attempt.url,
                headers=attempt.headers,
                extensions=attempt.extensions,
                **kwargs,
            )
        except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
            last_error = exc
    raise last_error  # type: ignore[misc]


def _request_pinned_sync(
    client: httpx.Client,
    *,
    method: str,
    target: ValidatedTarget,
    headers: dict[str, str] | None = None,
    **kwargs: Any,
) -> httpx.Response:
    attempts = _connect_attempts(target, headers)
    last_error: httpx.ConnectError | httpx.ConnectTimeout | None = None
    for attempt in attempts:
        try:
            return client.request(
                method,
                attempt.url,
                headers=attempt.headers,
                extensions=attempt.extensions,
                **kwargs,
            )
        except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
            last_error = exc
    raise last_error  # type: ignore[misc]


async def async_request_with_validation(
    client: httpx.AsyncClient,
    *,
    method: str,
    url: str,
    headers: dict[str, str] | None = None,
) -> tuple[httpx.Response, str]:
    target = validate_url_target(url)
    current_method = method.upper()
    for _ in range(_MAX_REDIRECTS + 1):
        response = await _request_pinned_async(
            client,
            method=current_method,
            target=target,
            headers=headers,
        )
        if not response.is_redirect:
            return response, target.url
        target = validate_redirect_target(target.url, response.headers.get("location"))
        if response.status_code == 303 and current_method != "HEAD":
            current_method = "GET"
    raise ValueError("Too many redirects.")


def sync_request_with_validation(
    client: httpx.Client,
    *,
    method: str,
    url: str,
    headers: dict[str, str] | None = None,
) -> tuple[httpx.Response, str]:
    target = validate_url_target(url)
    current_method = method.upper()
    for _ in range(_MAX_REDIRECTS + 1):
        response = _request_pinned_sync(
            client,
            method=current_method,
            target=target,
            headers=headers,
        )
        if not response.is_redirect:
            return response, target.url
        target = validate_redirect_target(target.url, response.headers.get("location"))
        if response.status_code == 303 and current_method != "HEAD":
            current_method = "GET"
    raise ValueError("Too many redirects.")


# ---------------------------------------------------------------------------
# Unified safe-fetch wrappers
# ---------------------------------------------------------------------------


async def safe_async_fetch(
    url: str,
    *,
    method: str = "GET",
    headers: dict[str, str] | None = None,
    json: Any = None,
    params: dict[str, str] | None = None,
    content: bytes | None = None,
    timeout: float = _DEFAULT_TIMEOUT,
    max_response_bytes: int = _MAX_RESPONSE_BYTES,
    http2: bool = False,
    user_agent: str | None = _DEFAULT_USER_AGENT,
) -> httpx.Response:
    """SSRF-safe async HTTP request with redirect validation and size limits.

    * Validates the URL (and every redirect hop) against SSRF policy.
    * Connects to the address validation approved, never a re-resolved one.
    * Enforces a response-body size ceiling.
    * Applies a consistent timeout and User-Agent header.

    Raises:
        SSRFBlockedError, target or redirect blocked by policy.
        ResponseTooLargeError, response body exceeds *max_response_bytes*.
        httpx.TimeoutException, request timed out.
        httpx.HTTPStatusError, if caller uses ``response.raise_for_status()``.
    """
    try:
        target = validate_url_target(url)
    except ValueError as exc:
        raise SSRFBlockedError(str(exc)) from exc

    request_headers = dict(headers or {})
    if user_agent and "user-agent" not in {k.lower() for k in request_headers}:
        request_headers["User-Agent"] = user_agent

    current_method = method.upper()

    async with httpx.AsyncClient(
        timeout=timeout,
        http2=http2,
        follow_redirects=False,
    ) as client:
        for hop in range(_MAX_REDIRECTS + 1):
            kwargs: dict[str, Any] = {}
            if hop == 0:
                if json is not None:
                    kwargs["json"] = json
                if content is not None:
                    kwargs["content"] = content
                if params is not None:
                    kwargs["params"] = params

            response = await _request_pinned_async(
                client,
                method=current_method,
                target=target,
                headers=request_headers,
                **kwargs,
            )

            if not response.is_redirect:
                if max_response_bytes > 0 and len(response.content) > max_response_bytes:
                    raise ResponseTooLargeError(
                        f"Response body ({len(response.content):,} bytes) exceeds "
                        f"limit ({max_response_bytes:,} bytes)."
                    )
                return response

            location = response.headers.get("location")
            try:
                target = validate_redirect_target(target.url, location)
            except ValueError as exc:
                raise SSRFBlockedError(f"Redirect to forbidden target: {exc}") from exc

            if response.status_code == 303 and current_method != "HEAD":
                current_method = "GET"

    raise ValueError("Too many redirects.")


def safe_sync_fetch(
    url: str,
    *,
    method: str = "GET",
    headers: dict[str, str] | None = None,
    json: Any = None,
    params: dict[str, str] | None = None,
    content: bytes | None = None,
    timeout: float = _DEFAULT_TIMEOUT,
    max_response_bytes: int = _MAX_RESPONSE_BYTES,
    user_agent: str | None = _DEFAULT_USER_AGENT,
) -> httpx.Response:
    """SSRF-safe synchronous HTTP request.  Same guarantees as *safe_async_fetch*."""
    try:
        target = validate_url_target(url)
    except ValueError as exc:
        raise SSRFBlockedError(str(exc)) from exc

    request_headers = dict(headers or {})
    if user_agent and "user-agent" not in {k.lower() for k in request_headers}:
        request_headers["User-Agent"] = user_agent

    current_method = method.upper()

    with httpx.Client(timeout=timeout, follow_redirects=False) as client:
        for hop in range(_MAX_REDIRECTS + 1):
            kwargs: dict[str, Any] = {}
            if hop == 0:
                if json is not None:
                    kwargs["json"] = json
                if content is not None:
                    kwargs["content"] = content
                if params is not None:
                    kwargs["params"] = params

            response = _request_pinned_sync(
                client,
                method=current_method,
                target=target,
                headers=request_headers,
                **kwargs,
            )

            if not response.is_redirect:
                if max_response_bytes > 0 and len(response.content) > max_response_bytes:
                    raise ResponseTooLargeError(
                        f"Response body ({len(response.content):,} bytes) exceeds "
                        f"limit ({max_response_bytes:,} bytes)."
                    )
                return response

            location = response.headers.get("location")
            try:
                target = validate_redirect_target(target.url, location)
            except ValueError as exc:
                raise SSRFBlockedError(f"Redirect to forbidden target: {exc}") from exc

            if response.status_code == 303 and current_method != "HEAD":
                current_method = "GET"

    raise ValueError("Too many redirects.")
