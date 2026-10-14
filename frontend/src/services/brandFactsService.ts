import { requestJson, requestVoid } from "@/services/http";

export type BrandFactKind = "fact" | "claim";

export type BrandFact = {
  id: number;
  project_id: number;
  kind: BrandFactKind;
  statement: string;
  is_forbidden: boolean;
  created_at: string | null;
};

export type BrandFactCreatePayload = {
  kind: BrandFactKind;
  statement: string;
  is_forbidden: boolean;
};

const brandFactsEndpoint = (projectId: string | number): string =>
  `/api/projects/${projectId}/brand-facts`;

export async function fetchBrandFacts(
  projectId: string | number,
  headers: HeadersInit = {}
): Promise<BrandFact[]> {
  return requestJson<BrandFact[]>({
    endpoint: brandFactsEndpoint(projectId),
    method: "GET",
    headers,
    errorMessage: "Unable to load brand guardrails.",
  });
}

export async function createBrandFact(
  projectId: string | number,
  payload: BrandFactCreatePayload,
  headers: HeadersInit = {}
): Promise<BrandFact> {
  return requestJson<BrandFact>({
    endpoint: brandFactsEndpoint(projectId),
    method: "POST",
    headers,
    body: payload,
    errorMessage: "Unable to add brand guardrail.",
  });
}

export async function deleteBrandFact(
  projectId: string | number,
  factId: number,
  headers: HeadersInit = {}
): Promise<void> {
  return requestVoid({
    endpoint: `${brandFactsEndpoint(projectId)}/${factId}`,
    method: "DELETE",
    headers,
    errorMessage: "Unable to remove brand guardrail.",
  });
}
