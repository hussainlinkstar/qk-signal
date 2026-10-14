import { notFound } from "next/navigation";

import AdminShell from "@/app/(app)/admin/AdminShell";
import { serverFetch } from "@/utils/server-fetch";

const STAFF_ROLES = new Set(["admin", "moderator"]);

/**
 * Staff check on the server, before any admin code reaches the browser.
 *
 * AdminGuardProvider already refuses to render for non-staff, and the API
 * returns 403 regardless, so data was never exposed. What was exposed is the
 * admin bundle itself: a customer who opened /admin downloaded it, including
 * the navigation for every internal tool. Deciding here means they get a 404
 * and nothing is shipped.
 *
 * The client guard stays. This is defence in depth, not a replacement, and it
 * keeps working if this check ever fails open.
 */
export default async function AdminLayout({ children }: { children: React.ReactNode }) {
  const response = await serverFetch("/users/me", {
    cache: "no-store",
    redirectOnUnauthorized: false,
  });

  if (!response.ok) {
    notFound();
  }

  const user = (await response.json()) as { role?: string };
  if (!STAFF_ROLES.has(user.role ?? "")) {
    notFound();
  }

  return <AdminShell>{children}</AdminShell>;
}
