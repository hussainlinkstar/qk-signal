"use client";

import SignalAlert from "@/components/signal/SignalAlert";
import { ChevronLeft, ChevronRight, Clock, LoaderCircle, RefreshCw } from "lucide-react";
import type { PortalAuditHistoryItem } from "@/services/portalService";
import { cx } from "@/components/ui/utils";

type PortalAuditHistoryProps = {
  projectId: string;
  items: PortalAuditHistoryItem[];
  total: number;
  page: number;
  pageSize: number;
  loading?: boolean;
  error?: string | null;
  onRetry?: () => void;
  onPageChange: (page: number) => void;
  onSelectAudit: (auditId: number) => void;
};

const formatDate = (value: string | null): string => {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "-";
  return date.toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
};

const formatScore = (value: number | null): string =>
  typeof value === "number" ? Math.round(value).toString() : "-";

const statusConfig: Record<string, { label: string; bg: string; text: string }> = {
  completed: { label: "Completed", bg: "bg-emerald-500/15", text: "text-emerald-400" },
  degraded: { label: "Degraded", bg: "bg-yellow-500/15", text: "text-yellow-400" },
  failed: { label: "Failed", bg: "bg-red-500/15", text: "text-red-400" },
};

const getStatusBadge = (status: string) => {
  const config = statusConfig[status.toLowerCase()] ?? {
    label: status,
    bg: "bg-white/10",
    text: "text-(--muted-foreground)",
  };

  return (
    <span
      className={cx(
        "inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-semibold",
        config.bg,
        config.text
      )}
    >
      {config.label}
    </span>
  );
};

export default function PortalAuditHistory({
  projectId: _projectId,
  items,
  total,
  page,
  pageSize,
  loading = false,
  error = null,
  onRetry,
  onPageChange,
  onSelectAudit,
}: PortalAuditHistoryProps) {
  const totalPages = Math.max(1, Math.ceil(total / pageSize));
  const hasPrev = page > 1;
  const hasNext = page < totalPages;

  if (loading) {
    return (
      <div
        role="status"
        className="rounded-xl border border-(--border) bg-(--surface) p-8 text-center text-sm text-(--muted-foreground)"
      >
        <LoaderCircle className="mx-auto mb-3 h-8 w-8 animate-spin opacity-60" />
        <p>Loading audit history...</p>
      </div>
    );
  }

  if (error) {
    return (
      <SignalAlert
        tone="danger"
        title="Audit history unavailable"
        actions={
          onRetry ? (
            <button
              type="button"
              onClick={onRetry}
              className="inline-flex items-center gap-2 rounded-(--r-md) border border-(--line) px-3 py-2"
            >
              <RefreshCw className="h-3.5 w-3.5" />
              Retry
            </button>
          ) : undefined
        }
      >
        {error}
      </SignalAlert>
    );
  }

  if (items.length === 0) {
    return (
      <div className="rounded-xl border border-(--border) bg-(--surface) p-8 text-center text-sm text-(--muted-foreground)">
        <Clock className="mx-auto mb-3 h-8 w-8 opacity-40" />
        <p>No audit history yet.</p>
      </div>
    );
  }

  return (
    <div className="overflow-hidden rounded-xl border border-(--border) bg-(--surface)">
      {/* Header */}
      <div className="grid grid-cols-[1fr_60px_60px_60px_100px] gap-2 border-b border-(--border) px-4 py-2.5 text-[11px] font-bold uppercase tracking-wider text-(--muted-foreground)">
        <span>Date</span>
        <span className="text-right">SEO</span>
        <span className="text-right">AI visibility</span>
        <span className="text-right">AI answers</span>
        <span className="text-right">Status</span>
      </div>

      {/* Rows */}
      <ul className="divide-y divide-(--border)">
        {items.map((item) => (
          <li key={item.id}>
            <button
              type="button"
              onClick={() => onSelectAudit(item.id)}
              className="grid w-full grid-cols-[1fr_60px_60px_60px_100px] items-center gap-2 px-4 py-3 text-left text-sm transition "
            >
              <span className="flex items-center gap-2 truncate text-(--foreground)">
                <Clock className="h-3.5 w-3.5 shrink-0 text-(--muted-foreground)" />
                {formatDate(item.created_at)}
              </span>
              <span className="text-right font-mono text-(--foreground)">
                {formatScore(item.seo_score)}
              </span>
              <span className="text-right font-mono text-(--foreground)">
                {formatScore(item.geo_score)}
              </span>
              <span className="text-right font-mono text-(--foreground)">
                {formatScore(item.aeo_score)}
              </span>
              <span className="flex justify-end">{getStatusBadge(item.status)}</span>
            </button>
          </li>
        ))}
      </ul>

      {/* Pagination */}
      {totalPages > 1 && (
        <div className="flex items-center justify-between border-t border-(--border) px-4 py-2.5">
          <button
            type="button"
            disabled={!hasPrev}
            onClick={() => onPageChange(page - 1)}
            className={cx(
              "inline-flex items-center gap-1 rounded-lg px-3 py-1.5 text-xs font-semibold transition",
              hasPrev
                ? "text-(--foreground) "
                : "cursor-not-allowed text-(--muted-foreground) opacity-40"
            )}
          >
            <ChevronLeft className="h-3.5 w-3.5" />
            Prev
          </button>

          <span className="text-xs text-(--muted-foreground)">
            Page {page} of {totalPages}
          </span>

          <button
            type="button"
            disabled={!hasNext}
            onClick={() => onPageChange(page + 1)}
            className={cx(
              "inline-flex items-center gap-1 rounded-lg px-3 py-1.5 text-xs font-semibold transition",
              hasNext
                ? "text-(--foreground) "
                : "cursor-not-allowed text-(--muted-foreground) opacity-40"
            )}
          >
            Next
            <ChevronRight className="h-3.5 w-3.5" />
          </button>
        </div>
      )}
    </div>
  );
}
