"use client";

import React from "react";
import {
  FileText,
  Sparkles,
  HelpCircle,
  BookOpen,
  MapPin,
  Play,
  Image,
  ShoppingCart,
  Newspaper,
  Search,
  Link2,
  AtSign,
  ListOrdered,
  type LucideIcon,
} from "lucide-react";
import Tooltip from "@/components/ui/Tooltip";
import { cx } from "@/components/ui/utils";

type SerpFeatureInfo = {
  label: string;
  fullLabel: string;
  colorClasses: string;
  icon: LucideIcon;
};

const SERP_FEATURE_CONFIG: Record<string, SerpFeatureInfo> = {
  featured_snippet: {
    label: "Snippet",
    fullLabel: "Featured Snippet",
    colorClasses: "border-teal-500/30 bg-teal-500/10 text-teal-400",
    icon: FileText,
  },
  ai_overview: {
    label: "AIO",
    fullLabel: "AI Overview",
    colorClasses: "border-violet-500/30 bg-violet-500/10 text-violet-400",
    icon: Sparkles,
  },
  people_also_ask: {
    label: "PAA",
    fullLabel: "People Also Ask",
    colorClasses: "border-sky-500/30 bg-sky-500/10 text-sky-400",
    icon: HelpCircle,
  },
  knowledge_panel: {
    label: "KP",
    fullLabel: "Knowledge Panel",
    colorClasses: "border-amber-500/30 bg-amber-500/10 text-amber-400",
    icon: BookOpen,
  },
  local_pack: {
    label: "Local",
    fullLabel: "Local Pack",
    colorClasses: "border-emerald-500/30 bg-emerald-500/10 text-emerald-400",
    icon: MapPin,
  },
  video: {
    label: "Video",
    fullLabel: "Video Results",
    colorClasses: "border-rose-500/30 bg-rose-500/10 text-rose-400",
    icon: Play,
  },
  images: {
    label: "Images",
    fullLabel: "Image Pack",
    colorClasses: "border-sky-500/30 bg-sky-500/10 text-sky-400",
    icon: Image,
  },
  shopping: {
    label: "Shop",
    fullLabel: "Shopping Results",
    colorClasses: "border-orange-500/30 bg-orange-500/10 text-orange-400",
    icon: ShoppingCart,
  },
  top_stories: {
    label: "News",
    fullLabel: "Top Stories",
    colorClasses: "border-zinc-400/30 bg-zinc-400/10 text-zinc-400",
    icon: Newspaper,
  },
  related_searches: {
    label: "Related",
    fullLabel: "Related Searches",
    colorClasses: "border-zinc-400/30 bg-zinc-400/10 text-zinc-400",
    icon: Search,
  },
  twitter: {
    label: "X/Twitter",
    fullLabel: "X (Twitter) Results",
    colorClasses: "border-zinc-400/30 bg-zinc-400/10 text-zinc-400",
    icon: AtSign,
  },
  site_links: {
    label: "Sitelinks",
    fullLabel: "Sitelinks",
    colorClasses: "border-zinc-400/30 bg-zinc-400/10 text-zinc-400",
    icon: Link2,
  },
};

const HIDDEN_FEATURES = new Set(["organic"]);

const DEFAULT_FEATURE: Omit<SerpFeatureInfo, "label" | "fullLabel"> = {
  colorClasses: "border-zinc-500/30 bg-zinc-500/10 text-zinc-400",
  icon: ListOrdered,
};

function humanize(key: string): string {
  return key.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

function getFeatureInfo(feature: string): SerpFeatureInfo {
  const config = SERP_FEATURE_CONFIG[feature];
  if (config) return config;
  const label = humanize(feature);
  return { label, fullLabel: label, ...DEFAULT_FEATURE };
}

export function SerpFeatureBadge({ feature }: { feature: string }) {
  const info = getFeatureInfo(feature);
  const Icon = info.icon;

  return (
    <Tooltip content={info.fullLabel} side="top">
      <span
        className={cx(
          "inline-flex items-center gap-1 rounded-full border px-1.5 py-0.5 text-[10px] font-semibold leading-tight whitespace-nowrap",
          info.colorClasses
        )}
      >
        <Icon size={10} className="shrink-0" />
        {info.label}
      </span>
    </Tooltip>
  );
}

export function SerpFeatureList({ features, max = 4 }: { features: string[]; max?: number }) {
  const visible = features.filter((f) => !HIDDEN_FEATURES.has(f));
  if (!visible.length) return <span className="text-(--t-3)">-</span>;

  const shown = visible.slice(0, max);
  const overflow = visible.length - max;

  return (
    <span className="inline-flex flex-wrap items-center gap-1">
      {shown.map((f) => (
        <SerpFeatureBadge key={f} feature={f} />
      ))}
      {overflow > 0 && (
        <Tooltip
          content={visible
            .slice(max)
            .map((f) => getFeatureInfo(f).fullLabel)
            .join(", ")}
          side="top"
        >
          <span className="inline-flex items-center rounded-full border border-zinc-500/30 bg-zinc-500/10 px-1.5 py-0.5 text-[10px] font-semibold text-zinc-400">
            +{overflow}
          </span>
        </Tooltip>
      )}
    </span>
  );
}

export function SerpFeatureSummary({
  snapshots,
}: {
  snapshots: Array<{ serp_features_present: string[] }>;
}) {
  const counts: Record<string, number> = {};
  for (const snap of snapshots) {
    for (const f of snap.serp_features_present) {
      if (HIDDEN_FEATURES.has(f)) continue;
      counts[f] = (counts[f] || 0) + 1;
    }
  }
  const entries = Object.entries(counts).sort((a, b) => b[1] - a[1]);
  if (!entries.length) return null;

  return (
    <div className="rounded-xl border-0 bg-(--line-2) p-4">
      <p className="text-[10px] font-bold uppercase tracking-widest text-(--t-3) mb-3">
        SERP Features Distribution
      </p>
      <div className="space-y-2">
        {entries.map(([feature, count]) => {
          const info = getFeatureInfo(feature);
          const Icon = info.icon;
          const pct = snapshots.length ? Math.round((count / snapshots.length) * 100) : 0;
          return (
            <div key={feature} className="flex items-center gap-2">
              <Icon size={13} className={info.colorClasses.split(" ").pop()} />
              <span className="text-xs text-(--t-2) w-28 truncate">{info.fullLabel}</span>
              <div className="flex-1 h-1.5 rounded-full bg-(--line-2) overflow-hidden">
                <div
                  className="h-full w-(--bw) rounded-full bg-current transition-all duration-300"
                  style={
                    {
                      "--bw": `${pct}%`,
                    } as React.CSSProperties
                  }
                />
              </div>
              <span className="text-[11px] font-semibold tabular-nums text-(--t-2) w-16 text-right">
                {count} / {snapshots.length}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

export { SERP_FEATURE_CONFIG, HIDDEN_FEATURES, getFeatureInfo };
