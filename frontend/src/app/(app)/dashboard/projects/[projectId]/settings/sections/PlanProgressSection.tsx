"use client";

import React from "react";

import PlanProgressView from "@/components/results/PlanProgressView";

/** Section 10. The shared component owns its own heading and controls. */
export default function PlanProgressSection({ projectId }: { projectId: string }) {
  return (
    <div id="plan-progress">
      <PlanProgressView projectId={projectId} />
    </div>
  );
}
