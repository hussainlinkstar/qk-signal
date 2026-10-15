"use client";

import SignalAlert from "@/components/signal/SignalAlert";
import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  ArrowRight,
  BarChart3,
  CheckCircle2,
  ClipboardList,
  FileText,
  Loader2,
  Palette,
  Wallet,
} from "lucide-react";

import { useAuth } from "@/components/auth/custom-auth";
import { getActiveWorkspaceId, workspaceHeaders } from "@/components/app/WorkspaceSwitcher";
import DashboardPageIntro from "@/components/dashboard/DashboardPageIntro";
import LockedFeatureButton from "@/components/dashboard/LockedFeatureButton";
import Badge from "@/components/ui/Badge";
import Button from "@/components/ui/Button";
import ColorPickerField, { normalizeHexColor } from "@/components/ui/ColorPickerField";
import { GlassCard } from "@/components/ui/GlassComponents";
import SelectField from "@/components/ui/SelectField";
import TextField from "@/components/ui/TextField";
import ToggleSwitch from "@/components/ui/ToggleSwitch";
import { CARD_CONTAINER_PRESETS, CARD_LABEL_CLASS } from "@/components/ui/cardStyleTokens";
import { cx } from "@/components/ui/utils";
import { BRAND_HEX, BRAND_PRIMARY_PRESETS, BRAND_SECONDARY_PRESETS } from "@/lib/brandPalette";
import { formatDateTime } from "@/lib/dateFormat";
import { getIntegrityStatusSnapshot } from "@/lib/integrityStatus";
import { resolvePlanCapabilities } from "@/lib/planCapabilities";
import { getPlanLockContent } from "@/lib/planLocks";
import {
  REPORT_LANGUAGE_OPTIONS,
  getReportLanguageLabel,
  normalizeReportLanguage,
} from "@/lib/reportLanguages";
import {
  downloadComplexReportPdfBlob,
  fetchComplexReportStatus,
  fetchWhiteLabelBranding,
  generateComplexReportPdf,
  generateWhiteLabelReportPdf,
} from "@/services/reportService";
import {
  fetchProjectAudits,
  fetchProjectCompetitors,
  fetchWorkspaceProjects,
  type ProjectAuditHistoryEntry,
  type ProjectCompetitorListItem,
  type WorkspaceProjectSummary,
} from "@/services/workspaceService";

const REPORT_POLL_DELAY_MS = 2000;
const REPORT_MAX_POLL_ATTEMPTS = 45;
const REPORT_JOB_STORAGE_PREFIX = "signal.reportJob.v1";

type StoredReportJob = { reportId: string; kind?: string };

// There is no collection endpoint for report jobs, so the only way to resume an
// in-flight export after a reload is to remember the job id client-side, scoped
// per user and per workspace. Drop this once SIGV2-1106 lands a list route.
const reportJobStorageKey = (userId: string): string => {
  const workspaceId = getActiveWorkspaceId();
  return `${REPORT_JOB_STORAGE_PREFIX}.${userId}.${workspaceId ?? "default"}`;
};

const readStoredReportJob = (userId: string): StoredReportJob | null => {
  try {
    const raw = window.localStorage.getItem(reportJobStorageKey(userId));
    if (!raw) {
      return null;
    }
    const parsed: unknown = JSON.parse(raw);
    if (
      parsed &&
      typeof parsed === "object" &&
      typeof (parsed as StoredReportJob).reportId === "string" &&
      (parsed as StoredReportJob).reportId
    ) {
      return parsed as StoredReportJob;
    }
    return null;
  } catch {
    return null;
  }
};

const persistReportJob = (userId: string, job: StoredReportJob): void => {
  try {
    window.localStorage.setItem(reportJobStorageKey(userId), JSON.stringify(job));
  } catch {
    // Storage can be unavailable (private mode, quota); losing resume is
    // acceptable, the job still completes while the page stays open.
  }
};

const clearStoredReportJob = (userId: string): void => {
  try {
    window.localStorage.removeItem(reportJobStorageKey(userId));
  } catch {
    // See persistReportJob.
  }
};
const DEFAULT_REPORT_PRIMARY_COLOR = BRAND_HEX.atlasBlue;
const DEFAULT_REPORT_SECONDARY_COLOR = BRAND_HEX.signalTeal;
const REPORT_PRIMARY_PRESETS = BRAND_PRIMARY_PRESETS;
const REPORT_SECONDARY_PRESETS = BRAND_SECONDARY_PRESETS;

type ExportAction =
  | "standard"
  | "aio"
  | "seo"
  | "executivePlatform"
  | "executiveBranded"
  | "executiveWhitelabel"
  | "project"
  | "competitorsLatest"
  | "competitorsTrend"
  | "financial";
type ProjectRangeMode = "all_time" | "custom";
type CompetitorExportMode = "latest" | "trend";
export type ReportFlow =
  | "standard"
  | "aio"
  | "seo"
  | "project"
  | "competitors"
  | "executive"
  | "financial";
type WizardStep = "project" | "audit" | "report" | "configure";
type BadgeTone = "default" | "success" | "warning" | "danger" | "info" | "teal" | "violet";

type BattleCompetitorOption = {
  key: string;
  name: string;
  rank: number | null;
  overall: number | null;
  geo: number | null;
  aeo: number | null;
  entityStrength: number | null;
};

const sleep = (ms: number) => new Promise((resolve) => window.setTimeout(resolve, ms));

const toDateInputValue = (value: string | null | undefined): string => {
  if (!value) {
    return "";
  }
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return "";
  }
  return parsed.toISOString().slice(0, 10);
};

const toDateRangeBoundaryIso = (value: string, boundary: "start" | "end"): string =>
  `${value}T${boundary === "start" ? "00:00:00.000Z" : "23:59:59.999Z"}`;

const sanitizeFileSegment = (value: string): string => {
  const sanitized = value
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
  return sanitized || "report";
};

const triggerPdfDownload = (blob: Blob, filename: string) => {
  const objectUrl = window.URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = objectUrl;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  window.setTimeout(() => window.URL.revokeObjectURL(objectUrl), 0);
};

const resolveAuditTargetType = (
  audit: Pick<ProjectAuditHistoryEntry, "audit_target_type"> | null | undefined
): "website" | "brand" => (audit?.audit_target_type === "brand" ? "brand" : "website");

const resolveAuditTargetLabel = (
  audit: Pick<ProjectAuditHistoryEntry, "target_name" | "target_url" | "url"> | null | undefined
): string => (audit?.target_name || audit?.target_url || audit?.url || "").trim();

const toNullableNumber = (value: unknown): number | null => {
  if (typeof value === "number" && Number.isFinite(value)) {
    return value;
  }
  if (typeof value === "string" && value.trim()) {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : null;
  }
  return null;
};

const toPositiveInteger = (value: unknown): number | null => {
  const resolved = toNullableNumber(value);
  if (resolved === null || !Number.isInteger(resolved) || resolved <= 0) {
    return null;
  }
  return resolved;
};

const extractBattleCompetitors = (
  report: ProjectAuditHistoryEntry["full_report"] | null | undefined
): BattleCompetitorOption[] => {
  if (!report || typeof report !== "object") {
    return [];
  }

  const rawCompetitors = (report as Record<string, unknown>).competitors;
  if (!Array.isArray(rawCompetitors)) {
    return [];
  }

  return rawCompetitors.flatMap((entry, index) => {
    if (!entry || typeof entry !== "object") {
      return [];
    }

    const payload = entry as Record<string, unknown>;
    const name = typeof payload.name === "string" ? payload.name.trim() : "";
    if (!name) {
      return [];
    }

    const rank = toPositiveInteger(payload.rank);
    return [
      {
        key: `${rank ?? index}:${name.toLowerCase()}`,
        name,
        rank,
        overall: toNullableNumber(payload.score),
        geo: toNullableNumber(payload.geo_visibility),
        aeo: toNullableNumber(payload.aeo_score),
        entityStrength: toNullableNumber(payload.entity_strength),
      },
    ];
  });
};

function StepButton({
  stepNumber,
  title,
  summary,
  current,
  complete,
  locked,
  onClick,
}: {
  stepNumber: number;
  title: string;
  summary: string;
  current: boolean;
  complete: boolean;
  locked: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={locked}
      className={cx(
        "w-full rounded-xl border px-4 py-4 text-left transition duration-normal",
        current
          ? "border-primary/40 bg-primary/20"
          : "border-(--border) bg-(--surface) hover:border-(--border-hover) hover:bg-(--surface-elevated)",
        locked ? "cursor-not-allowed opacity-60" : "cursor-pointer"
      )}
      aria-current={current ? "step" : undefined}
    >
      <div className="flex items-start gap-3">
        <div
          className={cx(
            "mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-full border text-xs font-semibold",
            complete
              ? "border-emerald-400/30 bg-emerald-500/15 text-emerald-100"
              : current
                ? "border-primary/50 bg-primary/20 text-primary-foreground"
                : "border-(--border) bg-(--surface-subtle) text-(--muted-foreground)"
          )}
        >
          {complete ? <CheckCircle2 className="h-4 w-4" /> : stepNumber}
        </div>

        <div className="min-w-0 flex-1 space-y-0.5">
          <p className="truncate text-sm font-semibold text-(--foreground)">{title}</p>
          <p className="truncate text-xs leading-5 text-(--muted-foreground)">{summary}</p>
        </div>
      </div>
    </button>
  );
}

