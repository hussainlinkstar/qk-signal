import React from "react";
import ProjectRouteBridge from "@/components/dashboard/ProjectRouteBridge";

export default function DashboardCompetitorsPage() {
  return (
    <ProjectRouteBridge
      moduleLabel="Competitor Intelligence"
      description="Open the project-level competitive dashboard to benchmark the client against tracked competitors and inspect AI-backed gap analysis."
      targetPath="/competitors"
      ctaLabel="Open Competitive Dashboard"
    />
  );
}
