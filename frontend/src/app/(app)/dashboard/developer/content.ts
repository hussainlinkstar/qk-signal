export const endpointRows = [
  // --- Audit CRUD & Core ---
  ["POST", "/api/v1/external/audit", "Queue a single audit job"],
  ["POST", "/api/v1/external/audit/bulk", "Queue up to 50 audit jobs in one request"],
  ["GET", "/api/v1/external/audit/{job_id}", "Poll job state, scores, and webhook delivery"],
  ["GET", "/api/v1/external/audit/{job_id}/report", "Fetch the raw persisted JSON report"],
  ["GET", "/api/v1/external/audit/preflight", "Validate URL and estimate cost before submission"],
  ["POST", "/api/v1/external/audit/estimate", "Estimate scan usage for an audit configuration"],
  ["GET", "/api/v1/external/audits", "List recent headless audit jobs"],

  // --- Export / CSV ---
  [
    "GET",
    "/api/v1/external/projects/{project_id}/scores/csv",
    "Download project score history as CSV",
  ],
  ["GET", "/api/v1/external/export", "Bulk export CSV rows across one or more projects"],

  // --- Projects ---
  ["GET", "/api/v1/external/projects", "List all projects for the API key owner"],
  ["GET", "/api/v1/external/projects/{project_id}", "Get project details with audit counts"],
  ["GET", "/api/v1/external/projects/{project_id}/audits", "List audits for a specific project"],

  // --- PDF Reports ---
  ["POST", "/api/v1/external/reports/generate", "Generate a PDF report for an audit"],
  ["GET", "/api/v1/external/reports/{report_id}/status", "Poll PDF report generation status"],
  ["GET", "/api/v1/external/reports/{report_id}/download", "Download a generated PDF report"],

  // --- Scheduled Audits ---
  ["GET", "/api/v1/external/scheduled-audits", "List all scheduled audit configurations"],
  ["GET", "/api/v1/external/scheduled-audits/{id}", "Get a specific scheduled audit"],
  ["POST", "/api/v1/external/scheduled-audits", "Create a new scheduled audit"],
  ["PATCH", "/api/v1/external/scheduled-audits/{id}", "Update a scheduled audit"],
  ["DELETE", "/api/v1/external/scheduled-audits/{id}", "Delete a scheduled audit"],

  // --- Competitors ---
  [
    "GET",
    "/api/v1/external/projects/{project_id}/competitors",
    "List tracked competitors for a project",
  ],
  [
    "GET",
    "/api/v1/external/projects/{project_id}/competitive-analysis",
    "Get latest competitive analysis summary",
  ],
  [
    "GET",
    "/api/v1/external/projects/{project_id}/competitive-analysis/trends",
    "Get competitive analysis trends over time",
  ],

  // --- Entity Authority ---
  [
    "GET",
    "/api/v1/external/projects/{project_id}/entity-authority",
    "Get entity authority scores and graph",
  ],
  [
    "GET",
    "/api/v1/external/projects/{project_id}/entity-authority/gaps",
    "Detect entity authority gaps",
  ],
  [
    "GET",
    "/api/v1/external/projects/{project_id}/entity-authority/trend",
    "Get entity authority trend data",
  ],

  // --- Strategic Insights ---
  [
    "POST",
    "/api/v1/external/projects/{project_id}/insights",
    "Generate AI strategic insights for an audit",
  ],

  // --- Visibility Monitoring ---
  [
    "GET",
    "/api/v1/external/projects/{project_id}/visibility/summary",
    "Get AI visibility summary for a project",
  ],
  [
    "GET",
    "/api/v1/external/projects/{project_id}/visibility/trends",
    "Get visibility trend data over time",
  ],

  // --- SERP Tracking ---
  ["GET", "/api/v1/external/projects/{project_id}/serp-tracking", "Get SERP tracking snapshots"],

  // --- LLM Traffic ---
  [
    "GET",
    "/api/v1/external/projects/{project_id}/llm-traffic",
    "Get LLM traffic analytics snapshots",
  ],

  // --- AI Search Volatility ---
  [
    "GET",
    "/api/v1/external/projects/{project_id}/ai-search-volatility",
    "Get AI search volatility summary and trends",
  ],

  // --- Off-Page Mentions ---
  [
    "GET",
    "/api/v1/external/projects/{project_id}/off-page-mentions/summary",
    "Get off-page mentions aggregation summary",
  ],
  [
    "GET",
    "/api/v1/external/projects/{project_id}/off-page-mentions/feed",
    "Get chronological off-page mentions feed",
  ],

  // --- Remediation Actions ---
  [
    "GET",
    "/api/v1/external/projects/{project_id}/tasks",
    "List remediation actions with status summary",
  ],
  ["GET", "/api/v1/external/projects/{project_id}/tasks/{id}", "Get a remediation action"],

  // --- Bot Logs ---
  [
    "GET",
    "/api/v1/external/projects/{project_id}/bot-logs/summary",
    "Get AI bot crawl log summary",
  ],

  // --- Workflows ---
  ["GET", "/api/v1/external/projects/{project_id}/workflows", "List project workflow automations"],
  ["GET", "/api/v1/external/projects/{project_id}/workflows/{id}", "Get a specific workflow"],
  [
    "PATCH",
    "/api/v1/external/projects/{project_id}/workflows/{id}/toggle",
    "Toggle a workflow active/inactive",
  ],

  // --- Alert Rules ---
  ["GET", "/api/v1/external/projects/{project_id}/alerts", "List project alert rules"],
  ["POST", "/api/v1/external/projects/{project_id}/alerts", "Create a new alert rule"],
  ["PUT", "/api/v1/external/projects/{project_id}/alerts/{id}", "Update an existing alert rule"],
  ["DELETE", "/api/v1/external/projects/{project_id}/alerts/{id}", "Delete an alert rule"],

  // --- OpenAPI & SDK ---
  ["GET", "/api/v1/external/openapi.json", "Download filtered OpenAPI spec for external API"],
  ["GET", "/api/v1/external/sdk-metadata", "Get SDK metadata, scopes, and rate limits"],
] as const;

