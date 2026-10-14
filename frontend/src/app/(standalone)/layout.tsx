import { redirect } from "next/navigation";
import Link from "next/link";
import { ChevronLeft } from "lucide-react";
import SignalBrandLockup from "@/components/signal/SignalBrandLockup";
import { serverFetch } from "@/utils/server-fetch";

export default async function StandaloneLayout({ children }: { children: React.ReactNode }) {
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
    <div className="flex min-h-screen flex-col bg-(--background)">
      <header className="glass-surface sticky top-0 z-topbar flex h-14 shrink-0 items-center gap-4 px-5 shadow-sm md:px-8">
        <Link
          href="/dashboard/developer"
          className="inline-flex items-center gap-[7px] text-[13px] font-semibold text-(--muted-foreground) transition-colors hover:text-(--foreground)"
        >
          <ChevronLeft aria-hidden="true" size={16} />
          Back to Developer Hub
        </Link>

        <div className="ml-auto">
          <Link href="/dashboard" aria-label="Qiko Signal dashboard">
            <SignalBrandLockup />
          </Link>
        </div>
      </header>

      <main className="flex-1">{children}</main>
    </div>
  );
}
