import React from "react";

import ProjectTaskBoardClient from "@/components/dashboard/ProjectTaskBoardClient";
import SoonSection from "@/components/results/SoonSection";
import SignalSectionHeader from "@/components/signal/SignalSectionHeader";

type Props = { params: Promise<{ projectId: string }> };

// SIGV2-1196: the approved sidebar IA carries Tasks as a non-navigating entry
// with a SOON badge (navigationConfig, "Tasks" under Automation), so the route
// behind that entry says the same thing instead of serving the board to anyone
// who types the URL. Same convention as the two Entities routes and as
// ConnectionsPanels' SHOW_* flags: flipping this flag restores the board.
//
// This hides the board UI only, and that is the whole of the change. Project
// tasks are not going away: the audit pipeline keeps minting them on every
// completed audit, the PDF reports keep their task sections, and the external
// API keeps serving its two task endpoints. ProjectTaskBoardClient, the
// workspace task services and the backend task models are all intentionally
// left working and untouched.
const SHOW_PROJECT_TASK_BOARD = false;

export default async function ProjectTasksPage({ params }: Props) {
  const { projectId } = await params;

  return SHOW_PROJECT_TASK_BOARD ? (
    <ProjectTaskBoardClient projectId={projectId} />
  ) : (
    <section className="space-y-8 pb-12">
      <SignalSectionHeader title="Tasks" />
      <SoonSection
        title="Tasks"
        note="Tasks is not built yet. It will show up here once it is ready."
      />
    </section>
  );
}
