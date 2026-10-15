"use client";

import React, { useCallback, useEffect, useMemo, useState } from "react";
import {
  Activity,
  AlertTriangle,
  CheckCircle2,
  Globe,
  Info,
  Lock,
  Monitor,
  RefreshCw,
  Shield,
  ShieldAlert,
  Terminal,
  XCircle,
  Zap,
} from "lucide-react";
import BrandLogo, { type BrandLogoId } from "@/components/ui/BrandLogo";
import { useAuth } from "@/components/auth/custom-auth";
import { AdminInlineError } from "@/components/admin/AdminInlineError";
import { AdminCardSkeleton } from "@/components/admin/AdminTableSkeleton";
import DashboardPageIntro from "@/components/dashboard/DashboardPageIntro";
import { useWorkspacePageHeader } from "@/components/dashboard/workspacePageHeader";
import type {
  AuditMetrics,
  SecurityPosture,
  ServiceHealthStatus,
  SystemStatusPayload,
} from "@/lib/system-status";

/* ── Types ──────────────────────────────────────────────────────── */

interface Service {
  id: string;
  name: string;
  icon: React.ReactNode;
  status: ServiceHealthStatus;
  details?: string;
}

type ConfigIssue = {
  title: string;
  details: string;
  severity: "high" | "medium";
};

/* ── Design tokens ──────────────────────────────────────────────── */

const MICRO_LABEL =
  "font-(family-name:--mono) text-[10.5px] uppercase tracking-[0.08em] text-(--t-3)";
const MONO_META = MICRO_LABEL.replace("uppercase ", "");
const WSEC = "rounded-[22px] border-0 bg-white px-[22px] py-[18px]";
const SEC_TITLE =
  "m-0 mb-4 flex items-center gap-2 font-(family-name:--disp) text-[15px] font-bold tracking-[-0.01em] text-(--t-1)";
const INSET = "rounded-(--r-md) border-0 bg-[#EEF1F6] p-4";
const CHIP =
  "inline-flex items-center gap-1.5 rounded-md px-2 py-[3px] font-(family-name:--mono) text-[10.5px] uppercase tracking-[0.04em]";

/* ── Constants ──────────────────────────────────────────────────── */

const serviceLogoMap: Partial<Record<string, BrandLogoId>> = {
  database: "postgresql",
  cache: "redis",
  scraper: "firecrawl",
  google_ai: "google_gemini",
  openai_ai: "openai",
  anthropic_ai: "anthropic",
  bing: "bing",
  perplexity: "perplexity",
  xai: "xai",
  deepseek: "deepseek",
  google_sso: "google",
};

const serviceLogoImageClassName: Partial<Record<string, string>> = {
  database: "h-5 w-5",
  cache: "h-5 w-5",
  scraper: "h-5 w-5",
  google_ai: "h-6 w-6",
  openai_ai: "h-5 w-5 invert",
  anthropic_ai: "h-5 w-5 invert",
  bing: "h-6 w-6",
  perplexity: "h-6 w-6",
  xai: "h-6 w-6",
  deepseek: "h-6 w-6",
  google_sso: "h-5 w-5",
};

function ServiceIcon({ id }: { id: string }) {
  const brand = serviceLogoMap[id];
  if (!brand) {
    return <Info size={16} />;
  }

  return (
    <BrandLogo
      brand={brand}
      decorative
      width={20}
      height={20}
      className="h-8 w-8"
      imageClassName={serviceLogoImageClassName[id] ?? "h-5 w-5"}
    />
  );
}

const statusConfig: Record<ServiceHealthStatus, { dot: string; label: string; color: string }> = {
  Operational: {
    dot: "bg-(--good)",
    label: "Operational",
    color: "text-(--good)",
  },
  "Degraded Performance": {
    dot: "bg-(--warn)",
    label: "Degraded",
    color: "text-(--warn)",
  },
  "Major Outage": {
    dot: "bg-(--bad)",
    label: "Outage",
    color: "text-(--bad)",
  },
  "Not Configured": {
    dot: "bg-(--line-2)",
    label: "Not Configured",
    color: "text-(--t-2)",
  },
  Unknown: {
    dot: "bg-(--line-2)",
    label: "Unverified",
    color: "text-(--t-2)",
  },
};

