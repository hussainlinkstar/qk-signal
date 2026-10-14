"use client";

import SignalAlert from "@/components/signal/SignalAlert";
import { asset } from "@/lib/basePath";
import Link from "next/link";
import React, { useCallback, useEffect, useMemo, useState } from "react";
import { Globe, Loader2, Unplug, UploadCloud, Wrench, Settings, Plus } from "lucide-react";
import { useSearchParams } from "next/navigation";

import { useAuth } from "@/components/auth/custom-auth";
import { getActiveWorkspaceId, workspaceHeaders } from "@/components/app/WorkspaceSwitcher";
import LockedFeatureButton from "@/components/dashboard/LockedFeatureButton";
import IntegrationBrandIcon from "@/components/ui/IntegrationBrandIcon";
import Modal from "@/components/ui/Modal";
import { cx } from "@/components/ui/utils";
import {
  connectTeams,
  disconnectSlack,
  disconnectTeams,
  disconnectWorkspaceDataConnection,
  fetchSlackChannels,
  fetchSlackStatus,
  fetchTeamsStatus,
  fetchWorkspaceDataConnections,
  saveWorkspaceDataConnection,
  sendSlackTestMessage,
  sendTeamsTestMessage,
  updateSlackDefaultChannel,
  type DataConnectionProvider,
  type DataConnectionSummary,
  type SlackChannel,
  type SlackStatus,
  type TeamsStatus,
} from "@/services/integrationService";
import {
  connectProjectCms,
  deleteProjectCmsConnection,
  fetchProjectCmsConnections,
  fetchProjectDataSources,
  fetchWorkspaceProjects,
  verifyProjectCmsConnection,
  type CmsType,
  type ProjectCmsConnection,
  type WorkspaceProjectSummary,
} from "@/services/workspaceService";

type OAuthProviderKey = DataConnectionProvider;
type ProviderKey = OAuthProviderKey | "slack" | "teams";

type ProviderFormState = {
  accessToken: string;
  refreshToken: string;
  scope: string;
};

type ProviderConfig = {
  key: ProviderKey | CmsType;
  title: string;
  description: string;
  icon: React.ReactNode;
};

type CmsFormState = {
  siteUrl: string;
  credentialOne: string;
  credentialTwo: string;
};

type CmsConfig = {
  key: CmsType;
  title: string;
  description: string;
  accent: string;
  icon: React.ReactNode;
  credentialOneLabel: string;
  credentialTwoLabel?: string;
};

// Jira, Slack and Teams are announced but not shipping yet (SIGV2-1265), so
// their rows read "Coming soon" and offer no connect affordance. This replaces
// the earlier decision to hide Teams outright: an integration the product
// intends to ship is more honest visible-and-pending than absent. The backends
// (jira_router, the Slack and Teams routers, the Jira export and the workflow
// engine) are fully working and intentionally untouched; removing a key here
// restores its connect affordance. A workspace that already holds one of these
// connections keeps its row, its state and its disconnect control, so no live
// connection is stranded.
const COMING_SOON_PROVIDERS: ReadonlySet<string> = new Set<ProviderKey>(["jira", "slack", "teams"]);

// CMS Fix Delivery and AI Bot Log Analyzer are hidden from the UI because the
// approved MVP design has no analogue for either section. The backend routes
// and services stay fully working and intentionally kept; flipping a flag
// restores its section. Like Teams, a connector with a live connection still
// renders its row with its manage/disconnect affordance so no existing
// credential is stranded invisible.
const SHOW_CMS_FIX_DELIVERY = false;
// The bot-log section holds no state of its own - it is a pair of links into
// /dashboard/projects/{id}/monitoring, which remains reachable - so nothing
// is stranded by hiding it outright.
const SHOW_BOT_LOG_ANALYZER = false;

const PROVIDERS: ProviderConfig[] = [
  {
    key: "google",
    title: "Google Search Console & GA4",
    description: "Shared workspace connection for Google properties.",
    icon: <IntegrationBrandIcon provider="google" className="h-5 w-5" />,
  },
  {
    key: "bing",
    title: "Bing Webmaster Tools",
    description: "Sync Bing visibility data and verification signals.",
    icon: <IntegrationBrandIcon provider="bing" className="h-5 w-5" />,
  },
  {
    key: "jira",
    title: "Atlassian Jira",
    description: "Export roadmap items into delivery workflows inside Jira.",
    icon: <IntegrationBrandIcon provider="jira" className="h-5 w-5" />,
  },
  {
    key: "slack",
    title: "Slack",
    description: "Send alerts and automation outcomes into your team channel.",
    icon: <IntegrationBrandIcon provider="slack" className="h-5 w-5" />,
  },
  {
    key: "teams",
    title: "Microsoft Teams",
    description: "Send workspace notifications into Teams through incoming webhooks.",
    icon: <IntegrationBrandIcon provider="teams" className="h-5 w-5" />,
  },
];

const CMS_CONNECTORS: CmsConfig[] = [
  {
    key: "wordpress",
    title: "WordPress",
    description: "Deploy JSON-LD, meta updates, and alt-text fixes through the WordPress REST API.",
    accent: "primary",
    icon: <Globe className="h-5 w-5" />,
    credentialOneLabel: "Username",
    credentialTwoLabel: "Application Password",
  },
  {
    key: "shopify",
    title: "Shopify",
    description: "Push metadata and structured head snippets through Shopify Admin APIs.",
    accent: "emerald",
    icon: <Wrench className="h-5 w-5" />,
    credentialOneLabel: "Admin API Access Token",
  },
];

const EMPTY_FORM: ProviderFormState = { accessToken: "", refreshToken: "", scope: "" };

const EMPTY_CMS_FORMS: Record<CmsType, CmsFormState> = {
  wordpress: { siteUrl: "", credentialOne: "", credentialTwo: "" },
  shopify: { siteUrl: "", credentialOne: "", credentialTwo: "" },
};

// signal-MVP vocabulary (signal.css .wsec/.card/.field/.btn)
const cardCls = "rounded-(--r) border border-(--line) bg-(--panel) px-[22px] py-[18px]";
const cardHeadCls =
  "m-0 mb-[3px] font-(family-name:--disp) text-[15px] font-bold tracking-[-0.01em]";
const cardDescCls = "m-0 mb-[18px] text-[12.5px] leading-[1.5] text-(--t-3)";
const fieldLabelCls =
  "mb-2 block font-(family-name:--mono) text-[10.5px] uppercase tracking-[0.08em] text-(--t-3)";
const inputCls =
  "field-focus-ring h-11 w-full rounded-[10px] border border-(--line) bg-(--paper) px-[13px] py-0 font-(family-name:--body-font) text-[13.5px] text-(--t-1) outline-none placeholder:text-(--t-3) focus:border-[#C7CDD6] disabled:bg-(--line-2) disabled:text-(--t-3)";
