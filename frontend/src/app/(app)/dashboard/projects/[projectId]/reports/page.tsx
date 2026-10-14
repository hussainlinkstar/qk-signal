import React from "react";

import ProjectPageFrame from "@/components/dashboard/ProjectPageFrame";
import ProjectProgressReportsClient from "@/components/dashboard/ProjectProgressReportsClient";

export default function ProjectReportsPage() {
  return (
    <ProjectPageFrame
      title="Monthly"
      accent="Reports"
      description="Review stored website and brand progress snapshots, generate a fresh report on demand, or trigger stakeholder delivery from the same workflow."
      descriptionClassName="max-w-2xl text-sm font-medium leading-relaxed text-(--t-2)"
    >
      <ProjectProgressReportsClient />
    </ProjectPageFrame>
  );
}
