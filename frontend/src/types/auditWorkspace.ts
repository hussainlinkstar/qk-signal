import { TIER_SHORT } from "@/constants/tiers";

export type AuditFormState = {
  auditTargetType: "website" | "brand";
  url: string;
  targetName: string;
  targetUrl: string;
  targetMetadata: Record<string, unknown>;
  provider: string;
  tier: string;
  language: string;
  market: string;
  category: string;
  entities: string[];
  entityInput: string;
};

export type AuditHistoryItem = {
  id: number;
  url: string;
  auditTargetType?: "website" | "brand";
  targetName?: string | null;
  targetUrl?: string | null;
  targetMetadata?: Record<string, unknown>;
  geoScore: number;
  seoScore: number | null;
  aeoScore: number | null;
  status: string;
  auditType: string;
  createdAt: string;
  projectId?: number;
  fullReport?: Record<string, unknown> | null;
  isArchived?: boolean;
  isPinned?: boolean;
};

export type AuditRecordResponse = {
  id: number;
  url: string;
  audit_target_type?: "website" | "brand";
  target_name?: string | null;
  target_url?: string | null;
  target_metadata?: Record<string, unknown>;
  geo_score: number;
  seo_score?: number;
  aeo_score?: number;
  status?: string;
  audit_type?: string;
  entity_analysis?: Record<string, any>;
  aeo_signals?: Record<string, any>;
  geo_signals?: Record<string, any>;
  technical_signals?: Record<string, any>;
  created_at: string;
  project_id?: number;
  full_report?: Record<string, any> | null;
};

/**
 * Resumable per-stage progress (SIGV2-1021). `status` is the backend stage
 * state machine: pending, running, completed, failed, skipped, degraded,
 * unknown. The endpoint omits the field entirely when it has no stage
 * evidence, so an absent array is "nothing reported", not "nothing happened".
 */
export type AuditJobStageStatusPayload = {
  id: string;
  status: string;
  attempt?: number;
  started_at?: string | null;
  completed_at?: string | null;
  reason?: string | null;
};

export type AuditJobStatusResponse = {
  job_id: string;
  status: string;
  audit_target_type?: "website" | "brand";
  target_name?: string | null;
  target_url?: string | null;
  target_metadata?: Record<string, unknown>;
  audit_id?: number | null;
  error?: string | null;
  created_at?: string | null;
  started_at?: string | null;
  completed_at?: string | null;
  request_id?: string | null;
  requested_tier?: string | null;
  stages?: AuditJobStageStatusPayload[] | null;
};

export type AuditJobLiveDebateEvent = {
  type:
    | "pipeline_started"
    | "layer_started"
    | "layer_completed"
    | "step_started"
    | "step_completed"
    | "debate_finished";
  occurred_at?: string | null;
  role?: string | null;
  semantic_role?: string | null;
  provider?: string | null;
  model?: string | null;
  pipeline_type?: string | null;
  layer_name?: string | null;
  domain?: string | null;
  status?: string | null;
  summary?: string | null;
  layer?: number | null;
  total_agents?: number | null;
  parallel_layers?: number | null;
  estimated_duration_s?: number | null;
  agents_in_layer?: number | null;
  parallel?: boolean | null;
  latency_ms?: number | null;
  total_latency_ms?: number | null;
  agents_completed?: number | null;
  agents_failed?: number | null;
  confidence_score?: number | null;
  profile?: string | null;
  fallback_reason?: string | null;
  judge_authority?: string | null;
  cascade_retry?: boolean | null;
  cascade_attempt?: number | null;
  cascade_excluded?: string[] | null;
};

export type EntityCandidate = {
  name: string;
  type: string;
  confidence: number | null;
};

export type EntityExtractionResponse = {
  entities?: Array<{
    name?: string;
    type?: string;
    confidence?: number;
  }>;
};

export const tabs = [
  { id: "overview", label: "Overview" },
  { id: "seo", label: "SEO" },
  { id: "aeo", label: "AI answers" },
  { id: "geo", label: "AI visibility" },
  { id: "competitors", label: "Competitors" },
  { id: "entities", label: "Entities" },
  { id: "technical", label: "Technical" },
  { id: "hallucinations", label: "Hallucinations" },
  { id: "export", label: "Export" },
] as const;

export type TabId = (typeof tabs)[number]["id"];

export const AUDIT_DRAFT_STORAGE_KEY = "audit-workspace-draft-v1";

export const DEFAULT_FORM_STATE: AuditFormState = {
  auditTargetType: "website",
  url: "",
  targetName: "",
  targetUrl: "",
  targetMetadata: {},
  provider: "google",
  tier: "fast",
  language: "en",
  market: "",
  category: "",
  entities: [],
  entityInput: "",
};

export const TIER_CARD_OPTIONS = [
  {
    value: "fast",
    label: TIER_SHORT.fast,
    helper: "The quickest look, covering the essentials. Lowest cost.",
  },
  {
    value: "smart",
    label: TIER_SHORT.smart,
    helper: "A full check of every area. Takes longer and costs more.",
  },
  {
    value: "deep_judgment",
    label: TIER_SHORT.deep_judgment,
    helper: "The most thorough check, with extra review passes. Slowest and most expensive.",
  },
] as const;
