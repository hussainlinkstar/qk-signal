"use client";

import React from "react";

import GuardrailsSection from "@/components/results/GuardrailsSection";

/** Section 8. The shared component owns its own heading and controls. */
export default function BrandGuardrailsSection({ projectId }: { projectId: string }) {
  return (
    <div id="guardrails">
      <GuardrailsSection projectId={projectId} />
    </div>
  );
}
