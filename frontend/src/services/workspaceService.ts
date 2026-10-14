import { requestJson, requestVoid, HttpRequestError } from "@/services/http";
import type { RoleMode } from "@/lib/roleMode";

export type WorkspaceRole = "ADMIN" | "MANAGER" | "EDITOR" | "VIEWER" | "CLIENT_READONLY";
export type InternalWorkspaceRole = Exclude<WorkspaceRole, "CLIENT_READONLY">;
export type CompetitiveDigestFrequency = "off" | "weekly" | "monthly";
export type CompetitiveMetric = "geo" | "seo" | "aeo" | "overall";
export type ProjectFeatureAccessState = {
  allowed: boolean;
  detail: string | null;
  status_code: 402 | 403 | null;
  required_plan: string | null;
};
export type ProjectFeatureAccess = {
  monitoring: ProjectFeatureAccessState;
  automations: ProjectFeatureAccessState;
  /** SIGV2-1134: the Advisor action plan and every preview of it. */
  advisor_recommendations: ProjectFeatureAccessState;
  entity_authority: ProjectFeatureAccessState;
  benchmark_intelligence: ProjectFeatureAccessState;
  scheduled_audits: ProjectFeatureAccessState;
  jira_export: ProjectFeatureAccessState;
};

export type ProjectScoreTarget = {
  current: number | null;
  target: number;
  gap: number | null;
  measured_at: string | null;
};

export type ProjectScoreTargets = {
  aio: ProjectScoreTarget;
  seo: ProjectScoreTarget;
};

export type WorkspaceProjectSummary = {
  id: number;
  workspace_id: number;
  name: string;
  domain_url: string | null;
  target_country: string | null;
  language: string;
  icp_roles: string[];
  pain_points: string | null;
  usp: string | null;
  competitors: string[];
  priority_pulse_tags: string[];
  sme_profiles: string[];
  created_at: string | null;
  audit_count: number;
  last_audit_at: string | null;
  latest_seo_score: number | null;
  latest_geo_score: number | null;
  latest_aeo_score: number | null;
  feature_access: ProjectFeatureAccess;
  auto_competitor_audits_enabled?: boolean;
  competitive_digest_frequency?: CompetitiveDigestFrequency;
  score_targets?: ProjectScoreTargets | null;
};

export type WorkspaceSummary = {
  id: number;
  name: string;
  owner_id: number;
  created_at: string | null;
  role: WorkspaceRole | string;
  is_owner: boolean;
  project_count: number;
  member_count: number;
  oauth_connection_count: number;
  role_mode?: RoleMode | null;
};

export type WorkspaceUpdatePayload = {
  name?: string;
  role_mode?: RoleMode;
};

export type WorkspaceCustomDomainSummary = {
  id: number;
  domain: string;
  dns_target: string;
  verified: boolean;
  ssl_status: "pending_verification" | "pending_ssl" | "active" | "error";
  verification_error: string | null;
  verification_checked_at: string | null;
  activated_at: string | null;
  created_at: string | null;
  preview_url: string;
};

export type WorkspaceWhiteLabelSettings = {
  workspace_id: number;
  workspace_name: string;
  company_name: string;
  custom_logo_url: string | null;
  primary_color: string;
  secondary_color: string;
  custom_favicon_url: string | null;
  custom_page_title: string;
  custom_meta_description: string | null;
  hide_powered_by: boolean;
  email_sender_name: string | null;
  email_reply_to: string | null;
  social_facebook_url: string | null;
  social_x_url: string | null;
  social_instagram_url: string | null;
  social_linkedin_url: string | null;
  social_youtube_url: string | null;
  social_tiktok_url: string | null;
  company_address: string | null;
  company_legal_name: string | null;
  company_trademark_text: string | null;
  footer_about_url: string | null;
  footer_blog_url: string | null;
  footer_support_url: string | null;
  footer_legal_url: string | null;
  footer_preferences_url: string | null;
  footer_privacy_url: string | null;
  dns_target: string | null;
  domains: WorkspaceCustomDomainSummary[];
};

export type WorkspaceWhiteLabelUpdatePayload = {
  custom_logo_url?: string | null;
  company_name?: string | null;
  primary_color?: string | null;
  secondary_color?: string | null;
  custom_favicon_url?: string | null;
  custom_page_title?: string | null;
  custom_meta_description?: string | null;
  hide_powered_by?: boolean;
  email_sender_name?: string | null;
  email_reply_to?: string | null;
  social_facebook_url?: string | null;
  social_x_url?: string | null;
  social_instagram_url?: string | null;
  social_linkedin_url?: string | null;
  social_youtube_url?: string | null;
  social_tiktok_url?: string | null;
  company_address?: string | null;
  company_legal_name?: string | null;
  company_trademark_text?: string | null;
  footer_about_url?: string | null;
  footer_blog_url?: string | null;
  footer_support_url?: string | null;
  footer_legal_url?: string | null;
  footer_preferences_url?: string | null;
  footer_privacy_url?: string | null;
};

export type WorkspaceEmailFooterSettings = {
  workspace_id: number;
  workspace_name: string;
  social_facebook_url: string | null;
  social_x_url: string | null;
  social_instagram_url: string | null;
  social_linkedin_url: string | null;
  social_youtube_url: string | null;
  social_tiktok_url: string | null;
  company_address: string | null;
  company_legal_name: string | null;
  company_trademark_text: string | null;
  footer_about_url: string | null;
  footer_blog_url: string | null;
  footer_support_url: string | null;
  footer_legal_url: string | null;
  footer_preferences_url: string | null;
  footer_privacy_url: string | null;
};

export type WorkspaceEmailFooterUpdatePayload = {
  social_facebook_url?: string | null;
  social_x_url?: string | null;
  social_instagram_url?: string | null;
  social_linkedin_url?: string | null;
  social_youtube_url?: string | null;
  social_tiktok_url?: string | null;
  company_address?: string | null;
  company_legal_name?: string | null;
  company_trademark_text?: string | null;
  footer_about_url?: string | null;
  footer_blog_url?: string | null;
  footer_support_url?: string | null;
  footer_legal_url?: string | null;
  footer_preferences_url?: string | null;
  footer_privacy_url?: string | null;
};

export type WorkspaceMemberSummary = {
  user_id: number;
  email: string;
  role: WorkspaceRole;
  is_owner: boolean;
  created_at: string | null;
};

export type ClientInvitationPayload = {
  email: string;
  name?: string | null;
  project_ids: number[];
};

export type ClientInvitationResult = {
  user_id: number;
  email: string;
  role: "CLIENT_READONLY";
  project_ids: number[];
  invited: boolean;
  created_at: string | null;
  email_queued: boolean;
  invitation_url: string | null;
};

export type ProjectDetails = WorkspaceProjectSummary;

export type ProjectCreatePayload = {
  name: string;
  domain_url?: string | null;
  target_country?: string | null;
  language?: string | null;
};

export type ProjectUpdatePayload = {
  name?: string;
  domain_url?: string | null;
  target_country?: string | null;
  language?: string | null;
  icp_roles?: string[];
  pain_points?: string | null;
  usp?: string | null;
  competitors?: string[];
  auto_competitor_audits_enabled?: boolean;
  competitive_digest_frequency?: CompetitiveDigestFrequency;
  priority_pulse_tags?: string[];
  sme_profiles?: string[];
  aio_score_target?: number | null;
  seo_score_target?: number | null;
};

export type ProjectSmartProfileGeneratePayload = {
  overwrite_existing?: boolean;
};

export type ProjectSmartProfileGenerateResponse = {
  project: ProjectDetails;
  model: string | null;
  required_fields: string[];
  missing_required_fields: string[];
  generated_fields: string[];
  skipped_fields: string[];
  grounded_sources: string[];
};

export type MagicLinkPayload = {
  project_id: number;
  token: string;
  link_url: string;
  expires_at: string;
  is_used: boolean;
  created_at: string | null;
};

