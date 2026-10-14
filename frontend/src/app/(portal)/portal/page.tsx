import Link from "next/link";
import { ArrowRight, Clock3, FolderOpen } from "lucide-react";
import type { PortalProjectSummary } from "@/services/portalService";
import { serverFetch } from "@/utils/server-fetch";

const formatScore = (value: number | null) =>
  typeof value === "number" ? Math.round(value) : "N/A";

const formatDate = (value: string | null) => {
  if (!value) {
    return "No assessments yet";
  }

  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "No assessments yet";
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

export default async function PortalHomePage() {
  const response = await serverFetch("/portal/projects", {
    cache: "no-store",
    redirectOnUnauthorized: false,
  });

  if (!response.ok) {
    return (
      <div className="rounded-5xl border border-white/10 bg-black/20 p-10 text-sm text-slate-300">
        Portal projects are temporarily unavailable.
      </div>
    );
  }

  const projects = (await response.json()) as PortalProjectSummary[];

  return (
    <div className="space-y-8">
      <section className="rounded-5xl border border-white/10  p-8 shadow-[0_30px_80px_rgba(0,0,0,0.22)]">
        <p className="text-[11px] font-bold uppercase tracking-[0.3em] text-slate-400">
          Project Access
        </p>
        <h2 className="mt-3 text-3xl font-black tracking-tight text-white md:text-4xl">
          Assigned project dashboards
        </h2>
        <p className="mt-4 max-w-2xl text-sm leading-7 text-slate-300">
          Each workspace below is scoped to your client account. You can review the latest SEO and
          AIO performance plus the Jira tasks already exported by the agency team.
        </p>
      </section>

      {projects.length === 0 ? (
        <div className="rounded-5xl border border-dashed border-white/15 bg-black/20 p-10 text-center">
          <FolderOpen className="mx-auto h-10 w-10 text-slate-500" />
          <h3 className="mt-4 text-xl font-bold text-white">No assigned projects yet</h3>
          <p className="mt-2 text-sm text-slate-400">
            Your agency has not assigned a project to this portal account yet.
          </p>
        </div>
      ) : (
        <div className="grid gap-6 xl:grid-cols-2">
          {projects.map((project) => (
            <article
              key={project.id}
              className="group rounded-5xl border border-white/10 bg-black/25 p-7 transition hover:border-white/20 hover:bg-black/30"
            >
              <div className="flex items-start justify-between gap-4">
                <div>
                  <p className="text-[11px] font-bold uppercase tracking-[0.26em] text-slate-500">
                    Assigned project
                  </p>
                  <h3 className="mt-2 text-2xl font-black text-white">{project.name}</h3>
                  <p className="mt-2 text-sm text-slate-400">
                    {stripDomainProtocol(project.domain_url)}
                  </p>
                </div>
                <Link
                  href={`/portal/projects/${project.id}`}
                  className="inline-flex items-center gap-2 rounded border border-white/10 bg-white/5 px-4 py-2 text-sm font-semibold text-white transition hover:bg-white/10"
                >
                  <span>Open</span>
                  <ArrowRight className="h-4 w-4 transition group-hover:translate-x-0.5" />
                </Link>
              </div>

              <div className="mt-6 grid grid-cols-3 gap-3">
                {[
                  { label: "SEO", value: formatScore(project.latest_seo_score) },
                  { label: "AI visibility", value: formatScore(project.latest_geo_score) },
                  { label: "AI answers", value: formatScore(project.latest_aeo_score) },
                ].map((metric) => (
                  <div key={metric.label} className="rounded-4xl border border-white/10  px-4 py-5">
                    <p className="text-[11px] font-bold uppercase tracking-[0.24em] text-slate-500">
                      {metric.label}
                    </p>
                    <p className="mt-3 text-3xl font-black text-white">{metric.value}</p>
                  </div>
                ))}
              </div>

              <div className="mt-6 flex items-center gap-2 text-sm text-slate-400">
                <Clock3 className="h-4 w-4" />
                <span>Latest audit: {formatDate(project.last_audit_at)}</span>
              </div>
            </article>
          ))}
        </div>
      )}
    </div>
  );
}