function SelectableCard({
  selected,
  onClick,
  title,
  description,
  badgeLabel,
  badgeColor = "default",
  children,
}: {
  selected: boolean;
  onClick: () => void;
  title: string;
  description: string;
  badgeLabel?: string;
  badgeColor?: BadgeTone;
  children?: React.ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={selected}
      className={cx(
        "w-full rounded-xl border p-4 text-left transition duration-normal",
        selected
          ? "border-primary/40 bg-primary/20"
          : "border-(--border) bg-(--surface) hover:border-(--border-hover) hover:bg-(--surface-elevated)"
      )}
    >
      <div className="flex items-start justify-between gap-4">
        <div className="space-y-1">
          <p className="text-base font-semibold text-(--foreground)">{title}</p>
          <p className="text-sm leading-6 text-(--muted-foreground)">{description}</p>
        </div>
        {badgeLabel ? (
          <Badge color={badgeColor} className="tracking-[0.14em]">
            {badgeLabel}
          </Badge>
        ) : null}
      </div>
      {children ? <div className="mt-4">{children}</div> : null}
    </button>
  );
}

function Notice({
  title,
  tone = "info",
  children,
}: {
  title: string;
  tone?: "info" | "warning" | "danger" | "success";
  children: React.ReactNode;
}) {
  const toneClasses =
    tone === "warning"
      ? "border-amber-400/20 bg-amber-500/10 text-amber-100"
      : tone === "danger"
        ? "border-rose-500/20 bg-rose-500/10 text-rose-100"
        : tone === "success"
          ? "border-emerald-400/20 bg-emerald-500/10 text-emerald-100"
          : "border-primary/20 bg-primary/10 text-(--text-soft)";

  return (
    <div className={cx("rounded-xl border px-4 py-3 text-sm leading-6", toneClasses)}>
      <p className="font-semibold text-(--foreground)">{title}</p>
      <div className="mt-1">{children}</div>
    </div>
  );
}

/**
 * The generate journey. The Report library (`/dashboard/reports`) is the
 * approved Reports screen and this is what its `Generate report` kind menu
 * opens, which is why `initialKind` exists: the kind is already chosen by the
 * time the customer arrives here, and re-asking for it would make the menu a
 * decoration. Generation stays an explicit action either way (decision of
 * 2 October: a PDF is produced on request and never automatically).
 */