export type MagicLinkProviderConnection = {
  provider: "google" | "bing";
  connected: boolean;
  connected_at: string | null;
  connected_by_email: string | null;
  has_refresh_token: boolean;
  expires_at: string | null;
  scope: string | null;
};

export type ProjectMagicLinkStatus = {
  project_id: number;
  status: "not_requested" | "pending" | "expired" | "connected";
  latest_link_created_at: string | null;
  latest_link_expires_at: string | null;
  latest_link_is_used: boolean;
  open_magic_link_count: number;
  providers: MagicLinkProviderConnection[];
};

export type ProjectDataSourceType =
  | "google_search_console"
  | "google_analytics_4"
  | "bing_webmaster";

export type ProjectDataSourceBindingMode = "workspace" | "client_magic_link" | "ai_estimate";

export type ProjectDataSourceAssignment = {
  id: number | null;
  project_id: number;
  provider: "google" | "bing";
  source_type: ProjectDataSourceType;
  binding_mode: ProjectDataSourceBindingMode;
  source_id: string | null;
  source_label: string | null;
  is_active: boolean;
  oauth_connection_id: number | null;
  project_oauth_connection_id: number | null;
  workspace_provider_connected: boolean;
  updated_at: string | null;
};

export type ProjectDataSourceCatalogItem = {
  id: string;
  label: string;
  description: string | null;
};

export type ProjectDataSourceCatalogResponse = {
  source_type: ProjectDataSourceType;
  provider: "google" | "bing";
  workspace_provider_connected: boolean;
  // SIGV2-1207: the workspace has no connection but the user holds one on
  // another workspace they can access.
  connected_on_other_workspace?: boolean;
  items: ProjectDataSourceCatalogItem[];
  required_scopes: string[];
  granted_scopes: string[];
  missing_scopes: string[];
  error: string | null;
  fetched_at: string;
};

export type ProjectAuditHistoryEntry = {
  id: number;
  project_id: number;
  site_id?: number | null;
  audit_type: "FAST" | "SMART" | "STANDARD" | "DEEP";
  url: string;
  audit_target_type?: "website" | "brand";
  target_name?: string | null;
  target_url?: string | null;
  target_metadata?: Record<string, unknown>;
  geo_score: number;
  seo_score: number | null;
  aeo_score: number | null;
  status: "completed" | "degraded" | "failed";
  created_at: string;
  full_report: Record<string, unknown> | null;
};

export type ProjectAuditModule = "seo" | "aeo" | "geo";

export type ProjectLatestAuditSelection = {
  module: ProjectAuditModule;
  status: "ready" | "stale" | "no_matching_audit" | "no_audits";
  message: string;
  recommended_audit_type: "STANDARD" | "DEEP";
  recommended_launch_tier: "fast" | "smart" | "deep";
  compatible_audit_types: Array<"FAST" | "SMART" | "STANDARD" | "DEEP">;
  stale_after_days: number;
  selected_audit_age_days: number | null;
  selected_audit: ProjectAuditHistoryEntry | null;
  latest_audit: ProjectAuditHistoryEntry | null;
};

export type ProjectBudgetStatus = "unlimited" | "healthy" | "warning" | "exhausted";

export type ProjectBudgetPeriod = {
  period_start: string;
  period_end: string;
  cycle_anchor_day: number;
  budget_limit_scans: number | null;
  consumed_scans: number;
  remaining_scans: number | null;
  percent_consumed: number | null;
  warning_threshold_reached: boolean;
  limit_reached: boolean;
  status: ProjectBudgetStatus;
};

export type ProjectBudgetSummary = {
  project_id: number;
  workspace_id: number;
  project_name: string;
  domain_url: string | null;
  budget_configured: boolean;
  monthly_limit_scans: number | null;
  cycle_anchor_day: number;
  current_period_start: string;
  current_period_end: string;
  consumed_scans: number;
  remaining_scans: number | null;
  percent_consumed: number | null;
  status: ProjectBudgetStatus;
  warning_threshold_reached: boolean;
  limit_reached: boolean;
  recent_periods: ProjectBudgetPeriod[];
};

export type ProjectBudgetUpsertPayload = {
  monthly_limit_scans: number;
  cycle_anchor_day: number;
};

export type WorkspaceCostBreakdown = {
  workspace_id: number;
  generated_at: string;
  projects: ProjectBudgetSummary[];
};

export type ProjectCompetitorScores = {
  geo: number | null;
  seo: number | null;
  aeo: number | null;
  overall: number | null;
};

export type ProjectCompetitorListItem = {
  id: number;
  project_id: number;
  competitor_site_id: number | null;
  target_url: string;
  normalized_domain: string;
  display_name: string;
  auto_audit_enabled: boolean;
  created_at: string | null;
  latest_status: "not_started" | "pending" | "failed" | "succeeded";
  latest_failure_reason: string | null;
  last_benchmarked_at: string | null;
  latest_source_audit_id: number | null;
  latest_scores: ProjectCompetitorScores;
};

export type ProjectCompetitorCreatePayload = {
  target_url: string;
  display_name?: string | null;
};

export type ProjectCompetitiveAnalysisProject = {
  id: number;
  name: string;
  url: string | null;
  scores: ProjectCompetitorScores;
  last_audit_at: string | null;
};

export type ProjectCompetitiveAnalysisCompetitor = {
  id: number;
  name: string;
  url: string;
  status: "not_started" | "pending" | "failed" | "succeeded";
  last_benchmarked_at: string | null;
  failure_reason: string | null;
  scores: ProjectCompetitorScores;
  delta: Record<CompetitiveMetric, number | null>;
};

export type CompetitiveBenchmarkStatus = {
  auto_competitor_audits_enabled: boolean;
  competitive_digest_frequency: CompetitiveDigestFrequency;
  pending_competitors: number;
  failed_competitors: number;
  configured_competitors: number;
  has_data: boolean;
};

export type ProjectCompetitiveAnalysisResponse = {
  project_id: number;
  project: ProjectCompetitiveAnalysisProject;
  competitors: ProjectCompetitiveAnalysisCompetitor[];
  rank: Record<CompetitiveMetric, number | null>;
  updated_at: string | null;
  benchmark_status: CompetitiveBenchmarkStatus;
};

export type ProjectCompetitiveTrendPoint = {
  date: string | null;
  value: number | null;
};

export type ProjectCompetitiveTrendLine = {
  key: string;
  label: string;
  is_project: boolean;
  points: ProjectCompetitiveTrendPoint[];
};

export type ProjectCompetitiveTrendResponse = {
  project_id: number;
  metric: CompetitiveMetric;
  period: "30d" | "90d" | "1y" | "all";
  lines: ProjectCompetitiveTrendLine[];
};

export type ProjectCompetitiveGapItem = {
  competitor_id: number;
  competitor_name: string;
  metric: Exclude<CompetitiveMetric, "overall">;
  project_score: number;
  competitor_score: number;
  delta: number;
  severity: "watch" | "medium" | "high";
  reason: string;
  recommendation: string;
  evidence: string[];
};

export type ProjectCompetitiveGapResponse = {
  project_id: number;
  generated_at: string | null;
  summary: {
    gap_count: number;
    largest_gap_metric: Exclude<CompetitiveMetric, "overall"> | null;
    largest_gap_delta: number | null;
  };
  gaps: ProjectCompetitiveGapItem[];
  pending_competitors: string[];
  failed_competitors: Array<{
    competitor_id: number;
    competitor_name: string;
    reason: string | null;
  }>;
};

export type ProjectCompetitiveRefreshResponse = {
  project_id: number;
  source_audit_id: number;
  queued_jobs: number;
  skipped_competitors: string[];
  message: string;
};

export type ProjectCompetitiveGapBriefResponse = {
  competitor_id: number;
  competitor_name: string;
  content: string;
  credits_charged: number;
};

export type ProjectTrendDirection = {
  seo: "up" | "down" | "stable";
  geo: "up" | "down" | "stable";
  aeo: "up" | "down" | "stable";
  overall: "up" | "down" | "stable";
};

