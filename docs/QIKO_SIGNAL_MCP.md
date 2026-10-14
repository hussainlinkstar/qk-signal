# Qiko Signal MCP

Connect an MCP client to Qiko Signal to read projects, audit results, recommendations, competitors, schedules and alerts, or request a new audit.

The server exposes **12 tools: 11 read tools and one tool that starts an audit**. Starting an audit consumes a scan from the account's plan allowance. Read tools do not consume scans.

This guide documents the implementation on `main`, verified on **8 October 2026** at commit [`1370b22c25d7078e5b0d7c945983b2f4f073917c`](https://github.com/Qiko-AILabs/qiko-signal/commit/1370b22c25d7078e5b0d7c945983b2f4f073917c). It does not establish that this revision is deployed in every environment. Check the target environment before connecting; `tools/list` provides its actual tool catalogue.

## Access and authentication

MCP access requires an active **Specialist** or **Executive** entitlement and a valid Qiko Signal API key. The server checks the plan before handling any method, including initialization and tool discovery.

Create a key through **Developer Hub → Manage API Keys**, which opens Workspace Settings. Copy the secret when it is created: it is returned once. Use a dedicated key for each integration and revoke it in Workspace Settings when access is no longer needed.

Authenticate every HTTP request with either:

```http
Authorization: Bearer <QIKO_SIGNAL_API_KEY>
```

or:

```http
X-API-Key: <QIKO_SIGNAL_API_KEY>
```

This implementation uses API keys, not OAuth. A client must support custom authentication headers or use the stdio bridge below. Never commit a real key to GitHub, include it in a URL, or place it in a frontend bundle.

### Scopes

| Scope | Enables |
| --- | --- |
| `projects:read` | Project discovery, project details and recommendations |
| `audit:read` | Audit results, history, breakdowns, scan status and scan allowance |
| `competitors:read` | Competitor snapshots; competitor-analysis entitlement is also required |
| `schedules:read` | Recurring audit schedules |
| `alerts:read` | Alert rules |
| `audit:write` | Starting a new audit with `signal_run_audit` |

Keys created without an explicit scope list receive the API's default read-only grant. Omitted scopes and an empty scope list both select that default. **`audit:write` is never included by default.** Supplying a nonempty scope list grants exactly the requested scopes rather than adding them to the defaults.

The current key-creation form submits only a key name, so its keys are read-only. To enable audit launches, create a key through the authenticated application endpoint `POST /api/v1/settings/api-keys` with an explicit scope list. This endpoint uses the application's normal user authentication; an MCP API key is not a substitute for that session.

Example request body for access to all 12 tools:

```json
{
  "name": "Signal MCP integration",
  "scopes": [
    "projects:read",
    "audit:read",
    "competitors:read",
    "schedules:read",
    "alerts:read",
    "audit:write"
  ]
}
```

For a read-only integration, leave out `audit:write`. The key-creation response includes the one-time `api_key` secret and its metadata in `item`.

## Endpoint and transport

Append `/api/v1/mcp` to the Signal application's base URL, retaining any existing path prefix.

| Target | MCP URL |
| --- | --- |
| Production default configured in the bridge | `https://qiko.ai/signal/api/v1/mcp` |
| Preprod | `https://signal.preprod.qiko.ai/api/v1/mcp` |
| Local backend example | `http://localhost:8200/api/v1/mcp` |

These URLs describe configuration, not a deployment health check. Confirm the application's base URL for your environment before sending a key.

| Property | Behavior |
| --- | --- |
| Transport | Streamable HTTP with JSON responses |
| Request | `POST`, JSON-RPC `2.0`, `Content-Type: application/json` |
| Response acceptance | Include `application/json` in `Accept` |
| Supported protocol versions | `2025-11-25`, `2025-06-18`, `2025-03-26` |
| Version header | Send the negotiated `MCP-Protocol-Version` on subsequent requests |
| Sessions | Stateless; no `Mcp-Session-Id` is issued |
| Streaming | No SSE stream; `GET` and `DELETE` return HTTP `405` |
| Notifications | HTTP `202`, with no response body |
| Capabilities | Tools only; no MCP resources, prompts or sampling |
| Request limits | Maximum body size 256 KiB; at most 20 messages in a batch |

Supported methods are `initialize`, `ping`, `tools/list` and `tools/call`. Tools are returned in one catalogue without pagination. The catalogue includes tools even when the key lacks their scope; authorization is enforced when a tool is called.

## HTTP quickstart

The following Bash example reads the key without echoing it. Set the URL to the environment you intend to use.

```bash
export QIKO_SIGNAL_MCP_URL='https://qiko.ai/signal/api/v1/mcp'
read -r -s -p 'Signal API key: ' QIKO_SIGNAL_API_KEY
printf '\n'
export QIKO_SIGNAL_API_KEY

mcp_post() {
  curl --silent --show-error \
    --request POST "$QIKO_SIGNAL_MCP_URL" \
    --header "Authorization: Bearer $QIKO_SIGNAL_API_KEY" \
    --header 'Content-Type: application/json' \
    --header 'Accept: application/json, text/event-stream' \
    --header 'MCP-Protocol-Version: 2025-11-25' \
    --data "$1"
}
```

Initialize the connection:

```bash
mcp_post '{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "initialize",
  "params": {
    "protocolVersion": "2025-11-25",
    "capabilities": {},
    "clientInfo": {"name": "signal-example", "version": "1.0.0"}
  }
}'
```

Read the negotiated version from `result.protocolVersion`. The example requests a supported version; if you request another revision, use the version the server returns for subsequent headers.

Send the initialized notification, then discover tools and projects:

```bash
mcp_post '{"jsonrpc":"2.0","method":"notifications/initialized"}'

mcp_post '{"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}'

mcp_post '{
  "jsonrpc": "2.0",
  "id": 3,
  "method": "tools/call",
  "params": {
    "name": "signal_list_projects",
    "arguments": {"limit": 20}
  }
}'
```

Use a returned `project_id` in later calls. The IDs below are illustrative; replace them with IDs accessible to your key.

## Tool reference

All arguments are JSON objects. Unknown fields are rejected. Project and audit IDs must be positive integers. Optional arguments may be omitted; tools without arguments take `{}`.

| Tool | Required scope | Arguments | Result |
| --- | --- | --- | --- |
| `signal_list_projects` | `projects:read` | `limit`: optional, default `20`, range `1–100` | `projects`, `count`; newest projects first |
| `signal_get_project` | `projects:read` | `project_id`: required | Project details and `latest_audit`, or `null` if none exists |
| `signal_get_audit` | `audit:read` | `project_id`: required; `audit_id`: optional, defaults to latest | One audit with IDs, target, tier, scores and timestamp |
| `signal_list_audits` | `audit:read` | `project_id`: required; `limit`: optional, default `10`, range `1–50` | `project_id`, `audits`, `count`; newest first |
| `signal_get_audit_breakdown` | `audit:read` | `project_id`: required; `audit_id`: optional, defaults to latest | `audit_id`, `project_id`, `scores`, `engines`, `completed_at` |
| `signal_list_recommendations` | `projects:read` | `project_id`: required; `status`: optional, `TODO`, `IN_PROGRESS` or `DONE`; `limit`: optional, default `20`, range `1–100` | `project_id`, `recommendations`, `count`; Signal's stored ranking |
| `signal_list_competitors` | `competitors:read` | `project_id`: required | `project_id`, `competitors`, `count`; latest completed snapshots |
| `signal_list_schedules` | `schedules:read` | `project_id`: optional, defaults to all reachable projects; `limit`: optional, default `20`, range `1–100` | `schedules`, `count`; ordered by next run |
| `signal_list_alerts` | `alerts:read` | `project_id`: required | `project_id`, `alerts`, `count`; newest rules first |
| `signal_get_scan_allowance` | `audit:read` | None: `{}` | `scans_limit`, `scans_used`, `scans_remaining`, `window_days`, `resets_at`, `unlimited` |
| `signal_run_audit` | `audit:write` | `project_id`: required; `tier`: optional, `fast`, `smart` or `deep_judgment`, default `fast` | Audit job information and remaining scan allowance |
| `signal_get_scan_status` | `audit:read` | `job_id`: required string, length `1–191` | Job status, project, tier, scores, error and timestamps |

### Reading results

Project objects contain `project_id`, `name`, `domain_url`, `target_country`, `language` and `created_at`. `signal_get_project` adds `latest_audit` with `audit_id`, `scores` and `completed_at`.

Audit score objects use the wire keys `seo`, `aeo`, `geo` and `overall`. These are the API's existing fields. For product presentation, Signal has two headline pillars: **SEO** and **AIO**; use **Search visibility** and **AI visibility** on score labels. AEO and GEO fields do not create additional headline pillars, and `overall` must not be relabelled as an AIO score.

`signal_get_audit_breakdown` returns stored report sections under `engines.seo`, `engines.aeo` and `engines.geo` when available. Each contains a score and up to five finding headlines. These are audit sections, not ChatGPT/Gemini provider measurements. Missing sections are omitted; this tool does not return the full raw report.

Recommendations contain `recommendation_id`, `project_id`, `title`, `category`, `priority`, `status` and `created_at`. Full descriptions and assignee identities are not returned.

Competitor entries contain `competitor_id`, `display_name`, `domain`, `scores` and `measured_at`. A competitor without a completed snapshot has `null` scores and timestamp. Treat this as unavailable data, not a zero score or a fresh measurement.

Schedules contain their ID, project, frequency, tier, active state, next/last run times and last run status. Alerts contain their ID, metric, comparator, threshold, active state and last-triggered timestamp.

Project audit tools exclude competitor benchmark audits. Scan-status lookup is limited to externally submitted jobs owned by the key's user; it is not a lookup for every dashboard scan. Project reads resolve workspace access server-side.

### Example read calls

Fetch the latest audit:

```json
{
  "jsonrpc": "2.0",
  "id": 4,
  "method": "tools/call",
  "params": {
    "name": "signal_get_audit",
    "arguments": {"project_id": 123}
  }
}
```

Read open recommendations:

```json
{
  "jsonrpc": "2.0",
  "id": 5,
  "method": "tools/call",
  "params": {
    "name": "signal_list_recommendations",
    "arguments": {"project_id": 123, "status": "TODO", "limit": 20}
  }
}
```

A successful call returns its payload in `result.structuredContent` and the same payload as JSON text in `result.content[0].text`. For example, an accessible account with no projects can return:

```json
{
  "jsonrpc": "2.0",
  "id": 3,
  "result": {
    "content": [{"type": "text", "text": "{\"count\": 0, \"projects\": []}"}],
    "structuredContent": {"projects": [], "count": 0},
    "isError": false
  }
}
```

### Starting an audit

Only call `signal_run_audit` when the user requests a fresh audit. Check `signal_get_scan_allowance` first. The launch tool audits the project's registered domain; it accepts neither an arbitrary URL nor a client-supplied idempotency key.

```json
{
  "jsonrpc": "2.0",
  "id": 6,
  "method": "tools/call",
  "params": {
    "name": "signal_run_audit",
    "arguments": {"project_id": 123, "tier": "fast"}
  }
}
```

The result contains `job_id`, `project_id`, `status`, `tier`, `target_url`, `already_running`, `estimated_completion_seconds`, `poll_with` and `scan_allowance`. It acknowledges a background job; it is not a completed audit result. Tier availability and scan limits are still enforced by the plan.

Follow the returned job instead of launching again:

```json
{
  "jsonrpc": "2.0",
  "id": 7,
  "method": "tools/call",
  "params": {
    "name": "signal_get_scan_status",
    "arguments": {"job_id": "replace-with-returned-job-id"}
  }
}
```

Job states include `queued`, `running`, `completed` and `failed`. Inspect `scores` after completion and `error` on failure. A missing score is not zero.

The server derives a launch idempotency key from the key owner's identity, project, tier and a **10-minute time bucket**. Repeating the same launch within that bucket replays the original job without another scan debit. This is not a rolling 10-minute guarantee across bucket boundaries. The shared launch path also prevents duplicate in-flight audits; a conflicting launch can be refused rather than returning a new job.

## Stdio clients

The repository includes [`scripts/mcp_stdio_bridge.py`](https://github.com/Qiko-AILabs/qiko-signal/blob/1370b22c25d7078e5b0d7c945983b2f4f073917c/scripts/mcp_stdio_bridge.py), a Python 3 bridge using only the standard library. It reads newline-delimited JSON-RPC from stdin and forwards requests to the hosted endpoint. It keeps plan checks, scopes and tool behavior on the server.

For a client that accepts an `mcpServers` configuration, adapt this example to your local checkout and secret storage. The key below is a placeholder; keep real credentials in the client's private configuration.

```json
{
  "mcpServers": {
    "qiko-signal": {
      "command": "python3",
      "args": ["/path/to/qiko-signal/scripts/mcp_stdio_bridge.py"],
      "env": {
        "QIKO_SIGNAL_MCP_URL": "https://qiko.ai/signal/api/v1/mcp",
        "QIKO_SIGNAL_API_KEY": "replace-with-your-private-api-key"
      }
    }
  }
}
```

| Variable | Behavior |
| --- | --- |
| `QIKO_SIGNAL_API_KEY` | Required |
| `QIKO_SIGNAL_MCP_URL` | Optional; defaults to `https://qiko.ai/signal/api/v1/mcp` |

The bridge uses `X-API-Key`, remembers the negotiated protocol version and has a 120-second HTTP timeout. It does not automatically retry or cache responses. Remote URLs must use HTTPS; plain HTTP is allowed for localhost development.

## Limits and troubleshooting

MCP shares the external API's per-key rate limiter:

| Plan | Requests per minute | Requests per day |
| --- | --- | --- |
| Specialist | 60 | 1,000 |
| Executive | 300 | 10,000 |

Read the returned `X-RateLimit-Limit`, `X-RateLimit-Remaining`, `X-RateLimit-Reset` and corresponding `X-RateLimit-Day-*` headers. A rate-limit refusal includes `Retry-After`. These request limits are separate from scan allowance; polling also uses requests.

| Response | Meaning and next step |
| --- | --- |
| HTTP `401` | Missing, invalid or revoked API key. Check the key and environment. |
| HTTP `403`, `PLAN_NOT_ELIGIBLE` | The account lacks MCP entitlement. Check its active plan. |
| HTTP `400`, `UNSUPPORTED_PROTOCOL_VERSION` | Use a supported `MCP-Protocol-Version`. |
| HTTP `405` | Use `POST`; this server has no GET stream or DELETE session operation. |
| HTTP `406` | Include `application/json` in `Accept`. |
| HTTP `413` | Reduce the request body below 256 KiB. |
| HTTP `429` | Wait for `Retry-After`; reduce request or polling frequency. |
| HTTP `503`, `RATE_LIMIT_CONFIGURATION_MISSING` | External API access is temporarily unavailable for the resolved plan. |
| JSON-RPC `-32700` | Malformed JSON. |
| JSON-RPC `-32600` | Invalid JSON-RPC request. |
| JSON-RPC `-32601` | Unknown method or tool. Refresh `tools/list`. |
| JSON-RPC `-32602` | Invalid arguments, including extra fields or out-of-range limits. |
| JSON-RPC `-32003` | Missing scope, denied access, entitlement refusal or rejected audit launch. Inspect `error.message` and optional `error.data`. |
| JSON-RPC `-32004` | Project, audit or job not found or not accessible. |
| JSON-RPC `-32603` | Internal server or stdio bridge error. Inspect the transport and server status. |

Authorization and validation failures are top-level JSON-RPC `error` objects, not successful tool content. Check the response envelope even when HTTP status is `200`.

Audit refusals may include `error.data.retryable: false`, with reasons such as `scan_allowance_exhausted`, `audit_already_running` or `not_entitled`. Stop automatic launch retries. For exhausted allowance, inspect the usage and reset information; for an existing job, poll its known ID.

## Implementation sources

The catalogue, schemas and limits above were checked against these files at the documented revision:

- [Tool registry, argument schemas, handlers and plan gate](https://github.com/Qiko-AILabs/qiko-signal/blob/1370b22c25d7078e5b0d7c945983b2f4f073917c/backend/services/mcp_server_service.py)
- [HTTP transport and protocol dispatch](https://github.com/Qiko-AILabs/qiko-signal/blob/1370b22c25d7078e5b0d7c945983b2f4f073917c/backend/routers/mcp_router.py)
- [API-key scopes, authentication and rate limits](https://github.com/Qiko-AILabs/qiko-signal/blob/1370b22c25d7078e5b0d7c945983b2f4f073917c/backend/services/external_api_service.py)
- [API-key creation and revocation](https://github.com/Qiko-AILabs/qiko-signal/blob/1370b22c25d7078e5b0d7c945983b2f4f073917c/backend/routers/api_keys_router.py)
- [Plan capabilities](https://github.com/Qiko-AILabs/qiko-signal/blob/1370b22c25d7078e5b0d7c945983b2f4f073917c/backend/app/config/plans.py)
- [Shared audit launch path](https://github.com/Qiko-AILabs/qiko-signal/blob/1370b22c25d7078e5b0d7c945983b2f4f073917c/backend/services/external_audit_launch_service.py)
- [MCP server tests](https://github.com/Qiko-AILabs/qiko-signal/blob/1370b22c25d7078e5b0d7c945983b2f4f073917c/backend/tests/test_mcp_server.py)
- [Stdio bridge tests](https://github.com/Qiko-AILabs/qiko-signal/blob/1370b22c25d7078e5b0d7c945983b2f4f073917c/backend/tests/test_mcp_stdio_bridge.py)

REST endpoints shown in Developer Hub are a separate interface. Their presence does not imply an equivalent MCP tool; use the 12-tool catalogue above or query `tools/list` on the environment you connect to.
