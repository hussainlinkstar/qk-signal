import { notFound } from "next/navigation";
import { AlertTriangle, ExternalLink, KanbanSquare, Sparkles, TrendingUp } from "lucide-react";
import PortalAnnotationThread from "@/components/portal/PortalAnnotationThread";
import PortalTrendChart from "@/components/portal/PortalTrendChart";
import PortalProjectActions from "@/components/portal/PortalProjectActions";
import { PortalApprovalButtons } from "@/components/portal/PortalApprovalButtons";
import { getReportLanguageLabel } from "@/lib/reportLanguages";
import type { PortalProjectDashboard, PortalTask } from "@/services/portalService";
import { serverFetch } from "@/utils/server-fetch";

type ProjectPortalPageProps = {
  params: Promise<{
    projectId: string;
  }>;
  searchParams: Promise<{
    audit_id?: string;
  }>;
};

const formatScore = (value: number | null | undefined) =>
  typeof value === "number" ? Math.round(value) : "N/A";

const formatDate = (value: string | null) => {
  if (!value) {
    return "Unavailable";
  }

  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "Unavailable";
  }

  return date.toLocaleString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
};

const stripDomainProtocol = (value: string | null) =>
  value ? value.replace(/^https?:\/\//i, "").replace(/\/$/, "") : "Pending domain";

export default async function ProjectPortalPage({ params, searchParams }: ProjectPortalPageProps) {
  const { projectId } = await params;
  const { audit_id } = await searchParams;

  const dashboardUrl = audit_id
    ? `/portal/projects/${projectId}/dashboard?audit_id=${audit_id}`
    : `/portal/projects/${projectId}/dashboard`;

  const [dashboardResponse, tasksResponse, brandingResponse] = await Promise.all([
    serverFetch(dashboardUrl, {
      cache: "no-store",
      redirectOnUnauthorized: false,
    }),
    serverFetch(`/portal/projects/${projectId}/tasks`, {
      cache: "no-store",
      redirectOnUnauthorized: false,
    }),
    serverFetch("/portal/branding", {
      cache: "no-store",
      redirectOnUnauthorized: false,
    }),
  ]);

  if (!dashboardResponse.ok) {
    if (dashboardResponse.status === 403 || dashboardResponse.status === 404) {
      notFound();
    }
    throw new Error(`Unable to load portal dashboard (${dashboardResponse.status}).`);
  }

  const dashboard = (await dashboardResponse.json()) as PortalProjectDashboard;
  const tasks = tasksResponse.ok ? ((await tasksResponse.json()) as PortalTask[]) : [];
  const branding = brandingResponse.ok
    ? ((await brandingResponse.json()) as {
        primary_color?: string | null;
        secondary_color?: string | null;
      })
    : {};

  const primaryColor = branding.primary_color || "#3dd9c5";
  const secondaryColor = branding.secondary_color || "#22D3EE";
  const latestAudit = dashboard.latest_audit;

  return (
    <div className="space-y-8">
      <section className="rounded-[36px] border border-white/10  p-8 shadow-[0_30px_80px_rgba(0,0,0,0.22)]">
        <div className="flex flex-col gap-6 lg:flex-row lg:items-end lg:justify-between">
          <div>
            <p className="text-[11px] font-bold uppercase tracking-[0.3em] text-slate-400">
              Project dashboard
            </p>
            <h2 className="mt-3 text-3xl font-black tracking-tight text-white md:text-4xl">
              {dashboard.project.name}
            </h2>
            <div
              className="mt-4 inline-flex items-center rounded-full border border-white/10 bg-(--surface) px-3 py-1 text-[11px] font-black uppercase tracking-[0.2em] text-slate-200"
              aria-label={`Report language ${getReportLanguageLabel(dashboard.project.language)}`}
            >
              {getReportLanguageLabel(dashboard.project.language)}
            </div>
            <p className="mt-4 text-sm leading-7 text-slate-300">
              {stripDomainProtocol(dashboard.project.domain_url)}
            </p>
          </div>
          {dashboard.project.domain_url ? (
            <a
              href={dashboard.project.domain_url}
              target="_blank"
              rel="noreferrer"
              className="inline-flex items-center gap-2 rounded border border-white/10 bg-white/5 px-4 py-2 text-sm font-semibold text-white transition hover:bg-white/10"
            >
              <span>Visit website</span>
              <ExternalLink className="h-4 w-4" />
            </a>
          ) : null}
        </div>
      </section>

      <section className="grid gap-4 md:grid-cols-4">
        {[
          {
            label: "SEO",
            value: formatScore(latestAudit?.seo_score ?? dashboard.project.latest_seo_score),
          },
          {
            label: "AI visibility",
            value: formatScore(latestAudit?.geo_score ?? dashboard.project.latest_geo_score),
          },
          {
            label: "AI answers",
            value: formatScore(latestAudit?.aeo_score ?? dashboard.project.latest_aeo_score),
          },
          {
            label: "Status",
            value: latestAudit?.status ? latestAudit.status.toUpperCase() : "No audit",
          },
        ].map((metric) => (
          <article
            key={metric.label}
            className="rounded-[28px] border border-white/10 bg-black/20 px-5 py-6"
          >
            <p className="text-[11px] font-bold uppercase tracking-[0.24em] text-slate-500">
              {metric.label}
            </p>
            <p className="mt-3 text-4xl font-black text-white">{metric.value}</p>
          </article>
        ))}
      </section>

      <PortalProjectActions projectId={projectId} auditId={latestAudit?.id ?? null} />

      <section className="grid gap-6 xl:grid-cols-[1.5fr_1fr]">
        <article className="rounded-[32px] border border-white/10 bg-black/20 p-6">
          <div className="mb-5 flex items-center gap-3">
            <TrendingUp className="h-5 w-5 text-white" />
            <div>
              <h3 className="text-xl font-black text-white">Performance trend</h3>
              <p className="text-sm text-slate-400">SEO and AIO history</p>
            </div>
          </div>
          <PortalTrendChart
            data={dashboard.trends}
            primaryColor={primaryColor}
            secondaryColor={secondaryColor}
          />
        </article>

        <article className="rounded-[32px] border border-white/10 bg-black/20 p-6">
          <div className="flex items-center gap-3">
            <Sparkles className="h-5 w-5 text-white" />
            <div>
              <h3 className="text-xl font-black text-white">Latest summary</h3>
              <p className="text-sm text-slate-400">
                Updated {formatDate(latestAudit?.created_at ?? dashboard.project.last_audit_at)}
              </p>
            </div>
          </div>
          {dashboard.latest_report?.expired ? (
            <div
              className="mt-4 inline-flex items-center gap-2 rounded-full border border-amber-500/30 bg-amber-500/10 px-3 py-1 text-[10px] font-black uppercase tracking-[0.18em] text-amber-200"
              title={`Removed after ${dashboard.latest_report.retention_days} days per retention policy.`}
            >
              <AlertTriangle className="h-3.5 w-3.5" />
              <span>Report expired</span>
            </div>
          ) : null}
          <p className="mt-5 text-sm leading-7 text-slate-300">
            {latestAudit?.summary ||
              "The latest assessment summary will appear here when enough signal is available."}
          </p>
        </article>
      </section>

      <section className="grid gap-6 xl:grid-cols-[1fr_1.2fr]">
        <article className="rounded-[32px] border border-white/10 bg-black/20 p-6">
          <div className="mb-5 flex items-center gap-3">
            <Sparkles className="h-5 w-5 text-white" />
            <div>
              <h3 className="text-xl font-black text-white">Recommended next actions</h3>
              <p className="text-sm text-slate-400">Prioritized by the latest assessment</p>
            </div>
          </div>

          {dashboard.recommendations.length === 0 ? (
            <p className="text-sm text-slate-400">
              No roadmap items are available yet for this project.
            </p>
          ) : (
            <div className="space-y-3">
              {dashboard.recommendations.map((recommendation) => (
                <div
                  key={recommendation.section_path || recommendation.title}
                  className="rounded-[24px] border border-white/10  p-4"
                >
                  <p className="font-semibold text-white">{recommendation.title}</p>
                  {recommendation.description ? (
                    <p className="mt-2 text-sm leading-6 text-slate-400">
                      {recommendation.description}
                    </p>
                  ) : null}
                  {latestAudit && recommendation.source_recommendation_key ? (
                    <div className="mt-3">
                      <PortalApprovalButtons
                        projectId={projectId}
                        auditId={latestAudit.id}
                        recommendationKey={recommendation.source_recommendation_key}
                        currentApproval={recommendation.approval ?? null}
                      />
                    </div>
                  ) : null}
                  {latestAudit && recommendation.annotation_count > 0 ? (
                    <PortalAnnotationThread
                      projectId={projectId}
                      auditId={latestAudit.id}
                      sectionPath={recommendation.section_path}
                      sourceRecommendationKey={recommendation.source_recommendation_key}
                      title={recommendation.title}
                      initialCount={recommendation.annotation_count}
                    />
                  ) : null}
                </div>
              ))}
            </div>
          )}
        </article>

        <article className="rounded-[32px] border border-white/10 bg-black/20 p-6">
          <div className="mb-5 flex items-center gap-3">
            <KanbanSquare className="h-5 w-5 text-white" />
            <div>
              <h3 className="text-xl font-black text-white">Exported Jira tasks</h3>
              <p className="text-sm text-slate-400">Read-only view of synced delivery items</p>
            </div>
          </div>

          {tasks.length === 0 ? (
            <p className="text-sm text-slate-400">
              No Jira tasks have been exported for this project yet.
            </p>
          ) : (
            <div className="space-y-3">
              {tasks.map((task) => (
                <a
                  key={task.id}
                  href={task.issue_url}
                  target="_blank"
                  rel="noreferrer"
                  className="block rounded-[24px] border border-white/10  p-4 transition hover:border-white/20 "
                >
                  <div className="flex flex-col gap-2 md:flex-row md:items-start md:justify-between">
                    <div>
                      <p className="text-sm font-black uppercase tracking-[0.18em] text-slate-400">
                        {task.issue_key}
                      </p>
                      <p className="mt-2 font-semibold text-white">{task.title}</p>
                    </div>
                    <div className="text-left md:text-right">
                      <p className="text-sm font-semibold text-white">{task.status_name}</p>
                      <p className="mt-1 text-xs uppercase tracking-[0.18em] text-slate-500">
                        {task.issue_type}
                      </p>
                    </div>
                  </div>
                  <p className="mt-3 text-xs text-slate-500">
                    Created {formatDate(task.created_at)}
                  </p>
                </a>
              ))}
            </div>
          )}
        </article>
      </section>
    </div>
  );
}