export type ProjectTrendPoint = {
  date: string;
  seo: number | null;
  geo: number | null;
  aeo: number | null;
  overall: number | null;
  volatility_score?: number | null;
  audit_count: number;
  latest_audit_at: string | null;
};

export type ProjectTrendSummaryPoint = {
  date: string | null;
  seo: number | null;
  geo: number | null;
  aeo: number | null;
  overall: number | null;
  audit_count: number | null;
  latest_audit_at: string | null;
};

export type ProjectTrendSummary = {
  first: ProjectTrendSummaryPoint | null;
  latest: ProjectTrendSummaryPoint | null;
  delta: Record<"seo" | "geo" | "aeo" | "overall", number | null>;
  trend_direction: ProjectTrendDirection;
};

export type ProjectTrendResponse = {
  project_id: number;
  period: "7d" | "30d" | "90d" | "1y" | "all";
  granularity: "daily" | "weekly" | "monthly";
  data_points: ProjectTrendPoint[];
  summary: ProjectTrendSummary;
};

export type ProjectTrendComparisonPeriod = {
  start: string;
  end: string;
  seo: number | null;
  geo: number | null;
  aeo: number | null;
  overall: number | null;
  audit_count: number;
};

export type ProjectTrendComparisonResponse = {
  project_id: number;
  period: "30d" | "90d" | "1y";
  current_period: ProjectTrendComparisonPeriod;
  previous_period: ProjectTrendComparisonPeriod;
  delta: Record<"seo" | "geo" | "aeo" | "overall", number | null>;
  trend_direction: ProjectTrendDirection;
};

export type WorkspaceTrendSparklinePoint = {
  date: string;
  seo?: number | null;
  aio?: number | null;
  overall: number | null;
};

export type WorkspaceTrendOverviewProject = {
  project_id: number;
  name: string;
  domain_url: string | null;
  last_audit_at: string | null;
  latest_scores: Record<"seo" | "geo" | "aeo" | "overall", number | null>;
  delta: Record<"seo" | "geo" | "aeo" | "overall", number | null>;
  trend_direction: ProjectTrendDirection;
  sparkline: WorkspaceTrendSparklinePoint[];
};

export type WorkspaceTrendOverview = {
  workspace_id: number;
  period: "7d" | "30d" | "90d" | "1y" | "all";
  projects: WorkspaceTrendOverviewProject[];
};

export type ProjectProgressReport = {
  id: number;
  project_id: number;
  workspace_id: number;
  report_month: string;
  period_start: string;
  period_end: string;
  generated_by: string;
  recipient_count: number;
  email_sent_at: string | null;
  created_at: string | null;
  language: string;
  expired: boolean;
  retention_days: number;
  snapshot: Record<string, unknown>;
};

export type ProjectProgressReportGeneratePayload = {
  report_month?: string | null;
  deliver_email?: boolean;
};

export type ProjectTaskStatus = "todo" | "in_progress" | "done";
export type ProjectTaskPriority = "low" | "medium" | "high" | "critical";
export type ProjectTaskOrigin = "manual" | "audit_recommendation";
export type ProjectTaskResolutionSource = "manual" | "audit_validated";

export type ProjectTaskAssignee = {
  user_id: number;
  email: string;
  role: string;
  is_owner: boolean;
};

export type ProjectTaskItem = {
  id: number;
  project_id: number;
  title: string;
  description: string | null;
  status: ProjectTaskStatus;
  priority: ProjectTaskPriority;
  origin: ProjectTaskOrigin;
  category: string;
  source_audit_id: number | null;
  source_recommendation_key: string | null;
  assigned_to_user_id: number | null;
  assignee: ProjectTaskAssignee | null;
  due_date: string | null;
  resolved_at: string | null;
  verified_at: string | null;
  verification_audit_id: number | null;
  resolution_source: ProjectTaskResolutionSource | null;
  sort_order: number;
  created_at: string | null;
  updated_at: string | null;
};

export type ProjectTaskSummary = {
  todo: number;
  in_progress: number;
  done: number;
  unassigned: number;
  audit_linked: number;
  overdue: number;
  validated: number;
};

export type ProjectTaskBoard = {
  project_id: number;
  workspace_id: number;
  can_edit: boolean;
  latest_audit_id: number | null;
  latest_audit_at: string | null;
  assignees: ProjectTaskAssignee[];
  summary: ProjectTaskSummary;
  tasks: ProjectTaskItem[];
};

export type ProjectTaskCreatePayload = {
  title: string;
  description?: string | null;
  status?: ProjectTaskStatus;
  priority?: ProjectTaskPriority;
  category?: string;
  assigned_to_user_id?: number | null;
  due_date?: string | null;
  source_audit_id?: number | null;
  source_recommendation_key?: string | null;
};

export type ProjectTaskUpdatePayload = Partial<ProjectTaskCreatePayload>;

export type ProjectTaskReorderColumnPayload = {
  status: ProjectTaskStatus;
  task_ids: number[];
};

export type ProjectTaskReorderPayload = {
  columns: ProjectTaskReorderColumnPayload[];
};

export type ProjectTaskImpactItem = {
  task_id: number;
  title: string;
  category: string;
  priority: ProjectTaskPriority;
  resolution_source: ProjectTaskResolutionSource | null;
  source_audit_id: number | null;
  source_audit_created_at: string | null;
  verification_audit_id: number | null;
  verified_at: string | null;
  resolved_at: string | null;
  verification_status: "validated" | "pending_validation";
  delta: {
    seo: number | null;
    geo: number | null;
    aeo: number | null;
    overall: number | null;
  };
  narrative: string | null;
};

export type ProjectTaskImpact = {
  project_id: number;
  summary: {
    resolved_count: number;
    validated_count: number;
    pending_validation_count: number;
    strongest_metric: "seo" | "geo" | "aeo" | null;
    strongest_delta: number | null;
  };
  items: ProjectTaskImpactItem[];
};

export type CmsType = "wordpress" | "shopify";
export type CmsField = "head_scripts" | "meta_title" | "meta_description" | "alt_text";

export type ProjectCmsConnection = {
  id: number;
  project_id: number;
  workspace_id: number;
  cms_type: CmsType;
  site_url: string;
  status: "pending" | "verified" | "error" | string;
  last_verified_at: string | null;
  schema_version: string;
  created_at: string | null;
  updated_at: string | null;
  credentials_preview: Record<string, string>;
};

export type ProjectCmsConnectPayload = {
  cms_type: CmsType;
  site_url: string;
  credentials: Record<string, string>;
};

export type TaskCmsPreview = {
  task_id: number;
  project_id: number;
  connection_id: number;
  page_url: string;
  field: CmsField | string;
  current_value: string | null;
  proposed_value: string;
  diff_html: string;
  confirmation_token: string;
  confirmation_expires_in_seconds: number;
};

export type ProjectCmsDeploymentLog = {
  id: number;
  project_task_id: number | null;
  cms_connection_id: number | null;
  initiated_by: number | null;
  page_url: string;
  field_changed: CmsField | string;
  value_before: string | null;
  value_after: string;
  cms_revision_id: string | null;
  status: "pushed" | "failed" | "rolled_back" | string;
  pushed_at: string | null;
  rolled_back_at: string | null;
  error_message: string | null;
  schema_version: string;
  created_at: string | null;
};

export type TaskCmsPushPayload = {
  connection_id: number;
  page_url: string;
  field: CmsField;
  confirmation_token: string;
  new_value?: string | null;
};

export type TaskCmsPushResponse = {
  success: boolean;
  task_id: number;
  project_id: number;
  connection_id: number;
  deployment_log: ProjectCmsDeploymentLog;
  revision_id: string | null;
  error_message: string | null;
};

export type TaskCmsRollbackPayload = {
  connection_id: number;
  deployment_log_id?: number | null;
};