export default function ReportsPageClient({ initialKind }: { initialKind?: ReportFlow } = {}) {
  const { getToken, isSignedIn, isLoading: authLoading, user } = useAuth();
  const { t } = useTranslation();

  const [projects, setProjects] = useState<WorkspaceProjectSummary[]>([]);
  const [audits, setAudits] = useState<ProjectAuditHistoryEntry[]>([]);
  const [trackedCompetitors, setTrackedCompetitors] = useState<ProjectCompetitorListItem[]>([]);

  const [selectedProjectId, setSelectedProjectId] = useState("");
  const [selectedAuditId, setSelectedAuditId] = useState("");
  const [selectedReportFlow, setSelectedReportFlow] = useState<ReportFlow>(
    initialKind ?? "standard"
  );
  const [currentStep, setCurrentStep] = useState<WizardStep>("project");

  const [agencyName, setAgencyName] = useState("");
  const [primaryColor, setPrimaryColor] = useState<string>(DEFAULT_REPORT_PRIMARY_COLOR);
  const [secondaryColor, setSecondaryColor] = useState<string>(DEFAULT_REPORT_SECONDARY_COLOR);
  const [footerText, setFooterText] = useState("");
  const [hasSavedAgencyLogo, setHasSavedAgencyLogo] = useState(false);
  const [reportLanguage, setReportLanguage] = useState("en");
  const [selectedBattleCompetitorKey, setSelectedBattleCompetitorKey] = useState("");
  const hideCreditCost = true;
  const [projectRangeMode, setProjectRangeMode] = useState<ProjectRangeMode>("all_time");
  const [projectDateFrom, setProjectDateFrom] = useState("");
  const [projectDateTo, setProjectDateTo] = useState("");
  const [competitorExportMode, setCompetitorExportMode] = useState<CompetitorExportMode>("latest");
  const [selectedTrackedCompetitorId, setSelectedTrackedCompetitorId] = useState("");

  const [loadingContext, setLoadingContext] = useState(true);
  const [loadingAudits, setLoadingAudits] = useState(false);
  const [loadingCompetitors, setLoadingCompetitors] = useState(false);
  const [contextError, setContextError] = useState<string | null>(null);
  const [actionStatus, setActionStatus] = useState("");
  const [actionError, setActionError] = useState<string | null>(null);
  const [runningAction, setRunningAction] = useState<ExportAction | null>(null);
  // Synchronous guard: runningAction is React state and does not disable the
  // generate buttons until the next render, so a fast double click would queue
  // two jobs without this.
  const actionInFlightRef = useRef(false);

  const [projectSearch, setProjectSearch] = useState("");
  const [projectPage, setProjectPage] = useState(0);
  const [auditSearch, setAuditSearch] = useState("");
  const [auditTypeFilter, setAuditTypeFilter] = useState("");
  const [auditPage, setAuditPage] = useState(0);

  const [sendByEmail, setSendByEmail] = useState(false);
  const [reportEmailAddress, setReportEmailAddress] = useState("");

  const getAuthHeaders = useCallback(async (): Promise<HeadersInit> => {
    const token = await getToken();
    if (!token) {
      throw new Error("Sign in required.");
    }
    return { Authorization: `Bearer ${token}`, ...workspaceHeaders() };
  }, [getToken]);

  const planCapabilities = useMemo(
    () => resolvePlanCapabilities(user?.subscription_plan),
    [user?.subscription_plan]
  );

  const canExportStandard = planCapabilities.has_pdf_audit_reports;
  const canExportBattle = planCapabilities.has_competitor_analysis;
  const canExportBranded = planCapabilities.has_advanced_reporting;
  const canExportWhiteLabel = planCapabilities.pdf_white_label;
  // SIGV2-1221: there is no `pdfExports` plan lock any more.
  // `MINIMUM_PLAN_BY_FEATURE["has_pdf_audit_reports"]` is `plan_starter`, so
  // every plan grants PDF audit exports and `canExportStandard` is only a
  // defensive guard. The lock it used to read named "Standard", which is a
  // plan a locked-out customer could not exist below - the same defect
  // SIGV2-1108 removed for live engine tracking. These fallbacks name no
  // plan at all, because there is no plan to upgrade to.
  const battleReportLock = getPlanLockContent("battleReports");
  const brandedReportLock = getPlanLockContent("brandedReports");

  useEffect(() => {
    if (user?.email && !reportEmailAddress) setReportEmailAddress(user.email);
  }, [user?.email]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    const loadContext = async () => {
      if (authLoading || !isSignedIn) {
        if (!authLoading) {
          setLoadingContext(false);
        }
        return;
      }

      setLoadingContext(true);
      setContextError(null);
      try {
        const headers = await getAuthHeaders();
        const [workspaceProjects, branding] = await Promise.all([
          fetchWorkspaceProjects(headers),
          fetchWhiteLabelBranding(headers).catch(() => null),
        ]);

        setProjects(workspaceProjects);
        if (workspaceProjects.length > 0) {
          setSelectedProjectId(String(workspaceProjects[0].id));
        }

        if (branding) {
          setAgencyName(branding.company_name ?? "");
          setPrimaryColor(normalizeHexColor(branding.primary_color, DEFAULT_REPORT_PRIMARY_COLOR));
          setSecondaryColor(
            normalizeHexColor(branding.secondary_color, DEFAULT_REPORT_SECONDARY_COLOR)
          );
          setHasSavedAgencyLogo(Boolean(branding.custom_logo_url?.trim()));
        }
      } catch (error) {
        setContextError(error instanceof Error ? error.message : "Unable to load report context.");
      } finally {
        setLoadingContext(false);
      }
    };

    void loadContext();
  }, [authLoading, getAuthHeaders, isSignedIn]);

  useEffect(() => {
    const loadAudits = async () => {
      const projectId = Number(selectedProjectId);
      if (!projectId || !isSignedIn) {
        setAudits([]);
        setSelectedAuditId("");
        setLoadingAudits(false);
        return;
      }

      setLoadingAudits(true);
      try {
        const headers = await getAuthHeaders();
        const projectAudits = await fetchProjectAudits(projectId, headers, {
          includeFullReport: true,
          limit: 25,
        });
        setAudits(projectAudits);
        setSelectedAuditId(projectAudits.length > 0 ? String(projectAudits[0].id) : "");
      } catch (error) {
        setAudits([]);
        setSelectedAuditId("");
        setActionError(error instanceof Error ? error.message : "Unable to load project audits.");
      } finally {
        setLoadingAudits(false);
      }
    };

    void loadAudits();
  }, [getAuthHeaders, isSignedIn, selectedProjectId]);

  useEffect(() => {
    const loadCompetitors = async () => {
      const projectId = Number(selectedProjectId);
      if (!projectId || !isSignedIn || !canExportBattle) {
        setTrackedCompetitors([]);
        setSelectedTrackedCompetitorId("");
        setLoadingCompetitors(false);
        return;
      }

      setLoadingCompetitors(true);
      try {
        const headers = await getAuthHeaders();
        const projectCompetitors = await fetchProjectCompetitors(projectId, headers);
        setTrackedCompetitors(projectCompetitors);
      } catch (error) {
        setTrackedCompetitors([]);
        setSelectedTrackedCompetitorId("");
        setActionError(
          error instanceof Error ? error.message : "Unable to load project competitors."
        );
      } finally {
        setLoadingCompetitors(false);
      }
    };

    void loadCompetitors();
  }, [canExportBattle, getAuthHeaders, isSignedIn, selectedProjectId]);

  const selectedProject = useMemo(
    () => projects.find((project) => String(project.id) === selectedProjectId) ?? null,
    [projects, selectedProjectId]
  );

  useEffect(() => {
    setReportLanguage(normalizeReportLanguage(selectedProject?.language));
  }, [selectedProject?.language]);

  const selectedAudit = useMemo(
    () => audits.find((audit) => String(audit.id) === selectedAuditId) ?? null,
    [audits, selectedAuditId]
  );

  useEffect(() => {
    if (!selectedProject && currentStep !== "project") {
      setCurrentStep("project");
      return;
    }
    if (!selectedAudit && (currentStep === "report" || currentStep === "configure")) {
      setCurrentStep("audit");
    }
  }, [currentStep, selectedAudit, selectedProject]);

  const selectedAuditSiteId = selectedAudit?.site_id ?? null;

  const PROJECTS_PER_PAGE = 9;
  const AUDITS_PER_PAGE = 8;

  const filteredProjects = useMemo(() => {
    const q = projectSearch.trim().toLowerCase();
    if (!q) return projects;
    return projects.filter(
      (p) => p.name.toLowerCase().includes(q) || (p.domain_url ?? "").toLowerCase().includes(q)
    );
  }, [projects, projectSearch]);

  const projectPageCount = Math.max(1, Math.ceil(filteredProjects.length / PROJECTS_PER_PAGE));
  const pagedProjects = useMemo(
    () =>
      filteredProjects.slice(
        projectPage * PROJECTS_PER_PAGE,
        (projectPage + 1) * PROJECTS_PER_PAGE
      ),
    [filteredProjects, projectPage]
  );

  const auditTypeOptions = useMemo(
    () => [...new Set(audits.map((a) => a.audit_type).filter(Boolean))],
    [audits]
  );

  const filteredAudits = useMemo(() => {
    return audits.filter((audit) => {
      if (auditTypeFilter && audit.audit_type !== auditTypeFilter) return false;
      const q = auditSearch.trim().toLowerCase();
      if (!q) return true;
      return (
        (audit.target_name ?? "").toLowerCase().includes(q) ||
        (audit.target_url ?? "").toLowerCase().includes(q) ||
        (audit.url ?? "").toLowerCase().includes(q) ||
        audit.audit_type.toLowerCase().includes(q)
      );
    });
  }, [audits, auditSearch, auditTypeFilter]);

  const auditPageCount = Math.max(1, Math.ceil(filteredAudits.length / AUDITS_PER_PAGE));
  const pagedAudits = useMemo(
    () => filteredAudits.slice(auditPage * AUDITS_PER_PAGE, (auditPage + 1) * AUDITS_PER_PAGE),
    [filteredAudits, auditPage]
  );

  const projectHistoryAudits = useMemo(
    () =>
      selectedAuditSiteId === null
        ? []
        : audits.filter((audit) => audit.site_id === selectedAuditSiteId),
    [audits, selectedAuditSiteId]
  );

  const projectHistoryCoverage = useMemo(() => {
    if (projectHistoryAudits.length === 0) {
      return null;
    }

    const dates = projectHistoryAudits
      .map((audit) => audit.created_at)
      .map((value) => new Date(value))
      .filter((value) => !Number.isNaN(value.getTime()));
    if (dates.length === 0) {
      return null;
    }

    const timestamps = dates.map((value) => value.getTime());
    return {
      auditCount: projectHistoryAudits.length,
      oldestDate: new Date(Math.min(...timestamps)).toISOString(),
      newestDate: new Date(Math.max(...timestamps)).toISOString(),
    };
  }, [projectHistoryAudits]);

  const selectedAuditIntegrity = useMemo(() => {
    const report = selectedAudit?.full_report;
    if (!report || typeof report !== "object") {
      return null;
    }
    return getIntegrityStatusSnapshot(report as Record<string, unknown>);
  }, [selectedAudit?.full_report]);

  const battleCompetitors = useMemo(
    () => extractBattleCompetitors(selectedAudit?.full_report),
    [selectedAudit?.full_report]
  );

  useEffect(() => {
    if (battleCompetitors.length === 0) {
      setSelectedBattleCompetitorKey("");
      return;
    }

    setSelectedBattleCompetitorKey((current) =>
      battleCompetitors.some((competitor) => competitor.key === current)
        ? current
        : battleCompetitors[0].key
    );
  }, [battleCompetitors]);

  const selectedBattleCompetitor = useMemo(
    () =>
      battleCompetitors.find((competitor) => competitor.key === selectedBattleCompetitorKey) ??
      null,
    [battleCompetitors, selectedBattleCompetitorKey]
  );

  const trackedCompetitorsWithTrendData = useMemo(
    () => trackedCompetitors.filter((competitor) => competitor.competitor_site_id !== null),
    [trackedCompetitors]
  );

  useEffect(() => {
    if (trackedCompetitorsWithTrendData.length === 0) {
      setSelectedTrackedCompetitorId("");
      return;
    }

    setSelectedTrackedCompetitorId((current) =>
      trackedCompetitorsWithTrendData.some((competitor) => String(competitor.id) === current)
        ? current
        : String(trackedCompetitorsWithTrendData[0].id)
    );
  }, [trackedCompetitorsWithTrendData]);

  const selectedTrackedCompetitor = useMemo(
    () =>
      trackedCompetitorsWithTrendData.find(
        (competitor) => String(competitor.id) === selectedTrackedCompetitorId
      ) ?? null,
    [selectedTrackedCompetitorId, trackedCompetitorsWithTrendData]
  );

  useEffect(() => {
    if (projectRangeMode !== "custom" || !projectHistoryCoverage) {
      return;
    }

    setProjectDateFrom((current) => current || toDateInputValue(projectHistoryCoverage.oldestDate));
    setProjectDateTo((current) => current || toDateInputValue(projectHistoryCoverage.newestDate));
  }, [projectHistoryCoverage, projectRangeMode]);

  const isCjkLanguage = reportLanguage === "ja" || reportLanguage === "zh";

  const buildFileName = useCallback(
    (variant: ExportAction) => {
      const projectSegment = sanitizeFileSegment(selectedProject?.name || "project");
      const auditSegment = sanitizeFileSegment(selectedAudit?.audit_type || "audit");
      const languageSegment = sanitizeFileSegment(reportLanguage);
      const variantSegment =
        variant === "executiveWhitelabel"
          ? "executive-white-label"
          : variant === "executiveBranded"
            ? "executive-branded"
            : variant === "executivePlatform"
              ? "executive-platform"
              : variant === "project"
                ? "project"
                : variant === "competitorsTrend"
                  ? `competitors-trend-${sanitizeFileSegment(
                      selectedTrackedCompetitor?.display_name || "competitor"
                    )}`
                  : variant === "competitorsLatest"
                    ? `competitors-latest-${sanitizeFileSegment(
                        selectedBattleCompetitor?.name || "competitor"
                      )}`
                    : variant === "financial"
                      ? "financial"
                      : variant === "aio" || variant === "seo"
                        ? variant
                        : "standard";
      return `${projectSegment}-${auditSegment}-${variantSegment}-${languageSegment}.pdf`;
    },
    [
      reportLanguage,
      selectedAudit?.audit_type,
      selectedBattleCompetitor?.name,
      selectedTrackedCompetitor?.display_name,
      selectedProject?.name,
    ]
  );

  const waitForReportDownload = useCallback(
    async (reportId: string, headers: HeadersInit, filename: string, pendingMessage: string) => {
      const userId = user?.id;
      if (userId) {
        persistReportJob(userId, { reportId });
      }
      const finishJob = () => {
        if (userId) {
          clearStoredReportJob(userId);
        }
      };
      try {
        for (let attempt = 0; attempt < REPORT_MAX_POLL_ATTEMPTS; attempt += 1) {
          if (attempt > 0) {
            await sleep(REPORT_POLL_DELAY_MS);
          }

          const status = await fetchComplexReportStatus(reportId, headers);
          if (status.status === "succeeded") {
            setActionStatus("Downloading PDF...");
            const downloadPayload = await downloadComplexReportPdfBlob(reportId, headers);
            triggerPdfDownload(downloadPayload.blob, downloadPayload.filename?.trim() || filename);
            finishJob();
            return;
          }
          if (status.status === "failed") {
            finishJob();
            throw new Error(status.error || "Report generation failed.");
          }
          if (status.status === "expired") {
            finishJob();
            throw new Error(
              `Report expired and was removed after ${status.retention_days ?? 30} days.`
            );
          }

          setActionStatus(`${pendingMessage} (${attempt + 1}/${REPORT_MAX_POLL_ATTEMPTS})`);
        }

        finishJob();
        throw new Error("Report generation timed out. Please try again.");
      } catch (error) {
        finishJob();
        throw error;
      }
    },
    [user?.id]
  );

  const runExclusive = useCallback(async (fn: () => Promise<void>) => {
    if (actionInFlightRef.current) {
      return;
    }
    actionInFlightRef.current = true;
    try {
      await fn();
    } finally {
      actionInFlightRef.current = false;
    }
  }, []);

  const resumeAttemptedRef = useRef(false);
  useEffect(() => {
    if (resumeAttemptedRef.current || authLoading || !isSignedIn || !user?.id) {
      return;
    }
    resumeAttemptedRef.current = true;

    const storedJob = readStoredReportJob(user.id);
    if (!storedJob) {
      return;
    }

    actionInFlightRef.current = true;
    setRunningAction("standard");
    setActionStatus(t("signalReports.resumingStatus"));
    void (async () => {
      try {
        const headers = await getAuthHeaders();
        await waitForReportDownload(
          storedJob.reportId,
          headers,
          "signal-report.pdf",
          t("signalReports.resumingStatus")
        );
        setActionStatus(t("signalReports.resumedStatus"));
      } catch (error) {
        setActionError(error instanceof Error ? error.message : "Report generation failed.");
        setActionStatus("");
      } finally {
        actionInFlightRef.current = false;
        setRunningAction(null);
      }
    })();
  }, [authLoading, getAuthHeaders, isSignedIn, t, user?.id, waitForReportDownload]);

  const runStandardExport = useCallback(
    async (kind: "standard" | "aio" | "seo") => {
      if (!canExportStandard) {
        setActionError("PDF exports are not available on your current plan.");
        return;
      }
      if (!selectedAudit) {
        setActionError("Select an audit before generating a report.");
        return;
      }

      setActionError(null);
      const reportLabel = kind === "standard" ? "Standard" : kind.toUpperCase();
      setRunningAction(kind);
      setActionStatus(`Queueing ${getReportLanguageLabel(reportLanguage)} PDF...`);
      try {
        const headers = await getAuthHeaders();
        const queuedReport = await generateComplexReportPdf(
          {
            audit_ids: [selectedAudit.id],
            project_id: selectedProject?.id,
            template_type: "Executive",
            report_options: {
              mode: "individual",
              sections: ["overview", "geo", "seo", "aeo"],
              report_type: "standard",
              report_kind: kind,
              branding_mode: "platform",
              hide_credit_cost: hideCreditCost,
              language: reportLanguage,
            },
          },
          headers
        );

        await waitForReportDownload(
          queuedReport.report_id,
          headers,
          buildFileName(kind),
          `Generating ${getReportLanguageLabel(reportLanguage)} report`
        );
        setActionStatus(
          `${reportLabel} PDF generated in ${getReportLanguageLabel(reportLanguage)}.`
        );
      } catch (error) {
        setActionError(
          error instanceof Error ? error.message : `${reportLabel} PDF export failed.`
        );
        setActionStatus("");
      } finally {
        setRunningAction(null);
      }
    },
    [
      buildFileName,
      canExportStandard,
      getAuthHeaders,
      hideCreditCost,
      reportLanguage,
      selectedAudit,
      selectedProject?.id,
      waitForReportDownload,
    ]
  );

  const runProjectExport = useCallback(async () => {
    if (!canExportStandard) {
      setActionError("Project PDF exports follow your PDF audit export access.");
      return;
    }
    if (!selectedAudit) {
      setActionError("Select an audit before generating a project progress report.");
      return;
    }
    if (selectedAuditSiteId === null) {
      setActionError(
        "Project progress exports need a site-linked audit. Select a website audit with historical runs."
      );
      return;
    }
    if (projectRangeMode === "custom") {
      if (!projectDateFrom || !projectDateTo) {
        setActionError("Select both a start date and an end date for the custom project range.");
        return;
      }
      if (projectDateFrom > projectDateTo) {
        setActionError("Start date must be earlier than or equal to the end date.");
        return;
      }
    }

    setActionError(null);
    setRunningAction("project");
    setActionStatus(`Queueing project progress ${getReportLanguageLabel(reportLanguage)} PDF...`);
    try {
      const headers = await getAuthHeaders();
      const queuedReport = await generateComplexReportPdf(
        {
          audit_ids: [selectedAudit.id],
          site_id: selectedAuditSiteId,
          date_from:
            projectRangeMode === "custom"
              ? toDateRangeBoundaryIso(projectDateFrom, "start")
              : undefined,
          date_to:
            projectRangeMode === "custom"
              ? toDateRangeBoundaryIso(projectDateTo, "end")
              : undefined,
          template_type: "Executive",
          report_options: {
            mode: "aggregated",
            sections: ["overview", "geo", "seo", "aeo"],
            report_type: "standard",
            report_kind: "project",
            branding_mode: "platform",
            hide_credit_cost: hideCreditCost,
            language: reportLanguage,
          },
        },
        headers
      );

      await waitForReportDownload(
        queuedReport.report_id,
        headers,
        buildFileName("project"),
        `Generating project progress report in ${getReportLanguageLabel(reportLanguage)}`
      );
      setActionStatus(
        `Project progress PDF generated in ${getReportLanguageLabel(reportLanguage)}.`
      );
    } catch (error) {
      setActionError(error instanceof Error ? error.message : "Project PDF export failed.");
      setActionStatus("");
    } finally {
      setRunningAction(null);
    }
  }, [
    buildFileName,
    canExportStandard,
    getAuthHeaders,
    hideCreditCost,
    projectDateFrom,
    projectDateTo,
    projectRangeMode,
    reportLanguage,
    selectedAudit,
    selectedAuditSiteId,
    waitForReportDownload,
  ]);

  const runBattleExport = useCallback(async () => {
    if (!canExportBattle) {
      setActionError("Competitor reports require competitor analysis on your current plan.");
      return;
    }
    if (!selectedAudit) {
      setActionError("Select an audit before generating a competitors report.");
      return;
    }
    if (!selectedBattleCompetitor) {
      setActionError("Select a competitor before generating a competitors report.");
      return;
    }

    setActionError(null);
    setRunningAction("competitorsLatest");
    setActionStatus(`Queueing latest competitors ${getReportLanguageLabel(reportLanguage)} PDF...`);
    try {
      const headers = await getAuthHeaders();
      const queuedReport = await generateComplexReportPdf(
        {
          audit_ids: [selectedAudit.id],
          project_id: selectedProject?.id,
          template_type: "Comparative",
          report_options: {
            mode: "individual",
            sections: ["overview", "geo", "seo", "aeo"],
            report_type: "battle",
            report_kind: "competitors",
            branding_mode: "platform",
            competitor_mode: "latest",
            hide_credit_cost: hideCreditCost,
            language: reportLanguage,
            comparison_competitor_name: selectedBattleCompetitor.name,
            comparison_competitor_rank:
              typeof selectedBattleCompetitor.rank === "number" && selectedBattleCompetitor.rank > 0
                ? selectedBattleCompetitor.rank
                : undefined,
          },
        },
        headers
      );

      await waitForReportDownload(
        queuedReport.report_id,
        headers,
        buildFileName("competitorsLatest"),
        `Generating competitors report for ${selectedBattleCompetitor.name}`
      );
      setActionStatus(`Competitors PDF generated in ${getReportLanguageLabel(reportLanguage)}.`);
    } catch (error) {
      setActionError(error instanceof Error ? error.message : "Competitors PDF export failed.");
      setActionStatus("");
    } finally {
      setRunningAction(null);
    }
  }, [
    buildFileName,
    canExportBattle,
    getAuthHeaders,
    hideCreditCost,
    reportLanguage,
    selectedAudit,
    selectedBattleCompetitor,
    selectedProject?.id,
    waitForReportDownload,
  ]);

  const runCompetitorTrendExport = useCallback(async () => {
    if (!canExportBattle) {
      setActionError("Competitive trend exports require competitor analysis on your current plan.");
      return;
    }
    if (!selectedAudit) {
      setActionError("Select an audit before generating a competitor trend report.");
      return;
    }
    if (selectedAuditSiteId === null) {
      setActionError("Select a site-linked audit before generating a competitor trend report.");
      return;
    }
    if (!selectedTrackedCompetitor || selectedTrackedCompetitor.competitor_site_id === null) {
      setActionError(
        "Select a tracked competitor with benchmark history before generating an all-time trend report."
      );
      return;
    }

    setActionError(null);
    setRunningAction("competitorsTrend");
    setActionStatus(
      `Queueing all-time competitor trend ${getReportLanguageLabel(reportLanguage)} PDF...`
    );
    try {
      const headers = await getAuthHeaders();
      const queuedReport = await generateComplexReportPdf(
        {
          audit_ids: [selectedAudit.id],
          site_id: selectedAuditSiteId,
          template_type: "Comparative",
          report_options: {
            mode: "aggregated",
            sections: ["overview", "geo", "seo", "aeo"],
            report_type: "battle",
            report_kind: "competitors",
            branding_mode: "platform",
            competitor_mode: "trend",
            competitors: [selectedTrackedCompetitor.competitor_site_id],
            comparison_competitor_name: selectedTrackedCompetitor.display_name,
            hide_credit_cost: hideCreditCost,
            language: reportLanguage,
          },
        },
        headers
      );

      await waitForReportDownload(
        queuedReport.report_id,
        headers,
        buildFileName("competitorsTrend"),
        `Generating all-time trend report for ${selectedTrackedCompetitor.display_name}`
      );
      setActionStatus(
        `Competitive trend PDF generated in ${getReportLanguageLabel(reportLanguage)}.`
      );
    } catch (error) {
      setActionError(
        error instanceof Error ? error.message : "Competitive trend PDF export failed."
      );
      setActionStatus("");
    } finally {
      setRunningAction(null);
    }
  }, [
    buildFileName,
    canExportBattle,
    getAuthHeaders,
    hideCreditCost,
    reportLanguage,
    selectedAudit,
    selectedAuditSiteId,
    selectedTrackedCompetitor,
    waitForReportDownload,
  ]);

  const runExecutiveExport = useCallback(
    async (variant: "platform" | "branded" | "whitelabel") => {
      if (variant === "platform" && !canExportStandard) {
        setActionError("Platform executive exports follow your PDF audit export access.");
        return;
      }
      if (variant === "branded" && !canExportBranded) {
        setActionError("Branded executive PDFs require advanced reporting on your current plan.");
        return;
      }
      if (variant === "whitelabel" && !canExportWhiteLabel) {
        setActionError(
          "White-label executive PDFs require PDF white-label access on your current plan."
        );
        return;
      }
      if (!selectedAudit) {
        setActionError(
          variant === "platform"
            ? "Select an audit before generating an executive report."
            : variant === "branded"
              ? "Select an audit before generating an agency-branded executive report."
              : "Select an audit before generating a white-label executive report."
        );
        return;
      }

      const reportLabel =
        variant === "platform"
          ? "platform executive"
          : variant === "branded"
            ? "agency-branded executive"
            : "white-label executive";
      const statusLabel =
        variant === "platform"
          ? "Platform executive"
          : variant === "branded"
            ? "Agency-branded executive"
            : "White-label executive";
      const runningVariant =
        variant === "platform"
          ? "executivePlatform"
          : variant === "branded"
            ? "executiveBranded"
            : "executiveWhitelabel";

      setActionError(null);
      setRunningAction(runningVariant);
      setActionStatus(`Queueing ${reportLabel} ${getReportLanguageLabel(reportLanguage)} PDF...`);
      try {
        const headers = await getAuthHeaders();
        const queuedReport = await generateWhiteLabelReportPdf(
          {
            audit_id: selectedAudit.id,
            agency_name: variant === "platform" ? undefined : agencyName.trim() || undefined,
            title:
              variant === "platform"
                ? "AI Visibility Diagnostic Blueprint"
                : agencyName.trim()
                  ? `${agencyName.trim()} AI Visibility Diagnostic Blueprint`
                  : "AI Visibility Diagnostic Blueprint",
            report_type:
              variant === "platform"
                ? "standard"
                : variant === "branded"
                  ? "branded"
                  : "whitelabel",
            report_kind: "executive",
            branding_mode: variant === "whitelabel" ? "white_label" : "platform",
            hide_credit_cost: hideCreditCost,
            footer_text: variant === "whitelabel" ? footerText.trim() || undefined : undefined,
            primary_color: variant === "platform" ? undefined : primaryColor.trim(),
            secondary_color: variant === "platform" ? undefined : secondaryColor.trim(),
            language: reportLanguage,
            include_competitor_analysis: false,
          },
          headers
        );

        await waitForReportDownload(
          queuedReport.report_id,
          headers,
          buildFileName(runningVariant),
          `Generating ${reportLabel} ${getReportLanguageLabel(reportLanguage)} report`
        );
        setActionStatus(
          `${statusLabel} PDF generated in ${getReportLanguageLabel(reportLanguage)}.`
        );
      } catch (error) {
        setActionError(
          error instanceof Error ? error.message : `${statusLabel} PDF export failed.`
        );
        setActionStatus("");
      } finally {
        setRunningAction(null);
      }
    },
    [
      agencyName,
      buildFileName,
      canExportBranded,
      canExportStandard,
      canExportWhiteLabel,
      footerText,
      getAuthHeaders,
      hideCreditCost,
      primaryColor,
      reportLanguage,
      secondaryColor,
      selectedAudit,
      waitForReportDownload,
    ]
  );

  const runFinancialExport = useCallback(async () => {
    if (!canExportStandard) {
      setActionError("Financial report exports follow your PDF audit export access.");
      return;
    }
    if (!selectedAudit) {
      setActionError("Select an audit before generating a financial report.");
      return;
    }
    if (!selectedAudit.project_id) {
      setActionError("Financial reports require a project-backed audit.");
      return;
    }

    setActionError(null);
    setRunningAction("financial");
    setActionStatus(`Queueing financial ${getReportLanguageLabel(reportLanguage)} PDF...`);
    try {
      const headers = await getAuthHeaders();
      const queuedReport = await generateComplexReportPdf(
        {
          audit_ids: [selectedAudit.id],
          project_id: selectedAudit.project_id,
          template_type: "Executive",
          report_options: {
            mode: "individual",
            sections: ["overview", "geo", "seo", "aeo"],
            report_type: "standard",
            report_kind: "financial",
            branding_mode: "platform",
            hide_credit_cost: hideCreditCost,
            language: reportLanguage,
          },
        },
        headers
      );

      await waitForReportDownload(
        queuedReport.report_id,
        headers,
        buildFileName("financial"),
        `Generating financial report in ${getReportLanguageLabel(reportLanguage)}`
      );
      setActionStatus(`Financial PDF generated in ${getReportLanguageLabel(reportLanguage)}.`);
    } catch (error) {
      setActionError(error instanceof Error ? error.message : "Financial PDF export failed.");
      setActionStatus("");
    } finally {
      setRunningAction(null);
    }
  }, [
    buildFileName,
    canExportStandard,
    getAuthHeaders,
    hideCreditCost,
    reportLanguage,
    selectedAudit,
    waitForReportDownload,
  ]);

  const selectedAuditTimestamp = selectedAudit
    ? formatDateTime(selectedAudit.created_at)
    : "No audit selected";
  const projectHistorySummary = projectHistoryCoverage
    ? `${projectHistoryCoverage.auditCount} audit${
        projectHistoryCoverage.auditCount === 1 ? "" : "s"
      } from ${formatDateTime(projectHistoryCoverage.oldestDate)} to ${formatDateTime(projectHistoryCoverage.newestDate)}`
    : selectedAuditSiteId !== null
      ? "Only the current site-linked audit is available for aggregation."
      : "Select a website audit with a linked site history to unlock project progress exports.";
  const previewAgencyName = agencyName.trim() || "Your agency name";
  const previewFooterCopy =
    footerText.trim() ||
    (canExportWhiteLabel
      ? "Optional agency footer text will appear here on white-label executive exports."
      : "Agency executive exports retain the Powered by Qiko Signal footer.");

  const reportChoices = useMemo(
    () => [
      {
        key: "standard" as const,
        title: "Standard PDF",
        description: "Single-audit technical export with the full core score breakdown.",
        helper: "Best for detailed stakeholders and internal review.",
        icon: FileText,
        available: canExportStandard,
        availabilityLabel: canExportStandard ? "Included" : "Upgrade",
        availabilityColor: canExportStandard ? ("success" as const) : ("warning" as const),
      },
      {
        key: "aio" as const,
        title: "AIO PDF",
        description: "Single-audit report focused on visibility in AI answers.",
        helper: "Use this to review your AIO score and AI answer findings.",
        icon: FileText,
        available: canExportStandard,
        availabilityLabel: canExportStandard ? "Included" : "Upgrade",
        availabilityColor: canExportStandard ? ("success" as const) : ("warning" as const),
      },
      {
        key: "seo" as const,
        title: "SEO PDF",
        description: "Single-audit report focused on traditional search visibility.",
        helper: "Use this to review your SEO score and search findings.",
        icon: FileText,
        available: canExportStandard,
        availabilityLabel: canExportStandard ? "Included" : "Upgrade",
        availabilityColor: canExportStandard ? ("success" as const) : ("warning" as const),
      },
      {
        key: "project" as const,
        title: "Project Progress PDF",
        description: "Rolls one site-linked audit history into a timeline report.",
        helper: "Use this for month-over-month or campaign progress updates.",
        icon: BarChart3,
        available: canExportStandard,
        availabilityLabel: canExportStandard ? "Included" : "Upgrade",
        availabilityColor: canExportStandard ? ("success" as const) : ("warning" as const),
      },
      {
        key: "competitors" as const,
        title: "Competitors PDF",
        description: "Compares the selected audit against latest or tracked benchmarks.",
        helper: "Use latest snapshot or all-time competitor trend mode.",
        icon: ClipboardList,
        available: canExportBattle,
        availabilityLabel: canExportBattle ? "Included" : "Upgrade",
        availabilityColor: canExportBattle ? ("success" as const) : ("warning" as const),
      },
      {
        key: "executive" as const,
        title: "Executive PDF",
        description: "Creates presentation-ready platform and agency variants.",
        helper: "Platform is tied to PDF access. Branded variants depend on plan tier.",
        icon: Palette,
        available: canExportStandard,
        availabilityLabel: canExportStandard ? "Included" : "Upgrade",
        availabilityColor: canExportStandard ? ("success" as const) : ("warning" as const),
      },
      {
        key: "financial" as const,
        title: "Financial PDF",
        description: "Summarizes project scan usage and audit activity context.",
        helper: "Use this for internal budget reviews and reconciliations.",
        icon: Wallet,
        available: canExportStandard,
        availabilityLabel: canExportStandard ? "Included" : "Upgrade",
        availabilityColor: canExportStandard ? ("success" as const) : ("warning" as const),
      },
    ],
    [canExportBattle, canExportStandard]
  );

  const selectedReportChoice =
    reportChoices.find((choice) => choice.key === selectedReportFlow) ?? reportChoices[0];

  const isProjectStepComplete = Boolean(selectedProject);
  const isAuditStepUnlocked = Boolean(selectedProject);
  const isAuditStepComplete = Boolean(selectedProject && selectedAudit);
  const isReportStepUnlocked = isAuditStepComplete;
  const isReportStepComplete = Boolean(selectedReportChoice && selectedAudit);
  const isConfigureStepUnlocked = isReportStepComplete;

  const goToStep = useCallback(
    (step: WizardStep) => {
      if (step === "project") {
        setCurrentStep(step);
        return;
      }
      if (step === "audit" && isAuditStepUnlocked) {
        setCurrentStep(step);
        return;
      }
      if (step === "report" && isReportStepUnlocked) {
        setCurrentStep(step);
        return;
      }
      if (step === "configure" && isConfigureStepUnlocked) {
        setCurrentStep(step);
      }
    },
    [isAuditStepUnlocked, isConfigureStepUnlocked, isReportStepUnlocked]
  );

  const wizardSteps = [
    {
      key: "project" as const,
      title: "Project",
      summary: selectedProject?.name || "No project selected",
      complete: isProjectStepComplete,
      locked: false,
    },
    {
      key: "audit" as const,
      title: "Audit",
      summary: selectedAudit
        ? `${selectedAudit.audit_type} · ${selectedAuditTimestamp}`
        : "No audit selected",
      complete: isAuditStepComplete,
      locked: !isAuditStepUnlocked,
    },
    {
      key: "report" as const,
      title: "Report type",
      summary: selectedReportChoice.title,
      complete: isReportStepComplete,
      locked: !isReportStepUnlocked,
    },
    {
      key: "configure" as const,
      title: "Configure & export",
      summary: selectedAudit ? selectedReportChoice.title : "Select a report first",
      complete: false,
      locked: !isConfigureStepUnlocked,
    },
  ];

  const renderConfigurePanel = () => {
    if (
      selectedReportFlow === "standard" ||
      selectedReportFlow === "aio" ||
      selectedReportFlow === "seo"
    ) {
      return null;
    }

    if (selectedReportFlow === "project") {
      if (!canExportStandard) return null;
      return (
        <div className="space-y-4">
          <SelectField
            label="Coverage"
            value={projectRangeMode}
            onChange={(event) => setProjectRangeMode(event.target.value as ProjectRangeMode)}
            className="h-9 rounded border-(--border) text-sm"
          >
            <option value="all_time">All audit history</option>
            <option value="custom">Custom date range</option>
          </SelectField>

          {projectRangeMode === "custom" ? (
            <div className="grid gap-3 sm:grid-cols-2">
              <TextField
                type="date"
                label="Start date"
                value={projectDateFrom}
                onChange={(event) => setProjectDateFrom(event.target.value)}
                className="h-9 rounded border-(--border) text-sm"
              />
              <TextField
                type="date"
                label="End date"
                value={projectDateTo}
                onChange={(event) => setProjectDateTo(event.target.value)}
                className="h-9 rounded border-(--border) text-sm"
              />
            </div>
          ) : null}

          <Notice title="History coverage">{projectHistorySummary}</Notice>

          {selectedAuditSiteId === null ? (
            <Notice title="Site-linked audit required" tone="warning">
              Brand-only audits cannot drive an aggregated history export.
            </Notice>
          ) : null}
        </div>
      );
    }

    if (selectedReportFlow === "competitors") {
      if (!canExportBattle) return null;
      return (
        <div className="space-y-4">
          <SelectField
            label="Mode"
            value={competitorExportMode}
            onChange={(event) =>
              setCompetitorExportMode(event.target.value as CompetitorExportMode)
            }
            className="h-9 rounded border-(--border) text-sm"
          >
            <option value="latest">Latest Snapshot</option>
            <option value="trend">Tracked Trend</option>
          </SelectField>

          {competitorExportMode === "latest" ? (
            battleCompetitors.length > 0 ? (
              <SelectField
                label="Competitor"
                value={selectedBattleCompetitorKey}
                onChange={(event) => setSelectedBattleCompetitorKey(event.target.value)}
                className="h-9 rounded border-(--border) text-sm"
              >
                {battleCompetitors.map((competitor) => (
                  <option key={competitor.key} value={competitor.key}>
                    {competitor.name}
                    {competitor.rank ? ` / Rank ${competitor.rank}` : ""}
                  </option>
                ))}
              </SelectField>
            ) : (
              <Notice title="No benchmark on this audit" tone="warning">
                Latest competitor exports require a canonical benchmark in the selected audit.
              </Notice>
            )
          ) : loadingCompetitors ? (
            <div className="flex items-center gap-3 rounded border-0 px-4 py-3 text-sm text-(--text-soft)">
              <Loader2 className="h-4 w-4 animate-spin" />
              Loading tracked competitors...
            </div>
          ) : trackedCompetitorsWithTrendData.length > 0 ? (
            <div className="space-y-3">
              <SelectField
                label="Tracked Competitor"
                value={selectedTrackedCompetitorId}
                onChange={(event) => setSelectedTrackedCompetitorId(event.target.value)}
                className="h-9 rounded border-(--border) text-sm"
              >
                {trackedCompetitorsWithTrendData.map((competitor) => (
                  <option key={competitor.id} value={String(competitor.id)}>
                    {competitor.display_name}
                  </option>
                ))}
              </SelectField>
              <p className="text-xs text-(--text-muted)">
                Last benchmark:{" "}
                {selectedTrackedCompetitor?.last_benchmarked_at
                  ? formatDateTime(selectedTrackedCompetitor.last_benchmarked_at)
                  : "No successful benchmark yet"}
              </p>
            </div>
          ) : (
            <Notice title="Tracked history not available" tone="warning">
              Tracked trend exports require site-linked competitor benchmark history.
            </Notice>
          )}
        </div>
      );
    }

    if (selectedReportFlow === "executive") {
      return (
        <div className="space-y-5">
          <div className="relative overflow-hidden rounded border-0 bg-(--surface) p-4">
            <div className="relative space-y-4">
              <div className="flex items-start justify-between gap-4">
                <div>
                  <p className={CARD_LABEL_CLASS}>Live preview</p>
                  <p className="mt-2 text-lg font-semibold text-(--foreground)">
                    {previewAgencyName}
                  </p>
                  <p className="text-sm text-(--text-soft)">AI Visibility Diagnostic Blueprint</p>
                </div>
                <div className="flex gap-2">
                  <span
                    className="h-4 w-4 rounded-full border-0 bg-(--c)"
                    style={{ "--c": primaryColor } as React.CSSProperties}
                    aria-hidden="true"
                  />
                  <span
                    className="h-4 w-4 rounded-full border-0 bg-(--c)"
                    style={{ "--c": secondaryColor } as React.CSSProperties}
                    aria-hidden="true"
                  />
                </div>
              </div>
              <div className="rounded-[14px] border-0 bg-[#EEF1F6] px-4 py-3 text-sm leading-6 text-(--text-soft)">
                {previewFooterCopy}
              </div>
            </div>
          </div>

          <TextField
            id="agency-report-name"
            label="Agency Name"
            value={agencyName}
            onChange={(event) => setAgencyName(event.target.value)}
            className="h-9 rounded border-(--border) text-sm"
          />

          <div className="grid gap-3 md:grid-cols-2">
            <ColorPickerField
              label="Primary Color"
              value={primaryColor}
              onChange={setPrimaryColor}
              presets={REPORT_PRIMARY_PRESETS}
              className="h-full"
            />
            <ColorPickerField
              label="Secondary Color"
              value={secondaryColor}
              onChange={setSecondaryColor}
              presets={REPORT_SECONDARY_PRESETS}
              className="h-full"
            />
          </div>

          <TextField
            id="agency-report-footer"
            label="Custom Footer"
            value={footerText}
            onChange={(event) => setFooterText(event.target.value)}
            placeholder="Optional footer text for agency executive exports"
            className="h-9 rounded border-(--border) text-sm"
          />

          {hasSavedAgencyLogo ? (
            <Notice title="Workspace logo found" tone="success">
              A saved workspace logo is available and will be used in executive branding variants.
            </Notice>
          ) : (
            <Notice title="No saved logo detected">
              Executive exports will fall back to text branding when needed.
            </Notice>
          )}

          <div className="grid gap-4 lg:grid-cols-3">
            <div className="rounded-[22px] border-0 bg-white p-5 shadow-xs">
              <div className="space-y-2">
                <p className="text-xs font-semibold uppercase tracking-[0.16em] text-(--foreground)">
                  Platform Executive
                </p>
                <p className="text-sm leading-6 text-(--muted-foreground)">
                  Uses the shared Qiko Signal shell for the executive diagnostic blueprint.
                </p>
              </div>
              <div className="mt-4">
                {canExportStandard ? (
                  <Button
                    variant="outline"
                    onClick={() => void runExclusive(() => runExecutiveExport("platform"))}
                    loading={runningAction === "executivePlatform"}
                    disabled={!selectedAudit || runningAction !== null}
                    className="w-full"
                  >
                    Generate Platform Executive PDF
                  </Button>
                ) : (
                  <LockedFeatureButton
                    buttonLabel="Generate Platform Executive PDF"
                    helperText={"Your current plan does not include PDF audit exports."}
                  />
                )}
              </div>
            </div>

            <div className="rounded-[22px] border-0 bg-white p-5 shadow-xs">
              <div className="space-y-2">
                <p className="text-xs font-semibold uppercase tracking-[0.16em] text-(--foreground)">
                  Agency Executive
                </p>
                <p className="text-sm leading-6 text-(--muted-foreground)">
                  Adds your agency identity while keeping a Powered by Qiko Signal footer.
                </p>
              </div>
              <div className="mt-4">
                {canExportBranded ? (
                  <Button
                    variant="inverse"
                    onClick={() => void runExclusive(() => runExecutiveExport("branded"))}
                    loading={runningAction === "executiveBranded"}
                    disabled={!selectedAudit || runningAction !== null}
                    className="w-full"
                  >
                    Generate Agency Executive PDF
                  </Button>
                ) : (
                  <LockedFeatureButton
                    buttonLabel="Generate Agency Executive PDF"
                    helperText={
                      brandedReportLock.helperText ??
                      "Agency executive PDFs unlock with advanced reporting."
                    }
                  />
                )}
              </div>
            </div>
          </div>
        </div>
      );
    }

    // financial (default)
    if (!selectedAudit?.project_id && canExportStandard) {
      return (
        <Notice title="Project-backed audit required" tone="warning">
          Financial reports require a project-backed audit.
        </Notice>
      );
    }
    return null;
  };

  const renderFooterGenerate = () => {
    const accentCls = "bg-(--accent) text-black border-(--accent) hover:opacity-90";

    if (selectedReportFlow === "executive") return null;

    if (
      selectedReportFlow === "standard" ||
      selectedReportFlow === "aio" ||
      selectedReportFlow === "seo"
    ) {
      const kind = selectedReportFlow;
      const label = kind === "standard" ? "Standard" : kind.toUpperCase();
      return canExportStandard ? (
        <Button
          variant="primary"
          className={accentCls}
          onClick={() => void runExclusive(() => runStandardExport(kind))}
          loading={runningAction === kind}
          disabled={!selectedAudit || runningAction !== null}
        >
          Generate {label} PDF
        </Button>
      ) : (
        <LockedFeatureButton
          buttonLabel={`Generate ${label} PDF`}
          helperText={"Your current plan does not include PDF audit exports."}
          buttonVariant="primary"
        />
      );
    }

    if (selectedReportFlow === "project") {
      return canExportStandard ? (
        <Button
          variant="primary"
          className={accentCls}
          onClick={() => void runExclusive(runProjectExport)}
          loading={runningAction === "project"}
          disabled={
            !selectedAudit ||
            selectedAuditSiteId === null ||
            runningAction !== null ||
            (projectRangeMode === "custom" && (!projectDateFrom || !projectDateTo))
          }
        >
          Generate Project PDF
        </Button>
      ) : (
        <LockedFeatureButton
          buttonLabel="Generate Project PDF"
          helperText={"Your current plan does not include PDF audit exports."}
        />
      );
    }

    if (selectedReportFlow === "competitors") {
      return canExportBattle ? (
        competitorExportMode === "latest" ? (
          <Button
            variant="primary"
            className={accentCls}
            onClick={() => void runExclusive(runBattleExport)}
            loading={runningAction === "competitorsLatest"}
            disabled={!selectedAudit || !selectedBattleCompetitor || runningAction !== null}
          >
            Generate Competitors PDF
          </Button>
        ) : (
          <Button
            variant="primary"
            className={accentCls}
            onClick={() => void runExclusive(runCompetitorTrendExport)}
            loading={runningAction === "competitorsTrend"}
            disabled={
              !selectedAudit ||
              selectedAuditSiteId === null ||
              !selectedTrackedCompetitor ||
              runningAction !== null
            }
          >
            Generate Trend Report
          </Button>
        )
      ) : (
        <LockedFeatureButton
          buttonLabel="Generate Competitors Report"
          helperText={
            battleReportLock.helperText ??
            "Competitor reports unlock on plans with competitor analysis."
          }
        />
      );
    }

    // financial
    return canExportStandard ? (
      <Button
        variant="primary"
        className={accentCls}
        onClick={() => void runExclusive(runFinancialExport)}
        loading={runningAction === "financial"}
        disabled={!selectedAudit || !selectedAudit.project_id || runningAction !== null}
      >
        Generate Financial PDF
      </Button>
    ) : (
      <LockedFeatureButton
        buttonLabel="Generate Financial PDF"
        helperText={"Your current plan does not include PDF audit exports."}
      />
    );
  };

  return (
    <div className="dashboard-page-shell space-y-6">
      <DashboardPageIntro icon={FileText} title="PDF Report Exports" color="var(--accent)">
        Choose a project, pick an audit, select a report type, then export.
      </DashboardPageIntro>

      {actionStatus ? (
        <SignalAlert
          tone={runningAction ? "info" : "success"}
          title={runningAction ? "Preparing report" : "Report ready"}
          icon={runningAction ? <Loader2 className="animate-spin" /> : undefined}
        >
          {actionStatus}
        </SignalAlert>
      ) : null}

      {actionError ? (
        <SignalAlert tone="danger" title="Report request failed">
          {actionError}
        </SignalAlert>
      ) : null}

      <div className="grid gap-6 xl:grid-cols-[260px_minmax(0,1fr)]">
        <GlassCard className={cx("border-(--border) bg-(--card) xl:sticky xl:top-6 xl:self-start")}>
          <div className="p-4 pb-0">
            <div className="flex items-center justify-between gap-3">
              <p className={CARD_LABEL_CLASS}>Steps</p>
              <Badge color="info" className="tracking-[0.14em]">
                {wizardSteps.findIndex((step) => step.key === currentStep) + 1} / 4
              </Badge>
            </div>
          </div>

          <div className="space-y-2 p-4">
            {wizardSteps.map((step, index) => (
              <StepButton
                key={step.key}
                stepNumber={index + 1}
                title={step.title}
                summary={step.summary}
                current={currentStep === step.key}
                complete={step.complete}
                locked={step.locked}
                onClick={() => goToStep(step.key)}
              />
            ))}
          </div>

          <div className="border-t border-(--border) px-4 pb-4 pt-3">
            <p className={cx(CARD_LABEL_CLASS, "mb-1.5")}>Language</p>
            <SelectField
              aria-label="Language"
              value={reportLanguage}
              onChange={(e) => setReportLanguage(normalizeReportLanguage(e.target.value))}
              className="h-9 w-full rounded border-(--border) text-sm"
            >
              {REPORT_LANGUAGE_OPTIONS.map((opt) => (
                <option key={opt.code} value={opt.code}>
                  {opt.label}
                </option>
              ))}
            </SelectField>
            {isCjkLanguage && (
              <p className="mt-1.5 text-xs text-amber-400">CJK font stack active</p>
            )}
          </div>
        </GlassCard>

        <GlassCard
          className={cx(
            CARD_CONTAINER_PRESETS.primary,
            "flex flex-col",
            "border-(--border) bg-(--card)"
          )}
        >
          {currentStep === "project" ? (
            <div className="flex flex-col flex-1 gap-6">
              <div className="flex items-center gap-3 border-b border-(--border) pb-4">
                <span className="inline-flex h-6 w-6 shrink-0 items-center justify-center rounded border-0 bg-[#E8F1FF] text-[10px] font-semibold text-[#1D4ED8]">
                  1
                </span>
                <h2 className="text-lg font-semibold text-(--foreground)">Choose the project</h2>
                {selectedProject && <CheckCircle2 className="ml-auto h-4 w-4 text-emerald-500" />}
              </div>

              <div className="flex-1">
                {loadingContext ? (
                  <div className="flex items-center gap-3 rounded-xl border-0 px-4 py-3 text-sm text-(--text-soft)">
                    <Loader2 className="h-4 w-4 animate-spin" />
                    Loading project context...
                  </div>
                ) : projects.length === 0 ? (
                  <Notice title="No workspace projects found" tone="warning">
                    Create a project first, then return here to generate reports from completed
                    audits.
                  </Notice>
                ) : (
                  <div className="space-y-4">
                    <TextField
                      placeholder="Search projects…"
                      value={projectSearch}
                      onChange={(e) => {
                        setProjectSearch(e.target.value);
                        setProjectPage(0);
                      }}
                      className="h-9 rounded border-(--border) text-sm"
                    />

                    {pagedProjects.length === 0 ? (
                      <Notice title="No projects match" tone="warning">
                        Try a different search term.
                      </Notice>
                    ) : (
                      <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
                        {pagedProjects.map((project) => {
                          const isSelected = String(project.id) === selectedProjectId;
                          return (
                            <button
                              key={project.id}
                              type="button"
                              onClick={() => setSelectedProjectId(String(project.id))}
                              className={cx(
                                "w-full rounded border p-3 text-left transition duration-normal",
                                isSelected
                                  ? "border-primary bg-primary/10"
                                  : "border-(--border) bg-(--surface) hover:border-(--border-hover) hover:bg-(--surface-elevated)"
                              )}
                            >
                              <div className="flex items-start justify-between gap-2">
                                <div className="min-w-0">
                                  <p className="truncate text-sm font-semibold text-(--foreground)">
                                    {project.name}
                                  </p>
                                  <p className="mt-0.5 truncate text-xs text-(--text-muted)">
                                    {project.domain_url || "No domain"}
                                  </p>
                                </div>
                                {isSelected ? (
                                  <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-emerald-500" />
                                ) : (
                                  <Badge
                                    color={project.audit_count > 0 ? "success" : "warning"}
                                    className="shrink-0 text-xs"
                                  >
                                    {project.audit_count}
                                  </Badge>
                                )}
                              </div>
                            </button>
                          );
                        })}
                      </div>
                    )}
                  </div>
                )}
                {contextError ? (
                  <Notice title="Context error" tone="danger">
                    {contextError}
                  </Notice>
                ) : null}
              </div>

              <div className="mt-auto flex items-center justify-between gap-4 border-t border-(--border) pt-5">
                <div className="flex items-center gap-2">
                  {projects.length > 0 && (
                    <>
                      <button
                        type="button"
                        disabled={projectPage === 0}
                        onClick={() => setProjectPage((p) => p - 1)}
                        className="rounded border-0 px-3 py-1.5 text-xs text-(--text-muted) disabled:opacity-40 hover:bg-(--surface-elevated)"
                      >
                        Prev
                      </button>
                      <span className="text-xs text-(--text-muted)">
                        {projectPage + 1} / {projectPageCount}
                      </span>
                      <button
                        type="button"
                        disabled={projectPage >= projectPageCount - 1}
                        onClick={() => setProjectPage((p) => p + 1)}
                        className="rounded border-0 px-3 py-1.5 text-xs text-(--text-muted) disabled:opacity-40 hover:bg-(--surface-elevated)"
                      >
                        Next
                      </button>
                    </>
                  )}
                </div>
                <Button
                  variant="primary"
                  onClick={() => goToStep("audit")}
                  disabled={!selectedProject}
                >
                  Continue
                  <ArrowRight className="h-4 w-4" />
                </Button>
              </div>
            </div>
          ) : null}

          {currentStep === "audit" ? (
            <div className="flex flex-col flex-1 gap-6">
              <div className="flex items-center gap-3 border-b border-(--border) pb-4">
                <span className="inline-flex h-6 w-6 shrink-0 items-center justify-center rounded border-0 bg-[#E8F1FF] text-[10px] font-semibold text-[#1D4ED8]">
                  2
                </span>
                <h2 className="text-lg font-semibold text-(--foreground)">Choose the audit</h2>
                <span className="text-sm text-(--text-muted)">{selectedProject?.name}</span>
                {selectedAudit && <CheckCircle2 className="ml-auto h-4 w-4 text-emerald-500" />}
              </div>

              <div className="flex-1">
                {loadingAudits ? (
                  <div className="flex items-center gap-3 rounded-xl border-0 px-4 py-3 text-sm text-(--text-soft)">
                    <Loader2 className="h-4 w-4 animate-spin" />
                    Loading completed audits...
                  </div>
                ) : audits.length === 0 ? (
                  <Notice title="No audits available" tone="warning">
                    This project does not have a completed audit to export yet.
                  </Notice>
                ) : (
                  <div className="space-y-4">
                    <div className="flex flex-wrap gap-2">
                      <TextField
                        placeholder="Search audits…"
                        value={auditSearch}
                        onChange={(e) => {
                          setAuditSearch(e.target.value);
                          setAuditPage(0);
                        }}
                        className="h-9 w-52 rounded border-(--border) text-sm"
                      />
                      <SelectField
                        label=""
                        value={auditTypeFilter}
                        onChange={(e) => {
                          setAuditTypeFilter(e.target.value);
                          setAuditPage(0);
                        }}
                        className="h-9 rounded border-(--border) text-sm"
                      >
                        <option value="">All types</option>
                        {auditTypeOptions.map((type) => (
                          <option key={type} value={type}>
                            {type}
                          </option>
                        ))}
                      </SelectField>
                      {(auditSearch || auditTypeFilter) && (
                        <button
                          type="button"
                          onClick={() => {
                            setAuditSearch("");
                            setAuditTypeFilter("");
                            setAuditPage(0);
                          }}
                          className="rounded border-0 px-3 py-1.5 text-xs text-(--text-muted) hover:bg-(--surface-elevated)"
                        >
                          Clear
                        </button>
                      )}
                    </div>

                    {pagedAudits.length === 0 ? (
                      <Notice title="No audits match" tone="warning">
                        Try clearing the filters.
                      </Notice>
                    ) : (
                      <div className="space-y-2">
                        {pagedAudits.map((audit) => {
                          const isSelected = String(audit.id) === selectedAuditId;
                          return (
                            <button
                              key={audit.id}
                              type="button"
                              onClick={() => setSelectedAuditId(String(audit.id))}
                              className={cx(
                                "flex w-full items-center gap-3 rounded border px-4 py-3 text-left transition duration-normal",
                                isSelected
                                  ? "border-primary/40 bg-primary/10"
                                  : "border-(--border) bg-(--surface) hover:border-(--border-hover) hover:bg-(--surface-elevated)"
                              )}
                            >
                              <div className="min-w-0 flex-1">
                                <p className="truncate text-sm font-semibold text-(--foreground)">
                                  {audit.audit_type} ·{" "}
                                  {resolveAuditTargetLabel(audit) || "Unnamed target"}
                                </p>
                                <p className="mt-0.5 truncate text-xs text-(--text-muted)">
                                  {resolveAuditTargetType(audit)} ·{" "}
                                  {formatDateTime(audit.created_at)}
                                  {audit.site_id ? " · site-linked" : ""}
                                </p>
                              </div>
                              <Badge
                                color={audit.status === "completed" ? "success" : "warning"}
                                className="shrink-0 uppercase tracking-[0.12em]"
                              >
                                {audit.status}
                              </Badge>
                              {isSelected && (
                                <CheckCircle2 className="h-4 w-4 shrink-0 text-emerald-500" />
                              )}
                            </button>
                          );
                        })}
                      </div>
                    )}

                    {selectedAuditIntegrity ? (
                      <Notice
                        title={
                          selectedAuditIntegrity.flagged
                            ? "Integrity: flagged claims"
                            : "Integrity: clear"
                        }
                        tone={selectedAuditIntegrity.flagged ? "warning" : "success"}
                      >
                        {selectedAuditIntegrity.reviewClaimCount} of{" "}
                        {selectedAuditIntegrity.totalClaims} claims flagged.
                      </Notice>
                    ) : null}
                  </div>
                )}
              </div>

              <div className="mt-auto flex items-center justify-between gap-4 border-t border-(--border) pt-5">
                <div className="flex items-center gap-2">
                  {audits.length > 0 && (
                    <>
                      <button
                        type="button"
                        disabled={auditPage === 0}
                        onClick={() => setAuditPage((p) => p - 1)}
                        className="rounded border-0 px-3 py-1.5 text-xs text-(--text-muted) disabled:opacity-40 hover:bg-(--surface-elevated)"
                      >
                        Prev
                      </button>
                      <span className="text-xs text-(--text-muted)">
                        {auditPage + 1} / {auditPageCount}
                      </span>
                      <button
                        type="button"
                        disabled={auditPage >= auditPageCount - 1}
                        onClick={() => setAuditPage((p) => p + 1)}
                        className="rounded border-0 px-3 py-1.5 text-xs text-(--text-muted) disabled:opacity-40 hover:bg-(--surface-elevated)"
                      >
                        Next
                      </button>
                    </>
                  )}
                </div>
                <div className="flex gap-3">
                  <Button variant="ghost" onClick={() => goToStep("project")}>
                    Back
                  </Button>
                  <Button
                    variant="primary"
                    onClick={() => goToStep("report")}
                    disabled={!selectedAudit}
                  >
                    Continue
                    <ArrowRight className="h-4 w-4" />
                  </Button>
                </div>
              </div>
            </div>
          ) : null}

          {currentStep === "report" ? (
            <div className="flex flex-col flex-1 gap-6">
              <div className="flex items-center gap-3 border-b border-(--border) pb-4">
                <span className="inline-flex h-6 w-6 shrink-0 items-center justify-center rounded border-0 bg-[#E8F1FF] text-[10px] font-semibold text-[#1D4ED8]">
                  3
                </span>
                <h2 className="text-lg font-semibold text-(--foreground)">Report type</h2>
              </div>

              <Notice title={t("signalReports.withheldNoticeTitle")}>
                {t("signalReports.withheldNoticeBody")}
              </Notice>

              <div className="flex-1 grid content-start gap-3 md:grid-cols-2 lg:grid-cols-3">
                {reportChoices.map((choice) => {
                  const Icon = choice.icon;
                  return (
                    <SelectableCard
                      key={choice.key}
                      selected={choice.key === selectedReportFlow}
                      onClick={() => setSelectedReportFlow(choice.key)}
                      title={choice.title}
                      description={choice.description}
                      badgeLabel={choice.availabilityLabel}
                      badgeColor={choice.availabilityColor}
                    >
                      <div className="flex items-center gap-2 pt-1">
                        <Icon className="h-4 w-4 shrink-0 text-primary" />
                        <p className="text-xs leading-5 text-(--muted-foreground)">
                          {choice.helper}
                        </p>
                      </div>
                    </SelectableCard>
                  );
                })}
              </div>

              <div className="mt-auto flex justify-end gap-3 border-t border-(--border) pt-5">
                <Button variant="ghost" onClick={() => goToStep("audit")}>
                  Back
                </Button>
                <Button
                  variant="primary"
                  onClick={() => goToStep("configure")}
                  disabled={!selectedAudit}
                >
                  Continue
                  <ArrowRight className="h-4 w-4" />
                </Button>
              </div>
            </div>
          ) : null}

          {currentStep === "configure" ? (
            <div className="flex flex-col flex-1 gap-6">
              <div className="flex items-center gap-3 border-b border-(--border) pb-4">
                <span className="inline-flex h-6 w-6 shrink-0 items-center justify-center rounded border-0 bg-[#E8F1FF] text-[10px] font-semibold text-[#1D4ED8]">
                  4
                </span>
                <h2 className="text-lg font-semibold text-(--foreground)">
                  {selectedReportChoice.title}
                </h2>
              </div>

              <div className="flex-1 space-y-5">
                {/* Report-specific configuration */}
                {renderConfigurePanel()}

                {/* Shared settings, always visible */}
                <div
                  className={cx(
                    "space-y-5",
                    selectedReportFlow !== "standard" &&
                      selectedReportFlow !== "aio" &&
                      selectedReportFlow !== "seo" &&
                      "border-t border-(--border) pt-5"
                  )}
                >
                  <div className="space-y-3">
                    <ToggleSwitch
                      checked={sendByEmail}
                      onChange={setSendByEmail}
                      label="Send by email"
                      description={
                        sendByEmail
                          ? "A copy of the report will be sent to the address below after generation."
                          : "Enable to send a copy of the report by email after generation."
                      }
                    />
                    {sendByEmail ? (
                      <div className="w-72">
                        <TextField
                          type="email"
                          label="Email address"
                          value={reportEmailAddress}
                          onChange={(event) => setReportEmailAddress(event.target.value)}
                          className="h-9 rounded border-(--border) text-sm"
                        />
                      </div>
                    ) : null}
                  </div>
                </div>

                {/* Integrity notice */}
                {selectedAuditIntegrity ? (
                  <Notice
                    title={
                      selectedAuditIntegrity.flagged
                        ? "Integrity: flagged claims"
                        : "Integrity: clear"
                    }
                    tone={selectedAuditIntegrity.flagged ? "warning" : "success"}
                  >
                    {selectedAuditIntegrity.groundingProfileLabel ?? "Legacy review"}
                    {selectedAuditIntegrity.trackBTotal > 0
                      ? ` · Track B ${selectedAuditIntegrity.trackBPassed}/${selectedAuditIntegrity.trackBTotal} passed`
                      : ""}
                    {selectedAuditIntegrity.degraded ? " · degraded fallback active" : ""}
                  </Notice>
                ) : null}
              </div>

              {/* Footer */}
              <div className="mt-auto flex items-center justify-between gap-3 border-t border-(--border) pt-5">
                <div className="flex gap-2">
                  <Button variant="ghost" onClick={() => goToStep("report")}>
                    Back
                  </Button>
                  <Button variant="ghost" onClick={() => goToStep("audit")}>
                    Change audit
                  </Button>
                </div>
                {renderFooterGenerate()}
              </div>
            </div>
          ) : null}
        </GlassCard>
      </div>
    </div>
  );
}
