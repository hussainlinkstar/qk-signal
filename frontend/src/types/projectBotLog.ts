export type BotLogTotals = {
  total_hits: number;
  verified_hits: number;
  spoofed_hits: number;
  error_4xx_hits: number;
  error_5xx_hits: number;
};

export type BotLogTimeSeriesPoint = {
  date: string;
  hits: number;
  verified_hits: number;
  spoofed_hits: number;
};

export type BotLogBreakdownRow = {
  bot_name: string;
  hits: number;
  verified_hits: number;
  spoofed_hits: number;
  error_4xx_hits: number;
  error_5xx_hits: number;
};

export type BotLogSectionHeatmapRow = {
  section: string;
  hits: number;
};

export type BotLogSpoofingRow = {
  bot_name: string;
  spoofed_hits: number;
};

export type BotLogIngestionSource = {
  id: number;
  source_type: string;
  display_name: string | null;
  config: Record<string, unknown>;
  is_active: boolean;
  last_sync_at: string | null;
  last_status: string | null;
  last_error: string | null;
  updated_at: string | null;
};

export type BotLogUploadDetails = {
  id: number;
  source_type: string;
  filename: string;
  status: string;
  bytes_processed: number;
  lines_processed: number;
  bot_hits: number;
  skipped_lines: number;
  uploaded_at: string | null;
  completed_at: string | null;
  error_message: string | null;
  metadata: Record<string, unknown>;
};

export type BotLogSummaryResponse = {
  project_id: number;
  generated_at: string;
  window_days: number;
  latest_snapshot_date: string | null;
  no_data: boolean;
  degraded: boolean;
  degraded_reasons: string[];
  totals: BotLogTotals;
  time_series: BotLogTimeSeriesPoint[];
  bot_breakdown: BotLogBreakdownRow[];
  section_heatmap: BotLogSectionHeatmapRow[];
  spoofing_radar: BotLogSpoofingRow[];
  ingestion_sources: BotLogIngestionSource[];
  latest_upload: BotLogUploadDetails | null;
};

export type BotLogSourceListResponse = {
  project_id: number;
  items: BotLogIngestionSource[];
};

export type UpsertBotLogSourcePayload = {
  source_type: "manual_upload" | "cloudflare_logpush" | "aws_s3" | "gcp_cloud_storage";
  display_name?: string;
  config?: Record<string, unknown>;
  is_active?: boolean;
};

export type BotLogUploadResponse = {
  project_id: number;
  upload_id: number;
  status: string;
  bytes_processed: number;
  lines_processed: number;
  bot_hits: number;
  skipped_lines: number;
  aggregate_rows: number;
  summary_rows: number;
  degraded: boolean;
  degraded_reasons: string[];
};