export type WorkspaceEmbedKeySummary = {
  id: number;
  workspace_id: number;
  user_id: number;
  label: string;
  allowed_origins: string[];
  daily_limit: number;
  is_active: boolean;
  key_prefix: string;
  key_last_four: string | null;
  last_used_at: string | null;
  created_at: string | null;
  schema_version: string;
};

export type WorkspaceEmbedKeyCreatePayload = {
  label: string;
  allowed_origins: string[];
  daily_limit?: number;
};

export type WorkspaceEmbedKeyCreateResponse = {
  api_key: string;
  item: WorkspaceEmbedKeySummary;
};

export type WorkspaceLead = {
  id: number;
  workspace_id: number;
  embed_key_id: number | null;
  email: string;
  url: string;
  entity: string | null;
  audit_job_id: string | null;
  scores: {
    geo: number | null;
    seo: number | null;
    aeo: number | null;
  } | null;
  source: string;
  status: "pending" | "audit_complete" | "contacted" | string;
  ip_address: string | null;
  created_at: string | null;
  schema_version: string;
};

export type WorkspaceLeadsResponse = {
  items: WorkspaceLead[];
  total: number;
  skip: number;
  limit: number;
};

export type SitemapCrawlEstimate = {
  url_count: number;
};

export type SitemapCrawlStartResponse = {
  job_id: string;
  status: string;
  total_urls: number | null;
};

export type SitemapCrawlStatus = {
  id: string;
  project_id: number;
  user_id: number;
  sitemap_url: string;
  status: "parsing" | "queuing" | "running" | "completed" | "failed" | string;
  total_urls: number | null;
  completed_urls: number;
  failed_urls: number;
  error: string | null;
  created_at: string | null;
  completed_at: string | null;
};

export type SitemapCrawlReport = {
  id: string;
  project_id: number;
  status: string;
  report: {
    aggregated_scores?: {
      geo: number | null;
      seo: number | null;
      aeo: number | null;
      site_health: number | null;
    };
    score_distribution?: {
      "80_plus": number;
      "60_79": number;
      "40_59": number;
      below_40: number;
    };
    top_issues?: Array<{ category: string; count: number }>;
    worst_pages?: Array<{
      url: string;
      geo: number | null;
      seo: number | null;
      aeo: number | null;
      overall: number | null;
      page_type?: string;
    }>;
    best_pages?: Array<{
      url: string;
      geo: number | null;
      seo: number | null;
      aeo: number | null;
      overall: number | null;
      page_type?: string;
    }>;
    page_type_breakdown?: Record<
      string,
      {
        count: number;
        avg_geo: number | null;
        avg_seo: number | null;
        avg_aeo: number | null;
        avg_overall: number | null;
      }
    >;
    site_insights?: Array<{ type: string; message: string }>;
    smart_crawl?: {
      mode: string;
      total_site_urls: number;
      sampled_urls: number;
      coverage_ratio: number;
      page_type_distribution: Record<string, number>;
      extrapolated_issues: Array<{
        page_type: string;
        label: string;
        sampled: number;
        estimated_total: number;
        avg_score: number;
        projected_affected_pages: number;
        confidence: "high" | "medium";
        insight: string;
      }>;
      extrapolation_note: string;
    };
    page_count?: number;
    generated_at?: string;
  };
};

/* ── Smart Crawl types ── */

export type SmartCrawlPlanBreakdown = {
  page_type: string;
  label: string;
  total_urls: number;
  sampled_urls: number;
  sample_urls: string[];
  skipped: boolean;
  coverage_ratio: number;
};

export type SmartCrawlEstimate = {
  total_site_urls: number;
  total_page_types: number;
  sampled_urls_count: number;
  plan: SmartCrawlPlanBreakdown[];
};

const WORKSPACE_LIST_ENDPOINT = "/api/workspaces";
const WORKSPACE_PROJECTS_ENDPOINT = "/api/workspaces/current/projects";
const WORKSPACE_CURRENT_ENDPOINT = "/api/workspaces/current";
const WORKSPACE_MEMBERS_ENDPOINT = "/api/workspaces/current/members";
const WORKSPACE_WHITE_LABEL_ENDPOINT = "/api/workspaces/current/white-label";
const WORKSPACE_EMAIL_FOOTER_ENDPOINT = "/api/workspaces/current/email-footer";
const PROJECT_AUDITS_ENDPOINT = (projectId: string | number) => `/api/projects/${projectId}/audits`;
const PROJECT_LATEST_AUDIT_ENDPOINT = (projectId: string | number) =>
  `/api/projects/${projectId}/audits/latest`;

export async function createWorkspace(
  name: string,
  headers: HeadersInit = {}
): Promise<WorkspaceSummary> {
  return requestJson<WorkspaceSummary>({
    endpoint: WORKSPACE_LIST_ENDPOINT,
    method: "POST",
    headers,
    body: { name },
    errorMessage: "Unable to create workspace.",
  });
}

export async function deleteWorkspace(
  workspaceId: number,
  headers: HeadersInit = {}
): Promise<void> {
  return requestVoid({
    endpoint: `${WORKSPACE_LIST_ENDPOINT}/${workspaceId}`,
    method: "DELETE",
    headers,
    errorMessage: "Unable to delete workspace.",
  });
}

export async function fetchUserWorkspaces(headers: HeadersInit = {}): Promise<WorkspaceSummary[]> {
  return requestJson<WorkspaceSummary[]>({
    endpoint: WORKSPACE_LIST_ENDPOINT,
    method: "GET",
    headers,
    errorMessage: "Unable to load workspaces.",
  });
}

export async function fetchCurrentWorkspace(headers: HeadersInit = {}): Promise<WorkspaceSummary> {
  return requestJson<WorkspaceSummary>({
    endpoint: WORKSPACE_CURRENT_ENDPOINT,
    method: "GET",
    headers,
    errorMessage: "Unable to load workspace.",
  });
}

export async function fetchWorkspaceProjects(
  headers: HeadersInit = {}
): Promise<WorkspaceProjectSummary[]> {
  return requestJson<WorkspaceProjectSummary[]>({
    endpoint: WORKSPACE_PROJECTS_ENDPOINT,
    method: "GET",
    headers,
    errorMessage: "Unable to load workspace projects.",
  });
}

export async function updateCurrentWorkspace(
  payload: WorkspaceUpdatePayload,
  headers: HeadersInit = {}
): Promise<WorkspaceSummary> {
  return requestJson<WorkspaceSummary>({
    endpoint: WORKSPACE_CURRENT_ENDPOINT,
    method: "PATCH",
    headers,
    body: payload,
    errorMessage: "Unable to update workspace.",
  });
}

export async function createWorkspaceProject(
  payload: ProjectCreatePayload,
  headers: HeadersInit = {}
): Promise<WorkspaceProjectSummary> {
  return requestJson<WorkspaceProjectSummary>({
    endpoint: WORKSPACE_PROJECTS_ENDPOINT,
    method: "POST",
    headers,
    body: payload,
    errorMessage: "Unable to create project.",
  });
}

export async function fetchProjectById(
  projectId: string | number,
  headers: HeadersInit = {}
): Promise<ProjectDetails> {
  return requestJson<ProjectDetails>({
    endpoint: `/api/projects/${projectId}`,
    method: "GET",
    headers,
    errorMessage: "Unable to load project.",
  });
}

export async function updateProjectById(
  projectId: string | number,
  payload: ProjectUpdatePayload,
  headers: HeadersInit = {}
): Promise<ProjectDetails> {
  return requestJson<ProjectDetails>({
    endpoint: `/api/projects/${projectId}`,
    method: "PATCH",
    headers,
    body: payload,
    errorMessage: "Unable to update project.",
  });
}

export async function deleteProjectById(
  projectId: string | number,
  headers: HeadersInit = {}
): Promise<void> {
  return requestVoid({
    endpoint: `/api/projects/${projectId}`,
    method: "DELETE",
    headers,
    errorMessage: "Unable to delete project.",
  });
}

