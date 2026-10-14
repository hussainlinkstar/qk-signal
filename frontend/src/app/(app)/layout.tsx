import type { Metadata } from "next";
import { redirect } from "next/navigation";
import AppTopBar from "@/components/app/AppTopBar";
import { MaintenanceBanner } from "@/components/MaintenanceBanner";
import { RoleModeProvider } from "@/contexts/RoleModeContext";
import { serverFetch } from "@/utils/server-fetch";

export const metadata: Metadata = {
  title: {
    default: "Dashboard",
    template: "%s | Qiko Signal",
  },
  // Authenticated app surfaces are not search landing pages.
  robots: { index: false, follow: false },
};

export default async function AppLayout({ children }: { children: React.ReactNode }) {
  const sessionResponse = await serverFetch("/auth/me", {
    cache: "no-store",
    redirectOnUnauthorized: false,
  });

  if (!sessionResponse.ok) {
    redirect("/login?session_expired=true&reason=auth_failed");
  }

  const session = (await sessionResponse.json()) as { portal_only?: boolean };
  if (session.portal_only) {
    redirect("/portal");
  }

  return (
    <RoleModeProvider>
      <div className="app-shell min-h-screen bg-(--background) app-surface-gradient">
        <MaintenanceBanner />
        <AppTopBar />
        {children}
      </div>
    </RoleModeProvider>
  );
}
