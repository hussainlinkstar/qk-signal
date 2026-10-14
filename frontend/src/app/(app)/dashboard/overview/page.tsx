"use client";

import SignalAlert from "@/components/signal/SignalAlert";
import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useTranslation } from "react-i18next";
import { Building2, ChevronRight, ExternalLink, Globe, Loader2, Settings } from "lucide-react";
import { SkelCard, SkelPagehead } from "@/components/signal/SignalSkeleton";

import { useAuth } from "@/components/auth/custom-auth";
import EmailVerificationBanner from "@/components/dashboard/EmailVerificationBanner";
import GettingStartedChecklist, {
  type GettingStartedItem,
} from "@/components/onboarding/GettingStartedChecklist";
import ProjectScoreSparkline from "@/components/dashboard/ProjectScoreSparkline";
import WorkspacePageFrame from "@/components/dashboard/WorkspacePageFrame";
import OnboardingWizard, { type Ga4ReturnOutcome } from "@/components/onboarding/OnboardingWizard";
import ProjectFormFields from "@/components/onboarding/ProjectSetupFields";
import PasskeySetupPrompt from "@/components/auth/PasskeySetupPrompt";
import Modal from "@/components/ui/Modal";
import { cx } from "@/components/ui/utils";
import { useBillingSettings } from "@/hooks/useBillingSettings";
import { useOnboardingState } from "@/hooks/useOnboardingState";
import { useSignalEntrance } from "@/hooks/useSignalChartMotion";
import { useTrialStatus } from "@/hooks/useTrialStatus";
import { asset } from "@/lib/basePath";
import { formatRelativeTime } from "@/lib/dateFormat";
import {
  clearOnboardingResume,
  readOnboardingResume,
  recordOnboardingResume,
} from "@/lib/onboardingResume";
import { resolveServedCapability } from "@/lib/planCapabilities";
import { AIO_TREND_COLOR, scoreDeltaMeta, scoreTrendPoints } from "@/lib/projectScoreTrend";
import { beginScanLaunch } from "@/lib/scanLaunch";
import { GLOBAL_TARGET_MARKET, toTargetCountry } from "@/lib/targetMarket";
import { fetchUserProjects, type UserProjectSummary } from "@/services/auditService";
import { fetchWorkspaceDataConnections } from "@/services/integrationService";
import {
  createProjectCompetitor,
  createWorkspaceProject,
  fetchCurrentWorkspace,
  fetchWorkspaceTrendOverview,
  type ProjectCreatePayload,
  type WorkspaceTrendOverviewProject,
} from "@/services/workspaceService";
import {
  getActiveWorkspaceId,
  useWorkspaceVersion,
  workspaceHeaders,
} from "@/components/app/WorkspaceSwitcher";