export async function generateProjectSmartProfile(
  projectId: string | number,
  payload: ProjectSmartProfileGeneratePayload,
  headers: HeadersInit = {}
): Promise<ProjectSmartProfileGenerateResponse> {
  return requestJson<ProjectSmartProfileGenerateResponse>({
    endpoint: `/api/projects/${projectId}/generate-smart-profile`,
    method: "POST",
    headers,
    body: payload,
    errorMessage: "Unable to generate smart profile.",
  });
}

export async function createProjectMagicLink(
  projectId: string | number,
  expiresInHours: number,
  headers: HeadersInit = {}
): Promise<MagicLinkPayload> {
  return requestJson<MagicLinkPayload>({
    endpoint: `/api/projects/${projectId}/magic-link`,
    method: "POST",
    headers,
    body: { expires_in_hours: expiresInHours },
    errorMessage: "Unable to generate magic link.",
  });
}

export async function fetchProjectMagicLinkStatus(
  projectId: string | number,
  headers: HeadersInit = {}
): Promise<ProjectMagicLinkStatus> {
  return requestJson<ProjectMagicLinkStatus>({
    endpoint: `/api/projects/${projectId}/magic-link-status`,
    method: "GET",
    headers,
    errorMessage: "Unable to load magic link status.",
  });
}

export async function fetchProjectDataSources(
  projectId: string | number,
  headers: HeadersInit = {}
): Promise<ProjectDataSourceAssignment[]> {
  return requestJson<ProjectDataSourceAssignment[]>({
    endpoint: `/api/projects/${projectId}/data-sources`,
    method: "GET",
    headers,
    errorMessage: "Unable to load project data sources.",
  });
}

export async function upsertProjectDataSource(
  projectId: string | number,
  sourceType: ProjectDataSourceType,
  payload: {
    binding_mode: ProjectDataSourceBindingMode;
    source_id?: string | null;
    source_label?: string | null;
    is_active?: boolean;
  },
  headers: HeadersInit = {}
): Promise<ProjectDataSourceAssignment> {
  return requestJson<ProjectDataSourceAssignment>({
    endpoint: `/api/projects/${projectId}/data-sources/${sourceType}`,
    method: "PUT",
    headers,
    body: payload,
    errorMessage: "Unable to save project data source mapping.",
  });
}

export async function deleteProjectDataSource(
  projectId: string | number,
  sourceType: ProjectDataSourceType,
  headers: HeadersInit = {}
): Promise<void> {
  return requestVoid({
    endpoint: `/api/projects/${projectId}/data-sources/${sourceType}`,
    method: "DELETE",
    headers,
    errorMessage: "Unable to remove project data source mapping.",
  });
}

export async function fetchProjectDataSourceCatalog(
  projectId: string | number,
  sourceType: ProjectDataSourceType,
  headers: HeadersInit = {}
): Promise<ProjectDataSourceCatalogResponse> {
  return requestJson<ProjectDataSourceCatalogResponse>({
    endpoint: `/api/projects/${projectId}/data-sources/${sourceType}/catalog`,
    method: "GET",
    headers,
    errorMessage: "Unable to load project data source catalog.",
  });
}

export async function fetchProjectAudits(
  projectId: string | number,
  headers: HeadersInit = {},
  options: {
    limit?: number;
    includeFullReport?: boolean;
    auditType?: "STANDARD" | "DEEP";
  } = {}
): Promise<ProjectAuditHistoryEntry[]> {
  const query = new URLSearchParams();
  if (typeof options.limit === "number") {
    query.set("limit", String(options.limit));
  }
  if (typeof options.includeFullReport === "boolean") {
    query.set("include_full_report", String(options.includeFullReport));
  }
  if (options.auditType) {
    query.set("audit_type", options.auditType);
  }
  const endpoint = query.toString()
    ? `${PROJECT_AUDITS_ENDPOINT(projectId)}?${query.toString()}`
    : PROJECT_AUDITS_ENDPOINT(projectId);
  return requestJson<ProjectAuditHistoryEntry[]>({
    endpoint,
    method: "GET",
    headers,
    errorMessage: "Unable to load project audits.",
  });
}

export async function fetchProjectLatestAudit(
  projectId: string | number,
  headers: HeadersInit = {},
  options: {
    includeFullReport?: boolean;
    auditType?: "STANDARD" | "DEEP";
  } = {}
): Promise<ProjectAuditHistoryEntry | null> {
  const query = new URLSearchParams();
  if (typeof options.includeFullReport === "boolean") {
    query.set("include_full_report", String(options.includeFullReport));
  }
  if (options.auditType) {
    query.set("audit_type", options.auditType);
  }
  const endpoint = query.toString()
    ? `${PROJECT_LATEST_AUDIT_ENDPOINT(projectId)}?${query.toString()}`
    : PROJECT_LATEST_AUDIT_ENDPOINT(projectId);
  return requestJson<ProjectAuditHistoryEntry | null>({
    endpoint,
    method: "GET",
    headers,
    errorMessage: "Unable to load latest project audit.",
  });
}

export async function fetchProjectLatestAuditSelection(
  projectId: string | number,
  headers: HeadersInit = {},
  options: {
    includeFullReport?: boolean;
    module: ProjectAuditModule;
  }
): Promise<ProjectLatestAuditSelection> {
  const query = new URLSearchParams();
  query.set("module", options.module);
  if (typeof options.includeFullReport === "boolean") {
    query.set("include_full_report", String(options.includeFullReport));
  }
  return requestJson<ProjectLatestAuditSelection>({
    endpoint: `${PROJECT_LATEST_AUDIT_ENDPOINT(projectId)}-selection?${query.toString()}`,
    method: "GET",
    headers,
    errorMessage: "Unable to load module audit selection.",
  });
}

export async function fetchWorkspaceMembers(
  headers: HeadersInit = {}
): Promise<WorkspaceMemberSummary[]> {
  return requestJson<WorkspaceMemberSummary[]>({
    endpoint: WORKSPACE_MEMBERS_ENDPOINT,
    method: "GET",
    headers,
    errorMessage: "Unable to load workspace members.",
  });
}

export async function addWorkspaceMember(
  email: string,
  role: WorkspaceMemberSummary["role"],
  headers: HeadersInit = {}
): Promise<WorkspaceMemberSummary> {
  return requestJson<WorkspaceMemberSummary>({
    endpoint: WORKSPACE_MEMBERS_ENDPOINT,
    method: "POST",
    headers,
    body: { email, role },
    errorMessage: "Unable to add workspace member.",
  });
}

export async function updateWorkspaceMemberRole(
  userId: number,
  role: WorkspaceMemberSummary["role"],
  headers: HeadersInit = {}
): Promise<WorkspaceMemberSummary> {
  return requestJson<WorkspaceMemberSummary>({
    endpoint: `${WORKSPACE_MEMBERS_ENDPOINT}/${userId}`,
    method: "PATCH",
    headers,
    body: { role },
    errorMessage: "Unable to update workspace member role.",
  });
}

export async function removeWorkspaceMember(
  userId: number,
  headers: HeadersInit = {}
): Promise<void> {
  return requestVoid({
    endpoint: `${WORKSPACE_MEMBERS_ENDPOINT}/${userId}`,
    method: "DELETE",
    headers,
    errorMessage: "Unable to remove workspace member.",
  });
}

export async function fetchWorkspaceWhiteLabelSettings(
  headers: HeadersInit = {}
): Promise<WorkspaceWhiteLabelSettings> {
  return requestJson<WorkspaceWhiteLabelSettings>({
    endpoint: WORKSPACE_WHITE_LABEL_ENDPOINT,
    method: "GET",
    headers,
    errorMessage: "Unable to load white-label settings.",
  });
}

export async function updateWorkspaceWhiteLabelSettings(
  payload: WorkspaceWhiteLabelUpdatePayload,
  headers: HeadersInit = {}
): Promise<WorkspaceWhiteLabelSettings> {
  return requestJson<WorkspaceWhiteLabelSettings>({
    endpoint: WORKSPACE_WHITE_LABEL_ENDPOINT,
    method: "PUT",
    headers,
    body: payload,
    errorMessage: "Unable to save white-label settings.",
  });
}

