import type { BenchmarkPercentileResponse, ProprietaryScoreResponse } from "@/types/benchmark";

type AuthHeaders = HeadersInit;

export class BenchmarkApiError extends Error {
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "BenchmarkApiError";
    this.status = status;
  }
}

async function requestBenchmark<T>(endpoint: string, headers: AuthHeaders): Promise<T> {
  const response = await fetch(endpoint, { method: "GET", headers });
  if (!response.ok) {
    const payload = (await response.json().catch(() => null)) as { detail?: string } | null;
    throw new BenchmarkApiError(
      response.status,
      payload?.detail ?? "Failed to load benchmark intelligence."
    );
  }
  return (await response.json()) as T;
}

export async function fetchProjectBenchmark(
  projectId: number | string,
  headers: AuthHeaders,
  metric = "geo_score"
): Promise<BenchmarkPercentileResponse> {
  return requestBenchmark<BenchmarkPercentileResponse>(
    `/api/v1/projects/${projectId}/benchmark?metric=${encodeURIComponent(metric)}`,
    headers
  );
}

export async function fetchCitationStability(
  projectId: number | string,
  headers: AuthHeaders
): Promise<ProprietaryScoreResponse> {
  return requestBenchmark<ProprietaryScoreResponse>(
    `/api/v1/projects/${projectId}/citation-stability`,
    headers
  );
}

export async function fetchRemediationImpact(
  projectId: number | string,
  headers: AuthHeaders
): Promise<ProprietaryScoreResponse> {
  return requestBenchmark<ProprietaryScoreResponse>(
    `/api/v1/projects/${projectId}/remediation-impact`,
    headers
  );
}
