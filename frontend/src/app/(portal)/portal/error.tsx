"use client";

import { useEffect } from "react";
import { RefreshCw, Home } from "lucide-react";
import Link from "next/link";
import SignalAlert, { SIGNAL_ALERT_ACTION } from "@/components/signal/SignalAlert";

export default function PortalErrorBoundary({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    console.error("[Portal Error Boundary]", error);
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
            <Link href="/portal" className={SIGNAL_ALERT_ACTION}>
              <Home size={14} />
              Portal Home
            </Link>
          </>
        }
      >
        <p>An unexpected error occurred. Please try again or contact your account manager.</p>
        {error?.message && <p className="mt-2 break-words">{error.message}</p>}
      </SignalAlert>
    </div>
  );
}