export async function fetchWorkspaceEmailFooterSettings(
  headers: HeadersInit = {}
): Promise<WorkspaceEmailFooterSettings> {
  return requestJson<WorkspaceEmailFooterSettings>({
    endpoint: WORKSPACE_EMAIL_FOOTER_ENDPOINT,
    method: "GET",
    headers,
    errorMessage: "Unable to load email footer settings.",
  });
}

export async function updateWorkspaceEmailFooterSettings(
  payload: WorkspaceEmailFooterUpdatePayload,
  headers: HeadersInit = {}
): Promise<WorkspaceEmailFooterSettings> {
  return requestJson<WorkspaceEmailFooterSettings>({
    endpoint: WORKSPACE_EMAIL_FOOTER_ENDPOINT,
    method: "PATCH",
    headers,
    body: payload,
    errorMessage: "Unable to save email footer settings.",
  });
}

export async function createWorkspaceCustomDomain(
  domain: string,
  headers: HeadersInit = {}
): Promise<WorkspaceWhiteLabelSettings> {
  return requestJson<WorkspaceWhiteLabelSettings>({
    endpoint: `${WORKSPACE_WHITE_LABEL_ENDPOINT}/domains`,
    method: "POST",
    headers,
    body: { domain },
    errorMessage: "Unable to add the custom domain.",
  });
}

export async function verifyWorkspaceCustomDomain(
  domainId: number,
  headers: HeadersInit = {}
): Promise<WorkspaceWhiteLabelSettings> {
  return requestJson<WorkspaceWhiteLabelSettings>({
    endpoint: `${WORKSPACE_WHITE_LABEL_ENDPOINT}/domains/${domainId}/verify`,
    method: "POST",
    headers,
    errorMessage: "Unable to verify the custom domain.",
  });
}

export async function deleteWorkspaceCustomDomain(
  domainId: number,
  headers: HeadersInit = {}
): Promise<void> {
  return requestVoid({
    endpoint: `${WORKSPACE_WHITE_LABEL_ENDPOINT}/domains/${domainId}`,
    method: "DELETE",
    headers,
    errorMessage: "Unable to remove the custom domain.",
  });
}

export async function inviteWorkspaceClient(
  workspaceId: number,
  payload: ClientInvitationPayload,
  headers: HeadersInit = {}
): Promise<ClientInvitationResult> {
  return requestJson<ClientInvitationResult>({
    endpoint: `/api/workspaces/${workspaceId}/invite-client`,
    method: "POST",
    headers,
    body: payload,
    errorMessage: "Unable to invite client portal user.",
  });
}

export async function fetchProjectBudget(
  workspaceId: number,
  projectId: string | number,
  headers: HeadersInit = {}
): Promise<ProjectBudgetSummary> {
  return requestJson<ProjectBudgetSummary>({
    endpoint: `/api/workspaces/${workspaceId}/projects/${projectId}/budget`,
    method: "GET",
    headers,
    errorMessage: "Unable to load project budget guardrail.",
  });
}

export async function upsertProjectBudget(
  workspaceId: number,
  projectId: string | number,
  payload: ProjectBudgetUpsertPayload,
  headers: HeadersInit = {}
): Promise<ProjectBudgetSummary> {
  return requestJson<ProjectBudgetSummary>({
    endpoint: `/api/workspaces/${workspaceId}/projects/${projectId}/budget`,
    method: "PUT",
    headers,
    body: payload,
    errorMessage: "Unable to save project budget guardrail.",
  });
}

export async function deleteProjectBudget(
  workspaceId: number,
  projectId: string | number,
  headers: HeadersInit = {}
): Promise<ProjectBudgetSummary> {
  return requestJson<ProjectBudgetSummary>({
    endpoint: `/api/workspaces/${workspaceId}/projects/${projectId}/budget`,
    method: "DELETE",
    headers,
    errorMessage: "Unable to remove project budget guardrail.",
  });
}

export async function fetchWorkspaceCostBreakdown(
  workspaceId: number,
  headers: HeadersInit = {}
): Promise<WorkspaceCostBreakdown> {
  return requestJson<WorkspaceCostBreakdown>({
    endpoint: `/api/workspaces/${workspaceId}/cost-breakdown`,
    method: "GET",
    headers,
    errorMessage: "Unable to load workspace cost breakdown.",
  });
}

export async function fetchProjectCompetitors(
  projectId: string | number,
  headers: HeadersInit = {}
): Promise<ProjectCompetitorListItem[]> {
  return requestJson<ProjectCompetitorListItem[]>({
    endpoint: `/api/projects/${projectId}/competitors`,
    method: "GET",
    headers,
    errorMessage: "Unable to load project competitors.",
  });
}

export async function createProjectCompetitor(
  projectId: string | number,
  payload: ProjectCompetitorCreatePayload,
  headers: HeadersInit = {}
): Promise<ProjectCompetitorListItem> {
  return requestJson<ProjectCompetitorListItem>({
    endpoint: `/api/projects/${projectId}/competitors`,
    method: "POST",
    headers,
    body: payload,
    errorMessage: "Unable to add competitor benchmark target.",
  });
}

export async function deleteProjectCompetitor(
  projectId: string | number,
  competitorId: number,
  headers: HeadersInit = {}
): Promise<void> {
  return requestVoid({
    endpoint: `/api/projects/${projectId}/competitors/${competitorId}`,
    method: "DELETE",
    headers,
    errorMessage: "Unable to remove competitor benchmark target.",
  });
}

export async function fetchProjectCompetitiveAnalysis(
  projectId: string | number,
  headers: HeadersInit = {}
): Promise<ProjectCompetitiveAnalysisResponse> {
  return requestJson<ProjectCompetitiveAnalysisResponse>({
    endpoint: `/api/projects/${projectId}/competitive-analysis`,
    method: "GET",
    headers,
    errorMessage: "Unable to load competitive analysis.",
  });
}

export async function fetchProjectCompetitiveTrends(
  projectId: string | number,
  headers: HeadersInit = {},
  options: {
    period?: "30d" | "90d" | "1y" | "all";
    metric?: CompetitiveMetric;
  } = {}
): Promise<ProjectCompetitiveTrendResponse> {
  const query = new URLSearchParams();
  if (options.period) {
    query.set("period", options.period);
  }
  if (options.metric) {
    query.set("metric", options.metric);
  }
  const endpoint = query.toString()
    ? `/api/projects/${projectId}/competitive-analysis/trends?${query.toString()}`
    : `/api/projects/${projectId}/competitive-analysis/trends`;
  return requestJson<ProjectCompetitiveTrendResponse>({
    endpoint,
    method: "GET",
    headers,
    errorMessage: "Unable to load competitive trend history.",
  });
}

export async function fetchProjectCompetitiveGaps(
  projectId: string | number,
  headers: HeadersInit = {}
): Promise<ProjectCompetitiveGapResponse> {
  return requestJson<ProjectCompetitiveGapResponse>({
    endpoint: `/api/projects/${projectId}/competitive-analysis/gaps`,
    method: "GET",
    headers,
    errorMessage: "Unable to load competitive gap analysis.",
  });
}

export async function refreshProjectCompetitiveAnalysis(
  projectId: string | number,
  headers: HeadersInit = {}
): Promise<ProjectCompetitiveRefreshResponse> {
  return requestJson<ProjectCompetitiveRefreshResponse>({
    endpoint: `/api/projects/${projectId}/competitive-analysis/refresh`,
    method: "POST",
    headers,
    errorMessage: "Unable to queue competitor benchmark refresh.",
  });
}