const serviceOrder = [
  "database",
  "cache",
  "scraper",
  "google_ai",
  "openai_ai",
  "anthropic_ai",
  "bing",
  "perplexity",
  "xai",
  "deepseek",
  "google_sso",
  "github_sso",
  "linkedin_sso",
  "microsoft_sso",
  "project_data_sources",
];

/* ── Helpers ─────────────────────────────────────────────────────── */

function StatTile({
  label,
  value,
  icon,
  color = "text-(--purple)",
}: {
  label: string;
  value: string | number;
  icon: React.ReactNode;
  color?: string;
}) {
  return (
    <div className="flex items-center gap-4 rounded-[22px] border-0 bg-white px-4 py-3">
      <div
        className={`flex h-10 w-10 items-center justify-center rounded-(--r-md) bg-(--paper) ${color}`}
      >
        {icon}
      </div>
      <div className="min-w-0">
        <p className={MICRO_LABEL}>{label}</p>
        <p className="font-(family-name:--disp) text-xl font-bold tabular-nums text-(--t-1)">
          {value}
        </p>
      </div>
    </div>
  );
}

/* ── Main component ──────────────────────────────────────────────── */

export default function SystemStatusClient() {
  const { getToken } = useAuth();
  const [services, setServices] = useState<Service[]>([]);
  const [metrics, setMetrics] = useState<AuditMetrics | null>(null);
  const [securityPosture, setSecurityPosture] = useState<SecurityPosture | null>(null);
  const [lastUpdated, setLastUpdated] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [isRefreshing, setIsRefreshing] = useState(false);

  const updateTimestamp = useCallback(() => {
    const now = new Date();
    setLastUpdated(now.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }));
  }, []);

  const applyPayload = useCallback(
    (payload: SystemStatusPayload) => {
      const nextServices = Object.entries(payload.services).map(([id, service]) => ({
        id,
        name: service.name,
        status: service.status,
        details: service.details,
        icon: <ServiceIcon id={id} />,
      }));

      nextServices.sort((a, b) => {
        const aIndex = serviceOrder.indexOf(a.id);
        const bIndex = serviceOrder.indexOf(b.id);
        const safeA = aIndex === -1 ? Number.MAX_SAFE_INTEGER : aIndex;
        const safeB = bIndex === -1 ? Number.MAX_SAFE_INTEGER : bIndex;
        return safeA - safeB;
      });

      setServices(nextServices);
      setMetrics(payload.audit_metrics ?? null);
      setSecurityPosture(payload.security_posture ?? null);
      setError("");
      setLoading(false);
      updateTimestamp();
    },
    [updateTimestamp]
  );

  const loadStatus = useCallback(async () => {
    setIsRefreshing(true);
    try {
      const headers: Record<string, string> = {};
      const token = await getToken();
      if (!token) {
        throw new Error("You must be signed in to view system status.");
      }
      headers.Authorization = `Bearer ${token}`;
      const response = await fetch("/api/system-status/admin", { headers });
      if (!response.ok) {
        throw new Error("Unable to fetch system status.");
      }
      const payload = (await response.json()) as SystemStatusPayload;
      applyPayload(payload);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to load status.");
      setLoading(false);
    } finally {
      setIsRefreshing(false);
    }
  }, [applyPayload, getToken]);

  useEffect(() => {
    void loadStatus();

    const stream = new EventSource("/api/system-status/admin/stream");
    let fallbackInterval: ReturnType<typeof setInterval> | undefined;

    stream.onmessage = (event) => {
      try {
        const payload = JSON.parse(event.data) as SystemStatusPayload;
        applyPayload(payload);
      } catch {
        // Ignore malformed stream frames.
      }
    };

    stream.addEventListener("status_error", () => {
      setError("Live sync interrupted. Falling back to periodic refresh.");
    });

    stream.onerror = () => {
      stream.close();
      if (!fallbackInterval) {
        fallbackInterval = setInterval(() => {
          void loadStatus();
        }, 30000);
      }
    };

    return () => {
      stream.close();
      if (fallbackInterval) {
        clearInterval(fallbackInterval);
      }
    };
  }, [applyPayload, loadStatus]);

  /* ── Derived state ────────────────────────────────────────────── */

  const serviceMap = useMemo(
    () =>
      services.reduce<Record<string, Service>>((acc, service) => {
        acc[service.id] = service;
        return acc;
      }, {}),
    [services]
  );

  const configIssues = useMemo<ConfigIssue[]>(() => {
    const issues: ConfigIssue[] = [];
    const cache = serviceMap.cache;
    if (cache && cache.status !== "Operational") {
      issues.push({
        title: "Cache connectivity issue",
        details: cache.details || "Cache health checks are degraded.",
        severity: cache.status === "Major Outage" ? "high" : "medium",
      });
    }

    const apiKeys = [
      "scraper",
      "google_ai",
      "openai_ai",
      "anthropic_ai",
      "bing",
      "perplexity",
      "xai",
      "deepseek",
      "google_sso",
      "github_sso",
      "linkedin_sso",
      "microsoft_sso",
    ];
    apiKeys.forEach((id) => {
      const service = serviceMap[id];
      if (service && service.status !== "Operational") {
        issues.push({
          title: `${service.name} configuration`,
          details: service.details || "API key is missing or invalid.",
          severity: service.status === "Major Outage" ? "high" : "medium",
        });
      }
    });

    return issues;
  }, [serviceMap]);

  const operationalCount = services.filter((s) => s.status === "Operational").length;
  const securityScore = securityPosture
    ? [
        securityPosture.redis_auth,
        securityPosture.redis_tls,
        !!securityPosture.credential_boundary_role,
      ].filter(Boolean).length
    : 0;

  /* ── Loading skeleton ─────────────────────────────────────────── */

  const { setHeader } = useWorkspacePageHeader();
  useEffect(() => {
    setHeader({
      actions: (
        <>
          {lastUpdated && (
            <span className={`${MONO_META} max-sm:hidden`}>Updated {lastUpdated}</span>
          )}
          <button
            onClick={() => void loadStatus()}
            disabled={isRefreshing}
            className="flex h-8 w-8 items-center justify-center rounded-(--r-sm) border-0 bg-white text-(--t-2) transition-colors hover:text-(--t-1) disabled:opacity-40"
            title="Refresh now"
            aria-label="Refresh now"
          >
            <RefreshCw size={14} className={isRefreshing ? "animate-spin" : ""} />
          </button>
        </>
      ),
    });
    return () => setHeader(null);
  }, [isRefreshing, lastUpdated, loadStatus, setHeader]);

  if (loading) {
    return (
      <>
        <DashboardPageIntro icon={ShieldAlert} title="System infrastructure diagnostics" />
        <AdminCardSkeleton cards={4} />
        <AdminCardSkeleton cards={3} />
      </>
    );
  }

  /* ── Fatal error ──────────────────────────────────────────────── */

  if (error && services.length === 0) {
    return <AdminInlineError message={error} onRetry={loadStatus} />;
  }

  /* ── Main render ──────────────────────────────────────────────── */

  return (
    <>
      {/* ── Header ─────────────────────────────────────────────── */}
      <DashboardPageIntro icon={ShieldAlert} title="System infrastructure diagnostics">
        Real-time health status, worker metrics, and security posture for core system components.
      </DashboardPageIntro>

      {/* ── Inline error (non-fatal) ──────────────────────────── */}
      {error && services.length > 0 && <AdminInlineError message={error} onRetry={loadStatus} />}

      {/* ── KPI Summary ───────────────────────────────────────── */}
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <StatTile
          label="Services"
          value={`${operationalCount}/${services.length}`}
          icon={<CheckCircle2 size={20} />}
          color={operationalCount === services.length ? "text-(--good)" : "text-(--warn)"}
        />
        <StatTile
          label="Issues"
          value={configIssues.length}
          icon={<AlertTriangle size={20} />}
          color={configIssues.length === 0 ? "text-(--good)" : "text-(--bad)"}
        />
        <StatTile
          label="Jobs processed"
          value={metrics ? metrics.jobs_succeeded + metrics.jobs_failed : "-"}
          icon={<Activity size={20} />}
          color="text-(--purple)"
        />
        <StatTile
          label="Security"
          value={`${securityScore}/3`}
          icon={<Shield size={20} />}
          color={securityScore === 3 ? "text-(--good)" : "text-(--warn)"}
        />
      </div>

      {/* ── Service Health Grid ────────────────────────────────── */}
      <section className={WSEC}>
        <h2 className={SEC_TITLE}>
          <Globe size={14} className="text-(--link)" /> Service health
        </h2>
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {services.map((service) => {
            const cfg = statusConfig[service.status];
            return (
              <div
                key={service.id}
                className="group flex min-w-0 items-center gap-3 rounded-(--r-md) border-0 bg-[#EEF1F6] p-4 transition-colors hover:border-(--line-2)"
              >
                <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-(--r-sm) border-0 bg-white text-(--purple)">
                  {service.icon}
                </div>
                <div className="min-w-0 flex-1">
                  <p className="truncate text-[13px] font-semibold text-(--t-1)">{service.name}</p>
                  <p className="truncate text-[11px] text-(--t-3)">
                    {service.details || "Responding normally."}
                  </p>
                </div>
                <div className="flex shrink-0 items-center gap-2">
                  <span className={MICRO_LABEL.replace("text-(--t-3)", cfg.color)}>
                    {cfg.label}
                  </span>
                  <span className={`flex h-2 w-2 rounded-full ${cfg.dot}`} />
                </div>
              </div>
            );
          })}
        </div>
      </section>

      {/* ── Issues + Worker Queue Metrics ─────────────────────── */}
      <div className="grid gap-6 lg:grid-cols-2">
        {/* System Issues */}
        <section className={WSEC}>
          <h2 className={SEC_TITLE}>
            <Terminal size={14} className="text-(--warn)" /> System issues
          </h2>
          {configIssues.length === 0 ? (
            <div className="flex items-center gap-3 rounded-[14px] border-0 bg-(--good-s) px-4 py-4">
              <CheckCircle2 size={16} className="shrink-0 text-(--good)" />
              <p className="text-xs font-semibold text-(--good)">
                All systems operational, no issues detected.
              </p>
            </div>
          ) : (
            <div className="space-y-3">
              {configIssues.map((issue, index) => (
                <div
                  key={`${issue.title}-${index}`}
                  className={`rounded-(--r-md) border p-4 ${
                    issue.severity === "high"
                      ? "border-(--bad) bg-(--bad-s)"
                      : "border-(--warn) bg-(--warn-s)"
                  }`}
                >
                  <div className="flex items-start gap-3">
                    {issue.severity === "high" ? (
                      <XCircle size={14} className="mt-0.5 shrink-0 text-(--bad)" />
                    ) : (
                      <AlertTriangle size={14} className="mt-0.5 shrink-0 text-(--warn)" />
                    )}
                    <div className="min-w-0">
                      <p
                        className={`text-xs font-semibold ${issue.severity === "high" ? "text-(--bad)" : "text-(--warn)"}`}
                      >
                        {issue.title}
                      </p>
                      <p className="mt-1 line-clamp-2 text-[11px] leading-relaxed text-(--t-2)">
                        {issue.details}
                      </p>
                    </div>
                    <span
                      className={`${CHIP} shrink-0 ${
                        issue.severity === "high"
                          ? "text-(--bad) bg-(--bad-s)"
                          : "text-(--warn) bg-(--warn-s)"
                      }`}
                    >
                      {issue.severity === "high" ? "Critical" : "Degraded"}
                    </span>
                  </div>
                </div>
              ))}
            </div>
          )}
        </section>

        {/* Worker Queue Metrics */}
        <section className={WSEC}>
          <h2 className={SEC_TITLE}>
            <Monitor size={14} className="text-(--purple)" /> Worker queue metrics
          </h2>
          {metrics ? (
            <div className="grid gap-3 sm:grid-cols-2">
              {[
                {
                  label: "Jobs started",
                  value: metrics.jobs_started,
                  icon: <Activity size={16} />,
                  color: "text-(--link)",
                },
                {
                  label: "Succeeded",
                  value: metrics.jobs_succeeded,
                  icon: <CheckCircle2 size={16} />,
                  color: "text-(--good)",
                },
                {
                  label: "Failed",
                  value: metrics.jobs_failed,
                  icon: <XCircle size={16} />,
                  color: metrics.jobs_failed > 0 ? "text-(--bad)" : "text-(--good)",
                },
                {
                  label: "Total attempts",
                  value: metrics.job_attempts_total,
                  icon: <Zap size={16} />,
                  color: "text-(--warn)",
                },
                {
                  label: "Retries",
                  value: metrics.job_retries,
                  icon: <RefreshCw size={16} />,
                  color: "text-(--purple)",
                },
                {
                  label: "Total duration",
                  value: `${metrics.job_duration_seconds_total.toFixed(1)}s`,
                  icon: <Activity size={16} />,
                  color: "text-(--purple)",
                },
              ].map((m) => (
                <div key={m.label} className={`${INSET} flex items-center gap-3`}>
                  <div
                    className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-(--r-sm) bg-(--panel) ${m.color}`}
                  >
                    {m.icon}
                  </div>
                  <div>
                    <p className={MICRO_LABEL}>{m.label}</p>
                    <p className="font-(family-name:--disp) text-lg font-bold tabular-nums text-(--t-1)">
                      {m.value}
                    </p>
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <div className="flex flex-col items-center justify-center rounded-[22px] border-0 bg-[#EEF1F6] py-12">
              <Activity size={28} className="mb-3 animate-pulse text-(--t-3)" />
              <p className={MONO_META}>Connecting to status stream...</p>
            </div>
          )}
        </section>
      </div>

      {/* ── Security Posture ───────────────────────────────────── */}
      {securityPosture && (
        <section className={WSEC}>
          <h2 className={SEC_TITLE}>
            <Shield size={14} className="text-(--purple)" /> Security posture
          </h2>
          <div className="grid gap-3 sm:grid-cols-3">
            {[
              {
                label: "Redis Auth",
                pass: securityPosture.redis_auth,
                detail: securityPosture.redis_auth ? "Credentials configured" : "No password set",
                icon: <Lock size={16} />,
              },
              {
                label: "Redis TLS",
                pass: securityPosture.redis_tls,
                detail: securityPosture.redis_tls ? "TLS enabled (rediss://)" : "Plain transport",
                icon: <Shield size={16} />,
              },
              {
                label: "Credential Boundary",
                pass: !!securityPosture.credential_boundary_role,
                detail: securityPosture.credential_boundary_role
                  ? `Role: ${securityPosture.credential_boundary_role} (${securityPosture.credential_boundary_enforce ? "enforcing" : "warn-only"})`
                  : "Not configured",
                icon: <ShieldAlert size={16} />,
              },
            ].map((item) => (
              <div key={item.label} className={`${INSET} flex items-center gap-3`}>
                <div
                  className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-(--r-sm) bg-(--panel) ${item.pass ? "text-(--good)" : "text-(--warn)"}`}
                >
                  {item.icon}
                </div>
                <div className="min-w-0 flex-1">
                  <p className="text-[13px] font-semibold text-(--t-1)">{item.label}</p>
                  <p className="mt-0.5 truncate text-[11px] text-(--t-3)">{item.detail}</p>
                </div>
                <span
                  className={`flex h-2 w-2 shrink-0 rounded-full ${
                    item.pass ? "bg-(--good)" : "bg-(--warn)"
                  }`}
                />
              </div>
            ))}
          </div>
        </section>
      )}
    </>
  );
}
