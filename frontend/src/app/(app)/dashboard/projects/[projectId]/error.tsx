"use client";

import { useEffect } from "react";
import { RefreshCw, Home } from "lucide-react";
import Link from "next/link";
import SignalAlert, { SIGNAL_ALERT_ACTION } from "@/components/signal/SignalAlert";

export default function ProjectErrorBoundary({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    console.error("[Project Error Boundary]", error);
  }, [error]);

  return (
    <div className="flex min-h-[50vh] items-center justify-center p-8">
      <SignalAlert
        tone="danger"
        title="Something went wrong"
        className="w-full max-w-2xl"
        actions={
          <>
            <button type="button" onClick={reset} className={SIGNAL_ALERT_ACTION}>
              <RefreshCw size={14} />
              Try Again
            </button>
            <Link href="/dashboard" className={SIGNAL_ALERT_ACTION}>
              <Home size={14} />
              Dashboard Home
            </Link>
          </>
        }
      >
        <p>An unexpected error occurred. This has been logged for investigation.</p>
        {error?.message && <p className="mt-2 break-words">{error.message}</p>}
      </SignalAlert>
    </div>
  );
}
