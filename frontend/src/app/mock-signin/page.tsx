"use client";

import { useEffect, useState } from "react";

/**
 * Mock-preview only: sets httpOnly auth cookies via /api/mock-signin, then
 * seeds workspace localStorage and sends you into the dashboard. Disabled
 * unless MOCK_PREVIEW=1 on the Next server.
 */
export default function MockSignInPage() {
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    (async () => {
      try {
        const response = await fetch("/api/mock-signin", { method: "POST" });
        if (!response.ok) {
          const body = (await response.json().catch(() => null)) as { detail?: string } | null;
          throw new Error(body?.detail ?? `Mock sign-in failed (${response.status})`);
        }
        window.localStorage.setItem("active_workspace_id", "1");
        if (!cancelled) {
          window.location.href = "/dashboard/overview";
        }
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : "Mock sign-in failed");
        }
      }
    })();

    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <main className="flex min-h-screen items-center justify-center p-8">
      <div className="max-w-md text-center">
        <h1 className="text-xl font-semibold">Mock preview sign-in</h1>
        <p className="mt-2 text-sm opacity-80">
          {error
            ? error
            : "Signing you in with stub auth… Start the app with MOCK_PREVIEW=1 if this fails."}
        </p>
      </div>
    </main>
  );
}