export async function generateProjectCompetitiveGapBrief(
  projectId: string | number,
  competitorId: number,
  headers: HeadersInit = {}
): Promise<ProjectCompetitiveGapBriefResponse> {
  return requestJson<ProjectCompetitiveGapBriefResponse>({
    endpoint: `/api/projects/${projectId}/competitive-analysis/gaps/${competitorId}/ai-brief`,
    method: "POST",
    headers,
    errorMessage: "Unable to generate competitive gap brief.",
  });
}

export async function fetchProjectTrends(
  projectId: string | number,
  headers: HeadersInit = {},
  options: {
    period?: "7d" | "30d" | "90d" | "1y" | "all";
    granularity?: "daily" | "weekly" | "monthly";
  } = {}
): Promise<ProjectTrendResponse> {
  const query = new URLSearchParams();
  if (options.period) {
    query.set("period", options.period);
  }
  if (options.granularity) {
    query.set("granularity", options.granularity);
  }
  const endpoint = query.toString()
    ? `/api/projects/${projectId}/trends?${query.toString()}`
    : `/api/projects/${projectId}/trends`;
  return requestJson<ProjectTrendResponse>({
    endpoint,
    method: "GET",
    headers,
    errorMessage: "Unable to load project trends.",
  });
}

export async function fetchProjectTrendComparison(
  projectId: string | number,
  headers: HeadersInit = {},
  options: {
    period?: "30d" | "90d" | "1y";
  } = {}
): Promise<ProjectTrendComparisonResponse> {
  const query = new URLSearchParams();
  if (options.period) {
    query.set("period", options.period);
  }
  const endpoint = query.toString()
    ? `/api/projects/${projectId}/trends/comparison?${query.toString()}`
    : `/api/projects/${projectId}/trends/comparison`;
  return requestJson<ProjectTrendComparisonResponse>({
    endpoint,
    method: "GET",
    headers,
    errorMessage: "Unable to compare project periods.",
  });
}

export async function fetchWorkspaceTrendOverview(
  workspaceId: number,
  headers: HeadersInit = {},
  options: {
    period?: "7d" | "30d" | "90d" | "1y" | "all";
  } = {}
): Promise<WorkspaceTrendOverview> {
  const query = new URLSearchParams();
  if (options.period) {
    query.set("period", options.period);
  }
  const endpoint = query.toString()
    ? `/api/workspaces/${workspaceId}/trends/overview?${query.toString()}`
    : `/api/workspaces/${workspaceId}/trends/overview`;
  return requestJson<WorkspaceTrendOverview>({
    endpoint,
    method: "GET",
    headers,
    errorMessage: "Unable to load workspace trend overview.",
  });
}

export async function fetchProjectTasks(
  projectId: string | number,
  headers: HeadersInit = {}
): Promise<ProjectTaskBoard> {
  return requestJson<ProjectTaskBoard>({
    endpoint: `/api/projects/${projectId}/tasks`,
    method: "GET",
    headers,
    errorMessage: "Unable to load project task board.",
  });
}

export async function createProjectTask(
  projectId: string | number,
  payload: ProjectTaskCreatePayload,
  headers: HeadersInit = {}
): Promise<ProjectTaskItem> {
  return requestJson<ProjectTaskItem>({
    endpoint: `/api/projects/${projectId}/tasks`,
    method: "POST",
    headers,
    body: payload,
    errorMessage: "Unable to create project task.",
  });
}

export async function updateProjectTask(
  projectId: string | number,
  taskId: number,
  payload: ProjectTaskUpdatePayload,
  headers: HeadersInit = {}
): Promise<ProjectTaskItem> {
  return requestJson<ProjectTaskItem>({
    endpoint: `/api/projects/${projectId}/tasks/${taskId}`,
    method: "PUT",
    headers,
    body: payload,
    errorMessage: "Unable to update project task.",
  });
}

export async function deleteProjectTask(
  projectId: string | number,
  taskId: number,
  headers: HeadersInit = {}
): Promise<void> {
  return requestVoid({
    endpoint: `/api/projects/${projectId}/tasks/${taskId}`,
    method: "DELETE",
    headers,
    errorMessage: "Unable to delete project task.",
  });
}

export async function reorderProjectTasks(
  projectId: string | number,
  payload: ProjectTaskReorderPayload,
  headers: HeadersInit = {}
): Promise<ProjectTaskBoard> {
  return requestJson<ProjectTaskBoard>({
    endpoint: `/api/projects/${projectId}/tasks/reorder`,
    method: "PATCH",
    headers,
    body: payload,
    errorMessage: "Unable to reorder project tasks.",
  });
}

export async function fetchProjectTaskImpact(
  projectId: string | number,
  headers: HeadersInit = {}
): Promise<ProjectTaskImpact> {
  return requestJson<ProjectTaskImpact>({
    endpoint: `/api/projects/${projectId}/tasks/impact`,
    method: "GET",
    headers,
    errorMessage: "Unable to load project task impact.",
  });
}

export async function fetchProjectCmsConnections(
  projectId: string | number,
  headers: HeadersInit = {}
): Promise<ProjectCmsConnection[]> {
  return requestJson<ProjectCmsConnection[]>({
    endpoint: `/api/projects/${projectId}/cms/connections`,
    method: "GET",
    headers,
    errorMessage: "Unable to load project CMS connections.",
  });
}

export async function connectProjectCms(
  projectId: string | number,
  payload: ProjectCmsConnectPayload,
  headers: HeadersInit = {}
): Promise<ProjectCmsConnection> {
  return requestJson<ProjectCmsConnection>({
    endpoint: `/api/projects/${projectId}/cms/connect`,
    method: "POST",
    headers,
    body: payload,
    errorMessage: "Unable to save CMS connection.",
  });
}

export async function verifyProjectCmsConnection(
  projectId: string | number,
  connectionId: number,
  headers: HeadersInit = {}
): Promise<ProjectCmsConnection> {
  return requestJson<ProjectCmsConnection>({
    endpoint: `/api/projects/${projectId}/cms/connections/${connectionId}/verify`,
    method: "POST",
    headers,
    errorMessage: "Unable to verify CMS connection.",
  });
}

export async function deleteProjectCmsConnection(
  projectId: string | number,
  connectionId: number,
  headers: HeadersInit = {}
): Promise<void> {
  return requestVoid({
    endpoint: `/api/projects/${projectId}/cms/connections/${connectionId}`,
    method: "DELETE",
    headers,
    errorMessage: "Unable to remove CMS connection.",
  });
}

export async function previewTaskCmsChange(
  taskId: number,
  payload: {
    connection_id: number;
    page_url: string;
    field: CmsField;
    new_value?: string | null;
  },
  headers: HeadersInit = {}
): Promise<TaskCmsPreview> {
  const query = new URLSearchParams({
    connection_id: String(payload.connection_id),
    page_url: payload.page_url,
    field: payload.field,
  });
  if (payload.new_value && payload.new_value.trim()) {
    query.set("new_value", payload.new_value);
  }
  return requestJson<TaskCmsPreview>({
    endpoint: `/api/tasks/${taskId}/cms/preview?${query.toString()}`,
    method: "GET",
    headers,
    errorMessage: "Unable to preview CMS change.",
  });
}

export async function pushTaskCmsChange(
  taskId: number,
  payload: TaskCmsPushPayload,
  headers: HeadersInit = {}
): Promise<TaskCmsPushResponse> {
  return requestJson<TaskCmsPushResponse>({
    endpoint: `/api/tasks/${taskId}/cms/push`,
    method: "POST",
    headers,
    body: payload,
    errorMessage: "Unable to push fix to CMS.",
  });
}

export async function rollbackTaskCmsChange(
  taskId: number,
  payload: TaskCmsRollbackPayload,
  headers: HeadersInit = {}
): Promise<TaskCmsPushResponse> {
  return requestJson<TaskCmsPushResponse>({
    endpoint: `/api/tasks/${taskId}/cms/rollback`,
    method: "POST",
    headers,
    body: payload,
    errorMessage: "Unable to roll back CMS deployment.",
  });
}

