"""Streamable HTTP transport for the Qiko Signal MCP server (SIGV2-1210).

One endpoint, ``POST /api/v1/mcp``, speaking JSON-RPC 2.0 over HTTP with JSON
responses. Three deliberate shapes:

* **Stateless.** No session is created, so there is no ``Mcp-Session-Id`` to
  hand out and nothing to resume. The backend runs as several containers
  behind a proxy; an in-process session store would work on one replica and
  fail on the next, which is worse than not offering sessions at all.
* **No SSE stream.** This server never initiates a message, so ``GET`` is
  refused rather than left open holding a connection that would carry nothing.
  ``DELETE`` is refused for the same reason: there is no session to end.
* **Authorization before dispatch.** The API key is authenticated and the plan
  gate runs as a dependency, so ``initialize``, ``tools/list`` and
  ``tools/call`` are all refused for an ineligible plan. Hiding tools from a
  listing is not a gate, so the gate is not in the listing.

Authentication is the existing Qiko Signal API key, as a bearer token or an
``X-API-Key`` header. This is not OAuth: there is no authorization server in
this estate, so the 401 carries a plain ``WWW-Authenticate: Bearer`` challenge
rather than protected-resource metadata pointing at something that does not
exist. OAuth 2.1 support is a separate decision, recorded on the ticket.
"""

from __future__ import annotations

import json
import logging
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from database import get_db
from services.external_api_service import (
    ExternalAPIPrincipal,
    enforce_external_rate_limit,
    external_error,
    get_api_key_principal,
)
from core.redis_client import get_async_redis
from services.mcp_server_service import (
    JSONRPC_INTERNAL_ERROR,
    JSONRPC_INVALID_PARAMS,
    JSONRPC_INVALID_REQUEST,
    JSONRPC_METHOD_NOT_FOUND,
    JSONRPC_PARSE_ERROR,
    MCP_SERVER_NAME,
    MCP_SERVER_TITLE,
    PROTOCOL_VERSION_HEADER,
    SUPPORTED_PROTOCOL_VERSIONS,
    McpProtocolError,
    ToolContext,
    call_tool,
    instructions,
    negotiate_protocol_version,
    require_mcp_plan,
    server_capabilities,
    tool_descriptors,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["MCP"])

# The challenge an unauthenticated client is answered with. Names the scheme
# and nothing else: there is no OAuth resource metadata to advertise.
_WWW_AUTHENTICATE = 'Bearer realm="qiko-signal-mcp"'

_MAX_BODY_BYTES = 256 * 1024
_MAX_BATCH_SIZE = 20


async def get_mcp_principal(
    request: Request,
    db: Session = Depends(get_db),
) -> ExternalAPIPrincipal:
    """Authenticate the key, then apply the plan gate, before any dispatch."""
    try:
        principal = await get_api_key_principal(request, db)
    except HTTPException as exc:
        if exc.status_code == 401:
            headers = dict(exc.headers or {})
            headers.setdefault("WWW-Authenticate", _WWW_AUTHENTICATE)
            raise HTTPException(
                status_code=exc.status_code, detail=exc.detail, headers=headers
            ) from exc
        raise
    require_mcp_plan(principal)
    return principal


def _require_supported_protocol_header(request: Request) -> None:
    """Refuse a protocol revision this server cannot speak.

    The header is optional on the initialization request and expected on the
    ones after it. An unsupported value is refused rather than ignored, so a
    client is never silently answered in a dialect it did not ask for.
    """
    declared = (request.headers.get(PROTOCOL_VERSION_HEADER) or "").strip()
    if declared and declared not in SUPPORTED_PROTOCOL_VERSIONS:
        raise external_error(
            code="UNSUPPORTED_PROTOCOL_VERSION",
            message=(
                f"Unsupported MCP protocol version: {declared}. Supported versions: "
                + ", ".join(SUPPORTED_PROTOCOL_VERSIONS)
                + "."
            ),
            status_code=400,
        )


def _require_json_accept(request: Request) -> None:
    """Require that the client will accept a JSON response.

    Streamable HTTP lets a server answer a request with either JSON or an
    event stream. This server only answers with JSON, so a client that accepts
    only ``text/event-stream`` is told so instead of being sent a body it
    declared it cannot read.
    """
    accept = (request.headers.get("accept") or "").lower()
    if not accept or "*/*" in accept or "application/json" in accept:
        return
    raise external_error(
        code="NOT_ACCEPTABLE",
        message="This MCP endpoint answers with application/json.",
        status_code=406,
    )


def _carry_headers(target: Response, source: Response) -> Response:
    """Copy the rate-limit headers onto the response actually returned.

    FastAPI only merges the injected ``Response``'s headers when the endpoint
    returns a model, not when it returns a ``Response``. Copying keeps
    ``X-RateLimit-*`` on every MCP answer, which is what a client reads to
    pace itself.
    """
    for name, value in source.headers.items():
        target.headers[name] = value
    return target


def _error_object(code: int, message: str, data: dict[str, Any] | None = None) -> dict[str, Any]:
    error: dict[str, Any] = {"code": code, "message": message}
    if data:
        error["data"] = data
    return error


def _failure(
    request_id: Any, code: int, message: str, data: dict[str, Any] | None = None
) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "error": _error_object(code, message, data)}


