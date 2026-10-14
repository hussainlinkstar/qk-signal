import type { AuditResult } from "@/types/auditResult";

export type AuditStatus =
  | "completed"
  | "degraded"
  | "failed"
  | "succeeded"
  | "ready"
  | "archived"
  | "purged";

export type RawAuditHistoryEntry = {
  id: number;
  url?: string | null;
  audit_target_type?: "website" | "brand" | null;
  target_name?: string | null;
  target_url?: string | null;
  target_metadata?: Record<string, unknown> | null;
  created_at?: string | null;
  status?: string | null;
  audit_type?: string | null;
  seo_score?: number | null;
  geo_score?: number | null;
  aeo_score?: number | null;
  project_id?: number | null;
  full_report?: unknown;
  is_archived?: boolean;
  is_pinned?: boolean;
};

export type ScoreKey = "seo" | "speed" | "indexing" | "mobile";

export type ScoreBreakdown = {
  seo: number;
  speed: number;
  indexing: number;
  mobile: number;
};

export type IssueCategoryKey =
  | "technical_seo"
  | "content_quality"
  | "indexability"
  | "mobile_ux"
  | "performance"
  | "schema"
  | "authority"
  | "security"
  | "other";

export type IssueSeverity = "low" | "medium" | "high" | "critical";

export type IssueCategory = {
  key: IssueCategoryKey;
  label: string;
  count: number;
  severity: IssueSeverity;
};

export type ActionImpact = "low" | "medium" | "high";
export type ActionEffort = "low" | "medium" | "high";

export type PriorityAction = {
  id: string;
  title: string;
  description: string;
  category: IssueCategoryKey;
  priority: 1 | 2 | 3 | 4 | 5;
  impact: ActionImpact;
  effort: ActionEffort;
  eta_days: number | null;
  owner?: string | null;
};

export type PriorityRoadmapItem = {
  task: string;
  category: string;
  impact: string;
  effort_score: number;
  reasoning: string;
  confidence?: "high" | "medium" | "low";
  label?: "measured" | "inferred" | "hypothesis";
  source_basis?: string[];
};

export type GroundingSource = {
  label: string;
  source_type: string;
  measured: boolean;
  updated_at?: string | null;
};

export type GroundedStrategicIdea = {
  text: string;
  confidence: "high" | "medium" | "low";
  label: "measured" | "inferred" | "hypothesis";
  source_basis: string[];
  status_note?: string | null;
  last_verified_at?: string | null;
};

export type AiStrategicInsights = {
  executive_summary: string;
  critical_alerts: string[];
  priority_roadmap: PriorityRoadmapItem[];
  content_gap_theory: string[];
  technical_debt_explanation: string;
  generated_at?: string;
  audit_id?: number;
  project_id?: number | null;
  grounding_sources: GroundingSource[];
  aeo_query_ideas: GroundedStrategicIdea[];
  geo_prompt_ideas: GroundedStrategicIdea[];
};

export type AuditDataQuality = {
  degraded: boolean;
  summary: string | null;
  issues: string[];
};

export type LegacyAuditReport = {
  site?: { url?: string | null } | null;
  seo?: {
    onpage?: number | null;
    performance?: number | null;
    indexing?: number | null;
    mobile?: number | null;
  } | null;
  scores?: Record<string, number | null | undefined> | null;
  metadata?: {
    created_at?: string | null;
    audit_outcome?: string | null;
  } | null;
  [key: string]: unknown;
};

export type RawAuditFullReport = AuditResult | LegacyAuditReport;

export type AiStrategistViewModel = {
  auditId: number;
  siteUrl: string;
  createdAt: string;
  projectId?: number | null;
  status: AuditStatus;
  scores: ScoreBreakdown;
  scoreDeltaVsPrevious: Partial<Record<ScoreKey, number>>;
  issueCategories: IssueCategory[];
  priorityActions: PriorityAction[];
  aiInsights: AiStrategicInsights;
  dataQuality?: AuditDataQuality;
};

export const DEFAULT_SCORE_BREAKDOWN: ScoreBreakdown = {
  seo: 0,
  speed: 0,
  indexing: 0,
  mobile: 0,
};

export const DEFAULT_AI_STRATEGIC_INSIGHTS: AiStrategicInsights = {
  executive_summary: "",
  critical_alerts: [],
  priority_roadmap: [],
  content_gap_theory: [],
  technical_debt_explanation: "",
  grounding_sources: [],
  aeo_query_ideas: [],
  geo_prompt_ideas: [],
};

export const DEFAULT_AUDIT_DATA_QUALITY: AuditDataQuality = {
  degraded: false,
  summary: null,
  issues: [],
};

export const DEFAULT_AI_STRATEGIST_VIEW_MODEL: AiStrategistViewModel = {
  auditId: 0,
  siteUrl: "",
  createdAt: "",
  projectId: null,
  status: "ready",
  scores: DEFAULT_SCORE_BREAKDOWN,
  scoreDeltaVsPrevious: {},
  issueCategories: [],
  priorityActions: [],
  aiInsights: DEFAULT_AI_STRATEGIC_INSIGHTS,
  dataQuality: DEFAULT_AUDIT_DATA_QUALITY,
};
