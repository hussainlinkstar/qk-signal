import React from "react";

import ProjectAutomationsClient from "./ProjectAutomationsClient";
import SoonSection from "@/components/results/SoonSection";
import SignalSectionHeader from "@/components/signal/SignalSectionHeader";

type Props = { params: Promise<{ projectId: string }> };

// SIGV2-1196 / SIGV2-1255: the approved product decision keeps Automations at
// "Coming Soon" availability. The route is not listed in the sidebar IA, and
// the real workflow engine is intentionally left intact behind this flag.
// Flipping the flag restores the customer-facing Automations page; until then
// typed/bookmark URLs render the same SOON treatment the nav uses for unbuilt
// modules.
const SHOW_PROJECT_AUTOMATIONS = false;

export default async function ProjectAutomationsPage({ params }: Props) {
  const { projectId: _projectId } = await params;

  if (SHOW_PROJECT_AUTOMATIONS) {
    return <ProjectAutomationsClient />;
  }

  return (
    <section className="space-y-8 pb-12">
      <SignalSectionHeader title="Automations" />
      <SoonSection
        title="Automations"
        note="Automations is not built yet. It will show up here once it is ready."
      />
    </section>
  );
}
