"use client";

import React, { useMemo } from "react";
import Link from "next/link";
import { Network, Radar, Zap, Share2 } from "lucide-react";

import {
  ProjectFeatureEmptyState,
  ProjectFeatureErrorState,
  ProjectFeatureHeader,
  ProjectFeatureLoadingView,
  ProjectFeatureMetaRow,
  ProjectMetricCard,
} from "@/components/dashboard/ProjectFeatureScaffold";
import { useProjectLatestAudit } from "@/hooks/useProjectLatestAudit";
import { isAuditResult } from "@/types/auditResult";
import { GlassCard } from "@/components/ui/GlassComponents";
import Button from "@/components/ui/Button";
import { resolveProjectAuditTarget } from "@/lib/projectAuditFeature";

function normalizeEntityList(value: unknown): string[] {
  if (!Array.isArray(value)) {
    return [];
  }
  return value
    .filter((entry): entry is string => typeof entry === "string" && entry.trim().length > 0)
    .slice(0, 24);
}

export default function ProjectEntitiesClient({ projectId }: { projectId: string }) {
  const { latestAudit, loading, error } = useProjectLatestAudit(projectId, {
    includeFullReport: true,
    preferredAuditType: "DEEP",
  });

  const report = useMemo(() => {
    const rawReport = latestAudit?.full_report;
    return isAuditResult(rawReport) ? rawReport : null;
  }, [latestAudit?.full_report]);

  const entities = useMemo(() => normalizeEntityList(report?.entities), [report?.entities]);
  const competitorDomains = useMemo(
    () =>
      (report?.competitors ?? [])
        .map((competitor) => competitor.name)
        .filter((name): name is string => typeof name === "string" && name.trim().length > 0)
        .slice(0, 8),
    [report?.competitors]
  );
  const semanticSuggestions = useMemo(() => {
    return (report?.suggestions ?? [])
      .filter((suggestion) =>
        /content|entity|topic|semantic|authority/i.test(
          `${suggestion.category ?? ""} ${suggestion.title ?? ""}`
        )
      )
      .slice(0, 5);
  }, [report?.suggestions]);
  const target = resolveProjectAuditTarget(latestAudit, report);

  if (loading) {
    return (
      <ProjectFeatureLoadingView
        label="Loading entity insights..."
        icon={Share2}
        title="Entity"
        accent="Mapping"
        metrics={3}
      />
    );
  }

  if (error) {
    return <ProjectFeatureErrorState message={error} title="No Entity Data" />;
  }

  if (!latestAudit || !report) {
    return (
      <ProjectFeatureEmptyState
        icon={Network}
        title="No Entity Insights Yet"
        description={
          <>
            Run a <span className="font-black text-(--t-1)">Deep Assessment</span> to extract entity
            coverage and competitor overlap insights.
          </>
        }
        action={
          <Link href={`/dashboard/projects/${projectId}/settings`}>
            <Button variant="outline" size="lg">
              Open Project Setup
            </Button>
          </Link>
        }
      />
    );
  }

  return (
    <section className="space-y-10 group/entities">
      <ProjectFeatureHeader
        icon={Share2}
        title="Entity"
        accent="Mapping"
        targetType={target.type}
        targetLabel={target.label}
      />

      <div className="grid gap-6 md:grid-cols-3">
        {[
          {
            label: "Detected Entities",
            value: entities.length,
            icon: <Share2 className="h-4 w-4" />,
            tone: "primary" as const,
          },
          {
            label: "Tracked Competitors",
            value: competitorDomains.length,
            icon: <Radar className="h-4 w-4" />,
            tone: "indigo" as const,
          },
          {
            label: "Priority Roadmap Items",
            value: semanticSuggestions.length,
            icon: <Zap className="h-4 w-4" />,
            tone: "primary" as const,
          },
        ].map((node, i) => (
          <ProjectMetricCard
            key={i}
            label={node.label}
            value={node.value}
            icon={node.icon}
            tone={node.tone}
            valueClassName="text-(--t-1)"
          />
        ))}
      </div>

      <div className="grid gap-8 lg:grid-cols-2">
        <GlassCard className="p-8 border-primary/20 bg-primary/[0.01]">
          <div className="flex items-center gap-3 mb-8">
            <div className="flex h-8 w-8 items-center justify-center rounded-lg border border-primary/30 bg-primary/10 text-primary">
              <Share2 size={16} />
            </div>
            <h3 className="text-xs font-black uppercase tracking-widest text-primary ">
              Entity Surface
            </h3>
          </div>
          <div className="flex flex-wrap gap-2">
            {entities.length === 0 ? (
              <p className="text-xs text-(--t-3) ">No semantic entities extracted for this run.</p>
            ) : (
              entities.map((entity) => (
                <span
                  key={entity}
                  className="rounded-xl border border-(--line) bg-(--line-2) px-3 py-1.5 text-[10px] font-black uppercase tracking-widest text-(--t-2)  hover:border-primary/30 hover:bg-primary/5 transition-all"
                >
                  {entity}
                </span>
              ))
            )}
          </div>
        </GlassCard>

        <GlassCard className="p-8 border-primary/20 bg-primary/[0.01]">
          <div className="flex items-center gap-3 mb-8">
            <div className="flex h-8 w-8 items-center justify-center rounded-lg border border-[color-mix(in_srgb,var(--purple)_30%,transparent)] bg-[color-mix(in_srgb,var(--purple)_10%,transparent)] text-(--purple)">
              <Radar size={16} />
            </div>
            <h3 className="text-xs font-black uppercase tracking-widest text-(--purple) ">
              Competitor Coverage
            </h3>
          </div>
          <div className="space-y-3">
            {competitorDomains.length === 0 ? (
              <p className="text-xs text-(--t-3) ">No competitor entities linked in this audit.</p>
            ) : (
              competitorDomains.map((domain) => (
                <div
                  key={domain}
                  className="rounded border border-(--line) bg-(--line-2) px-5 py-3 text-sm font-black text-(--t-1)  uppercase tracking-tighter hover:bg-(--line-2) transition-all"
                >
                  {domain}
                </div>
              ))
            )}
          </div>
        </GlassCard>
      </div>

      <GlassCard className="p-8 border-primary/20 bg-primary/[0.01]">
        <div className="flex items-center gap-3 mb-8">
          <div className="flex h-8 w-8 items-center justify-center rounded-lg border border-primary/30 bg-primary/10 text-primary">
            <Zap size={16} />
          </div>
          <h3 className="text-xs font-black uppercase tracking-widest text-primary ">
            Priority Semantic Roadmap
          </h3>
        </div>
        <div className="grid md:grid-cols-2 gap-4">
          {semanticSuggestions.length === 0 ? (
            <p className="text-xs text-(--t-3) ">No semantic recommendations identified.</p>
          ) : (
            semanticSuggestions.map((suggestion, index) => (
              <div
                key={`${suggestion.title}-${index}`}
                className="rounded border border-(--line) bg-(--line-2) p-4 hover:bg-(--line-2) transition-all"
              >
                <p className="text-[10px] font-black text-primary uppercase tracking-[0.2em] mb-1  opacity-60">
                  Recommendation
                </p>
                <p className="text-sm font-black text-(--t-1)  mb-1">{suggestion.title}</p>
                <p className="text-xs text-(--t-2) font-medium leading-relaxed  opacity-80">
                  {suggestion.action}
                </p>
              </div>
            ))
          )}
        </div>
      </GlassCard>

      <ProjectFeatureMetaRow
        auditType={latestAudit.audit_type}
        targetType={target.type}
        date={latestAudit.created_at}
      />
    </section>
  );
}
