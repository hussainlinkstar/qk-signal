"use client";

import React from "react";
import { Sparkles } from "lucide-react";
import { motion } from "motion/react";

import ProjectPageFrame from "@/components/dashboard/ProjectPageFrame";
import LLMTrafficChart from "@/components/dashboard/LLMTrafficChart";
import SnippetBattlePanel from "@/components/dashboard/SnippetBattlePanel";
import KeywordManager from "@/components/dashboard/KeywordManager";
import ProjectVisibilityPanel from "@/components/dashboard/ProjectVisibilityPanel";
import BrandVsCompetitorVisibilityChart from "@/components/dashboard/BrandVsCompetitorVisibilityChart";
import ProjectBotLogAnalyzerPanel from "@/components/dashboard/ProjectBotLogAnalyzerPanel";
import ProjectOffPageMentionsPanel from "@/components/dashboard/ProjectOffPageMentionsPanel";
import ProjectVolatilityIndexPanel from "@/components/dashboard/ProjectVolatilityIndexPanel";

export default function ProjectMonitoringClient({ projectId }: { projectId: string }) {
  return (
    <ProjectPageFrame
      title="Continuous"
      accent="Monitoring"
      description="Track AI-engine traffic, snippet ownership, visibility volatility, crawler behavior, and off-page mentions from the same project workspace."
      className="pb-20"
    >
      <div className="inline-flex w-fit items-center gap-2 rounded-full border-0 bg-[#E8F1FF] px-2.5 py-1 text-[10px] font-black uppercase tracking-widest text-primary">
        <Sparkles className="h-3 w-3" />
        AIO Live Tracking
      </div>

      <div className="space-y-12 group/monitoring">
        <motion.section
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.1 }}
        >
          <LLMTrafficChart projectId={projectId} />
        </motion.section>

        <motion.section
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.2 }}
        >
          <SnippetBattlePanel projectId={projectId} />
        </motion.section>

        <motion.section
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.3 }}
        >
          <KeywordManager projectId={projectId} />
        </motion.section>

        <motion.section
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.4 }}
        >
          <ProjectVisibilityPanel projectId={projectId} />
        </motion.section>

        <motion.section
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.45 }}
        >
          <BrandVsCompetitorVisibilityChart projectId={projectId} />
        </motion.section>

        <motion.section
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.5 }}
        >
          <ProjectBotLogAnalyzerPanel projectId={projectId} />
        </motion.section>

        <motion.section
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.6 }}
        >
          <ProjectVolatilityIndexPanel projectId={projectId} />
        </motion.section>

        <motion.section
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.7 }}
        >
          <ProjectOffPageMentionsPanel projectId={projectId} />
        </motion.section>
      </div>
    </ProjectPageFrame>
  );
}
