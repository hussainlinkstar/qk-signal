import React from "react";

import SoonSection from "@/components/results/SoonSection";
import SignalSectionHeader from "@/components/signal/SignalSectionHeader";

type Props = { params: Promise<{ projectId: string }> };

// SIGV2-1196 / SIGV2-1255: the approved sidebar IA does not include an Entity
// Authority entry, and the standalone project page is not part of the MVP.
// The route stays reachable for bookmark/typed-URL compatibility, but it
// renders the same SOON treatment the nav uses for unbuilt modules instead
// of surfacing the real (and otherwise hidden) entity authority analysis.
// The backend API, entity scoring, gap detection and knowledge graph are
// intentionally left working; flipping this flag restores the page.
const SHOW_PROJECT_ENTITY_AUTHORITY = false;

export default async function ProjectEntityAuthorityPage({ params }: Props) {
  const { projectId: _projectId } = await params;

  if (SHOW_PROJECT_ENTITY_AUTHORITY) {
    // Restore the full ProjectEntityAuthorityPage client component here when
    // the feature is approved for the sidebar and for customer navigation.
    return null;
  }

  return (
    <section className="space-y-8 pb-12">
      <SignalSectionHeader title="Entity Authority" />
      <SoonSection
        title="Entity Authority"
        note="Entity Authority is not built yet. It will show up here once it is ready."
      />
    </section>
  );
}
