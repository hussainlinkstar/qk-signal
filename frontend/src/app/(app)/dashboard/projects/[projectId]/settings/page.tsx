"use client";

import React, { useState, useEffect, useMemo, useCallback, useRef } from "react";
import { useParams, useRouter } from "next/navigation";
import { useTranslation } from "react-i18next";
import { Settings, Sparkles, ArrowRight } from "lucide-react";
import { useAuth } from "@/components/auth/custom-auth";
import DashboardPageIntro from "@/components/dashboard/DashboardPageIntro";
import SignalCrumb from "@/components/signal/SignalCrumb";
import { SkelCard, SkelPagehead } from "@/components/signal/SignalSkeleton";
import { useWorkspacePageHeader } from "@/components/dashboard/workspacePageHeader";
import SignalTabs, { SignalTabPanel } from "@/components/signal/SignalTabs";
import Modal from "@/components/ui/Modal";
import {
  createProjectMagicLink,
  deleteProjectBudget,
  deleteProjectById,
  deleteProjectDataSource,
  fetchProjectBudget,
  fetchProjectById,
  fetchProjectDataSourceCatalog,
  fetchProjectDataSources,
  fetchProjectMagicLinkStatus,
  generateProjectSmartProfile,
  ProjectBudgetSummary,
  ProjectDataSourceAssignment,
  ProjectDataSourceType,
  ProjectMagicLinkStatus,
  upsertProjectBudget,
  upsertProjectDataSource,
  updateProjectById,
} from "@/services/workspaceService";
import { GLOBAL_TARGET_MARKET, toTargetCountry } from "@/lib/targetMarket";

import BrandGuardrailsSection from "./sections/BrandGuardrailsSection";
import BudgetSection from "./sections/BudgetSection";
import ConnectedDataSection, {
  DATA_SOURCE_ORDER,
  type ConnectedDataMessage,
  type ProjectDataSourceCatalogState,
  type ProjectDataSourceDraft,
} from "./sections/ConnectedDataSection";
import ProjectCompetitorManager from "@/components/settings/ProjectCompetitorManager";

import DeleteProjectSection from "./sections/DeleteProjectSection";
import LearningsSection from "./sections/LearningsSection";
import MonitoringAlertsSection from "./sections/MonitoringAlertsSection";
import MonitoringSection from "./sections/MonitoringSection";
import PlanProgressSection from "./sections/PlanProgressSection";
import ProjectDetailsSection, { type ProjectSettingsState } from "./sections/ProjectDetailsSection";
import ScoreTargetsSection from "./sections/ScoreTargetsSection";
import TrackedCompetitorsSection from "./sections/TrackedCompetitorsSection";
import TrackedPromptsSection from "./sections/TrackedPromptsSection";

const DEFAULT_PROJECT_SETTINGS: ProjectSettingsState = {
  name: "",
  domainUrl: "",
  targetCountry: "",
  language: "en",
  icpRoles: [],
  painPoints: "",
  usp: "",
  priorityPulseTags: "",
  smeProfiles: "",
};

const REQUIRED_AI_FIELDS = [
  { key: "name", labelKey: "signalProjectSettings.requiredField.name" },
  { key: "domainUrl", labelKey: "signalProjectSettings.requiredField.domain" },
  { key: "targetCountry", labelKey: "signalProjectSettings.requiredField.market" },
  { key: "language", labelKey: "signalProjectSettings.requiredField.language" },
] as const;

const splitLinesOrComma = (value: string) =>
  value
    .split(/[\n,]/g)
    .map((item) => item.trim())
    .filter(Boolean);

const DEFAULT_DATA_SOURCE_DRAFT: ProjectDataSourceDraft = {
  bindingMode: "workspace",
  sourceId: "",
  sourceLabel: "",
  // Choosing a source and saving it means the user wants it used, so a fresh
  // binding is active. Switching off stays possible via the row checkbox, it
  // is just never the silent default.
  isActive: true,
};

const EMPTY_DATA_SOURCE_DRAFTS: Record<ProjectDataSourceType, ProjectDataSourceDraft> = {
  google_search_console: { ...DEFAULT_DATA_SOURCE_DRAFT },
  google_analytics_4: { ...DEFAULT_DATA_SOURCE_DRAFT },
  bing_webmaster: { ...DEFAULT_DATA_SOURCE_DRAFT },
};

const EMPTY_CATALOG: ProjectDataSourceCatalogState = {
  loading: false,
  error: null,
  items: [],
  requiredScopes: [],
  grantedScopes: [],
  missingScopes: [],
  connectedOnOtherWorkspace: false,
};

