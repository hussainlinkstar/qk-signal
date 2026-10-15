"use client";

import { useEffect } from "react";
import { AlertTriangle, RefreshCw, Home } from "lucide-react";
import Link from "next/link";
import Button from "@/components/ui/Button";

export default function AdminErrorBoundary({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    console.error("[Admin Error Boundary]", error);
  }, [error]);

  return (
    <div className="flex min-h-[50vh] flex-col items-center justify-center p-8 text-center">
      <div className="max-w-md rounded-[22px] border-0 bg-white p-8">
        <div className="mx-auto mb-5 flex h-12 w-12 items-center justify-center rounded-(--r-md) bg-(--bad-s)">
          <AlertTriangle className="text-(--bad)" size={24} />
        </div>

        <h2 className="m-0 mb-2 font-(family-name:--disp) text-[17px] font-bold tracking-[-0.01em] text-(--t-1)">
          System error
        </h2>

        <p className="mb-2 text-sm leading-relaxed text-(--t-2)">
          An unexpected error occurred in the admin panel. This has been logged for investigation.
        </p>

        {error?.message && (
          <p className="mb-6 break-all rounded-(--r-md) border-0 bg-[#EEF1F6] px-3 py-2 font-(family-name:--mono) text-[11px] text-(--bad)">
            {error.message}
          </p>
        )}

        <div className="flex items-center justify-center gap-3">
          <Button variant="primary" size="sm" onClick={reset}>
            <RefreshCw size={14} />
            Try again
          </Button>

          <Link href="/admin/overview">
            <Button variant="ghost" size="sm">
              <Home size={14} />
              Dashboard
            </Button>
          </Link>
        </div>
      </div>
    </div>
  );
}
