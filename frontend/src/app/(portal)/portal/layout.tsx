import { redirect } from "next/navigation";
import PortalShell from "@/components/portal/PortalShell";
import type { PortalBranding, PortalProjectSummary } from "@/services/portalService";
import { serverFetch } from "@/utils/server-fetch";

const fallbackBranding: PortalBranding = {
  workspace_id: 0,
  workspace_name: "Client Portal",
  agency_name: "Client Portal",
  custom_logo_url: null,
  primary_color: null,
  secondary_color: null,
  custom_favicon_url: null,
  custom_page_title: null,
  hide_powered_by: false,
};

export default async function PortalLayout({ children }: { children: React.ReactNode }) {
  const sessionResponse = await serverFetch("/auth/me", {
    cache: "no-store",
    redirectOnUnauthorized: false,
  });

  if (!sessionResponse.ok) {
    redirect("/login?session_expired=true&reason=auth_failed");
  }

  const session = (await sessionResponse.json()) as {
    portal_only?: boolean;
  };

  if (!session.portal_only) {
    redirect("/dashboard");
  }

  const [brandingResponse, projectsResponse] = await Promise.all([
    serverFetch("/portal/branding", { cache: "no-store", redirectOnUnauthorized: false }),
    serverFetch("/portal/projects", { cache: "no-store", redirectOnUnauthorized: false }),
  ]);

  const branding = brandingResponse.ok
    ? ((await brandingResponse.json()) as PortalBranding)
    : fallbackBranding;
  const projects = projectsResponse.ok
    ? ((await projectsResponse.json()) as PortalProjectSummary[])
    : [];

  return (
    <PortalShell branding={branding} projects={projects}>
      {children}
    </PortalShell>
  );
}
