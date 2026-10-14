import React from "react";

import SoonSection from "@/components/results/SoonSection";
import SignalSectionHeader from "@/components/signal/SignalSectionHeader";

// SIGV2-1196 / SIGV2-1255: the approved sidebar IA does not include a Leads
// entry, and the standalone /dashboard/leads page is not part of the MVP.
// The route stays reachable for bookmark/typed-URL compatibility, but it
// renders the same SOON treatment the nav uses for unbuilt modules instead
// of surfacing the real (and otherwise hidden) leads widget. The backend
// API, workspace embed key models and lead-capture flow are intentionally
// left working; flipping this flag restores the page.
const SHOW_LEADS = false;

export default async function LeadsPage() {
  if (SHOW_LEADS) {
    // Restore the full LeadsPage client component here when the feature is
    // approved for the sidebar and for customer navigation.
    return null;
  }

  return (
    <section className="space-y-8 pb-12">
      <SignalSectionHeader title="Leads" />
      <SoonSection
        title="Leads"
        note="Leads is not built yet. It will show up here once it is ready."
      />
    </section>
  );
}