def _success(request_id: Any, result: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _handle_initialize(params: dict[str, Any]) -> dict[str, Any]:
    requested = params.get("protocolVersion")
    return {
        "protocolVersion": negotiate_protocol_version(
            requested if isinstance(requested, str) else None
        ),
        "capabilities": server_capabilities(),
        "serverInfo": {
            "name": MCP_SERVER_NAME,
            "title": MCP_SERVER_TITLE,
            "version": "1.0.0",
        },
        "instructions": instructions(),
    }


async def _handle_message(
    *,
    message: Any,
    ctx: ToolContext,
) -> dict[str, Any] | None:
    """Answer one JSON-RPC message, or ``None`` for a notification."""
    if not isinstance(message, dict):
        return _failure(None, JSONRPC_INVALID_REQUEST, "A JSON-RPC message must be an object.")

    request_id = message.get("id")
    is_notification = "id" not in message
    method = message.get("method")
    params = message.get("params")
    if params is None:
        params = {}
    if not isinstance(params, dict):
        return (
            None
            if is_notification
            else _failure(request_id, JSONRPC_INVALID_PARAMS, "params must be an object.")
        )

    if message.get("jsonrpc") != "2.0":
        return (
            None
            if is_notification
            else _failure(request_id, JSONRPC_INVALID_REQUEST, "jsonrpc must be '2.0'.")
        )

    if not isinstance(method, str) or not method:
        return (
            None
            if is_notification
            else _failure(request_id, JSONRPC_INVALID_REQUEST, "method is required.")
        )

    # Notifications are acknowledged by the transport with 202 and no body.
    if is_notification:
        return None

    try:
        if method == "initialize":
            return _success(request_id, _handle_initialize(params))
        if method == "ping":
            return _success(request_id, {})
        if method == "tools/list":
            # No cursor: the catalogue is a dozen tools and fits in one page.
            return _success(request_id, {"tools": tool_descriptors()})
        if method == "tools/call":
            return _success(
                request_id,
                await call_tool(
                    ctx=ctx,
                    name=params.get("name"),
                    arguments=params.get("arguments"),
                ),
            )
    except McpProtocolError as exc:
        # ``data`` carries the structured half of a refusal, including whether
        # it is worth retrying. Dropping it would leave an autonomous client
        # with only prose to decide on.
        return _failure(request_id, exc.code, exc.message, exc.data)
    except HTTPException:
        # Rate limiting and anything else answered at the HTTP layer stays at
        # the HTTP layer, where the client can read the status and Retry-After.
        raise
    except Exception:
        logger.exception(
            "mcp.dispatch_failed method=%s api_key_id=%s", method, ctx.principal.api_key.id
        )
        return _failure(request_id, JSONRPC_INTERNAL_ERROR, "Internal server error.")

    return _failure(request_id, JSONRPC_METHOD_NOT_FOUND, f"Unknown method: {method}.")


@router.post("/mcp")
async def mcp_streamable_http(
    request: Request,
    response: Response,
    principal: Annotated[ExternalAPIPrincipal, Depends(get_mcp_principal)],
    db: Session = Depends(get_db),
):
    """Serve one Streamable HTTP POST: a single message or a small batch."""
    _require_supported_protocol_header(request)
    _require_json_accept(request)
    await enforce_external_rate_limit(response=response, principal=principal)

    raw_body = await request.body()
    if len(raw_body) > _MAX_BODY_BYTES:
        raise external_error(
            code="PAYLOAD_TOO_LARGE",
            message="The MCP request body is too large.",
            status_code=413,
        )

    try:
        payload = json.loads(raw_body or b"")
    except (json.JSONDecodeError, UnicodeDecodeError):
        return _carry_headers(
            JSONResponse(
                status_code=400,
                content=_failure(None, JSONRPC_PARSE_ERROR, "Malformed JSON."),
            ),
            response,
        )

    messages = payload if isinstance(payload, list) else [payload]
    if not messages:
        return _carry_headers(
            JSONResponse(
                status_code=400,
                content=_failure(None, JSONRPC_INVALID_REQUEST, "No JSON-RPC message was sent."),
            ),
            response,
        )
    if len(messages) > _MAX_BATCH_SIZE:
        raise external_error(
            code="VALIDATION_ERROR",
            message=f"A batch may contain at most {_MAX_BATCH_SIZE} messages.",
            status_code=400,
        )

    # Sequential rather than gathered: the batch shares one database session
    # and one of these messages may start an audit, so they are answered in
    # the order the client sent them.
    replies: list[dict[str, Any]] = []
    ctx = ToolContext(
        db=db,
        principal=principal,
        # Resolved from this module's namespace on every request, so this
        # surface decides which Redis client its own calls talk to.
        redis_ctx=get_async_redis,
        correlation_id=getattr(request.state, "request_id", None),
    )
    for message in messages:
        reply = await _handle_message(message=message, ctx=ctx)
        if reply is not None:
            replies.append(reply)

    # Every message was a notification: acknowledged, with no body to return.
    if not replies:
        return _carry_headers(Response(status_code=202), response)

    body: Any = replies if isinstance(payload, list) else replies[0]
    return _carry_headers(JSONResponse(status_code=200, content=body), response)


@router.api_route("/mcp", methods=["GET", "DELETE"], include_in_schema=False)
async def mcp_unsupported_methods() -> Response:
    """Refuse the stream and the session-teardown half of the transport.

    Answered before authentication on purpose: the refusal is a property of
    this server, identical for every caller, so there is nothing to learn from
    it and no reason to make a client authenticate to be told no.
    """
    raise HTTPException(
        status_code=405,
        detail={
            "code": "METHOD_NOT_ALLOWED",
            "message": (
                "This MCP endpoint is stateless and POST-only: it opens no event "
                "stream and holds no session."
            ),
            "status": 405,
        },
        headers={"Allow": "POST"},
    )
