import React from "react";

import ProjectRouteBridge from "@/components/dashboard/ProjectRouteBridge";
import SoonSection from "@/components/results/SoonSection";
import SignalSectionHeader from "@/components/signal/SignalSectionHeader";

// SIGV2-1196: Entities is presented as unbuilt everywhere a customer can see
// it. The approved sidebar IA carries it as a non-navigating entry with a
// SOON badge (navigationConfig, "Entities"), so the route behind that entry
// has to say the same thing rather than serving the module to anyone who
// types the URL. The project picker below, the project entity pages and the
// backend entity services stay fully working and are intentionally kept;
// flipping this flag restores the module. This route owns no
// customer-created state of its own, it only chooses a project, so hiding it
// strands nothing.
const SHOW_ENTITIES_MODULE = false;

export default function DashboardEntitiesPage() {
  return SHOW_ENTITIES_MODULE ? (
    <ProjectRouteBridge
      moduleLabel="Entities & Semantic Footprint"
      description="Entity and semantic analysis is now project-scoped. Select a project to continue."
      targetPath="/entities"
      ctaLabel="Open Project Entities"
    />
  ) : (
    <div className="dashboard-page-shell">
      <SignalSectionHeader title="Entities" />
      <SoonSection
        title="Entities"
        note="Entities is not built yet. It will show up here once it is ready."
      />
    </div>
  );
}
