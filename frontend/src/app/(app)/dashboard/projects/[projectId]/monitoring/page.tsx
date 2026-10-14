import React from "react";

import ProjectMonitoringClient from "./ProjectMonitoringClient";

type Props = { params: Promise<{ projectId: string }> };

export default async function ProjectMonitoringPage({ params }: Props) {
  const { projectId } = await params;

  return <ProjectMonitoringClient projectId={projectId} />;
}
