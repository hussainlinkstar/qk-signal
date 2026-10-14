import { requestJson } from "@/services/http";

export type CanonicalSubscriptionPlan =
  | "plan_starter"
  | "plan_agency_trial"
  | "plan_standard"
  | "plan_specialist"
  | "plan_executive";

export type ApiKeySummary = {
  id: number;
  name: string;
  key_prefix: string;
  key_last_four: string | null;
  scopes: string[];
  is_active: boolean;
  created_at: string | null;
  last_used_at: string | null;
  revoked_at: string | null;
};

export type ApiKeyListResponse = {
  items: ApiKeySummary[];
  plan_type: CanonicalSubscriptionPlan;
  api_access_enabled: boolean;
  mcp_access_enabled: boolean;
  developer_hub_url: string;
};

export type ApiKeyCreatePayload = {
  name: string;
};

export type ApiKeyCreateResponse = {
  api_key: string;
  item: ApiKeySummary;
  developer_hub_url: string;
};

export type ApiKeyDeleteResponse = {
  revoked: boolean;
  item: ApiKeySummary;
};

const API_KEYS_ENDPOINT = "/api/v1/settings/api-keys";

export async function fetchApiKeys(headers: HeadersInit = {}): Promise<ApiKeyListResponse> {
  return requestJson<ApiKeyListResponse>({
    endpoint: API_KEYS_ENDPOINT,
    method: "GET",
    headers,
    errorMessage: "Unable to load API keys.",
  });
}

export async function createApiKey(
  payload: ApiKeyCreatePayload,
  headers: HeadersInit = {}
): Promise<ApiKeyCreateResponse> {
  return requestJson<ApiKeyCreateResponse>({
    endpoint: API_KEYS_ENDPOINT,
    method: "POST",
    headers,
    body: payload,
    errorMessage: "Unable to create API key.",
  });
}

export async function revokeApiKey(
  apiKeyId: number,
  headers: HeadersInit = {}
): Promise<ApiKeyDeleteResponse> {
  return requestJson<ApiKeyDeleteResponse>({
    endpoint: `${API_KEYS_ENDPOINT}/${apiKeyId}`,
    method: "DELETE",
    headers,
    errorMessage: "Unable to revoke API key.",
  });
}