const selectCls =
  "field-focus-ring h-11 w-full appearance-none rounded-[10px] border border-(--line) bg-(--paper) py-0 pl-[13px] pr-[34px] font-(family-name:--body-font) cursor-pointer text-[13.5px] text-(--t-1) outline-none wselect-chevron";
const btnCls =
  "inline-flex h-[38px] cursor-pointer items-center justify-center gap-2 rounded-[10px] border border-(--line) bg-(--panel) px-[15px] py-0 font-(family-name:--body-font) text-[13.5px] font-semibold text-(--t-1) hover:border-[#D7DAE0] disabled:cursor-not-allowed disabled:opacity-45";
const btnPrimaryCls =
  "inline-flex h-[38px] cursor-pointer items-center justify-center gap-2 rounded-[10px] border border-(--primary) bg-(--primary) px-[15px] py-0 font-(family-name:--body-font) text-[13.5px] font-semibold text-white hover:bg-(--primary-hover) disabled:cursor-not-allowed disabled:opacity-45";
// signal-MVP `.conn` row anatomy: flat hairline-separated rows inside a .wsec
// card - no nested tiles. `.ci` 32px icon tile, `.cn` flex text, `.t` 13.5/600,
// `.s` mono 11.5 meta, `.badge-ok` pill for the connected state, compact 32px
// actions at the row end.
const connRowCls =
  "flex flex-wrap items-center gap-3 border-t border-t-(--line-2) py-3 first:border-t-0";
const connIconCls =
  "flex h-8 w-8 flex-none items-center justify-center rounded-[8px] bg-(--line-2) text-(--t-2) [&_svg]:h-[17px] [&_svg]:w-[17px]";
const connTitleCls = "text-[13.5px] font-semibold text-(--t-1)";
const connSubCls = "font-(family-name:--mono) text-[11.5px] text-(--t-3)";
// `.conn .cn` prose descriptions are body text; `--mono` `.s` is reserved for
// short technical metadata (masked token, refresh flag, status ids).
const connDescCls = "text-[12.5px] leading-[1.5] text-(--t-3)";
const btnSmCls =
  "inline-flex h-8 cursor-pointer items-center justify-center gap-2 rounded-[10px] border border-(--line) bg-(--panel) px-3 py-0 font-(family-name:--body-font) text-[12.5px] font-semibold text-(--t-1) hover:border-[#D7DAE0] disabled:cursor-not-allowed disabled:opacity-45 max-md:min-h-11";
const tagCls =
  "inline-flex items-center rounded-[6px] bg-[rgba(147,51,234,0.10)] px-2 py-[3px] font-(family-name:--mono) text-[9.5px] uppercase tracking-[0.06em] text-[#7C3AED]";

function getMessage(error: unknown, fallback: string) {
  return error instanceof Error && error.message.trim() ? error.message : fallback;
}

const statusDotClass = "h-1.5 w-1.5 shrink-0 rounded-full";

const StatusBadge = ({
  comingSoon,
  connected,
  locked,
  needsKey,
  stale,
  unconfigured,
}: {
  /** Announced integration that cannot be connected yet; outranks every other
      state because nothing the customer does changes it. */
  comingSoon?: boolean;
  connected?: boolean;
  locked?: boolean;
  needsKey?: boolean;
  /** Provider has no OAuth credentials on this deployment - distinct from
      disconnected, and never user-fixable from this page. */
  unconfigured?: boolean;
  /**
   * Token has expired with no refresh token, so nothing can recover it without
   * the user re-running the OAuth flow. An expired token that still has a
   * refresh token is normal and self-healing, so it stays "Connected".
   */
  stale?: boolean;
}) => {
  const status = comingSoon
    ? "coming-soon"
    : locked
      ? "locked"
      : needsKey
        ? "needs-key"
        : stale
          ? "stale"
          : unconfigured
            ? "unconfigured"
            : connected
              ? "connected"
              : "disconnected";
  // signal-MVP pill badges: `.badge-ok` for connected (mono 10.5 on --good-s),
  // `.tag` for the plan-gated state, muted pill for the rest.
  const pill =
    "inline-flex items-center gap-[6px] rounded-full px-[9px] py-1 font-(family-name:--mono) text-[10.5px] tracking-[0.06em]";
  const pillTone = {
    connected: "bg-(--good-s) text-(--good)",
    "coming-soon": "bg-[rgba(147,51,234,0.10)] text-[#7C3AED]",
    locked: "bg-[rgba(147,51,234,0.10)] text-[#7C3AED]",
    stale: "bg-(--warn-s) text-(--warn)",
    "needs-key": "bg-(--warn-s) text-(--warn)",
    unconfigured: "bg-(--line-2) text-(--t-3)",
    disconnected: "bg-(--line-2) text-(--t-3)",
  }[status];
  const dot = {
    stale: "bg-(--warn)",
    "coming-soon": "bg-[#7C3AED]",
    locked: "bg-[#7C3AED]",
    "needs-key": "bg-(--warn)",
    unconfigured: "bg-(--t-3)",
    connected: "signal-pulse-dot bg-(--good)",
    disconnected: "bg-(--t-3)",
  }[status];
  const labels = {
    stale: "Reconnect required",
    "coming-soon": "Coming soon",
    locked: "Upgrade required",
    "needs-key": "Needs API key",
    unconfigured: "Not configured",
    connected: "Connected",
    disconnected: "Not connected",
  };

  return (
    <span className={cx(pill, pillTone)}>
      <span className={cx(statusDotClass, dot)} />
      {labels[status]}
    </span>
  );
};

function Field({
  label,
  htmlFor,
  children,
}: {
  label: string;
  htmlFor?: string;
  children: React.ReactNode;
}) {
  return (
    <div className="mb-0">
      <label className={fieldLabelCls} htmlFor={htmlFor}>
        {label}
      </label>
      {children}
    </div>
  );
}

const ConfigurationModal = ({
  isOpen,
  onClose,
  title,
  children,
}: {
  isOpen: boolean;
  onClose: () => void;
  title: string;
  children: React.ReactNode;
}) => {
  const titleId = `connection-modal-${title.toLowerCase().replace(/[^a-z0-9]+/g, "-")}`;

  return (
    <Modal
      open={isOpen}
      onClose={onClose}
      ariaLabelledby={titleId}
      panelClassName="max-h-[calc(100vh-2rem)] w-full max-w-md overflow-y-auto border border-(--line) bg-(--panel) p-5 sm:p-6"
    >
      <div className="mb-4 flex items-center justify-between gap-4">
        <h3
          id={titleId}
          className="m-0 font-(family-name:--disp) text-[15px] font-bold tracking-[-0.01em]"
        >
          {title}
        </h3>
        <button
          type="button"
          onClick={onClose}
          className="inline-flex min-h-11 min-w-11 cursor-pointer items-center justify-center rounded-[10px] border border-(--line) bg-transparent text-[13px] font-semibold text-(--t-3) hover:text-(--t-1)"
          aria-label={`Close ${title}`}
        >
          Close
        </button>
      </div>
      <div>{children}</div>
    </Modal>
  );
};

