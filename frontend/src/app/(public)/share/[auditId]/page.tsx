"use client";

import React, { useCallback, useEffect, useState } from "react";
import { useParams, useSearchParams } from "next/navigation";
import { Loader2 } from "lucide-react";
import AuditWorkspace from "@/components/results/AuditWorkspace";
import { type CanonicalAuditReport } from "@/lib/reportAdapters";
import { normalizeReport } from "@/lib/auditWorkspaceUtils";
import type { AuditRecordResponse } from "@/types/auditWorkspace";

/**
 * Public share page, renders an audit in read-only mode.
 * Route: /share/[auditId]?token=<share_token>
 */
export default function SharedAuditPage() {
  const params = useParams();
  const searchParams = useSearchParams();
  const auditId = params?.auditId as string | undefined;
  const token = searchParams?.get("token");

  const [report, setReport] = useState<CanonicalAuditReport | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!auditId || isNaN(Number(auditId)) || !token) {
      setError("Invalid audit link.");
      setLoading(false);
      return;
    }

    let cancelled = false;

    (async () => {
      try {
        const res = await fetch(`/api/audits/${auditId}/shared?token=${encodeURIComponent(token)}`);
        if (!res.ok) {
          throw new Error(
            res.status === 404
              ? "This audit was not found or has expired."
              : res.status === 403
                ? "This share link is invalid or has expired."
                : "Unable to load the shared report."
          );
        }
        const data: AuditRecordResponse = await res.json();
        if (cancelled) return;

        const normalized = normalizeReport(data, data.url || "");
        setReport(normalized);
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : "Unable to load the shared report.");
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [auditId, token]);

  // Provide a no-op auth headers function (public route)
  const getAuthHeaders = useCallback(async () => ({}), []);

  if (loading) {
    return (
      <main className="flex min-h-screen items-center justify-center bg-(--background) text-white">
        <div className="flex items-center gap-3 text-slate-400">
          <Loader2 className="h-5 w-5 animate-spin" />
          <span className="text-sm font-medium">Loading shared report...</span>
        </div>
      </main>
    );
  }

  if (error || !report) {
    return (
      <main className="flex min-h-screen items-center justify-center bg-(--background) text-white">
        <div className="text-center space-y-3">
          <h1 className="text-2xl font-bold">Shared Report Unavailable</h1>
          <p className="text-slate-400">
            {error || "This shared audit link is not valid or has expired."}
          </p>
        </div>
      </main>
    );
  }

  return (
    <main id="main-content" className="min-h-screen bg-(--background) px-4 py-12 md:px-8">
      <div className="mx-auto max-w-7xl">
        <AuditWorkspace
          title="Shared Website or Brand Entity Assessment Report"
          description="This is a read-only shared report with target-aware website/brand context."
          isSignedIn={false}
          getAuthHeaders={getAuthHeaders}
          initialReport={report}
          readOnly
          framed
        />
      </div>
    </main>
  );
}