const EMPTY_SOURCE_CATALOGS: Record<ProjectDataSourceType, ProjectDataSourceCatalogState> = {
  google_search_console: { ...EMPTY_CATALOG },
  google_analytics_4: { ...EMPTY_CATALOG },
  bing_webmaster: { ...EMPTY_CATALOG },
};

const buildDraftFromAssignment = (
  assignment: ProjectDataSourceAssignment | undefined
): ProjectDataSourceDraft => {
  if (!assignment) {
    return { ...DEFAULT_DATA_SOURCE_DRAFT };
  }
  return {
    bindingMode: assignment.binding_mode,
    sourceId: assignment.source_id || "",
    sourceLabel: assignment.source_label || "",
    // A real bound row preserves its deliberate off state; an unbound stub
    // (the backend returns rows with no source_id for not-yet-bound types)
    // defaults to active so a fresh pick never saves silently inactive.
    isActive: assignment.source_id ? assignment.is_active : true,
  };
};

/* SIGV2-1171: the Connected data card's outcomes carry their tone with them,
   so a refusal is drawn as a refusal instead of sharing one grey paragraph
   with every confirmation. Two constructors rather than a literal at each of
   the nineteen call sites, so a new site cannot forget the tone. */
const connectedOk = (text: string): ConnectedDataMessage => ({ tone: "success", text });
const connectedFail = (text: string): ConnectedDataMessage => ({ tone: "danger", text });
const connectedInfo = (text: string): ConnectedDataMessage => ({ tone: "info", text });

