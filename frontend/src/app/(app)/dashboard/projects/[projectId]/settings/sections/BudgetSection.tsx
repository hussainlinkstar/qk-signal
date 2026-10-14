"use client";

import React from "react";

import { ProjectBudgetGuardrailCard } from "@/components/settings/ProjectBudgetGuardrailCard";

/** Section 11. The shared card owns its own heading, figures and controls. */
export default function BudgetSection(
  props: React.ComponentProps<typeof ProjectBudgetGuardrailCard>
) {
  return (
    <div id="budget">
      <ProjectBudgetGuardrailCard {...props} />
    </div>
  );
}
