import React from "react";

import ProjectPageFrame from "@/components/dashboard/ProjectPageFrame";
import ProjectTimelineClient from "@/components/dashboard/ProjectTimelineClient";

export default function ProjectTimelinePage() {
  return (
    <ProjectPageFrame
      title="Trend"
      accent="Intelligence"
      accentClassName="text-(--purple)"
      description="Track score movement over time, compare recent periods, and inspect the audit checkpoints that feed monthly progress reporting."
      descriptionClassName="max-w-2xl text-sm font-medium leading-relaxed text-(--t-2)"
    >
      <ProjectTimelineClient />
    </ProjectPageFrame>
  );
}