export default function ConnectionsPanels() {
  const searchParams = useSearchParams();
  const { getToken, isSignedIn, isLoading: authLoading } = useAuth();

  const [connections, setConnections] = useState<DataConnectionSummary[]>([]);
  const [slackStatus, setSlackStatus] = useState<SlackStatus | null>(null);
  const [teamsStatus, setTeamsStatus] = useState<TeamsStatus | null>(null);
  const [slackChannels, setSlackChannels] = useState<SlackChannel[]>([]);
  const [selectedSlackChannelId, setSelectedSlackChannelId] = useState("");
  const [teamsDraft, setTeamsDraft] = useState({ webhookUrl: "", channelName: "" });
  const [forms, setForms] = useState<Record<OAuthProviderKey, ProviderFormState>>({
    google: { ...EMPTY_FORM },
    bing: { ...EMPTY_FORM },
    jira: { ...EMPTY_FORM },
  });
  const [activeProvider, setActiveProvider] = useState<ProviderKey | null>(null);
  const [oauthRedirectProvider, setOauthRedirectProvider] = useState<ProviderKey | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [successMessage, setSuccessMessage] = useState<string | null>(null);
  const [workspaceProjects, setWorkspaceProjects] = useState<WorkspaceProjectSummary[]>([]);
  // Workspace OAuth and per-project GA4 property binding are separate steps
  // (SIGV2-1190). Null = the binding check has not run for this load.
  const [ga4UnboundProjects, setGa4UnboundProjects] = useState<WorkspaceProjectSummary[] | null>(
    null
  );
  const [selectedCmsProjectId, setSelectedCmsProjectId] = useState("");
  const [projectCmsConnections, setProjectCmsConnections] = useState<ProjectCmsConnection[]>([]);
  const [cmsForms, setCmsForms] = useState<Record<CmsType, CmsFormState>>(EMPTY_CMS_FORMS);
  const [activeCmsAction, setActiveCmsAction] = useState<string | null>(null);
  const [modalConfig, setModalConfig] = useState<{
    isOpen: boolean;
    provider: ProviderKey | CmsType | null;
    type: "oauth" | "teams" | "cms" | null;
  }>({ isOpen: false, provider: null, type: null });

  const getAuthHeaders = useCallback(async (): Promise<HeadersInit> => {
    const token = await getToken();
    if (!token) throw new Error("Authentication required.");
    return { Authorization: `Bearer ${token}`, ...workspaceHeaders() };
  }, [getToken]);

  const connectionsByProvider = useMemo(
    () =>
      connections.reduce<Record<OAuthProviderKey, DataConnectionSummary | null>>(
        (acc, item) => ({ ...acc, [item.provider]: item }),
        { google: null, bing: null, jira: null }
      ),
    [connections]
  );

  const activeProjectForServerLogs =
    selectedCmsProjectId || (workspaceProjects[0] ? String(workspaceProjects[0].id) : "");

  const cmsConnectionsByType = useMemo(
    () =>
      projectCmsConnections.reduce<Record<CmsType, ProjectCmsConnection | null>>(
        (acc, connection) => ({
          ...acc,
          [connection.cms_type]: connection,
        }),
        { wordpress: null, shopify: null }
      ),
    [projectCmsConnections]
  );

  // Hidden by default (see SHOW_CMS_FIX_DELIVERY): connectors with no live
  // connection drop out, and the card itself disappears when none remain.
  const visibleCmsConnectors = SHOW_CMS_FIX_DELIVERY
    ? CMS_CONNECTORS
    : CMS_CONNECTORS.filter((connector) => Boolean(cmsConnectionsByType[connector.key]));
  const showCmsCard = SHOW_CMS_FIX_DELIVERY || visibleCmsConnectors.length > 0;

  const loadConnections = useCallback(async () => {
    if (authLoading || !isSignedIn) {
      if (!authLoading) setIsLoading(false);
      return;
    }
    setIsLoading(true);
    setErrorMessage(null);
    try {
      const headers = await getAuthHeaders();
      const [core, slack, teams, projects] = await Promise.all([
        fetchWorkspaceDataConnections(headers),
        fetchSlackStatus(headers).catch(() => null),
        fetchTeamsStatus(headers).catch(() => null),
        fetchWorkspaceProjects(headers).catch(() => []),
      ]);
      const googleConnected = Boolean(
        core.find((connection) => connection.provider === "google")?.connected
      );
      let ga4Unbound: WorkspaceProjectSummary[] | null = null;
      if (googleConnected && projects.length > 0) {
        // A workspace grant alone shows no data: each project still needs its
        // GA4 property bound in Connected data settings (SIGV2-1190). A failed
        // read counts as unbound so needed guidance is never hidden; the
        // destination page resolves the real state either way.
        const checks = await Promise.all(
          projects.map(async (project) => {
            const assignments = await fetchProjectDataSources(project.id, headers).catch(
              () => null
            );
            const bound = Boolean(
              assignments?.some(
                (a) => a.source_type === "google_analytics_4" && a.is_active && a.source_id
              )
            );
            return bound ? null : project;
          })
        );
        ga4Unbound = checks.filter(
          (project): project is WorkspaceProjectSummary => project !== null
        );
      }
      setConnections(core);
      setSlackStatus(slack);
      setTeamsStatus(teams);
      setGa4UnboundProjects(ga4Unbound);
      setWorkspaceProjects(projects);
      setSelectedCmsProjectId((current) => current || (projects[0] ? String(projects[0].id) : ""));
      setSelectedSlackChannelId(slack?.default_channel_id || "");
      if (slack?.is_connected) {
        setSlackChannels(await fetchSlackChannels(headers).catch(() => []));
      } else {
        setSlackChannels([]);
      }
    } catch (error) {
      setErrorMessage(getMessage(error, "Unable to sync integrations."));
    } finally {
      setIsLoading(false);
    }
  }, [authLoading, getAuthHeaders, isSignedIn]);

  const loadProjectCmsConnections = useCallback(async () => {
    if (authLoading || !isSignedIn || !selectedCmsProjectId) {
      if (!selectedCmsProjectId) {
        setProjectCmsConnections([]);
      }
      return;
    }
    try {
      const headers = await getAuthHeaders();
      const connections = await fetchProjectCmsConnections(Number(selectedCmsProjectId), headers);
      setProjectCmsConnections(connections);
    } catch (error) {
      setProjectCmsConnections([]);
      setErrorMessage(getMessage(error, "Unable to load project CMS connections."));
    }
  }, [authLoading, getAuthHeaders, isSignedIn, selectedCmsProjectId]);

  useEffect(() => {
    void loadConnections();
  }, [loadConnections]);

  useEffect(() => {
    void loadProjectCmsConnections();
  }, [loadProjectCmsConnections]);

  // Marks the "Connect an integration" onboarding step complete. Best-effort:
  // a failure here must never surface as an error for the underlying
  // connection action, so it is always wrapped in its own try/catch.
  const markIntegrationConnected = useCallback(async () => {
    try {
      const headers = await getAuthHeaders();
      await fetch("/api/users/me/onboarding", {
        method: "PATCH",
        headers: { ...headers, "Content-Type": "application/json" },
        body: JSON.stringify({
          started: true,
          dismissed: false,
          add_completed_steps: ["connect_integration"],
        }),
      });
    } catch {
      // non-critical
    }
  }, [getAuthHeaders]);

  useEffect(() => {
    const provider = searchParams.get("provider");
    const status = searchParams.get("status");
    const message = searchParams.get("message");
    if (!provider || !status) return;
    if (status === "connected") {
      setSuccessMessage(
        `${provider.charAt(0).toUpperCase() + provider.slice(1)} connected successfully.`
      );
      void loadConnections();
      void markIntegrationConnected();
      return;
    }
    if (status === "error") {
      setErrorMessage(
        message
          ? `Connection failed (${provider.charAt(0).toUpperCase() + provider.slice(1)}): ${message}`
          : `Connection setup was canceled for ${provider.charAt(0).toUpperCase() + provider.slice(1)}.`
      );
    }
  }, [loadConnections, markIntegrationConnected, searchParams]);

  const saveOAuth = async (provider: OAuthProviderKey) => {
    setActiveProvider(provider);
    try {
      const headers = await getAuthHeaders();
      await saveWorkspaceDataConnection(
        provider,
        {
          access_token: forms[provider].accessToken,
          refresh_token: forms[provider].refreshToken || null,
          scope: forms[provider].scope || null,
        },
        headers
      );
      setForms((current) => ({ ...current, [provider]: { ...EMPTY_FORM } }));
      setSuccessMessage(
        `${provider.charAt(0).toUpperCase() + provider.slice(1)} connection saved.`
      );
      setModalConfig({ isOpen: false, provider: null, type: null });
      await loadConnections();
      void markIntegrationConnected();
    } catch (error) {
      setErrorMessage(getMessage(error, "Unable to save the connection."));
    } finally {
      setActiveProvider(null);
    }
  };

  const disconnectOAuth = async (provider: OAuthProviderKey) => {
    setActiveProvider(provider);
    try {
      const headers = await getAuthHeaders();
      await disconnectWorkspaceDataConnection(provider, headers);
      setSuccessMessage(`${provider.charAt(0).toUpperCase() + provider.slice(1)} disconnected.`);
      await loadConnections();
    } catch (error) {
      setErrorMessage(getMessage(error, "Unable to disconnect the provider."));
    } finally {
      setActiveProvider(null);
    }
  };

  const startOAuth = (provider: ProviderKey) => {
    setOauthRedirectProvider(provider);
    // SIGV2-1207: a browser redirect cannot carry X-Workspace-Id, so the active
    // workspace rides as a query parameter. Without it the backend binds the
    // connection to the user's oldest owned workspace.
    const workspaceId = getActiveWorkspaceId();
    const workspaceParam = workspaceId !== null ? `?workspace_id=${workspaceId}` : "";
    window.location.href =
      provider === "jira"
        ? asset("/api/integrations/jira/authorize")
        : provider === "slack"
          ? asset("/api/integrations/slack/authorize")
          : asset(`/api/workspaces/current/oauth-connections/${provider}/start${workspaceParam}`);
  };

  const saveSlackChannel = async () => {
    setActiveProvider("slack");
    try {
      const headers = await getAuthHeaders();
      const selected = slackChannels.find((channel) => channel.id === selectedSlackChannelId);
      await updateSlackDefaultChannel(
        {
          channel_id: selectedSlackChannelId,
          channel_name: selected?.name || null,
        },
        headers
      );
      setSuccessMessage("Slack default channel updated.");
      await loadConnections();
    } catch (error) {
      setErrorMessage(getMessage(error, "Unable to update the Slack channel."));
    } finally {
      setActiveProvider(null);
    }
  };

  const saveTeams = async () => {
    setActiveProvider("teams");
    try {
      const headers = await getAuthHeaders();
      await connectTeams(
        {
          webhook_url: teamsDraft.webhookUrl,
          channel_name: teamsDraft.channelName || null,
        },
        headers
      );
      setSuccessMessage("Teams webhook saved.");
      setModalConfig({ isOpen: false, provider: null, type: null });
      await loadConnections();
      void markIntegrationConnected();
    } catch (error) {
      setErrorMessage(getMessage(error, "Unable to save the Teams webhook."));
    } finally {
      setActiveProvider(null);
    }
  };

  const isBusy = (provider: ProviderKey) => activeProvider === provider;
  const isCmsBusy = (actionKey: string) => activeCmsAction === actionKey;

  const saveCmsConnection = async (cmsType: CmsType) => {
    if (!selectedCmsProjectId) {
      setErrorMessage("Choose a project before connecting a CMS.");
      return;
    }
    const form = cmsForms[cmsType];
    if (!form.siteUrl.trim() || !form.credentialOne.trim()) {
      setErrorMessage("Site URL and required credentials are mandatory.");
      return;
    }
    if (cmsType === "wordpress" && !form.credentialTwo.trim()) {
      setErrorMessage("WordPress requires both username and application password.");
      return;
    }

    const actionKey = `connect-${cmsType}`;
    setActiveCmsAction(actionKey);
    try {
      const headers = await getAuthHeaders();
      const payload =
        cmsType === "wordpress"
          ? {
              cms_type: cmsType,
              site_url: form.siteUrl.trim(),
              credentials: {
                username: form.credentialOne.trim(),
                app_password: form.credentialTwo.trim(),
              },
            }
          : {
              cms_type: cmsType,
              site_url: form.siteUrl.trim(),
              credentials: {
                access_token: form.credentialOne.trim(),
              },
            };
      const connection = await connectProjectCms(Number(selectedCmsProjectId), payload, headers);
      await verifyProjectCmsConnection(Number(selectedCmsProjectId), connection.id, headers);
      setCmsForms((current) => ({
        ...current,
        [cmsType]: { ...EMPTY_CMS_FORMS[cmsType] },
      }));
      setSuccessMessage(
        `${cmsType === "wordpress" ? "WordPress" : "Shopify"} connection saved and verified.`
      );
      setModalConfig({ isOpen: false, provider: null, type: null });
      await loadProjectCmsConnections();
    } catch (error) {
      setErrorMessage(getMessage(error, "Unable to save CMS connection."));
    } finally {
      setActiveCmsAction(null);
    }
  };

  const verifyCmsConnection = async (connection: ProjectCmsConnection) => {
    if (!selectedCmsProjectId) return;
    const actionKey = `verify-${connection.id}`;
    setActiveCmsAction(actionKey);
    try {
      const headers = await getAuthHeaders();
      await verifyProjectCmsConnection(Number(selectedCmsProjectId), connection.id, headers);
      setSuccessMessage(
        `${connection.cms_type === "wordpress" ? "WordPress" : "Shopify"} connection verified.`
      );
      await loadProjectCmsConnections();
    } catch (error) {
      setErrorMessage(getMessage(error, "Unable to verify CMS connection."));
    } finally {
      setActiveCmsAction(null);
    }
  };

  const disconnectCmsConnection = async (connection: ProjectCmsConnection) => {
    if (!selectedCmsProjectId) return;
    const actionKey = `disconnect-${connection.id}`;
    setActiveCmsAction(actionKey);
    try {
      const headers = await getAuthHeaders();
      await deleteProjectCmsConnection(Number(selectedCmsProjectId), connection.id, headers);
      setSuccessMessage(
        `${connection.cms_type === "wordpress" ? "WordPress" : "Shopify"} connection removed.`
      );
      await loadProjectCmsConnections();
    } catch (error) {
      setErrorMessage(getMessage(error, "Unable to remove CMS connection."));
    } finally {
      setActiveCmsAction(null);
    }
  };

  if (isLoading) {
    return (
      <>
        {[0, 1, 2].map((index) => (
          <div key={index} className={cardCls} role="status" aria-label="Loading connections">
            <div className="skel skel-line w40" />
            <div className="skel skel-line w80" />
            <div className="mt-4 flex flex-col gap-3">
              <div className="skel skel-line" />
              <div className="skel skel-line w60" />
            </div>
          </div>
        ))}
      </>
    );
  }

  const visibleProviders = PROVIDERS;

  return (
    <>
      {errorMessage && (
        <SignalAlert tone="danger" title="Connection update failed">
          {errorMessage}
        </SignalAlert>
      )}
      {successMessage && (
        <SignalAlert tone="success" title="Connection updated">
          {successMessage}
        </SignalAlert>
      )}

      {/* Integrations */}
      <div className={cardCls}>
        <h3 className={cardHeadCls}>Workspace Connections</h3>
        <p className={cardDescCls}>
          Workspace-level integrations power shared data access, real-time alerts, and project
          automations across the delivery team.
        </p>
        <div>
          {visibleProviders.map((provider) => {
            const core =
              provider.key === "google" || provider.key === "bing" || provider.key === "jira"
                ? connectionsByProvider[provider.key]
                : null;
            const slack =
              provider.key === "slack"
                ? (slackStatus ?? {
                    is_connected: false,
                    team_id: null,
                    team_name: null,
                    bot_user_id: null,
                    default_channel_id: null,
                    default_channel_name: null,
                    scope: null,
                    updated_at: null,
                    is_plan_locked: false,
                    detail: null,
                  })
                : null;
            const teams =
              provider.key === "teams"
                ? (teamsStatus ?? {
                    is_connected: false,
                    channel_name: null,
                    webhook_preview: null,
                    updated_at: null,
                    is_plan_locked: false,
                    detail: null,
                  })
                : null;
            const coreProvider = provider.key as OAuthProviderKey;
            const planLocked = Boolean(slack?.is_plan_locked || teams?.is_plan_locked);
            const connected = Boolean(
              (core ? core.connected : false) || slack?.is_connected || teams?.is_connected
            );
            // The provider has no OAuth credentials on this deployment: no
            // connect affordance can complete, so none is offered.
            const coreUnconfigured = Boolean(core && !core.connected && !core.configured);
            // A row in the table is not the same thing as a working grant: the
            // card used to read "Connected" indefinitely for a token that had
            // expired weeks earlier and had no way to refresh itself.
            const coreExpired = Boolean(
              core?.expires_at && new Date(core.expires_at).getTime() <= Date.now()
            );
            const stale = Boolean(core && coreExpired && !core.has_refresh_token);
            // An announced integration that is not shipping yet. A live
            // connection outranks it, so an existing grant keeps its state and
            // its disconnect control instead of being hidden behind a promise.
            const comingSoon = COMING_SOON_PROVIDERS.has(provider.key) && !connected;

            return (
              <div key={provider.key} className={connRowCls}>
                <div className={connIconCls}>{provider.icon}</div>
                <div className="min-w-0 flex-1 basis-48">
                  <div className={connTitleCls}>{provider.title}</div>
                  <div className={connDescCls}>{provider.description}</div>
                  {slack?.is_connected ? (
                    <>
                      <div className={connSubCls}>
                        {`Workspace: ${slack.team_name || slack.team_id}`}
                      </div>
                      <div className={connSubCls}>
                        {`Channel: ${
                          slack.default_channel_name ? `#${slack.default_channel_name}` : "Not set"
                        }`}
                      </div>
                    </>
                  ) : null}
                  {teams?.is_connected ? (
                    <>
                      <div className={connSubCls}>
                        {`Channel: ${teams.channel_name || "Not labeled"}`}
                      </div>
                      <div className={connSubCls}>
                        {`Webhook: ${teams.webhook_preview || "Configured"}`}
                      </div>
                    </>
                  ) : null}
                  {core?.connected ? (
                    <>
                      <div className={connDescCls}>Connected at workspace level.</div>
                      {provider.key === "google" &&
                      ga4UnboundProjects !== null &&
                      workspaceProjects.length > 0 ? (
                        // The workspace grant alone shows no data: each project
                        // still needs its GA4 property bound in Connected data
                        // settings, which is where this link lands. Only a
                        // project with no active binding gets the prompt - an
                        // already-bound project must not read as unfinished.
                        ga4UnboundProjects.length > 0 ? (
                          <Link
                            href={`/dashboard/projects/${ga4UnboundProjects[0].id}/settings#data-sources`}
                            className="mt-1 inline-flex items-center gap-1 text-[12.5px] font-semibold text-(--brand) hover:underline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-(--purple) max-md:min-h-11"
                          >
                            Choose the GA4 property for {ga4UnboundProjects[0].name}
                          </Link>
                        ) : (
                          <div className={connSubCls}>GA4 property linked for every project.</div>
                        )
                      ) : null}
                    </>
                  ) : null}
                  {core && !core.connected && !core.configured && !comingSoon ? (
                    <div className={connDescCls}>
                      Not configured in this environment - the deployment has no OAuth credentials
                      for this provider.
                    </div>
                  ) : null}
                </div>
                {/* signal-MVP rule: suppress the pill only when it restates
                    the action ("Not connected" beside Connect). Pills that add
                    state the action label does not carry - Connected,
                    Reconnect required, the action-free unconfigured case -
                    stay. Plan-locked rows already explain themselves via the
                    LockedFeatureButton helper text. */}
                {comingSoon || (!planLocked && (connected || stale || coreUnconfigured)) ? (
                  <StatusBadge
                    comingSoon={comingSoon}
                    connected={connected}
                    stale={stale}
                    unconfigured={coreUnconfigured}
                  />
                ) : null}

                {/* Slack */}
                {!comingSoon &&
                  provider.key === "slack" &&
                  slack &&
                  (slack.is_plan_locked ? (
                    <LockedFeatureButton
                      buttonLabel="Connect Slack"
                      helperText={slack.detail || "Slack requires Specialist or higher"}
                    />
                  ) : slack.is_connected ? (
                    <div className="flex flex-none flex-wrap items-center justify-end gap-2">
                      <button
                        type="button"
                        className={btnSmCls}
                        onClick={() =>
                          setModalConfig({
                            isOpen: true,
                            provider: "slack",
                            type: "oauth",
                          })
                        }
                      >
                        <Settings className="h-3.5 w-3.5" />
                        Configure
                      </button>
                      <button
                        type="button"
                        className={btnSmCls}
                        disabled={isBusy("slack")}
                        onClick={async () => {
                          setActiveProvider("slack");
                          try {
                            const headers = await getAuthHeaders();
                            await sendSlackTestMessage(
                              {
                                channel_id: selectedSlackChannelId || null,
                              },
                              headers
                            );
                            setSuccessMessage("Slack test message sent.");
                          } catch (error) {
                            setErrorMessage(getMessage(error, "Unable to send test message."));
                          } finally {
                            setActiveProvider(null);
                          }
                        }}
                      >
                        {isBusy("slack") ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : null}
                        Test
                      </button>
                      <button
                        type="button"
                        className={btnSmCls}
                        onClick={async () => {
                          if (confirm("Are you sure you want to disconnect Slack?")) {
                            setActiveProvider("slack");
                            try {
                              const headers = await getAuthHeaders();
                              await disconnectSlack(headers);
                              setSuccessMessage("Slack disconnected.");
                              await loadConnections();
                            } catch (error) {
                              setErrorMessage(getMessage(error, "Unable to disconnect."));
                            } finally {
                              setActiveProvider(null);
                            }
                          }
                        }}
                      >
                        <Unplug className="h-3.5 w-3.5" />
                        Disconnect
                      </button>
                    </div>
                  ) : (
                    <button
                      type="button"
                      className={btnSmCls}
                      onClick={() => startOAuth("slack")}
                      disabled={Boolean(oauthRedirectProvider)}
                    >
                      {oauthRedirectProvider === "slack" ? (
                        <Loader2 className="h-3.5 w-3.5 animate-spin" />
                      ) : (
                        <Plus className="h-3.5 w-3.5" />
                      )}
                      Connect Slack
                    </button>
                  ))}

                {/* Teams */}
                {!comingSoon &&
                  provider.key === "teams" &&
                  teams &&
                  (teams.is_plan_locked ? (
                    <LockedFeatureButton
                      buttonLabel="Connect Teams"
                      helperText={teams.detail || "Teams requires Specialist or higher"}
                    />
                  ) : teams.is_connected ? (
                    <div className="flex flex-none flex-wrap items-center justify-end gap-2">
                      <button
                        type="button"
                        className={btnSmCls}
                        disabled={isBusy("teams")}
                        onClick={async () => {
                          setActiveProvider("teams");
                          try {
                            const headers = await getAuthHeaders();
                            await sendTeamsTestMessage(headers);
                            setSuccessMessage("Teams test message sent.");
                          } catch (error) {
                            setErrorMessage(getMessage(error, "Unable to send test message."));
                          } finally {
                            setActiveProvider(null);
                          }
                        }}
                      >
                        {isBusy("teams") ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : null}
                        Test
                      </button>
                      <button
                        type="button"
                        className={btnSmCls}
                        onClick={async () => {
                          if (confirm("Are you sure you want to disconnect Teams?")) {
                            setActiveProvider("teams");
                            try {
                              const headers = await getAuthHeaders();
                              await disconnectTeams(headers);
                              setSuccessMessage("Teams disconnected.");
                              await loadConnections();
                            } catch (error) {
                              setErrorMessage(getMessage(error, "Unable to disconnect."));
                            } finally {
                              setActiveProvider(null);
                            }
                          }
                        }}
                      >
                        <Unplug className="h-3.5 w-3.5" />
                        Disconnect
                      </button>
                    </div>
                  ) : (
                    <button
                      type="button"
                      className={btnSmCls}
                      onClick={() =>
                        setModalConfig({
                          isOpen: true,
                          provider: "teams",
                          type: "teams",
                        })
                      }
                    >
                      <Plus className="h-3.5 w-3.5" />
                      Configure Teams
                    </button>
                  ))}

                {/* OAuth providers */}
                {!comingSoon &&
                  provider.key !== "slack" &&
                  provider.key !== "teams" &&
                  (core && core.connected ? (
                    <div className="flex flex-none flex-wrap items-center justify-end gap-2">
                      <button
                        type="button"
                        className={btnSmCls}
                        onClick={() => disconnectOAuth(coreProvider)}
                      >
                        <Unplug className="h-3.5 w-3.5" />
                        Disconnect
                      </button>
                    </div>
                  ) : core && !core.configured ? null : (
                    <div className="flex flex-none flex-wrap items-center justify-end gap-2">
                      <button
                        type="button"
                        className={btnSmCls}
                        onClick={() => startOAuth(coreProvider)}
                        disabled={Boolean(oauthRedirectProvider)}
                      >
                        {oauthRedirectProvider === coreProvider ? (
                          <Loader2 className="h-3.5 w-3.5 animate-spin" />
                        ) : (
                          <Plus className="h-3.5 w-3.5" />
                        )}
                        Connect {coreProvider.charAt(0).toUpperCase() + coreProvider.slice(1)}
                      </button>
                      <button
                        type="button"
                        onClick={() =>
                          setModalConfig({
                            isOpen: true,
                            provider: coreProvider,
                            type: "oauth",
                          })
                        }
                        className="inline-flex cursor-pointer items-center justify-center gap-1 border-none bg-transparent text-[12px] text-(--t-3) hover:text-(--t-1) max-md:inline-flex max-md:min-h-11 max-md:items-center"
                      >
                        <Settings className="h-3 w-3" />
                        Advanced options
                      </button>
                    </div>
                  ))}
              </div>
            );
          })}
        </div>
      </div>

      {/* CMS Fix Delivery */}
      {showCmsCard ? (
        <div className={cardCls}>
          <div className="flex min-w-0 flex-col items-start gap-3 sm:flex-row sm:items-start sm:justify-between">
            <div>
              <h3 className={cardHeadCls}>CMS Fix Delivery</h3>
              <p className={cardDescCls}>
                Connect projects to production CMS for auditable push-to-live deployment.
              </p>
            </div>
            {/* signal-MVP `.tag`: mono 9.5px uppercase purple chip for the
              plan-gated state; the upgrade affordance stays a separate link. */}
            <div className="flex flex-none items-center gap-2">
              <span className={tagCls}>Requires Executive</span>
              <Link href="/dashboard/billing?section=plans" className={btnSmCls}>
                Upgrade
              </Link>
            </div>
          </div>

          {workspaceProjects.length === 0 ? (
            <div className="rounded-(--r-md) border border-dashed border-(--line) p-6 text-center">
              <p className="m-0 text-[12.5px] text-(--t-3)">
                Create at least one project to configure CMS delivery integrations
              </p>
            </div>
          ) : (
            <>
              <div className="mb-4 max-w-md">
                <Field label="Project" htmlFor="cms-project">
                  <select
                    id="cms-project"
                    className={selectCls}
                    value={selectedCmsProjectId}
                    onChange={(e) => setSelectedCmsProjectId(e.target.value)}
                  >
                    {workspaceProjects.map((project) => (
                      <option key={project.id} value={String(project.id)}>
                        {project.name}
                      </option>
                    ))}
                  </select>
                </Field>
              </div>

              <div>
                {visibleCmsConnectors.map((connector) => {
                  const existing = cmsConnectionsByType[connector.key];
                  const isConnected = Boolean(existing);
                  const isVerified = existing?.status === "verified";

                  return (
                    <div key={connector.key} className={connRowCls}>
                      <div className={connIconCls}>{connector.icon}</div>
                      <div className="min-w-0 flex-1 basis-48">
                        <div className={connTitleCls}>{connector.title}</div>
                        <div className={connDescCls}>{connector.description}</div>
                        {isConnected && existing ? (
                          <>
                            <div className={connSubCls}>{`Site: ${existing.site_url}`}</div>
                            <div className={connSubCls}>{`Status: ${existing.status}`}</div>
                          </>
                        ) : null}
                      </div>
                      {/* "Needs API key" adds state Verify/Disconnect do not
                        say; an unconnected row has only the Set up action. */}
                      {isConnected && existing ? (
                        <StatusBadge connected={isVerified} needsKey={!isVerified} />
                      ) : null}
                      {isConnected && existing ? (
                        <div className="flex flex-none flex-wrap items-center justify-end gap-2">
                          <button
                            type="button"
                            className={btnSmCls}
                            disabled={isCmsBusy(`verify-${existing.id}`)}
                            onClick={() => verifyCmsConnection(existing)}
                          >
                            {isCmsBusy(`verify-${existing.id}`) ? (
                              <Loader2 className="h-3.5 w-3.5 animate-spin" />
                            ) : null}
                            Verify
                          </button>
                          <button
                            type="button"
                            className={btnSmCls}
                            disabled={isCmsBusy(`disconnect-${existing.id}`)}
                            onClick={() => disconnectCmsConnection(existing)}
                          >
                            <Unplug className="h-3.5 w-3.5" />
                            Disconnect
                          </button>
                        </div>
                      ) : (
                        <button
                          type="button"
                          className={btnSmCls}
                          onClick={() =>
                            setModalConfig({
                              isOpen: true,
                              provider: connector.key,
                              type: "cms",
                            })
                          }
                          disabled={!selectedCmsProjectId}
                        >
                          <Plus className="h-3.5 w-3.5" />
                          Set up {connector.title}
                        </button>
                      )}
                    </div>
                  );
                })}
              </div>
            </>
          )}
        </div>
      ) : null}

      {/* AI Bot Log Analyzer */}
      {SHOW_BOT_LOG_ANALYZER ? (
        <div className={cardCls}>
          <h3 className={cardHeadCls}>AI Bot Log Analyzer</h3>
          <p className={cardDescCls}>
            Upload access logs to inspect bot crawler diagnostics with spoofing checks.
          </p>

          {workspaceProjects.length === 0 ? (
            <div className="rounded-(--r-md) border border-dashed border-(--line) p-6 text-center">
              <p className="m-0 text-[12.5px] text-(--t-3)">
                Create at least one project to enable bot log monitoring
              </p>
            </div>
          ) : (
            <div className="flex flex-col gap-4">
              <div className="max-w-md">
                <Field label="Project" htmlFor="log-project">
                  <select
                    id="log-project"
                    className={selectCls}
                    value={selectedCmsProjectId}
                    onChange={(e) => setSelectedCmsProjectId(e.target.value)}
                  >
                    {workspaceProjects.map((project) => (
                      <option key={project.id} value={String(project.id)}>
                        {project.name}
                      </option>
                    ))}
                  </select>
                </Field>
              </div>

              <div className={connRowCls}>
                <div className={connIconCls}>
                  <UploadCloud />
                </div>
                <div className="min-w-0 flex-1 basis-48">
                  <div className={connTitleCls}>Bot log monitoring</div>
                  <div className={connDescCls}>
                    Open the project monitoring workspace to configure connectors and upload log
                    files.
                  </div>
                </div>
                <div className="flex flex-none flex-wrap items-center justify-end gap-2">
                  <Link
                    href={`/dashboard/projects/${activeProjectForServerLogs}/monitoring#bot-log-analyzer`}
                    className={btnSmCls}
                  >
                    Open Bot Log Analyzer
                  </Link>
                  <Link
                    href={`/dashboard/projects/${activeProjectForServerLogs}/monitoring`}
                    className={btnSmCls}
                  >
                    Monitoring Hub
                  </Link>
                </div>
              </div>
            </div>
          )}
        </div>
      ) : null}

      {/* Slack Channel Configuration Modal */}
      <ConfigurationModal
        isOpen={
          modalConfig.isOpen && modalConfig.provider === "slack" && modalConfig.type === "oauth"
        }
        onClose={() => setModalConfig({ isOpen: false, provider: null, type: null })}
        title="Configure Slack Channel"
      >
        <div className="flex flex-col gap-4">
          <Field label="Default channel" htmlFor="modal-slack-channel">
            <select
              id="modal-slack-channel"
              className={selectCls}
              value={selectedSlackChannelId}
              onChange={(e) => setSelectedSlackChannelId(e.target.value)}
            >
              <option value="">Select a channel</option>
              {slackChannels.map((channel) => (
                <option key={channel.id} value={channel.id}>
                  #{channel.name}
                </option>
              ))}
            </select>
          </Field>
          <div className="flex flex-wrap gap-3 pt-1">
            <button
              type="button"
              className={btnPrimaryCls}
              onClick={() => saveSlackChannel()}
              disabled={!selectedSlackChannelId || isBusy("slack")}
            >
              {isBusy("slack") ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : null}
              Save channel
            </button>
            <button
              type="button"
              className={btnCls}
              onClick={() => setModalConfig({ isOpen: false, provider: null, type: null })}
            >
              Cancel
            </button>
          </div>
        </div>
      </ConfigurationModal>

      {/* Teams Configuration Modal */}
      <ConfigurationModal
        isOpen={
          modalConfig.isOpen && modalConfig.provider === "teams" && modalConfig.type === "teams"
        }
        onClose={() => setModalConfig({ isOpen: false, provider: null, type: null })}
        title="Configure Microsoft Teams"
      >
        <div className="flex flex-col gap-4">
          <Field label="Webhook URL">
            <input
              className={inputCls}
              value={teamsDraft.webhookUrl}
              onChange={(e) =>
                setTeamsDraft((current) => ({ ...current, webhookUrl: e.target.value }))
              }
              placeholder="https://outlook.office.com/webhook/..."
            />
          </Field>
          <Field label="Channel label (optional)">
            <input
              className={inputCls}
              value={teamsDraft.channelName}
              onChange={(e) =>
                setTeamsDraft((current) => ({ ...current, channelName: e.target.value }))
              }
              placeholder="e.g., SEO Alerts"
            />
          </Field>
          <div className="flex flex-wrap gap-3 pt-1">
            <button
              type="button"
              className={btnPrimaryCls}
              onClick={() => saveTeams()}
              disabled={!teamsDraft.webhookUrl.trim() || isBusy("teams")}
            >
              {isBusy("teams") ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : null}
              Save webhook
            </button>
            <button
              type="button"
              className={btnCls}
              onClick={() => setModalConfig({ isOpen: false, provider: null, type: null })}
            >
              Cancel
            </button>
          </div>
        </div>
      </ConfigurationModal>

      {/* OAuth Manual Configuration Modal */}
      {["google", "bing", "jira"].includes(modalConfig.provider as string) && (
        <ConfigurationModal
          isOpen={modalConfig.isOpen && modalConfig.type === "oauth"}
          onClose={() => setModalConfig({ isOpen: false, provider: null, type: null })}
          title={`Configure ${modalConfig.provider?.charAt(0).toUpperCase()}${modalConfig.provider?.slice(1)} Manually`}
        >
          <div className="flex flex-col gap-4">
            <Field label="Access token">
              <input
                className={inputCls}
                value={forms[modalConfig.provider as OAuthProviderKey]?.accessToken || ""}
                onChange={(e) =>
                  setForms((current) => ({
                    ...current,
                    [modalConfig.provider as OAuthProviderKey]: {
                      ...current[modalConfig.provider as OAuthProviderKey],
                      accessToken: e.target.value,
                    },
                  }))
                }
                placeholder="Paste your access token"
              />
            </Field>
            <Field label="Refresh token (optional)">
              <input
                className={inputCls}
                value={forms[modalConfig.provider as OAuthProviderKey]?.refreshToken || ""}
                onChange={(e) =>
                  setForms((current) => ({
                    ...current,
                    [modalConfig.provider as OAuthProviderKey]: {
                      ...current[modalConfig.provider as OAuthProviderKey],
                      refreshToken: e.target.value,
                    },
                  }))
                }
                placeholder="Paste your refresh token"
              />
            </Field>
            <Field label="Scopes (optional)">
              <input
                className={inputCls}
                value={forms[modalConfig.provider as OAuthProviderKey]?.scope || ""}
                onChange={(e) =>
                  setForms((current) => ({
                    ...current,
                    [modalConfig.provider as OAuthProviderKey]: {
                      ...current[modalConfig.provider as OAuthProviderKey],
                      scope: e.target.value,
                    },
                  }))
                }
                placeholder="e.g., read write"
              />
            </Field>
            <div className="flex flex-wrap gap-3 pt-1">
              <button
                type="button"
                className={btnPrimaryCls}
                onClick={() => saveOAuth(modalConfig.provider as OAuthProviderKey)}
                disabled={
                  !forms[modalConfig.provider as OAuthProviderKey]?.accessToken.trim() ||
                  isBusy(modalConfig.provider as ProviderKey)
                }
              >
                {isBusy(modalConfig.provider as ProviderKey) ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                ) : null}
                Save connection
              </button>
              <button
                type="button"
                className={btnCls}
                onClick={() => setModalConfig({ isOpen: false, provider: null, type: null })}
              >
                Cancel
              </button>
            </div>
          </div>
        </ConfigurationModal>
      )}

      {/* CMS Configuration Modal */}
      {["wordpress", "shopify"].includes(modalConfig.provider as string) && (
        <ConfigurationModal
          isOpen={modalConfig.isOpen && modalConfig.type === "cms"}
          onClose={() => setModalConfig({ isOpen: false, provider: null, type: null })}
          title={`Configure ${modalConfig.provider === "wordpress" ? "WordPress" : "Shopify"}`}
        >
          <div className="flex flex-col gap-4">
            <Field label="Site URL">
              <input
                className={inputCls}
                value={cmsForms[modalConfig.provider as CmsType]?.siteUrl || ""}
                onChange={(e) =>
                  setCmsForms((current) => ({
                    ...current,
                    [modalConfig.provider as CmsType]: {
                      ...current[modalConfig.provider as CmsType],
                      siteUrl: e.target.value,
                    },
                  }))
                }
                placeholder="https://example.com"
              />
            </Field>
            <Field
              label={
                CMS_CONNECTORS.find((c) => c.key === modalConfig.provider)?.credentialOneLabel || ""
              }
            >
              <input
                className={inputCls}
                value={cmsForms[modalConfig.provider as CmsType]?.credentialOne || ""}
                onChange={(e) =>
                  setCmsForms((current) => ({
                    ...current,
                    [modalConfig.provider as CmsType]: {
                      ...current[modalConfig.provider as CmsType],
                      credentialOne: e.target.value,
                    },
                  }))
                }
                placeholder={modalConfig.provider === "wordpress" ? "admin" : "shpat_xxxxx"}
              />
            </Field>
            {modalConfig.provider === "wordpress" && (
              <Field label="Application Password">
                <input
                  className={inputCls}
                  value={cmsForms.wordpress.credentialTwo}
                  onChange={(e) =>
                    setCmsForms((current) => ({
                      ...current,
                      wordpress: {
                        ...current.wordpress,
                        credentialTwo: e.target.value,
                      },
                    }))
                  }
                  placeholder="xxxx xxxx xxxx xxxx"
                  type="password"
                />
              </Field>
            )}
            <div className="flex flex-wrap gap-3 pt-1">
              <button
                type="button"
                className={btnPrimaryCls}
                onClick={() => saveCmsConnection(modalConfig.provider as CmsType)}
                disabled={!selectedCmsProjectId || isCmsBusy(`connect-${modalConfig.provider}`)}
              >
                {isCmsBusy(`connect-${modalConfig.provider}`) ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                ) : null}
                Connect {modalConfig.provider === "wordpress" ? "WordPress" : "Shopify"}
              </button>
              <button
                type="button"
                className={btnCls}
                onClick={() => setModalConfig({ isOpen: false, provider: null, type: null })}
              >
                Cancel
              </button>
            </div>
          </div>
        </ConfigurationModal>
      )}
    </>
  );
}