const API_BASE_URL = `${(process.env.NEXT_PUBLIC_APP_URL || "https://qiko.ai/signal").replace(
  /\/+$/,
  ""
)}/api/v1`;

export const codeSamples = {
  curl: `curl -X POST ${API_BASE_URL}/external/audit \\
  -H "Authorization: Bearer stx_live_your_key" \\
  -H "Content-Type: application/json" \\
  -H "X-Request-ID: audit-demo-001" \\
  -d '{
    "url": "https://example.com",
    "tier": "fast",
    "idempotency_key": "demo-001",
    "webhook_url": "https://agency.example/hooks/audit"
  }'`,
  python: `import requests

response = requests.post(
    "${API_BASE_URL}/external/audit",
    headers={
        "Authorization": "Bearer stx_live_your_key",
        "Content-Type": "application/json",
        "X-Request-ID": "audit-demo-001",
    },
    json={
        "url": "https://example.com",
        "tier": "fast",
        "idempotency_key": "demo-001",
    },
    timeout=30,
)
print(response.json())`,
  node: `const response = await fetch("${API_BASE_URL}/external/audit", {
  method: "POST",
  headers: {
    Authorization: "Bearer stx_live_your_key",
    "Content-Type": "application/json",
    "X-Request-ID": "audit-demo-001",
  },
  body: JSON.stringify({
    url: "https://example.com",
    tier: "fast",
    idempotency_key: "demo-001",
  }),
});

console.log(await response.json());`,
} as const;

export type SampleKey = keyof typeof codeSamples;

// SIGV2-1210/1231: the hosted MCP server. Same API key, same base as the
// external API, one extra path segment. Stateless Streamable HTTP: POST-only,
// JSON responses, no session id, no SSE stream.
const APP_BASE_URL = (process.env.NEXT_PUBLIC_APP_URL || "https://qiko.ai/signal").replace(
  /\/+$/,
  ""
);

export const mcpEndpointUrl = `${APP_BASE_URL}/api/v1/mcp`;

export const mcpEndpointRows = [
  ["Production", mcpEndpointUrl],
  ["Preprod", "https://signal.preprod.qiko.ai/api/v1/mcp"],
  ["Local backend", "http://localhost:8200/api/v1/mcp"],
] as const;

export const mcpAuthSnippet = `Authorization: Bearer <QIKO_SIGNAL_API_KEY>
# or
X-API-Key: <QIKO_SIGNAL_API_KEY>`;

export const mcpClaudeDesktopConfig = `{
  "mcpServers": {
    "qiko-signal": {
      "command": "python3",
      "args": ["/path/to/mcp_stdio_bridge.py"],
      "env": {
        "QIKO_SIGNAL_MCP_URL": "${mcpEndpointUrl}",
        "QIKO_SIGNAL_API_KEY": "your-signal-api-key"
      }
    }
  }
}`;

export const mcpSamples = {
  httpConfig: `{
  "mcpServers": {
    "qiko-signal": {
      "url": "${mcpEndpointUrl}",
      "headers": {
        "Authorization": "Bearer stx_live_your_key"
      }
    }
  }
}`,
  initialize: `curl -X POST ${mcpEndpointUrl} \\
  -H "Authorization: Bearer <QIKO_SIGNAL_API_KEY>" \\
  -H "Content-Type: application/json" \\
  -H "Accept: application/json" \\
  -d '{
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
      "protocolVersion": "2025-11-25",
      "capabilities": {},
      "clientInfo": {"name": "my-client", "version": "1.0.0"}
    }
  }'`,
} as const;

// Mirrors TOOL_REGISTRY in backend/services/mcp_server_service.py: 11 read
// tools plus the one tool that spends a scan.
export const mcpToolRows = [
  ["signal_list_projects", "projects:read", "List reachable projects"],
  ["signal_get_project", "projects:read", "One project plus its latest audit"],
  ["signal_list_recommendations", "projects:read", "Ranked open or resolved recommendations"],
  ["signal_get_audit", "audit:read", "One audit's SEO, GEO and AEO scores"],
  ["signal_list_audits", "audit:read", "Audit history for a project"],
  ["signal_get_audit_breakdown", "audit:read", "Per-engine detail behind a score"],
  ["signal_get_scan_status", "audit:read", "Poll a launched audit job"],
  ["signal_get_scan_allowance", "audit:read", "Scans used and remaining in the window"],
  ["signal_list_competitors", "competitors:read", "Tracked competitors with latest scores"],
  ["signal_list_schedules", "schedules:read", "Recurring audit schedules"],
  ["signal_list_alerts", "alerts:read", "Alert rules for a project"],
  ["signal_run_audit", "audit:write", "Start a new audit (consumes one scan)"],
] as const;
