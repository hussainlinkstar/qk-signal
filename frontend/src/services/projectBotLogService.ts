import { requestJson } from "@/services/http";
import type {
  BotLogIngestionSource,
  BotLogSourceListResponse,
  BotLogSummaryResponse,
  BotLogUploadResponse,
  UpsertBotLogSourcePayload,
} from "@/types/projectBotLog";

type AuthHeaders = HeadersInit;

export class BotLogApiError extends Error {
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "BotLogApiError";
    this.status = status;
  }
}

async function parseApiError(response: Response, fallback: string): Promise<never> {
  const payload = (await response.json().catch(() => null)) as { detail?: string } | null;
  throw new BotLogApiError(response.status, payload?.detail ?? fallback);
}

export async function fetchProjectBotLogSummary(
  projectId: number | string,
  headers: AuthHeaders,
  days = 30
): Promise<BotLogSummaryResponse> {
  const response = await fetch(
    `/api/v1/projects/${projectId}/monitoring/bot-logs/summary?days=${days}`,
    {
      method: "GET",
      headers,
    }
  );

  if (!response.ok) {
    await parseApiError(response, "Failed to load AI bot log summary.");
  }

  return (await response.json()) as BotLogSummaryResponse;
}

export async function fetchProjectBotLogSources(
  projectId: number | string,
  headers: AuthHeaders
): Promise<BotLogSourceListResponse> {
  const response = await fetch(`/api/v1/projects/${projectId}/monitoring/bot-logs/sources`, {
    method: "GET",
    headers,
  });

  if (!response.ok) {
    await parseApiError(response, "Failed to load bot log ingestion sources.");
  }

  return (await response.json()) as BotLogSourceListResponse;
}

export async function upsertProjectBotLogSource(
  projectId: number | string,
  payload: UpsertBotLogSourcePayload,
  headers: AuthHeaders
): Promise<BotLogIngestionSource> {
  return requestJson<BotLogIngestionSource>({
    endpoint: `/api/v1/projects/${projectId}/monitoring/bot-logs/sources`,
    method: "POST",
    headers,
    body: payload,
    errorMessage: "Failed to save bot log source.",
  });
}

export async function uploadProjectBotLogFile(
  projectId: number | string,
  file: File,
  headers: AuthHeaders,
  options?: {
    sourceType?: "manual_upload" | "cloudflare_logpush" | "aws_s3" | "gcp_cloud_storage";
    sourceId?: number;
  }
): Promise<BotLogUploadResponse> {
  const query = new URLSearchParams();
  if (options?.sourceType) {
    query.set("source_type", options.sourceType);
  }
  if (typeof options?.sourceId === "number") {
    query.set("source_id", String(options.sourceId));
  }

  const formData = new FormData();
  formData.append("file", file);

  const response = await fetch(
    `/api/v1/projects/${projectId}/monitoring/bot-logs/upload${query.toString() ? `?${query.toString()}` : ""}`,
    {
      method: "POST",
      headers,
      body: formData,
    }
  );

  if (!response.ok) {
    await parseApiError(response, "Failed to upload bot log file.");
  }

  return (await response.json()) as BotLogUploadResponse;
}
