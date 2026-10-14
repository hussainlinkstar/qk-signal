import React from "react";

import SoonSection from "@/components/results/SoonSection";
import SignalSectionHeader from "@/components/signal/SignalSectionHeader";

import ProjectEntitiesClient from "./ProjectEntitiesClient";

type Props = { params: Promise<{ projectId: string }> };

// SIGV2-1196: same decision as the workspace-level /dashboard/entities route.
// The sidebar presents Entities with a SOON badge and no link, so this page
// carries the SOON treatment instead of the built feature; otherwise a typed
// URL serves a module the product says is still coming, complete with its
// plan lock and upgrade prompt. ProjectEntitiesClient and the audit entity
// data behind it stay fully working and are intentionally kept; flipping this
// flag restores the module. The page only reads the latest audit and owns no
// customer-created state of its own, so hiding it strands nothing.
const SHOW_PROJECT_ENTITIES = false;

export default async function ProjectEntitiesPage({ params }: Props) {
  const { projectId } = await params;

  return SHOW_PROJECT_ENTITIES ? (
    <ProjectEntitiesClient projectId={projectId} />
  ) : (
    <section className="space-y-8 pb-12">
      <SignalSectionHeader title="Entities" />
      <SoonSection
        title="Entities"
        note="Entities is not built yet. It will show up here once it is ready."
      />
    </section>
  );
}