const deriveDomainLabel = (domainUrl: string | null | undefined, fallbackName: string) => {
  if (!domainUrl) return fallbackName;
  try {
    const parsed = new URL(domainUrl);
    return parsed.hostname || fallbackName;
  } catch {
    return domainUrl.replace(/^https?:\/\//i, "") || fallbackName;
  }
};

// SIGV2-1307: named, so the setter can tell this message from a real failure
// and clear only the one whose condition has gone.
const PROJECT_NAME_REQUIRED_MESSAGE = "Project name is required.";

const average = (values: Array<number | null | undefined>) => {
  const valid = values.filter((value): value is number => typeof value === "number");
  if (valid.length === 0) return null;
  return valid.reduce((sum, value) => sum + value, 0) / valid.length;
};

const scoreRingClass = (value: number | null | undefined) => {
  if (typeof value !== "number") return "text-(--border)";
  if (value >= 80) return "text-(--accent)";
  if (value >= 50) return "text-(--muted-foreground)";
  return "text-(--accent-warm)";
};

const scoreValueClass = (value: number | null | undefined) => {
  if (typeof value !== "number") return "text-(--muted-foreground)";
  if (value >= 80) return "text-(--accent)";
  if (value >= 50) return "text-(--text-bright)";
  return "text-(--accent-warm)";
};

const aggregateDeltaLabel = (value: number | null) => {
  if (typeof value !== "number") return "0.0% 7d";
  const rounded = Math.round(value * 100) / 100;
  if (rounded > 0) return `+${rounded}% 7d`;
  if (rounded < 0) return `${rounded}% 7d`;
  return "0.0% 7d";
};

const getProjectMinScore = (project: UserProjectSummary) => {
  const scores = [
    project.latest_seo_score,
    project.latest_aeo_score,
    project.latest_geo_score,
  ].filter((value): value is number => typeof value === "number");
  if (scores.length === 0) return null;
  return Math.min(...scores);
};

const formatAuditCount = (count: number) => `${count} ${count === 1 ? "audit" : "audits"}`;

// Approved `.pc-fav` tiles carry distinct accent colours per card
// (#0C0F16 / #0E7C6B / #B45309 in the mockup); cycle them by position so
// every project gets a stable, deterministic tint.
const PROJECT_FAV_COLORS = ["#0C0F16", "#0E7C6B", "#B45309"];

const OVERVIEW_CARD_RADIUS_CLASS = "rounded-(--r-lg)";
const PROJECT_CARD_HOVER_CLASS =
  "transition-all duration-200 hover:-translate-y-0.5 hover:border-[#D7DAE0] hover:shadow-[0_6px_24px_rgba(12,15,22,0.07)]";
const PRIMARY_CARD_HOVER_CLASS =
  "transition-all duration-200 hover:border-(--accent-warm) hover:shadow-[0_6px_24px_rgba(12,15,22,0.07)]";

function useOverviewDashboard() {
  const router = useRouter();
  const { getToken, isLoading: authLoading, isSignedIn } = useAuth();

  const [projects, setProjects] = useState<UserProjectSummary[]>([]);
  const [workspaceName, setWorkspaceName] = useState("Workspace");
  const [trendOverviewByProject, setTrendOverviewByProject] = useState<
    Record<number, WorkspaceTrendOverviewProject>
  >({});
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [projectName, setProjectNameState] = useState("");
  const [projectDomain, setProjectDomain] = useState("");
  const [projectCountry, setProjectCountry] = useState(GLOBAL_TARGET_MARKET);
  const [projectLanguage, setProjectLanguage] = useState("en");
  const [isCreating, setIsCreating] = useState(false);
  const [creationMessage, setCreationMessage] = useState<string | null>(null);
  const createInFlightRef = useRef(false);

  // SIGV2-1307: the validation message does not outlive its condition.
  //
  // QA: "Add Project kept 'Project name is required' after the name was
  // filled, including during submit." `creationMessage` was only cleared once
  // a submit got past the guard, so typing a name left the complaint on
  // screen, and the next submit showed it for as long as the request took.
  //
  // A message that survives the thing it describes teaches people to ignore
  // validation, which costs more than the one message.
  const setProjectName = useCallback((value: string) => {
    setProjectNameState(value);
    setCreationMessage((current) =>
      current === PROJECT_NAME_REQUIRED_MESSAGE && value.trim() ? null : current
    );
  }, []);

  const workspaceVersion = useWorkspaceVersion();
  const previousWorkspaceVersionRef = useRef(workspaceVersion);

  const getAuthHeaders = useCallback(async (): Promise<HeadersInit> => {
    const token = await getToken();
    if (!token) throw new Error("Authentication failed. Please log in again.");
    return { Authorization: `Bearer ${token}`, ...workspaceHeaders() };
  }, [getToken]);

  const loadOverview = useCallback(async () => {
    if (authLoading || !isSignedIn) {
      if (!authLoading) setIsLoading(false);
      return;
    }

    setIsLoading(true);
    setError(null);
    try {
      const headers = await getAuthHeaders();
      const [workspace, projectSummaries] = await Promise.all([
        fetchCurrentWorkspace(headers).catch(() => ({ name: "Workspace" })),
        fetchUserProjects(headers),
      ]);

      setWorkspaceName(workspace.name);
      const workspaceId =
        "id" in workspace && typeof workspace.id === "number" ? workspace.id : null;
      setProjects(projectSummaries);

      const trendOverview = workspaceId
        ? await fetchWorkspaceTrendOverview(workspaceId, headers, { period: "90d" }).catch(
            () => null
          )
        : null;

      setTrendOverviewByProject(
        trendOverview
          ? Object.fromEntries(trendOverview.projects.map((item) => [item.project_id, item]))
          : {}
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : "Sync failure.");
    } finally {
      setIsLoading(false);
    }
  }, [authLoading, getAuthHeaders, isSignedIn]);

  useEffect(() => {
    void loadOverview();
  }, [loadOverview]);

  // Switching workspace invalidates every scoped record the page holds: the
  // project cards and their trend deltas belong to the previous workspace and
  // must not linger (a deleted or inaccessible project would otherwise stay on
  // screen until the refetch resolved).
  useEffect(() => {
    if (previousWorkspaceVersionRef.current === workspaceVersion) return;
    previousWorkspaceVersionRef.current = workspaceVersion;
    setProjects([]);
    setTrendOverviewByProject({});
    setError(null);
    void loadOverview();
  }, [loadOverview, workspaceVersion]);

  const createProject = useCallback(
    async (payload: ProjectCreatePayload) => {
      const headers = await getAuthHeaders();
      const created = await createWorkspaceProject(payload, headers);
      await loadOverview();
      return created;
    },
    [getAuthHeaders, loadOverview]
  );

  // SIGV2-1220: one competitor per call, so the wizard knows exactly which
  // ones landed. A batch that failed halfway used to make the retry re-post an
  // already-saved competitor, which the API refuses as a duplicate, and the
  // onboarding step could never be passed.
  const addCompetitor = useCallback(
    async (projectId: number, domain: string) => {
      const headers = await getAuthHeaders();
      await createProjectCompetitor(projectId, { target_url: domain }, headers);
    },
    [getAuthHeaders]
  );

  const googleConnectionStatus = useCallback(async (): Promise<{
    connected: boolean;
    configured: boolean;
  }> => {
    const headers = await getAuthHeaders();
    const connections = await fetchWorkspaceDataConnections(headers);
    const google = connections.find((connection) => connection.provider === "google");
    // `configured !== false` so a row predating the flag (or none at all)
    // keeps the affordance rather than wrongly reporting unconfigured.
    return {
      connected: Boolean(google?.connected),
      configured: google ? google.configured !== false : true,
    };
  }, [getAuthHeaders]);

  const handleCreateProject = async () => {
    // Ref guard, not state: two clicks inside the same render batch must not
    // issue two POSTs.
    if (createInFlightRef.current) return false;
    if (!projectName.trim()) {
      setCreationMessage(PROJECT_NAME_REQUIRED_MESSAGE);
      return false;
    }

    createInFlightRef.current = true;
    setIsCreating(true);
    setCreationMessage(null);
    try {
      const created = await createProject({
        name: projectName.trim(),
        domain_url: projectDomain.trim() || null,
        target_country: toTargetCountry(projectCountry),
        language: projectLanguage.trim() || "en",
      });

      setProjectNameState("");
      setProjectDomain("");
      setProjectCountry(GLOBAL_TARGET_MARKET);
      setCreationMessage("Project created successfully.");
      router.push(`/dashboard/projects/${created.id}`);
      return true;
    } catch (err) {
      // The entered values stay in state so a retry does not lose them.
      setCreationMessage(err instanceof Error ? err.message : "Unable to create project.");
      return false;
    } finally {
      createInFlightRef.current = false;
      setIsCreating(false);
    }
  };

  return {
    projects,
    workspaceName,
    trendOverviewByProject,
    isLoading,
    error,
    projectName,
    setProjectName,
    projectDomain,
    setProjectDomain,
    projectCountry,
    setProjectCountry,
    projectLanguage,
    setProjectLanguage,
    isCreating,
    creationMessage,
    handleCreateProject,
    createProject,
    addCompetitor,
    googleConnectionStatus,
    reload: loadOverview,
  };
}

function MetricCircle({
  label,
  value,
}: {
  label: "SEO" | "AIO";
  value: number | null | undefined;
}) {
  const normalized = typeof value === "number" ? Math.max(0, Math.min(100, Math.round(value))) : 0;

  return (
    <div className="flex w-1/3 flex-col items-center gap-2">
      <div className="relative h-12 w-12">
        <svg className="h-full w-full -rotate-90" viewBox="0 0 36 36">
          <path
            className="text-(--border)"
            d="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831"
            fill="none"
            stroke="currentColor"
            strokeDasharray="100, 100"
            strokeWidth="4"
          />
          <path
            className={cx("transition-all duration-300", scoreRingClass(value))}
            d="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831"
            fill="none"
            stroke="currentColor"
            strokeDasharray={`${normalized}, 100`}
            strokeWidth="4"
          />
        </svg>
        <div className="absolute inset-0 flex items-center justify-center">
          <span className={cx("text-sm font-bold", scoreValueClass(value))}>
            {typeof value === "number" ? Math.round(value) : "-"}
          </span>
        </div>
      </div>
      <span className="text-[10px] font-bold uppercase tracking-[0.14em] text-(--muted-foreground)">
        {label}
      </span>
    </div>
  );
}

function ProjectHeader({
  displayName,
  domainLabel,
  onOpenProject,
  onOpenSettings,
}: {
  displayName: string;
  domainLabel: string;
  onOpenProject: () => void;
  onOpenSettings: () => void;
}) {
  return (
    <div className="mb-auto flex items-start justify-between gap-3">
      <button type="button" onClick={onOpenProject} className="min-w-0 text-left">
        <div className="flex items-center gap-2">
          <Building2 className="h-4 w-4 shrink-0 text-(--accent)" />
          <h3 className="truncate pr-2 font-sans text-lg font-black tracking-[-0.02em] text-(--text-bright)">
            {displayName}
          </h3>
        </div>
        <div className="mt-1 flex items-center gap-2 text-xs text-(--muted-foreground)">
          <Globe className="h-3.5 w-3.5 shrink-0" />
          <span className="truncate">{domainLabel}</span>
        </div>
      </button>

      <div className="flex shrink-0 items-center gap-1 lg:opacity-0 lg:transition-opacity lg:group-hover:opacity-100 lg:group-focus-within:opacity-100">
        <button
          type="button"
          aria-label={`Project settings for ${displayName}`}
          onClick={(event) => {
            event.stopPropagation();
            onOpenSettings();
          }}
          className="rounded-none border border-transparent p-1.5 text-(--muted-foreground) transition-colors hover:border-(--border) hover:text-(--text-bright)"
        >
          <Settings className="h-4 w-4" />
        </button>
        <ExternalLink className="h-4 w-4 text-(--muted-foreground)" />
      </div>
    </div>
  );
}

const PROJECT_MODAL_TITLE_ID = "create-project-title";
const PROJECT_MODAL_SUB_ID = "create-project-sub";

function ProjectCreateModal({
  open,
  onClose,
  settings,
}: {
  open: boolean;
  onClose: () => void;
  settings: ReturnType<typeof useOverviewDashboard>;
}) {
  const { t } = useTranslation();
  return (
    <Modal
      open={open}
      onClose={onClose}
      /* signal-MVP `.modal`: 560px, radius 20, padding 28/30/26. */
      panelClassName="w-full max-w-[560px] rounded-[20px] border border-(--line) bg-(--panel) p-[28px_30px_26px]"
      /* The approved `.modal-title` is the dialog's name; without this the
         shared Modal adds a second, visually hidden "Dialog" heading. */
      ariaLabelledby={PROJECT_MODAL_TITLE_ID}
      ariaDescribedby={PROJECT_MODAL_SUB_ID}
    >
      <p className="font-(family-name:--mono) text-[11px] uppercase tracking-[0.14em] text-(--t-3)">
        {t("projectForm.eyebrow")}
      </p>
      <h2
        id={PROJECT_MODAL_TITLE_ID}
        className="my-2 mb-1.5 font-(family-name:--disp) text-[23px] font-extrabold tracking-[-0.02em]"
      >
        {t("projectForm.title")}
      </h2>
      <p
        id={PROJECT_MODAL_SUB_ID}
        className="m-0 mb-[22px] text-[13.5px] leading-[1.5] text-(--t-2)"
      >
        {t("projectForm.sub")}
      </p>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <ProjectFormFields
          variant="modal"
          fields={["name", "domain", "market", "language"]}
          values={{
            name: settings.projectName,
            domain: settings.projectDomain,
            market: settings.projectCountry,
            language: settings.projectLanguage,
          }}
          disabled={settings.isCreating}
          onChange={(key, value) => {
            if (key === "name") settings.setProjectName(value);
            if (key === "domain") settings.setProjectDomain(value);
            if (key === "market") settings.setProjectCountry(value);
            if (key === "language") settings.setProjectLanguage(value);
          }}
        />
      </div>

      <div className="mt-6 flex items-center justify-end gap-[10px]">
        {settings.creationMessage ? (
          <p className="me-auto text-[12.5px] text-(--bad)">{settings.creationMessage}</p>
        ) : null}
        {/* signal-MVP `.btn` / `.btn pri`: h-38, px-15, 13.5/600, radius 10,
            disabled at --disabled-opacity (.45) from the themed button rule,
            and the single approved 3px --ring on keyboard focus. */}
        <button
          type="button"
          className="inline-flex h-[38px] cursor-pointer items-center gap-2 rounded-[10px] border border-(--line) bg-(--panel) px-[15px] font-(family-name:--body-font) text-[13.5px] font-semibold text-(--t-1) transition-colors hover:border-(--line-btn-hover) focus-visible:outline-hidden focus-visible:ring-[3px] focus-visible:ring-(--ring)"
          onClick={onClose}
          disabled={settings.isCreating}
        >
          {t("projectForm.cancel")}
        </button>
        <button
          type="button"
          className="inline-flex h-[38px] cursor-pointer items-center gap-2 rounded-[10px] border border-(--ink) bg-(--ink) px-[15px] font-(family-name:--body-font) text-[13.5px] font-semibold text-white transition-colors hover:bg-black focus-visible:outline-hidden focus-visible:ring-[3px] focus-visible:ring-(--ring)"
          onClick={async () => {
            const created = await settings.handleCreateProject();
            if (created) onClose();
          }}
          disabled={settings.isCreating}
        >
          {settings.isCreating ? (
            <span className="flex items-center gap-2">
              <Loader2 className="h-4 w-4 animate-spin" />
              {t("projectForm.submitting")}
            </span>
          ) : (
            t("projectForm.submit")
          )}
        </button>
      </div>
    </Modal>
  );
}

/**
 * Begins the onboarding's "Run my first scan" (SIGV2-1159).
 *
 * The approved onboarding's last step runs the scan (mockup: Signal
 * Onboarding.html launches Signal Audit Run.html) rather than presenting the
 * start-scan form a second time. Two separate things happen here, and the
 * distinction is the security boundary:
 *
 * - the returned href **prefills** the form, and carries nothing privileged:
 *   anyone can send that link and it opens the form, as it always did;
 * - the recorded launch intent is the **authority** to start, and lives in
 *   this tab's `sessionStorage` where no link can reach it.
 *
 * A resumed wizard names no target, so the project's own domain is used. With
 * no resolvable target there is nothing to start: no intent is recorded and
 * the form opens as before.
 *
 * The two steps themselves live in `lib/scanLaunch.ts`, which is the single
 * launch path every control that starts a scan goes through (SIGV2-1184).
 */
export function beginFirstScanLaunch(
  projectId: number,
  target?: { url: string; name: string },
  project?: { domain?: string | null; display_name?: string | null } | null
): string {
  return beginScanLaunch(projectId, {
    url: target?.url || project?.domain || "",
    name: target?.name || project?.display_name || "",
  });
}

export default function OverviewPage() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { t } = useTranslation();
  const { user } = useAuth();
  const settings = useOverviewDashboard();
  const {
    state: onboardingState,
    isLoading: onboardingLoading,
    updateState: updateOnboardingState,
  } = useOnboardingState();
  const { trial, isLoading: trialLoading } = useTrialStatus();
  const { billingOverview } = useBillingSettings();

  const [wizardOpen, setWizardOpen] = useState(false);
  const [createModalOpen, setCreateModalOpen] = useState(false);
  const [emailBannerDismissed, setEmailBannerDismissed] = useState(false);

  // SIGV2-1220: what the GA4 connect left behind before the browser went to
  // Google, read once on mount. The recorded workspace must match the active
  // one or the context is not ours to resume (SIGV2-1207's rule: refuse, do
  // not substitute).
  const [onboardingResume, setOnboardingResume] = useState(() =>
    readOnboardingResume({ activeWorkspaceId: getActiveWorkspaceId() })
  );

  // What the OAuth callback said. A report only: `connected` here never marks
  // the step complete, because only the connections endpoint can confirm a
  // connection (SIGV2-1202).
  const ga4Outcome = useMemo<Ga4ReturnOutcome | null>(() => {
    if (!searchParams || searchParams.get("provider") !== "google") return null;
    const status = searchParams.get("status");
    if (status !== "connected" && status !== "error") return null;
    return { status, message: searchParams.get("message") };
  }, [searchParams]);

  // The entitlement the API serves decides whether the competitor step is
  // offered at all. Before that payload lands the local table stands in, so an
  // entitled customer is never locked out by a slow request.
  const canTrackCompetitors = useMemo(
    () =>
      resolveServedCapability(billingOverview, "has_competitor_analysis", user?.subscription_plan),
    [billingOverview, user?.subscription_plan]
  );

  const completedSteps = useMemo(
    () => new Set(onboardingState.completed_steps),
    [onboardingState.completed_steps]
  );
  const isTrialUser = trial.is_trial;
  const isEmailVerified = user?.email_verified !== false;
  const pcardEntranceRef = useSignalEntrance(
    `pcards:${settings.isLoading ? "loading" : "ready"}:${settings.projects.map((project) => project.project_id).join(",")}`
  );
  const hasProjects = settings.projects.length > 0;
  const hasAudits = settings.projects.some((project) => project.audit_count > 0);
  const workspaceConfigured =
    completedSteps.has("workspace_named") ||
    settings.workspaceName.trim().toLowerCase() !== "workspace";

  // The wizard ends once the customer has a project (the approved flow creates
  // it at step 2 and persists `first_project`). Anything earlier resumes in
  // place.
  //
  // SIGV2-1220: a recorded resume context overrides that. The project is
  // created at step 2, so "a project exists" is true for the whole second half
  // of the flow; after connecting GA4 it made the wizard count as finished and
  // steps 4 and 5 became unreachable.
  const wizardFinished =
    onboardingResume === null && (hasProjects || completedSteps.has("first_project"));

  const checklistItems = useMemo<GettingStartedItem[]>(
    () => [
      {
        id: "verify_email",
        title: "Verify your email",
        description:
          "Check your inbox for a verification link, required for password recovery and notifications.",
        completed: isEmailVerified,
        href: isEmailVerified
          ? "/dashboard/overview"
          : `/verify-email?email=${encodeURIComponent(user?.email ?? "")}`,
      },
      {
        id: "workspace_named",
        title: "Name your workspace",
        description:
          'Go to Settings and give your workspace a name your team will recognize (e.g. "Acme Agency").',
        completed: workspaceConfigured,
        href: "/dashboard/settings",
      },
      {
        id: "first_project",
        title: "Create your first project",
        description:
          "Add a client or website project, this unlocks monitoring, reports, and recommendations.",
        completed: hasProjects || completedSteps.has("first_project"),
        href: "/dashboard/overview",
      },
      {
        id: "first_audit",
        title: "Run your first audit",
        description:
          "Pick a project and run an audit to generate your SEO and AIO baseline scores.",
        completed: hasAudits || completedSteps.has("first_audit"),
        href: "/dashboard/audit",
      },
      {
        id: "first_report",
        title: "Review your first report",
        description: "Open Reports to see your audit results and share them with clients as a PDF.",
        completed: hasAudits || completedSteps.has("first_report"),
        href: "/dashboard/reports",
      },
      {
        id: "invite_team_member",
        title: "Invite a team member",
        description:
          "Add collaborators from Settings so your team can view and manage projects together.",
        completed: completedSteps.has("invite_team_member"),
        optional: true,
        href: "/dashboard/settings",
      },
      {
        id: "connect_integration",
        title: "Connect an integration",
        description:
          "Link Slack, Jira, or other tools from Connections to automate alerts and reporting.",
        completed: completedSteps.has("connect_integration"),
        optional: true,
        href: "/dashboard/connections",
      },
    ],
    [completedSteps, hasAudits, hasProjects, isEmailVerified, user?.email, workspaceConfigured]
  );

  const requiredChecklistItems = checklistItems.filter((item) => !item.optional);
  const requiredCompleted = requiredChecklistItems.filter((item) => item.completed).length;
  const shouldShowChecklist =
    !onboardingLoading &&
    !onboardingState.dismissed_at &&
    !wizardOpen &&
    requiredCompleted < requiredChecklistItems.length;

  const aggregateMetrics = useMemo(() => {
    const seo = average(settings.projects.map((project) => project.latest_seo_score));
    const aeo = average(settings.projects.map((project) => project.latest_aeo_score));
    const geo = average(settings.projects.map((project) => project.latest_geo_score));
    const aio = average([aeo, geo]);
    const overall = average([seo, aio]);

    const delta = average(
      Object.values(settings.trendOverviewByProject).map((item) => item.delta.overall)
    );

    return { seo, aeo, geo, aio, overall, delta };
  }, [settings.projects, settings.trendOverviewByProject]);

  const placeholderCount = settings.isLoading ? Math.max(0, 3 - settings.projects.length) : 0;

  const markOnboardingStepComplete = useCallback(
    async (step: string) => {
      await updateOnboardingState({
        started: true,
        dismissed: false,
        add_completed_steps: [step],
      });
    },
    [updateOnboardingState]
  );

  const dismissOnboarding = useCallback(async () => {
    await updateOnboardingState({ dismissed: true });
  }, [updateOnboardingState]);

  // Leaving the wizard, by any route, consumes the resume context. Without
  // this a later visit in the same tab would reopen it.
  const closeWizard = useCallback(() => {
    clearOnboardingResume();
    setOnboardingResume(null);
    setWizardOpen(false);
  }, []);

  useEffect(() => {
    if (settings.isLoading || onboardingLoading || trialLoading || onboardingState.dismissed_at) {
      return;
    }
    if (isTrialUser || wizardFinished) {
      return;
    }
    setWizardOpen(true);
  }, [
    isTrialUser,
    onboardingLoading,
    onboardingState.dismissed_at,
    settings.isLoading,
    trialLoading,
    wizardFinished,
  ]);

  useEffect(() => {
    if (settings.isLoading || onboardingLoading) {
      return;
    }
    const autoSteps: string[] = [];
    if (workspaceConfigured && !completedSteps.has("workspace_named")) {
      autoSteps.push("workspace_named");
    }
    if (hasProjects && !completedSteps.has("first_project")) {
      autoSteps.push("first_project");
    }
    if (hasAudits) {
      if (!completedSteps.has("first_audit")) autoSteps.push("first_audit");
      if (!completedSteps.has("first_report")) autoSteps.push("first_report");
    }
    if (autoSteps.length > 0) {
      void updateOnboardingState({
        add_completed_steps: autoSteps,
        started: true,
        dismissed: false,
      });
    }
  }, [
    completedSteps,
    hasAudits,
    hasProjects,
    onboardingLoading,
    settings.isLoading,
    updateOnboardingState,
    workspaceConfigured,
  ]);

  useEffect(() => {
    if (onboardingLoading || onboardingState.dismissed_at || !user?.id) {
      return;
    }
    if (requiredCompleted < requiredChecklistItems.length) {
      window.localStorage.removeItem(`onboarding-checklist-complete:${user.id}`);
      return;
    }
    const storageKey = `onboarding-checklist-complete:${user.id}`;
    const seenCompletion = window.localStorage.getItem(storageKey);
    if (seenCompletion === "seen") {
      void dismissOnboarding();
      return;
    }
    window.localStorage.setItem(storageKey, "seen");
  }, [
    dismissOnboarding,
    onboardingLoading,
    onboardingState.dismissed_at,
    requiredChecklistItems.length,
    requiredCompleted,
    user?.id,
  ]);

  if (settings.isLoading && !wizardOpen) {
    return (
      <div role="status" aria-label="Loading workspace" className="flex flex-col gap-5">
        <SkelPagehead />
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          <SkelCard />
          <SkelCard />
          <SkelCard />
        </div>
      </div>
    );
  }

  return (
    <WorkspacePageFrame
      // While the wizard runs, the approved `.top` crumb reads "Get started"
      // instead of the workspace `.dom` + `.meta` pair.
      title={wizardOpen ? t("onboarding.crumb") : settings.workspaceName || "Workspace"}
      meta={
        wizardOpen ? undefined : t("wsOverview.projectCount", { count: settings.projects.length })
      }
    >
      {wizardOpen ? (
        // The approved onboarding is a full page in the shell, not a modal:
        // while it runs it replaces the overview content entirely.
        <OnboardingWizard
          open={wizardOpen}
          // SIGV2-1220: a resumed wizard comes back to the step it left, with
          // the project it created, not to step 1 with the first project in
          // the workspace as a guess.
          initialStep={(onboardingResume?.step ?? 1) as 1 | 2 | 3 | 4 | 5}
          knownProjectId={onboardingResume?.projectId ?? settings.projects[0]?.project_id ?? null}
          canTrackCompetitors={canTrackCompetitors}
          ga4Outcome={ga4Outcome}
          onClose={closeWizard}
          onDismiss={dismissOnboarding}
          onProjectCreated={async (payload) => {
            const created = await settings.createProject(payload);
            return { id: created.id };
          }}
          onSaveCompetitor={settings.addCompetitor}
          onLoadGa4Status={settings.googleConnectionStatus}
          onConnectGa4={({ projectId, step }) => {
            // The real workspace OAuth start. SIGV2-1207: a browser redirect
            // cannot carry X-Workspace-Id, so the active workspace rides as a
            // query parameter. Without it the backend binds the connection to
            // the user's oldest workspace.
            const workspaceId = getActiveWorkspaceId();
            // SIGV2-1220: where to carry on from is recorded here, in this
            // tab, before the browser leaves. `return_to` is a key the backend
            // resolves against its own closed map, never a URL, so nothing in
            // this request can become the redirect target.
            recordOnboardingResume({ workspaceId, projectId, step });
            const query = new URLSearchParams({ return_to: "onboarding" });
            if (workspaceId !== null) query.set("workspace_id", String(workspaceId));
            window.location.href = asset(
              `/api/workspaces/current/oauth-connections/google/start?${query.toString()}`
            );
          }}
          onMarkStepComplete={markOnboardingStepComplete}
          onLaunchAudit={(projectId, target) => {
            router.push(
              beginFirstScanLaunch(
                projectId,
                target,
                settings.projects.find((entry) => entry.project_id === projectId)
              )
            );
          }}
        />
      ) : (
        <div className="space-y-[18px]">
          {/* signal-MVP `.wrap`: measured dhead -> .pgrid gap (declared gap 22
              minus the h1 line-box bottom). `.dhead` keeps title and sub on
              one baseline row, gap 16. */}
          <div className="flex items-end gap-4">
            <h1 className="m-0 font-(family-name:--disp) text-[24px] leading-8 font-extrabold tracking-[-0.02em]">
              {t("wsOverview.title")}
            </h1>
            <p className="m-0 text-[13px] leading-4 text-(--t-2)">{t("wsOverview.sub")}</p>
          </div>

          {!isEmailVerified && !emailBannerDismissed && user?.email ? (
            <EmailVerificationBanner
              email={user.email}
              onDismiss={() => setEmailBannerDismissed(true)}
            />
          ) : null}

          <ProjectCreateModal
            open={createModalOpen}
            onClose={() => setCreateModalOpen(false)}
            settings={settings}
          />

          <section className="space-y-[18px]">
            {/* signal-MVP `.pgrid`: repeat(auto-fill,minmax(320px,1fr)), gap 16. */}
            <div
              ref={pcardEntranceRef}
              className="grid grid-cols-[repeat(auto-fill,minmax(320px,1fr))] gap-4"
            >
              {/* shared AIO ring gradient, same position-independent pattern as
                  the mockup's page-level defs */}
              <svg width="0" height="0" className="absolute" aria-hidden="true">
                <defs>
                  <linearGradient id="gAIOw" x1="0" y1="0" x2="1" y2="1">
                    <stop offset="0" stopColor="var(--blue)" />
                    <stop offset="1" stopColor="var(--purple)" />
                  </linearGradient>
                </defs>
              </svg>
              {settings.projects.map((project, projectIndex) => {
                const domainLabel = deriveDomainLabel(project.domain, project.display_name);
                const fav = (project.display_name || domainLabel || "P")
                  .trim()
                  .charAt(0)
                  .toUpperCase();
                const aioRaw = average([project.latest_aeo_score, project.latest_geo_score]);
                const aio =
                  typeof aioRaw === "number" && Number.isFinite(aioRaw) ? Math.round(aioRaw) : null;
                const seo =
                  typeof project.latest_seo_score === "number" &&
                  Number.isFinite(project.latest_seo_score)
                    ? Math.round(project.latest_seo_score)
                    : null;
                const hasScores = project.audit_count > 0;
                const scanned = project.latest_audit_at
                  ? t("wsOverview.scannedAt", {
                      time: formatRelativeTime(project.latest_audit_at),
                    })
                  : t("wsOverview.noBaseline");
                const trend = settings.trendOverviewByProject[project.project_id];
                const seoDelta = hasScores ? scoreDeltaMeta(trend?.delta.seo) : null;
                const aioDelta = hasScores
                  ? scoreDeltaMeta(average([trend?.delta.aeo, trend?.delta.geo]))
                  : null;
                const sparkValues = (key: "seo" | "aio") =>
                  hasScores ? scoreTrendPoints(trend?.sparkline, key) : [];
                const aioSparkPoints = sparkValues("aio");
                const seoSparkPoints = sparkValues("seo");
                return (
                  // A link, not a button: the MVP project card is an anchor, and this
                  // way it supports open in new tab, middle click and copy link.
                  <Link
                    key={project.project_id}
                    href={`/dashboard/projects/${project.project_id}`}
                    className="flex flex-col gap-4 rounded-(--r) border border-(--line) bg-(--panel) p-5 text-left transition-[border-color,box-shadow,transform] duration-200 hover:-translate-y-0.5 hover:border-(--line-btn-hover) hover:shadow-[0_8px_26px_-18px_rgba(12,15,22,0.28)]"
                  >
                    <div className="flex items-center gap-[11px]">
                      <div
                        className="flex h-[34px] w-[34px] flex-none items-center justify-center rounded-[9px] font-(family-name:--disp) text-[15px] font-bold text-white"
                        style={{
                          backgroundColor:
                            PROJECT_FAV_COLORS[projectIndex % PROJECT_FAV_COLORS.length],
                        }}
                      >
                        {fav}
                      </div>
                      <div className="min-w-0 flex-1">
                        <b className="block font-(family-name:--disp) text-[14.5px] leading-[19px] font-bold tracking-[-0.01em]">
                          {project.display_name}
                        </b>
                        <small className="mt-px block font-(family-name:--font-roboto-mono) text-[11.5px] leading-[15px] text-(--t-3)">
                          {domainLabel}
                        </small>
                      </div>
                      {hasScores ? (
                        <span className="inline-flex flex-none items-center gap-1.5 rounded-[999px] bg-(--good-s) px-[9px] py-1 font-(family-name:--font-roboto-mono) text-[10px] leading-[13px] tracking-[0.05em] text-(--good)">
                          <span className="signal-pulse-dot h-[5px] w-[5px] rounded-[50%] bg-(--good)" />
                          {t("wsOverview.monitoring")}
                        </span>
                      ) : null}
                    </div>
                    <div className="flex flex-col gap-3 border-t border-t-(--line-2) pt-3.5">
                      <div className="flex items-center gap-[13px]">
                        <div className="relative h-[58px] w-[58px] flex-none">
                          <svg className="h-[58px] w-[58px] -rotate-90" viewBox="0 0 84 84">
                            <circle
                              cx="42"
                              cy="42"
                              r="34"
                              fill="none"
                              stroke="var(--line)"
                              strokeWidth="8"
                            />
                            <circle
                              cx="42"
                              cy="42"
                              r="34"
                              fill="none"
                              stroke="url(#gAIOw)"
                              strokeWidth="8"
                              strokeLinecap="round"
                              strokeDasharray={213.63}
                              strokeDashoffset={213.63 * (1 - (aio ?? 0) / 100)}
                              data-signal-enter="ring"
                            />
                          </svg>
                          <div
                            className="absolute inset-0 flex items-center justify-center font-(family-name:--disp) text-[16px] font-black tracking-[-0.02em]"
                            data-signal-enter="count"
                            data-signal-count={aio ?? undefined}
                          >
                            {aio ?? "-"}
                          </div>
                        </div>
                        <div className="flex min-w-[50px] flex-none flex-col gap-[3px]">
                          <span className="font-(family-name:--font-roboto-mono) text-[10.5px] uppercase tracking-[0.1em] text-(--t-3)">
                            AIO
                          </span>
                          {aioDelta ? (
                            <span
                              className={cx(
                                "font-(family-name:--font-roboto-mono) text-[11.5px] font-semibold",
                                aioDelta.cls
                              )}
                            >
                              {aioDelta.text}
                            </span>
                          ) : null}
                        </div>
                        {aioSparkPoints.length >= 2 ? (
                          <ProjectScoreSparkline points={aioSparkPoints} color={AIO_TREND_COLOR} />
                        ) : null}
                      </div>
                      <div className="flex items-center gap-[13px]">
                        <div className="relative h-[58px] w-[58px] flex-none">
                          <svg className="h-[58px] w-[58px] -rotate-90" viewBox="0 0 84 84">
                            <circle
                              cx="42"
                              cy="42"
                              r="34"
                              fill="none"
                              stroke="var(--line)"
                              strokeWidth="8"
                            />
                            <circle
                              cx="42"
                              cy="42"
                              r="34"
                              fill="none"
                              stroke="var(--blue)"
                              strokeWidth="8"
                              strokeLinecap="round"
                              strokeDasharray={213.63}
                              strokeDashoffset={213.63 * (1 - (seo ?? 0) / 100)}
                              data-signal-enter="ring"
                            />
                          </svg>
                          <div
                            className="absolute inset-0 flex items-center justify-center font-(family-name:--disp) text-[16px] font-black tracking-[-0.02em]"
                            data-signal-enter="count"
                            data-signal-count={seo ?? undefined}
                          >
                            {seo ?? "-"}
                          </div>
                        </div>
                        <div className="flex min-w-[50px] flex-none flex-col gap-[3px]">
                          <span className="font-(family-name:--font-roboto-mono) text-[10.5px] uppercase tracking-[0.1em] text-(--t-3)">
                            SEO
                          </span>
                          {seoDelta ? (
                            <span
                              className={cx(
                                "font-(family-name:--font-roboto-mono) text-[11.5px] font-semibold",
                                seoDelta.cls
                              )}
                            >
                              {seoDelta.text}
                            </span>
                          ) : null}
                        </div>
                        {seoSparkPoints.length >= 2 ? (
                          <ProjectScoreSparkline points={seoSparkPoints} color="#2563EB" />
                        ) : null}
                      </div>
                    </div>
                    <div className="mt-auto flex items-center justify-between border-t border-t-(--line-2) pt-3.5 text-[12.5px] leading-[15px] text-(--t-2)">
                      <span>{scanned}</span>
                      <span className="inline-flex items-center gap-[5px] font-semibold text-(--blue)">
                        {t("wsOverview.openProject")}
                        <ChevronRight aria-hidden="true" className="h-3.5 w-3.5" />
                      </span>
                    </div>
                  </Link>
                );
              })}
              {/* globals.css `button:not(.rounded-full)` is unlayered and beats
                  utility radii, so the approved 16px goes through inline style. */}
              <button
                type="button"
                style={{ borderRadius: "var(--r)" }}
                /* `col-start-1` (SIGV2-1121): the tile stays one card wide but
                   always opens its own row. Pinning only its column start
                   makes auto-placement move to the next row whenever the
                   cursor has passed column 1, at every column count this
                   auto-fill grid reflows through, and leaves it where it is
                   when the cursor is already at column 1 (no projects, or a
                   single-column grid), so it never leaves an empty cell above
                   itself.
                   `self-start`: the approved `.padd` is 365x123, its own
                   content height, so the tile keeps that height instead of
                   stretching to the row and reading as an empty panel. */
                className="col-start-1 flex cursor-pointer flex-col items-center justify-center gap-2 self-start border-[1.5px] border-dashed border-(--line) bg-transparent px-5 py-6 text-center font-(family-name:--body-font) text-(--t-3) transition-[border-color,color] duration-150 hover:border-(--purple) hover:text-(--purple)"
                onClick={() => setCreateModalOpen(true)}
              >
                <svg
                  className="h-6 w-6 flex-none [stroke-width:1.8]"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                >
                  <path d="M12 5v14M5 12h14" />
                </svg>
                <b className="font-(family-name:--disp) text-[14px] leading-[18px] font-bold text-(--t-1)">
                  {t("wsOverview.addProject")}
                </b>
                <span className="text-[12.5px] leading-4 text-(--t-3)">
                  {t("wsOverview.addProjectSub")}
                </span>
              </button>
            </div>
            {settings.error ? (
              <SignalAlert tone="danger" title={t("alerts.errorTitle")}>
                <p>{settings.error}</p>
                <button
                  type="button"
                  className="inline-flex h-[38px] min-h-11 cursor-pointer items-center gap-2 rounded-[10px] border border-(--line) bg-(--panel) px-[15px] font-(family-name:--body-font) text-[13.5px] font-semibold text-(--t-1) hover:border-[#D7DAE0]"
                  onClick={() => void settings.reload()}
                >
                  {t("common.tryAgain")}
                </button>
              </SignalAlert>
            ) : null}
          </section>

          {shouldShowChecklist ? (
            <GettingStartedChecklist
              items={checklistItems}
              onDismiss={() => {
                void dismissOnboarding();
              }}
            />
          ) : null}

          <PasskeySetupPrompt />
        </div>
      )}
    </WorkspacePageFrame>
  );
}