export async function fetchProjectCmsDeploymentLog(
  projectId: string | number,
  headers: HeadersInit = {},
  options: {
    taskId?: number;
    connectionId?: number;
    limit?: number;
  } = {}
): Promise<ProjectCmsDeploymentLog[]> {
  const query = new URLSearchParams();
  if (typeof options.taskId === "number") {
    query.set("task_id", String(options.taskId));
  }
  if (typeof options.connectionId === "number") {
    query.set("connection_id", String(options.connectionId));
  }
  if (typeof options.limit === "number") {
    query.set("limit", String(options.limit));
  }
  const endpoint = query.toString()
    ? `/api/projects/${projectId}/cms/deployment-log?${query.toString()}`
    : `/api/projects/${projectId}/cms/deployment-log`;
  return requestJson<ProjectCmsDeploymentLog[]>({
    endpoint,
    method: "GET",
    headers,
    errorMessage: "Unable to load CMS deployment log.",
  });
}

export async function fetchWorkspaceEmbedKeys(
  workspaceId: string | number,
  headers: HeadersInit = {}
): Promise<WorkspaceEmbedKeySummary[]> {
  return requestJson<WorkspaceEmbedKeySummary[]>({
    endpoint: `/api/workspaces/${workspaceId}/embed-keys`,
    method: "GET",
    headers,
    errorMessage: "Unable to load embed API keys.",
  });
}

export async function createWorkspaceEmbedKey(
  workspaceId: string | number,
  payload: WorkspaceEmbedKeyCreatePayload,
  headers: HeadersInit = {}
): Promise<WorkspaceEmbedKeyCreateResponse> {
  return requestJson<WorkspaceEmbedKeyCreateResponse>({
    endpoint: `/api/workspaces/${workspaceId}/embed-keys`,
    method: "POST",
    headers,
    body: payload,
    errorMessage: "Unable to create embed API key.",
  });
}

export async function deleteWorkspaceEmbedKey(
  workspaceId: string | number,
  embedKeyId: number,
  headers: HeadersInit = {}
): Promise<{ revoked: boolean; item: WorkspaceEmbedKeySummary }> {
  return requestJson<{ revoked: boolean; item: WorkspaceEmbedKeySummary }>({
    endpoint: `/api/workspaces/${workspaceId}/embed-keys/${embedKeyId}`,
    method: "DELETE",
    headers,
    errorMessage: "Unable to revoke embed API key.",
  });
}

export async function fetchWorkspaceLeads(
  workspaceId: string | number,
  headers: HeadersInit = {},
  options: {
    skip?: number;
    limit?: number;
    status?: string;
  } = {}
): Promise<WorkspaceLeadsResponse> {
  const query = new URLSearchParams();
  if (typeof options.skip === "number") {
    query.set("skip", String(options.skip));
  }
  if (typeof options.limit === "number") {
    query.set("limit", String(options.limit));
  }
  if (options.status) {
    query.set("status", options.status);
  }
  const endpoint = query.toString()
    ? `/api/workspaces/${workspaceId}/leads?${query.toString()}`
    : `/api/workspaces/${workspaceId}/leads`;
  return requestJson<WorkspaceLeadsResponse>({
    endpoint,
    method: "GET",
    headers,
    errorMessage: "Unable to load leads.",
  });
}

export async function estimateProjectSitemapCrawl(
  projectId: string | number,
  payload: { sitemap_url: string },
  headers: HeadersInit = {}
): Promise<SitemapCrawlEstimate> {
  return requestJson<SitemapCrawlEstimate>({
    endpoint: `/api/projects/${projectId}/sitemap-crawl/estimate`,
    method: "POST",
    headers,
    body: payload,
    errorMessage: "Unable to estimate the scan cost of this crawl.",
  });
}

export async function startProjectSitemapCrawl(
  projectId: string | number,
  payload: { sitemap_url: string },
  headers: HeadersInit = {}
): Promise<SitemapCrawlStartResponse> {
  return requestJson<SitemapCrawlStartResponse>({
    endpoint: `/api/projects/${projectId}/sitemap-crawl`,
    method: "POST",
    headers,
    body: payload,
    errorMessage: "Unable to start sitemap crawl.",
  });
}

/**
 * Fetch the most recently created sitemap crawl job for a project, so the
 * Site Crawl page can reattach to a running crawl or show the last report
 * after a refresh/navigation instead of losing all progress.
 *
 * Proxies to `GET /api/v1/projects/{project_id}/sitemap-crawl/latest`, which
 * returns 404 when the project has never had a crawl. That surfaces here as
 * an {@link HttpRequestError} with `status === 404`, which we treat as "no
 * crawl yet" and resolve to `null` instead of throwing.
 */
export async function fetchLatestProjectSitemapCrawl(
  projectId: string | number,
  headers: HeadersInit = {}
): Promise<SitemapCrawlStatus | null> {
  try {
    return await requestJson<SitemapCrawlStatus>({
      endpoint: `/api/projects/${projectId}/sitemap-crawl/latest`,
      method: "GET",
      headers,
      errorMessage: "Unable to load the latest sitemap crawl.",
    });
  } catch (error) {
    if (error instanceof HttpRequestError && error.status === 404) {
      return null;
    }
    throw error;
  }
}

export async function fetchSitemapCrawlStatus(
  crawlJobId: string,
  headers: HeadersInit = {}
): Promise<SitemapCrawlStatus> {
  return requestJson<SitemapCrawlStatus>({
    endpoint: `/api/sitemap-crawl/${crawlJobId}`,
    method: "GET",
    headers,
    errorMessage: "Unable to load sitemap crawl status.",
  });
}

export async function fetchSitemapCrawlReport(
  crawlJobId: string,
  headers: HeadersInit = {}
): Promise<SitemapCrawlReport> {
  return requestJson<SitemapCrawlReport>({
    endpoint: `/api/sitemap-crawl/${crawlJobId}/report`,
    method: "GET",
    headers,
    errorMessage: "Unable to load sitemap crawl report.",
  });
}

/* ── Smart Crawl API ── */

export async function estimateSmartCrawl(
  projectId: string | number,
  payload: { sitemap_url: string },
  headers: HeadersInit = {}
): Promise<SmartCrawlEstimate> {
  return requestJson<SmartCrawlEstimate>({
    endpoint: `/api/projects/${projectId}/smart-crawl/estimate`,
    method: "POST",
    headers,
    body: payload,
    errorMessage: "Unable to estimate smart crawl.",
  });
}

export async function startSmartCrawl(
  projectId: string | number,
  payload: { sitemap_url: string },
  headers: HeadersInit = {}
): Promise<SitemapCrawlStartResponse> {
  return requestJson<SitemapCrawlStartResponse>({
    endpoint: `/api/projects/${projectId}/smart-crawl`,
    method: "POST",
    headers,
    body: payload,
    errorMessage: "Unable to start smart crawl.",
  });
}

export async function fetchProjectProgressReports(
  projectId: string | number,
  headers: HeadersInit = {}
): Promise<ProjectProgressReport[]> {
  return requestJson<ProjectProgressReport[]>({
    endpoint: `/api/projects/${projectId}/reports`,
    method: "GET",
    headers,
    errorMessage: "Unable to load project progress reports.",
  });
}

export async function fetchProjectProgressReport(
  projectId: string | number,
  reportId: string | number,
  headers: HeadersInit = {}
): Promise<ProjectProgressReport> {
  return requestJson<ProjectProgressReport>({
    endpoint: `/api/projects/${projectId}/reports/${reportId}`,
    method: "GET",
    headers,
    errorMessage: "Unable to load project progress report.",
  });
}

export async function generateProjectProgressReport(
  projectId: string | number,
  payload: ProjectProgressReportGeneratePayload,
  headers: HeadersInit = {}
): Promise<ProjectProgressReport> {
  return requestJson<ProjectProgressReport>({
    endpoint: `/api/projects/${projectId}/reports/generate`,
    method: "POST",
    headers,
    body: payload,
    errorMessage: "Unable to generate project progress report.",
  });
}
