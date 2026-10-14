import { requestJson, requestVoid } from "@/services/http";

export type DataConnectionProvider = "google" | "bing" | "jira";

export type DataConnectionSummary = {
  provider: DataConnectionProvider;
  has_refresh_token: boolean;
  token_type: string | null;
  scope: string | null;
  expires_at: string | null;
  updated_at: string | null;
  access_token_preview: string | null;
  site_name?: string | null;
  site_url?: string | null;
  /** A stored connection exists for this workspace. */
  connected: boolean;
  /** The deployment holds OAuth credentials for this provider; when false no
      connect affordance can work, so the UI must not offer one. */
  configured: boolean;
};

export type SlackStatus = {
  is_connected: boolean;
  team_id: string | null;
  team_name: string | null;
  bot_user_id: string | null;
  default_channel_id: string | null;
  default_channel_name: string | null;
  scope: string | null;
  updated_at: string | null;
  is_plan_locked?: boolean;
  detail?: string | null;
};

export type SlackChannel = {
  id: string;
  name: string;
};

export type TeamsStatus = {
  is_connected: boolean;
  channel_name: string | null;
  webhook_preview: string | null;
  updated_at: string | null;
  is_plan_locked?: boolean;
  detail?: string | null;
};

export type ExternalApiHealth = {
  is_degraded: boolean;
  detail: string | null;
};

async function fetchStatusWithPlanLock<T extends Record<string, unknown>>(
  endpoint: string,
  headers: HeadersInit = {}
): Promise<T & { is_plan_locked?: boolean; detail?: string | null }> {
  const response = await fetch(endpoint, { headers });
  if (response.status === 402) {
    const payload = (await response.json().catch(() => null)) as { detail?: string } | null;
    return {
      is_plan_locked: true,
      detail: payload?.detail ?? "Upgrade required.",
    } as T & { is_plan_locked: boolean; detail: string | null };
  }
  if (!response.ok) {
    const payload = (await response.json().catch(() => null)) as { detail?: string } | null;
    throw new Error(payload?.detail ?? "Unable to load integration status.");
  }
  return (await response.json()) as T & { is_plan_locked?: boolean; detail?: string | null };
}

export async function fetchWorkspaceDataConnections(
  headers: HeadersInit = {}
): Promise<DataConnectionSummary[]> {
  return requestJson<DataConnectionSummary[]>({
    endpoint: "/api/workspaces/current/oauth-connections",
    method: "GET",
    headers,
    errorMessage: "Unable to load workspace connections.",
  });
}

export async function saveWorkspaceDataConnection(
  provider: DataConnectionProvider,
  payload: {
    access_token: string;
    refresh_token?: string | null;
    token_type?: string | null;
    scope?: string | null;
  },
  headers: HeadersInit = {}
): Promise<DataConnectionSummary> {
  return requestJson<DataConnectionSummary>({
    endpoint: `/api/workspaces/current/oauth-connections/${provider}`,
    method: "PUT",
    headers,
    body: payload,
    errorMessage: "Unable to save the connection.",
  });
}

export async function disconnectWorkspaceDataConnection(
  provider: DataConnectionProvider,
  headers: HeadersInit = {}
): Promise<void> {
  return requestVoid({
    endpoint: `/api/workspaces/current/oauth-connections/${provider}`,
    method: "DELETE",
    headers,
    errorMessage: "Unable to disconnect the provider.",
  });
}

export async function fetchSlackStatus(headers: HeadersInit = {}): Promise<SlackStatus> {
  return fetchStatusWithPlanLock<SlackStatus>("/api/integrations/slack/status", headers);
}

export async function fetchSlackChannels(headers: HeadersInit = {}): Promise<SlackChannel[]> {
  return requestJson<SlackChannel[]>({
    endpoint: "/api/integrations/slack/channels",
    method: "GET",
    headers,
    errorMessage: "Unable to load Slack channels.",
  });
}

export async function updateSlackDefaultChannel(
  payload: { channel_id: string; channel_name?: string | null },
  headers: HeadersInit = {}
): Promise<SlackStatus> {
  return requestJson<SlackStatus>({
    endpoint: "/api/integrations/slack/default-channel",
    method: "PUT",
    headers,
    body: payload,
    errorMessage: "Unable to update the Slack default channel.",
  });
}

export async function sendSlackTestMessage(
  payload: { channel_id?: string | null } = {},
  headers: HeadersInit = {}
): Promise<void> {
  return requestVoid({
    endpoint: "/api/integrations/slack/test",
    method: "POST",
    headers,
    body: payload,
    errorMessage: "Unable to send the Slack test message.",
  });
}

export async function disconnectSlack(headers: HeadersInit = {}): Promise<void> {
  return requestVoid({
    endpoint: "/api/integrations/slack/disconnect",
    method: "DELETE",
    headers,
    errorMessage: "Unable to disconnect Slack.",
  });
}

export async function fetchTeamsStatus(headers: HeadersInit = {}): Promise<TeamsStatus> {
  return fetchStatusWithPlanLock<TeamsStatus>("/api/integrations/teams/status", headers);
}

export async function connectTeams(
  payload: { webhook_url: string; channel_name?: string | null },
  headers: HeadersInit = {}
): Promise<TeamsStatus> {
  return requestJson<TeamsStatus>({
    endpoint: "/api/integrations/teams/connect",
    method: "POST",
    headers,
    body: payload,
    errorMessage: "Unable to save the Teams webhook.",
  });
}

export async function sendTeamsTestMessage(headers: HeadersInit = {}): Promise<void> {
  return requestVoid({
    endpoint: "/api/integrations/teams/test",
    method: "POST",
    headers,
    errorMessage: "Unable to send the Teams test message.",
  });
}

export async function disconnectTeams(headers: HeadersInit = {}): Promise<void> {
  return requestVoid({
    endpoint: "/api/integrations/teams/disconnect",
    method: "DELETE",
    headers,
    errorMessage: "Unable to disconnect Teams.",
  });
}

export async function fetchExternalApiHealth(
  headers: HeadersInit = {}
): Promise<ExternalApiHealth> {
  const response = await fetch("/api/system-status", { headers });
  if (!response.ok) {
    return {
      is_degraded: true,
      detail: "Unable to verify export API health right now.",
    };
  }

  const payload = (await response.json().catch(() => null)) as {
    services?: Record<
      string,
      {
        status?: string | null;
      }
    >;
  } | null;

  const databaseStatus = payload?.services?.database?.status ?? null;
  const cacheStatus = payload?.services?.cache?.status ?? null;
  const isHealthy = databaseStatus === "Operational" && cacheStatus === "Operational";

  return {
    is_degraded: !isHealthy,
    detail: isHealthy
      ? null
      : "Database or cache health is degraded, so CSV connector exports may fail.",
  };
}