export default function ProjectSettingsPage() {
  const router = useRouter();
  const params = useParams<{ projectId: string }>();
  const { t } = useTranslation();
  const { getToken, isLoading: authLoading, isSignedIn } = useAuth();
  const [activeTab, setActiveTab] = useState<"product" | "brand">("product");
  const [form, setForm] = useState<ProjectSettingsState>(DEFAULT_PROJECT_SETTINGS);
  const [loadingProject, setLoadingProject] = useState(true);
  const [savingProject, setSavingProject] = useState(false);
  const [generatingSmartProfile, setGeneratingSmartProfile] = useState(false);
  const [customRoleInput, setCustomRoleInput] = useState("");
  const [projectMessage, setProjectMessage] = useState<string | null>(null);
  const [smartProfileModal, setSmartProfileModal] = useState<{
    open: boolean;
    title: string;
    message: string;
    showAuditCta: boolean;
  }>({
    open: false,
    title: "",
    message: "",
    showAuditCta: false,
  });
  const [magicLinkMessage, setMagicLinkMessage] = useState<ConnectedDataMessage | null>(null);
  const [magicLinkUrl, setMagicLinkUrl] = useState<string | null>(null);
  const [isGeneratingMagicLink, setIsGeneratingMagicLink] = useState(false);
  const [magicLinkStatus, setMagicLinkStatus] = useState<ProjectMagicLinkStatus | null>(null);
  const [loadingMagicLinkStatus, setLoadingMagicLinkStatus] = useState(false);
  const [workspaceId, setWorkspaceId] = useState<number | null>(null);
  const [projectBudget, setProjectBudget] = useState<ProjectBudgetSummary | null>(null);
  const [loadingProjectBudget, setLoadingProjectBudget] = useState(false);
  const [savingProjectBudget, setSavingProjectBudget] = useState(false);
  const [projectBudgetError, setProjectBudgetError] = useState<string | null>(null);
  const [projectBudgetMessage, setProjectBudgetMessage] = useState<string | null>(null);
  const [projectBudgetLimitInput, setProjectBudgetLimitInput] = useState("");
  const [projectBudgetAnchorDay, setProjectBudgetAnchorDay] = useState(1);
  const [dataSources, setDataSources] = useState<ProjectDataSourceAssignment[]>([]);
  const [dataSourceDrafts, setDataSourceDrafts] =
    useState<Record<ProjectDataSourceType, ProjectDataSourceDraft>>(EMPTY_DATA_SOURCE_DRAFTS);
  const [sourceCatalogs, setSourceCatalogs] =
    useState<Record<ProjectDataSourceType, ProjectDataSourceCatalogState>>(EMPTY_SOURCE_CATALOGS);
  const [dataSourceMessage, setDataSourceMessage] = useState<ConnectedDataMessage | null>(null);
  const [activeDataSourceAction, setActiveDataSourceAction] = useState<string | null>(null);
  const [deleteConfirmName, setDeleteConfirmName] = useState("");
  const [deleteProjectMessage, setDeleteProjectMessage] = useState<string | null>(null);
  const [deletingProject, setDeletingProject] = useState(false);

  // `loadProject` used to depend on `dataSources.length`, so the first
  // successful load changed the callback, re-ran the effect, and put the page
  // back into its full-screen loading state for a second round trip. The count
  // is only read inside the error branch, so it is held in a ref instead.
  const dataSourceCountRef = useRef(0);

  const projectId = useMemo(() => params?.projectId ?? "", [params?.projectId]);
  // Approved `.top` crumb (Dashboard > Settings) inside the shared
  // SignalTopBar, registered via the page-header context.
  const { setHeader } = useWorkspacePageHeader();
  const topCrumb = useMemo(
    () => (
      <SignalCrumb
        items={[
          { label: t("nav.dashboard"), href: `/dashboard/projects/${projectId}` },
          { label: t("signalProjectSettings.page.title") },
        ]}
      />
    ),
    [t, projectId]
  );
  useEffect(() => {
    setHeader({ crumb: topCrumb });
    return () => setHeader(null);
  }, [setHeader, topCrumb]);
  const interactionDisabled = authLoading || !isSignedIn;
  const aiMissingRequiredFields = useMemo(
    () =>
      REQUIRED_AI_FIELDS.filter((field) => {
        const value = form[field.key];
        return typeof value !== "string" || !value.trim();
      }).map((field) => t(field.labelKey)),
    [form, t]
  );

  const sourceName = useCallback(
    (sourceType: ProjectDataSourceType) =>
      t(`signalProjectSettings.connectedData.sourceName.${sourceType}`),
    [t]
  );

  const getAuthHeaders = useCallback(async (): Promise<HeadersInit> => {
    const token = await getToken();
    if (!token) {
      throw new Error(t("signalProjectSettings.page.signedOutProject"));
    }
    return { Authorization: `Bearer ${token}` };
  }, [getToken, t]);

  const loadProjectDataSources = useCallback(
    async (headers: HeadersInit) => {
      if (!projectId) {
        return;
      }
      const assignments = await fetchProjectDataSources(projectId, headers);
      dataSourceCountRef.current = assignments.length;
      setDataSources(assignments);
      setDataSourceDrafts({
        google_search_console: buildDraftFromAssignment(
          assignments.find((item) => item.source_type === "google_search_console")
        ),
        google_analytics_4: buildDraftFromAssignment(
          assignments.find((item) => item.source_type === "google_analytics_4")
        ),
        bing_webmaster: buildDraftFromAssignment(
          assignments.find((item) => item.source_type === "bing_webmaster")
        ),
      });
    },
    [projectId]
  );

  const updateDataSourceDraft = useCallback(
    (
      sourceType: ProjectDataSourceType,
      field: keyof ProjectDataSourceDraft,
      value: string | boolean
    ) => {
      setDataSourceDrafts((current) => ({
        ...current,
        [sourceType]: {
          ...current[sourceType],
          [field]: value,
        },
      }));
    },
    []
  );

  const loadSourceCatalogForType = useCallback(
    async (sourceType: ProjectDataSourceType, headers: HeadersInit): Promise<boolean> => {
      if (!projectId) {
        return false;
      }
      setSourceCatalogs((current) => ({
        ...current,
        [sourceType]: { ...current[sourceType], loading: true, error: null },
      }));
      try {
        const payload = await fetchProjectDataSourceCatalog(projectId, sourceType, headers);
        const autoSelectCandidate = payload.items.length === 1 ? payload.items[0] : null;

        if (autoSelectCandidate) {
          setDataSourceDrafts((current) => {
            const currentDraft = current[sourceType];
            if (currentDraft.bindingMode !== "workspace" || currentDraft.sourceId.trim()) {
              return current;
            }
            return {
              ...current,
              [sourceType]: {
                ...currentDraft,
                sourceId: autoSelectCandidate.id,
                sourceLabel: autoSelectCandidate.label || currentDraft.sourceLabel,
              },
            };
          });
        }

        setSourceCatalogs((current) => ({
          ...current,
          [sourceType]: {
            loading: false,
            error: payload.error || null,
            items: payload.items,
            requiredScopes: payload.required_scopes || [],
            grantedScopes: payload.granted_scopes || [],
            missingScopes: payload.missing_scopes || [],
            connectedOnOtherWorkspace: payload.connected_on_other_workspace === true,
          },
        }));
        return !payload.error;
      } catch (error) {
        setSourceCatalogs((current) => ({
          ...current,
          [sourceType]: {
            ...EMPTY_CATALOG,
            error:
              error instanceof Error
                ? error.message
                : t("signalProjectSettings.connectedData.refreshFailed"),
          },
        }));
        return false;
      }
    },
    [projectId, t]
  );

  const loadAllSourceCatalogs = useCallback(
    async (headers: HeadersInit) => {
      await Promise.all(
        DATA_SOURCE_ORDER.map(async (sourceType) => {
          await loadSourceCatalogForType(sourceType, headers);
        })
      );
    },
    [loadSourceCatalogForType]
  );

  const loadMagicLinkStatus = useCallback(
    async (headers: HeadersInit) => {
      if (!projectId) {
        return;
      }
      setLoadingMagicLinkStatus(true);
      try {
        const payload = await fetchProjectMagicLinkStatus(projectId, headers);
        setMagicLinkStatus(payload);
      } catch {
        setMagicLinkStatus(null);
      } finally {
        setLoadingMagicLinkStatus(false);
      }
    },
    [projectId]
  );

  const applyProjectBudgetState = useCallback((payload: ProjectBudgetSummary) => {
    setProjectBudget(payload);
    setProjectBudgetLimitInput(
      payload.monthly_limit_scans === null || payload.monthly_limit_scans === undefined
        ? ""
        : String(payload.monthly_limit_scans)
    );
    setProjectBudgetAnchorDay(payload.cycle_anchor_day || 1);
  }, []);

  const loadProjectBudget = useCallback(
    async (nextWorkspaceId: number, headers: HeadersInit) => {
      if (!projectId) {
        return;
      }
      setLoadingProjectBudget(true);
      setProjectBudgetError(null);
      try {
        const payload = await fetchProjectBudget(nextWorkspaceId, projectId, headers);
        applyProjectBudgetState(payload);
      } catch (error) {
        setProjectBudgetError(
          error instanceof Error ? error.message : t("signalProjectSettings.budget.loadFailed")
        );
        setProjectBudget(null);
      } finally {
        setLoadingProjectBudget(false);
      }
    },
    [applyProjectBudgetState, projectId, t]
  );

  const loadProject = useCallback(async () => {
    if (!projectId || authLoading) {
      setLoadingProject(false);
      return;
    }
    if (!isSignedIn) {
      setLoadingProject(false);
      setProjectMessage(t("signalProjectSettings.page.signedOutProject"));
      setDataSourceMessage(connectedInfo(t("signalProjectSettings.page.signedOutDataSources")));
      dataSourceCountRef.current = 0;
      setDataSources([]);
      setMagicLinkStatus(null);
      return;
    }

    setLoadingProject(true);
    setProjectMessage(null);
    setProjectBudgetMessage(null);
    setProjectBudgetError(null);
    setDataSourceMessage(null);
    try {
      const headers = await getAuthHeaders();
      const project = await fetchProjectById(projectId, headers);
      setWorkspaceId(project.workspace_id);
      setForm({
        name: project.name,
        domainUrl: project.domain_url || "",
        targetCountry: project.target_country || GLOBAL_TARGET_MARKET,
        language: project.language || "en",
        icpRoles: project.icp_roles || [],
        painPoints: project.pain_points || "",
        usp: project.usp || "",
        priorityPulseTags: (project.priority_pulse_tags || []).join(", "),
        smeProfiles: (project.sme_profiles || []).join("\n"),
      });
      await Promise.all([
        loadProjectDataSources(headers),
        loadAllSourceCatalogs(headers),
        loadMagicLinkStatus(headers),
        loadProjectBudget(project.workspace_id, headers),
      ]);
    } catch (error) {
      const message =
        error instanceof Error ? error.message : t("signalProjectSettings.page.loadFailed");
      setProjectMessage(message);
      if (!dataSourceCountRef.current) {
        setDataSourceMessage(connectedFail(message));
      }
    } finally {
      setLoadingProject(false);
    }
  }, [
    authLoading,
    getAuthHeaders,
    isSignedIn,
    loadAllSourceCatalogs,
    loadMagicLinkStatus,
    loadProjectBudget,
    loadProjectDataSources,
    projectId,
    t,
  ]);

  useEffect(() => {
    void loadProject();
  }, [loadProject]);

  const toggleIcpRole = (role: string) => {
    setForm((current) => {
      const exists = current.icpRoles.includes(role);
      return {
        ...current,
        icpRoles: exists
          ? current.icpRoles.filter((item) => item !== role)
          : [...current.icpRoles, role],
      };
    });
  };

  const addCustomIcpRole = () => {
    const role = customRoleInput.trim();
    if (!role) return;
    if (!form.icpRoles.includes(role)) {
      setForm((current) => ({
        ...current,
        icpRoles: [...current.icpRoles, role],
      }));
    }
    setCustomRoleInput("");
  };

  const closeSmartProfileModal = useCallback(() => {
    setSmartProfileModal((current) => ({ ...current, open: false }));
  }, []);

  const goToAuditWorkspace = useCallback(() => {
    setSmartProfileModal((current) => ({ ...current, open: false }));
    router.push(`/dashboard/audit?projectId=${projectId}&tier=smart&tab=overview`);
  }, [projectId, router]);

  const saveProjectSettings = async () => {
    if (!projectId) {
      setProjectMessage(t("signalProjectSettings.page.missingProject"));
      return;
    }

    setSavingProject(true);
    setProjectMessage(null);
    try {
      const headers = await getAuthHeaders();
      const payload = {
        name: form.name.trim(),
        domain_url: form.domainUrl.trim() || null,
        target_country: toTargetCountry(form.targetCountry),
        language: form.language.trim().toLowerCase() || "en",
        icp_roles: form.icpRoles,
        pain_points: form.painPoints.trim() || null,
        usp: form.usp.trim() || null,
        priority_pulse_tags: splitLinesOrComma(form.priorityPulseTags),
        sme_profiles: splitLinesOrComma(form.smeProfiles),
      };
      await updateProjectById(projectId, payload, headers);
      setProjectMessage(t("signalProjectSettings.projectDetails.saved"));
      await loadProject();
    } catch (error) {
      setProjectMessage(
        error instanceof Error
          ? error.message
          : t("signalProjectSettings.projectDetails.saveFailed")
      );
    } finally {
      setSavingProject(false);
    }
  };

  const generateSmartProfileWithAI = async () => {
    if (!projectId) {
      setProjectMessage(t("signalProjectSettings.page.missingProject"));
      return;
    }

    if (aiMissingRequiredFields.length > 0) {
      setProjectMessage(
        t("signalProjectSettings.projectDetails.missingFields", {
          fields: aiMissingRequiredFields.join(", "),
        })
      );
      return;
    }

    setGeneratingSmartProfile(true);
    setProjectMessage(null);
    try {
      const headers = await getAuthHeaders();
      const generated = await generateProjectSmartProfile(
        projectId,
        { overwrite_existing: true },
        headers
      );
      const project = generated.project;
      setForm({
        name: project.name,
        domainUrl: project.domain_url || "",
        targetCountry: project.target_country || GLOBAL_TARGET_MARKET,
        language: project.language || "en",
        icpRoles: project.icp_roles || [],
        painPoints: project.pain_points || "",
        usp: project.usp || "",
        priorityPulseTags: (project.priority_pulse_tags || []).join(", "),
        smeProfiles: (project.sme_profiles || []).join("\n"),
      });
      if (generated.generated_fields.length === 0) {
        const hasLatestAuditEvidence = generated.grounded_sources.includes("latest_project_audit");
        setProjectMessage(null);
        setSmartProfileModal({
          open: true,
          title: t("signalProjectSettings.projectDetails.groundedTitle"),
          message: hasLatestAuditEvidence
            ? t("signalProjectSettings.projectDetails.groundedWithAudit")
            : t("signalProjectSettings.projectDetails.groundedWithoutAudit"),
          showAuditCta: true,
        });
      } else {
        setSmartProfileModal((current) => ({ ...current, open: false }));
        setProjectMessage(
          t("signalProjectSettings.projectDetails.generatedSummary", {
            updated: generated.generated_fields.length,
            skipped: generated.skipped_fields.length,
          })
        );
      }
    } catch (error) {
      setProjectMessage(
        error instanceof Error
          ? error.message
          : t("signalProjectSettings.projectDetails.generateFailed")
      );
    } finally {
      setGeneratingSmartProfile(false);
    }
  };

  const saveProjectDataSource = async (sourceType: ProjectDataSourceType) => {
    if (!projectId) {
      setDataSourceMessage(connectedFail(t("signalProjectSettings.page.missingProject")));
      return;
    }

    setActiveDataSourceAction(`${sourceType}:save`);
    setDataSourceMessage(null);
    try {
      const headers = await getAuthHeaders();
      const draft = dataSourceDrafts[sourceType];
      await upsertProjectDataSource(
        projectId,
        sourceType,
        {
          binding_mode: draft.bindingMode,
          source_id: draft.sourceId.trim() || null,
          source_label: draft.sourceLabel.trim() || null,
          is_active: draft.isActive,
        },
        headers
      );
      setDataSourceMessage(
        connectedOk(
          t("signalProjectSettings.connectedData.savedMessage", {
            source: sourceName(sourceType),
          })
        )
      );
      await loadProjectDataSources(headers);
    } catch (error) {
      setDataSourceMessage(
        connectedFail(
          error instanceof Error
            ? error.message
            : t("signalProjectSettings.connectedData.saveFailed")
        )
      );
    } finally {
      setActiveDataSourceAction(null);
    }
  };

  const clearProjectDataSource = async (sourceType: ProjectDataSourceType) => {
    if (!projectId) {
      setDataSourceMessage(connectedFail(t("signalProjectSettings.page.missingProject")));
      return;
    }

    setActiveDataSourceAction(`${sourceType}:clear`);
    setDataSourceMessage(null);
    try {
      const headers = await getAuthHeaders();
      await deleteProjectDataSource(projectId, sourceType, headers);
      setDataSourceMessage(
        connectedOk(
          t("signalProjectSettings.connectedData.removedMessage", {
            source: sourceName(sourceType),
          })
        )
      );
      await loadProjectDataSources(headers);
    } catch (error) {
      setDataSourceMessage(
        connectedFail(
          error instanceof Error
            ? error.message
            : t("signalProjectSettings.connectedData.removeFailed")
        )
      );
    } finally {
      setActiveDataSourceAction(null);
    }
  };

  const refreshSourceCatalog = async (sourceType: ProjectDataSourceType) => {
    if (!projectId) {
      setDataSourceMessage(connectedFail(t("signalProjectSettings.page.missingProject")));
      return;
    }
    setActiveDataSourceAction(`${sourceType}:catalog`);
    setDataSourceMessage(null);
    try {
      const headers = await getAuthHeaders();
      const ok = await loadSourceCatalogForType(sourceType, headers);
      setDataSourceMessage(
        ok
          ? connectedOk(
              t("signalProjectSettings.connectedData.refreshedMessage", {
                source: sourceName(sourceType),
              })
            )
          : connectedFail(
              t("signalProjectSettings.connectedData.refreshFailedMessage", {
                source: sourceName(sourceType),
              })
            )
      );
    } catch (error) {
      setDataSourceMessage(
        connectedFail(
          error instanceof Error
            ? error.message
            : t("signalProjectSettings.connectedData.refreshFailed")
        )
      );
    } finally {
      setActiveDataSourceAction(null);
    }
  };

  const selectSourceAccount = (sourceType: ProjectDataSourceType, nextSourceId: string) => {
    const selected = sourceCatalogs[sourceType].items.find((item) => item.id === nextSourceId);
    setDataSourceDrafts((current) => ({
      ...current,
      [sourceType]: {
        ...current[sourceType],
        sourceId: nextSourceId,
        sourceLabel: selected?.label || current[sourceType].sourceLabel,
        isActive: true,
      },
    }));
  };

  const generateMagicLink = async () => {
    if (!projectId) {
      setMagicLinkMessage(connectedFail(t("signalProjectSettings.page.missingProject")));
      return;
    }

    setIsGeneratingMagicLink(true);
    setMagicLinkMessage(null);
    setMagicLinkUrl(null);
    try {
      const headers = await getAuthHeaders();
      const payload = await createProjectMagicLink(projectId, 72, headers);
      setMagicLinkUrl(payload.link_url);
      setMagicLinkMessage(connectedOk(t("signalProjectSettings.handshake.generated")));
      await loadMagicLinkStatus(headers);
    } catch (error) {
      setMagicLinkMessage(
        connectedFail(
          error instanceof Error ? error.message : t("signalProjectSettings.handshake.failed")
        )
      );
    } finally {
      setIsGeneratingMagicLink(false);
    }
  };

  const deleteProject = async () => {
    if (!projectId) {
      setDeleteProjectMessage(t("signalProjectSettings.page.missingProject"));
      return;
    }

    if (deleteConfirmName.trim() !== form.name.trim()) {
      setDeleteProjectMessage(t("signalProjectSettings.deleteProject.mismatch"));
      return;
    }

    setDeletingProject(true);
    setDeleteProjectMessage(null);
    try {
      const headers = await getAuthHeaders();
      await deleteProjectById(projectId, headers);
      setDeleteProjectMessage(t("signalProjectSettings.deleteProject.deleted"));
      router.push("/dashboard");
    } catch (error) {
      setDeleteProjectMessage(
        error instanceof Error ? error.message : t("signalProjectSettings.deleteProject.failed")
      );
    } finally {
      setDeletingProject(false);
    }
  };

  const removeProjectBudgetGuardrail = async () => {
    if (!projectId || workspaceId === null) {
      setProjectBudgetError(t("signalProjectSettings.budget.contextMissing"));
      return;
    }

    setSavingProjectBudget(true);
    setProjectBudgetError(null);
    setProjectBudgetMessage(null);
    try {
      const headers = await getAuthHeaders();
      const payload = await deleteProjectBudget(workspaceId, projectId, headers);
      applyProjectBudgetState(payload);
      setProjectBudgetMessage(t("signalProjectSettings.budget.removed"));
    } catch (error) {
      setProjectBudgetError(
        error instanceof Error ? error.message : t("signalProjectSettings.budget.removeFailed")
      );
    } finally {
      setSavingProjectBudget(false);
    }
  };

  const saveProjectBudget = async () => {
    if (!projectId || workspaceId === null) {
      setProjectBudgetError(t("signalProjectSettings.budget.contextMissing"));
      return;
    }

    const normalizedValue = projectBudgetLimitInput.trim();
    if (!normalizedValue) {
      if (projectBudget?.budget_configured) {
        await removeProjectBudgetGuardrail();
        return;
      }
      setProjectBudgetError(t("signalProjectSettings.budget.enterLimit"));
      return;
    }

    const parsedLimit = Number(normalizedValue);
    if (!Number.isFinite(parsedLimit) || parsedLimit < 0 || !Number.isInteger(parsedLimit)) {
      setProjectBudgetError(t("signalProjectSettings.budget.wholeNumber"));
      return;
    }

    setSavingProjectBudget(true);
    setProjectBudgetError(null);
    setProjectBudgetMessage(null);
    try {
      const headers = await getAuthHeaders();
      const payload = await upsertProjectBudget(
        workspaceId,
        projectId,
        {
          monthly_limit_scans: parsedLimit,
          cycle_anchor_day: projectBudgetAnchorDay,
        },
        headers
      );
      applyProjectBudgetState(payload);
      setProjectBudgetMessage(
        parsedLimit === 0
          ? t("signalProjectSettings.budget.savedBlocked")
          : t("signalProjectSettings.budget.saved")
      );
    } catch (error) {
      setProjectBudgetError(
        error instanceof Error ? error.message : t("signalProjectSettings.budget.saveFailed")
      );
    } finally {
      setSavingProjectBudget(false);
    }
  };

  if (loadingProject) {
    return (
      <div
        role="status"
        aria-label={t("signalProjectSettings.page.loading")}
        className="flex flex-col gap-5"
      >
        <SkelPagehead />
        <SkelCard />
        <SkelCard />
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-[22px]">
      <DashboardPageIntro icon={Settings} title={t("signalProjectSettings.page.title")}>
        {t("signalProjectSettings.page.intro")}
      </DashboardPageIntro>

      <SignalTabs<"product" | "brand">
        tabs={[
          { id: "product", label: t("signalProjectSettings.tabs.product") },
          { id: "brand", label: t("signalProjectSettings.tabs.brand") },
        ]}
        activeId={activeTab}
        onChange={setActiveTab}
      />

      {/* SIGV2-1039: the approved Product Settings tab is a two-column
          `.setgrid` of four cards, not a stack of five full-width ones. The
          stack rendered the same content at 2.2x the design's page height,
          which was the single largest contributor to this screen's divergence.
          Tracked prompts sits inside the Tracked-competitors card, as it does
          in the design. */}
      <SignalTabPanel id="product" activeId={activeTab} className="grid gap-4 md:grid-cols-2">
        <ScoreTargetsSection projectId={projectId} />
        <TrackedCompetitorsSection
          projectId={projectId}
          onAddCompetitor={() => {
            setActiveTab("brand");
            window.setTimeout(() => {
              document.getElementById("competitive-intelligence")?.scrollIntoView({
                block: "start",
              });
              document.getElementById("competitor-target-url")?.focus();
            }, 350);
          }}
        >
          <TrackedPromptsSection projectId={projectId} bare />
        </TrackedCompetitorsSection>
        <ConnectedDataSection
          assignments={dataSources}
          drafts={dataSourceDrafts}
          catalogs={sourceCatalogs}
          activeAction={activeDataSourceAction}
          interactionDisabled={interactionDisabled}
          message={dataSourceMessage}
          onDraftChange={updateDataSourceDraft}
          onAccountSelect={selectSourceAccount}
          onRefresh={refreshSourceCatalog}
          onSave={saveProjectDataSource}
          onRemove={clearProjectDataSource}
          magicLinkStatus={magicLinkStatus}
          loadingMagicLinkStatus={loadingMagicLinkStatus}
          magicLinkMessage={magicLinkMessage}
          magicLinkUrl={magicLinkUrl}
          generatingMagicLink={isGeneratingMagicLink}
          onGenerateMagicLink={generateMagicLink}
        />
        <MonitoringSection />
      </SignalTabPanel>

      <SignalTabPanel id="brand" activeId={activeTab}>
        <ProjectDetailsSection
          form={form}
          onFormChange={(patch) => setForm((current) => ({ ...current, ...patch }))}
          customRole={customRoleInput}
          onCustomRoleChange={setCustomRoleInput}
          onAddCustomRole={addCustomIcpRole}
          onToggleRole={toggleIcpRole}
          onSave={saveProjectSettings}
          onGenerate={generateSmartProfileWithAI}
          saving={savingProject}
          generating={generatingSmartProfile}
          disabled={interactionDisabled || loadingProject}
          missingFields={aiMissingRequiredFields}
          message={projectMessage}
        />
        <ProjectCompetitorManager projectId={projectId} />
        <BrandGuardrailsSection projectId={projectId} />
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
          <LearningsSection projectId={projectId} />
          <PlanProgressSection projectId={projectId} />
        </div>
        <BudgetSection
          budget={projectBudget}
          isLoading={loadingProjectBudget}
          error={projectBudgetError}
          message={projectBudgetMessage}
          disabled={interactionDisabled || loadingProject}
          isSaving={savingProjectBudget}
          limitInput={projectBudgetLimitInput}
          cycleAnchorDay={projectBudgetAnchorDay}
          onLimitInputChange={setProjectBudgetLimitInput}
          onCycleAnchorDayChange={setProjectBudgetAnchorDay}
          onSave={saveProjectBudget}
          onRemove={removeProjectBudgetGuardrail}
        />
        <MonitoringAlertsSection projectId={projectId} />
        <DeleteProjectSection
          projectName={form.name}
          confirmName={deleteConfirmName}
          onConfirmNameChange={setDeleteConfirmName}
          onDelete={deleteProject}
          deleting={deletingProject}
          disabled={interactionDisabled || loadingProject}
          message={deleteProjectMessage}
        />
      </SignalTabPanel>

      <Modal
        open={smartProfileModal.open}
        onClose={closeSmartProfileModal}
        panelClassName="w-full max-w-2xl border-(--line) bg-(--panel)"
      >
        <div className="bg-(--paper) font-(family-name:--body-font) text-(--t-1) antialiased">
          <div className="mb-2 flex items-center gap-2.5">
            <span>
              <Sparkles size={16} strokeWidth={2} color="var(--purple)" aria-hidden="true" />
            </span>
            <h3 className="m-0">{smartProfileModal.title}</h3>
          </div>
          <p className="m-0 mb-[18px]">{smartProfileModal.message}</p>
          <div className="flex justify-end gap-2.5">
            <button
              type="button"
              className="inline-flex h-[38px] cursor-pointer items-center gap-2 rounded-[10px] border border-(--line) bg-(--panel) px-[15px] font-(family-name:--body-font) text-[13.5px] font-semibold text-(--t-1) hover:border-(--line-btn-hover)"
              onClick={closeSmartProfileModal}
            >
              {t("signalProjectSettings.projectDetails.close")}
            </button>
            {smartProfileModal.showAuditCta && (
              <button
                type="button"
                className="inline-flex h-[38px] cursor-pointer items-center gap-2 rounded-[10px] border border-(--ink) bg-(--ink) px-[15px] font-(family-name:--body-font) text-[13.5px] font-semibold text-white hover:bg-black"
                onClick={goToAuditWorkspace}
              >
                {t("signalProjectSettings.projectDetails.runSmartAudit")}
                <ArrowRight size={16} strokeWidth={2} aria-hidden="true" />
              </button>
            )}
          </div>
        </div>
      </Modal>
    </div>
  );
}
