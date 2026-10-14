import type {
  EntityAuthorityGap,
  EntityAuthoritySummary,
  EntityAuthorityTrendResponse,
  EntityGraphResponse,
} from "@/types/entityAuthority";

type AuthHeaders = HeadersInit;

export class EntityAuthorityApiError extends Error {
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "EntityAuthorityApiError";
    this.status = status;
  }
}

async function requestEntityAuthority<T>(
  endpoint: string,
  method: "GET" | "POST",
  headers: AuthHeaders
): Promise<T> {
  const response = await fetch(endpoint, {
    method,
    headers,
  });
  if (!response.ok) {
    const payload = (await response.json().catch(() => null)) as { detail?: string } | null;
    throw new EntityAuthorityApiError(
      response.status,
      payload?.detail ?? "Failed to load entity authority data."
    );
  }
  return (await response.json()) as T;
}

export async function fetchEntityAuthoritySummary(
  projectId: number | string,
  headers: AuthHeaders
): Promise<EntityAuthoritySummary> {
  return requestEntityAuthority<EntityAuthoritySummary>(
    `/api/v1/projects/${projectId}/entity-authority`,
    "GET",
    headers
  );
}

export async function recomputeEntityAuthoritySummary(
  projectId: number | string,
  headers: AuthHeaders
): Promise<EntityAuthoritySummary> {
  return requestEntityAuthority<EntityAuthoritySummary>(
    `/api/v1/projects/${projectId}/entity-authority/compute`,
    "POST",
    headers
  );
}

export async function fetchEntityAuthorityGaps(
  projectId: number | string,
  headers: AuthHeaders
): Promise<EntityAuthorityGap[]> {
  return requestEntityAuthority<EntityAuthorityGap[]>(
    `/api/v1/projects/${projectId}/entity-authority/gaps`,
    "GET",
    headers
  );
}

export async function fetchEntityAuthorityTrend(
  projectId: number | string,
  headers: AuthHeaders,
  limit = 12
): Promise<EntityAuthorityTrendResponse> {
  return requestEntityAuthority<EntityAuthorityTrendResponse>(
    `/api/v1/projects/${projectId}/entity-authority/trend?limit=${limit}`,
    "GET",
    headers
  );
}

export async function fetchEntityGraph(
  projectId: number | string,
  headers: AuthHeaders
): Promise<EntityGraphResponse> {
  return requestEntityAuthority<EntityGraphResponse>(
    `/api/v1/projects/${projectId}/entity-graph`,
    "GET",
    headers
  );
}
