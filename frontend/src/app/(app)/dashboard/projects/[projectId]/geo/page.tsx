import { redirect } from "next/navigation";

// GEO is folded into the single AIO pillar (AEO + GEO) — see /aeo.
export default async function ProjectGeoRedirect({
  params,
}: {
  params: Promise<{ projectId: string }>;
}) {
  const { projectId } = await params;
  redirect(`/dashboard/projects/${projectId}/ai-answers`);
}
