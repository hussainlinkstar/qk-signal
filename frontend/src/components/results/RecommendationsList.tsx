import React, { useState, useEffect } from "react";
import { useParams } from "next/navigation";
import ReactMarkdown from "react-markdown";
import {
  Sparkles,
  Target,
  AlertCircle,
  TrendingUp,
  ShieldCheck,
  Lightbulb,
  Search,
  ExternalLink,
  CheckCircle2,
  HelpCircle,
  AlertTriangle,
} from "lucide-react";
import { cx } from "@/components/ui/utils";
import type { DetailedRecommendation } from "@/lib/reportAdapters";
import { useJiraExportTracker } from "@/hooks/useJiraExportTracker";
import GeoIcon from "@/components/ui/GeoIcon";
import ClaimFeedbackButtons from "@/components/results/ClaimFeedbackButtons";
import { useClaimFeedback } from "@/hooks/useClaimFeedback";
import { buildClaimKeyAsync } from "@/lib/claimKey";
import { isTitleRedundantWithDescription } from "@/lib/recommendationTitle";

const RecommendationsList = ({
  recommendations,
  projectId: propProjectId,
  auditId: propAuditId,
  sampleMode = false,
}: {
  recommendations: DetailedRecommendation[];
  projectId?: string | number | null;
  siteUrl?: string | null;
  auditId?: string | number | null;
  sampleMode?: boolean;
}) => {
  const params = useParams<{ projectId: string; id: string }>();
  const projectId = propProjectId || params?.projectId || "";
  const auditId = propAuditId || params?.id || null;
  const { getTrackedExport } = useJiraExportTracker(projectId);
  const { getMyFeedback, getSummary, submit, remove } = useClaimFeedback(auditId);
  const [claimKeys, setClaimKeys] = useState<Record<number, string>>({});

  useEffect(() => {
    let cancelled = false;
    async function computeKeys() {
      const keys: Record<number, string> = {};
      for (let i = 0; i < recommendations.length; i++) {
        const rec = recommendations[i];
        keys[i] = await buildClaimKeyAsync({
          title: rec.title,
          category: rec.category,
          description: rec.description,
        });
      }
      if (!cancelled) setClaimKeys(keys);
    }
    computeKeys();
    return () => {
      cancelled = true;
    };
  }, [recommendations]);

  if (!recommendations || recommendations.length === 0) {
    return null;
  }

  return (
    <div className="space-y-8">
      {recommendations.map((rec, index) => {
        const trackedExport = getTrackedExport(`results:${rec.title}`);
        const isTechnical = rec.category.toLowerCase().includes("technical");
        const isSEO =
          (rec.engines.includes("SEO") || rec.category.toLowerCase().includes("seo")) &&
          !isTechnical;
        const isAEO =
          rec.engines.includes("AEO") ||
          rec.category.toLowerCase().includes("aeo") ||
          rec.category.toLowerCase().includes("answer");
        const isGEO =
          rec.engines.includes("GEO") ||
          rec.category.toLowerCase().includes("geo") ||
          rec.category.toLowerCase().includes("citation") ||
          rec.category.toLowerCase().includes("generative");

        const CategoryIcon = isTechnical
          ? Search
          : isSEO
            ? Search
            : isAEO
              ? Sparkles
              : isGEO
                ? GeoIcon
                : Lightbulb;

        const categoryColor = isTechnical
          ? "text-(--purple) bg-cyan-500/10 border-cyan-500/20"
          : isSEO
            ? "text-blue-400 bg-blue-500/10 border-blue-500/20"
            : isAEO
              ? "text-fuchsia-400 bg-fuchsia-500/10 border-fuchsia-500/20"
              : isGEO
                ? "text-emerald-400 bg-emerald-500/10 border-emerald-500/20"
                : "text-(--purple) bg-[color-mix(in_srgb,var(--purple)_10%,transparent)] border-[color-mix(in_srgb,var(--purple)_20%,transparent)]";

        const priorityColor =
          rec.impact === "Critical"
            ? "text-rose-400 bg-rose-500/10 border-rose-500/20"
            : rec.impact === "Strategic"
              ? "text-amber-400 bg-amber-500/10 border-amber-500/20"
              : "text-(--t-2) bg-(--line-2) border-(--line)";

        const ck = claimKeys[index];
        const myFb = ck ? getMyFeedback(ck) : undefined;
        const fbSummary = ck ? getSummary(ck) : null;

        return (
          <div
            key={index}
            className="group relative overflow-hidden rounded border border-(--line) bg-[color-mix(in_srgb,var(--panel)_20%,transparent)] p-10 md:p-12 transition-all duration-700 hover:bg-[color-mix(in_srgb,var(--panel)_40%,transparent)] hover:border-(--line) shadow-2xl"
          >
            {/* Ambient status glow */}
            <div
              className={cx(
                "absolute -top-24 -right-24 w-64 h-64 rounded-full blur-[100px] opacity-0 group-hover:opacity-10 transition-opacity duration-1000 pointer-events-none",
                rec.impact === "Critical"
                  ? "bg-rose-500"
                  : rec.impact === "Strategic"
                    ? "bg-amber-500"
                    : "bg-indigo-500"
              )}
            />

            <div className="flex flex-col gap-6 relative z-10">
              {/* Header Row: Badges and Alignment */}
              <div className="flex flex-wrap items-center justify-between gap-4">
                <div className="flex items-center gap-3">
                  <div className="flex items-center justify-center w-8 h-8 rounded-xl bg-(--line-2) border border-(--line) shadow-inner text-xs font-black text-(--t-3) group-hover:text-(--t-1) transition-colors">
                    {String(index + 1).padStart(2, "0")}
                  </div>
                  <div
                    className={cx(
                      "flex items-center gap-1.5 px-3 py-1 rounded-lg border text-[10px] font-black uppercase tracking-widest transition-all",
                      categoryColor
                    )}
                  >
                    <CategoryIcon className="h-3.5 w-3.5" />
                    {rec.category}
                  </div>
                </div>

                <div className="flex items-center gap-2">
                  <div
                    className={cx(
                      "flex items-center gap-1.5 px-2.5 py-1 rounded-md border text-[9px] font-black tracking-widest uppercase",
                      priorityColor
                    )}
                  >
                    {rec.impact === "Critical" ? (
                      <AlertCircle className="w-3 h-3" />
                    ) : rec.impact === "Strategic" ? (
                      <TrendingUp className="w-3 h-3" />
                    ) : (
                      <ShieldCheck className="w-3 h-3" />
                    )}
                    {rec.impact}
                  </div>

                  {rec.confidence && (
                    <div
                      className={cx(
                        "flex items-center gap-1.5 px-2.5 py-1 rounded-md border text-[9px] font-black tracking-widest uppercase",
                        rec.confidence === "high"
                          ? "text-emerald-400 bg-emerald-500/10 border-emerald-500/20"
                          : rec.confidence === "medium"
                            ? "text-amber-400 bg-amber-500/10 border-amber-500/20"
                            : "text-rose-400 bg-rose-500/10 border-rose-500/20"
                      )}
                    >
                      {rec.confidence === "high" ? (
                        <CheckCircle2 className="w-3 h-3" />
                      ) : rec.confidence === "medium" ? (
                        <HelpCircle className="w-3 h-3" />
                      ) : (
                        <AlertTriangle className="w-3 h-3" />
                      )}
                      {rec.confidence}
                    </div>
                  )}

                  {/* Engine Icons */}
                  <div className="flex items-center gap-1.5 ml-2">
                    {rec.engines.map((engine) => (
                      <div
                        key={engine}
                        className={cx(
                          "p-1.5 rounded-lg border border-(--line) bg-(--line-2) text-(--t-3)",
                          engine === "SEO" && "text-blue-400/60",
                          engine === "GEO" && "text-emerald-400/60",
                          engine === "AEO" && "text-fuchsia-400/60"
                        )}
                      >
                        {engine === "SEO" && <Target className="w-3.5 h-3.5" />}
                        {engine === "GEO" && <GeoIcon className="w-3.5 h-3.5" />}
                        {engine === "AEO" && <Sparkles className="w-3.5 h-3.5" />}
                      </div>
                    ))}
                  </div>
                </div>
              </div>

              {/* Core Insight */}
              <div className="space-y-6">
                {!isTitleRedundantWithDescription(rec.title, rec.description) && (
                  <h4 className="text-2xl font-bold text-(--t-1) tracking-tight leading-tight group-hover:text-(--t-1) transition-colors duration-500">
                    {rec.title}
                  </h4>
                )}
                <div className="prose prose-invert prose-base max-w-none border-l-2 border-(--line) pl-10 group-hover:border-primary/40 transition-all duration-700">
                  <ReactMarkdown
                    components={{
                      p: ({ children }) => (
                        <p className="text-(--t-2) leading-relaxed font-medium mb-0 text-lg">
                          {children}
                        </p>
                      ),
                      strong: ({ children }) => (
                        <strong className="text-(--t-1) font-bold underline decoration-primary/20 underline-offset-4">
                          {children}
                        </strong>
                      ),
                    }}
                  >
                    {rec.description}
                  </ReactMarkdown>
                </div>
              </div>

              {/* Neural Trace Footer */}
              <div className="pt-8 flex flex-col gap-4 border-t border-(--line)">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-3 text-[11px] font-bold text-(--t-3) uppercase tracking-[0.25em] group-hover:text-(--t-2) transition-colors">
                    <div className="w-1.5 h-1.5 rounded-full bg-primary animate-pulse" />
                    Strategic Recommendation
                  </div>
                  {!sampleMode && (
                    <div className="flex items-center gap-4">
                      {trackedExport ? (
                        <>
                          <span className="rounded-xl border border-emerald-400/20 bg-emerald-500/10 px-4 py-2 text-[10px] font-bold uppercase tracking-widest text-emerald-200">
                            Sent to Jira
                          </span>
                          <a
                            href={trackedExport.issueUrl}
                            target="_blank"
                            rel="noreferrer"
                            className="flex items-center gap-2.5 text-[10px] font-bold uppercase tracking-widest transition-all text-emerald-200 border border-emerald-500/20 bg-emerald-500/5 px-4 py-2 rounded-xl hover:bg-emerald-500/10 hover:border-emerald-500/40"
                          >
                            Ticket {trackedExport.issueKey}
                            <ExternalLink className="h-3.5 w-3.5" />
                          </a>
                        </>
                      ) : null}
                    </div>
                  )}
                </div>

                {/* Claim Feedback */}
                {ck && auditId && (
                  <ClaimFeedbackButtons
                    claimKey={ck}
                    currentFeedback={myFb?.feedback_type || null}
                    summary={fbSummary}
                    onSubmit={(type, text) =>
                      submit({
                        claimKey: ck,
                        claimText: rec.title,
                        claimCategory: rec.category,
                        feedbackType: type,
                        feedbackText: text,
                      })
                    }
                    onRemove={myFb ? () => remove(myFb.id, ck) : undefined}
                  />
                )}
              </div>
            </div>
          </div>
        );
      })}
    </div>
  );
};

export default RecommendationsList;
