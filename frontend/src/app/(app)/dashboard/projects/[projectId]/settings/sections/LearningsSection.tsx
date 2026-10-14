"use client";

import React from "react";

import LearningsView from "@/components/results/LearningsView";

/** Section 9. The shared component owns its own heading and controls. */
export default function LearningsSection({ projectId }: { projectId: string }) {
  return (
    <div id="learnings">
      <LearningsView projectId={projectId} />
    </div>
  );
}
