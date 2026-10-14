"use client";

import React, { useState } from "react";
import { motion, AnimatePresence } from "motion/react";
import { ChevronDown, ChevronRight } from "lucide-react";
import { getScoreColor } from "@/lib/scoreColors";

type SubScore = {
  key: string;
  label: string;
  score: number;
  weight: number;
};

type ScoreBreakdownAccordionProps = {
  title: string;
  overallScore: number;
  subScores: SubScore[];
  defaultOpen?: boolean;
  isBrandWithoutUrl?: boolean;
};

const LABEL_MAP: Record<string, string> = {
  // SEO
  core_web_vitals: "Core Web Vitals & Performance",
  technical_seo: "Technical SEO",
  onpage_content: "On-Page & Content Quality",
  eeat_trust: "E-E-A-T & Trust Signals",
  security_accessibility: "Security & Accessibility",
  // GEO
  advanced_local_schema: "Advanced Local Schema",
  napw_completeness: "NAP-W Completeness",
  spatial_content: "Spatial Content Relevance",
  brand_citation: "Brand & Citation Readiness",
  // AEO
  llm_schema_readiness: "AI/LLM Schema Readiness",
  semantic_entity_density: "Semantic & Entity Density",
  information_gain: "Information Gain & Readability",
  snippet_formatting: "Snippet & LLM Formatting",
};

const BRAND_LABEL_MAP: Record<string, string> = {
  // SEO (brand context)
  technical_seo: "Search Presence Signals",
  onpage_content: "Content & Entity Quality",
  eeat_trust: "E-E-A-T & Authority",
  security_accessibility: "Trust & Accessibility",
  // GEO (brand context)
  advanced_local_schema: "Entity Schema Coverage",
  napw_completeness: "Entity Data Completeness",
  spatial_content: "Contextual Relevance",
  brand_citation: "Brand & Citation Readiness",
  // AEO (brand context)
  llm_schema_readiness: "AI/LLM Entity Readiness",
  semantic_entity_density: "Semantic & Entity Density",
  information_gain: "Information Gain & Readability",
  snippet_formatting: "Snippet & LLM Formatting",
};

function formatLabel(key: string, isBrand = false): string {
  if (isBrand) {
    return (
      BRAND_LABEL_MAP[key] ??
      LABEL_MAP[key] ??
      key.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase())
    );
  }
  return LABEL_MAP[key] ?? key.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

const ScoreBreakdownAccordion = ({
  title,
  overallScore,
  subScores,
  defaultOpen = false,
  isBrandWithoutUrl = false,
}: ScoreBreakdownAccordionProps) => {
  const [isOpen, setIsOpen] = useState(defaultOpen);
  const overallColor = getScoreColor(overallScore);

  if (!subScores || subScores.length === 0) return null;

  return (
    <div className="overflow-hidden rounded-xl border border-(--line) bg-(--line-2) shadow-lg  transition-all duration-300 hover:border-(--line)">
      {/* Header */}
      <button
        onClick={() => setIsOpen(!isOpen)}
        className="group flex w-full items-center justify-between gap-3 px-5 py-4 text-left transition-colors hover:bg-(--line-2)"
        aria-expanded={isOpen}
      >
        <div className="flex items-center gap-3">
          <div className="flex h-6 w-6 items-center justify-center rounded-lg bg-(--line-2) text-(--t-2) transition-transform duration-300">
            {isOpen ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
          </div>
          <span className="text-sm font-black uppercase tracking-widest text-(--t-2) transition-colors group-hover:text-(--t-1)">
            {title}
          </span>
        </div>
        <div className="flex items-center gap-2">
          <div className="h-1 w-12 rounded-full overflow-hidden bg-(--line-2) sm:block hidden">
            <div
              className={`h-full w-(--bw) ${overallColor.bg}`}
              style={{ "--bw": `${overallScore}%` } as React.CSSProperties}
            />
          </div>
          <span className={`font-mono text-sm font-black ${overallColor.text} tabular-nums`}>
            {Math.round(overallScore)}
          </span>
        </div>
      </button>

      {/* Expanded content */}
      <AnimatePresence initial={false}>
        {isOpen && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.3, ease: [0.04, 0.62, 0.23, 0.98] }}
            className="overflow-hidden"
          >
            <div className="space-y-4 border-t border-(--line) px-6 pb-6 pt-5">
              {subScores.map((sub) => {
                const color = getScoreColor(sub.score);
                return (
                  <div key={sub.key} className="space-y-2">
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-2">
                        <span className="text-[10px] font-black uppercase tracking-widest text-(--t-2)">
                          {formatLabel(sub.key, isBrandWithoutUrl)}
                        </span>
                        <span className="rounded-md bg-(--line-2) px-1.5 py-0.5 text-[8px] font-black uppercase text-(--t-3)">
                          {Math.round(sub.weight * 100)}%
                        </span>
                      </div>
                      <span
                        className={`font-mono text-[11px] font-black ${color.text} tabular-nums`}
                      >
                        {Math.round(sub.score)}
                      </span>
                    </div>
                    <div className="h-1 w-full overflow-hidden rounded-full bg-(--line-2)">
                      <motion.div
                        initial={{ width: 0 }}
                        animate={{ width: `${Math.max(0, Math.min(100, sub.score))}%` }}
                        transition={{ duration: 0.8, delay: 0.2 }}
                        className={`h-full rounded-full ${color.bg}`}
                      />
                    </div>
                  </div>
                );
              })}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
};

export default ScoreBreakdownAccordion;
