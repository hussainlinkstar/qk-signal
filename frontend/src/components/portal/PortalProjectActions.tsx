"use client";

import { useState, useCallback } from "react";
import { Download, History } from "lucide-react";
import { toast } from "sonner";
import { asset } from "@/lib/basePath";
import Button from "@/components/ui/Button";
import PortalAuditHistory from "@/components/portal/PortalAuditHistory";
import { PortalApprovalButtons } from "@/components/portal/PortalApprovalButtons";
import {
  type PortalAuditHistoryItem,
  type PortalApprovalInfo,
  fetchPortalAuditHistory,
  downloadPortalPdf,
} from "@/services/portalService";

interface PortalProjectActionsProps {
  projectId: string;
  auditId: number | null;
}

export default function PortalProjectActions({ projectId, auditId }: PortalProjectActionsProps) {
  const [pdfLoading, setPdfLoading] = useState(false);
  const [showHistory, setShowHistory] = useState(false);
  const [historyItems, setHistoryItems] = useState<PortalAuditHistoryItem[]>([]);
  const [historyTotal, setHistoryTotal] = useState(0);
  const [historyPage, setHistoryPage] = useState(1);
  const [historyRetryPage, setHistoryRetryPage] = useState(1);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [historyError, setHistoryError] = useState<string | null>(null);

  const loadHistory = useCallback(
    async (page: number) => {
      setHistoryLoading(true);
      setHistoryError(null);
      setHistoryRetryPage(page);
      try {
        const data = await fetchPortalAuditHistory(projectId, page, 10);
        setHistoryItems(data.items);
        setHistoryTotal(data.total);
        setHistoryPage(data.page);
      } catch {
        setHistoryError("Failed to load audit history.");
        toast.error("Failed to load audit history");
      } finally {
        setHistoryLoading(false);
      }
    },
    [projectId]
  );

  const handleToggleHistory = useCallback(async () => {
    if (showHistory) {
      setShowHistory(false);
      return;
    }
    setShowHistory(true);
    await loadHistory(1);
  }, [showHistory, loadHistory]);

  const handleDownloadPdf = useCallback(async () => {
    if (!auditId) return;
    setPdfLoading(true);
    try {
      await downloadPortalPdf(projectId, auditId);
      toast.success("PDF downloaded");
    } catch (err) {
      const message = err instanceof Error ? err.message : "PDF download failed";
      toast.error(message);
    } finally {
      setPdfLoading(false);
    }
  }, [projectId, auditId]);

  const handleSelectAudit = useCallback(
    (selectedAuditId: number) => {
      window.location.href = asset(`/portal/projects/${projectId}?audit_id=${selectedAuditId}`);
    },
    [projectId]
  );

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2">
        <Button variant="outline" size="sm" onClick={handleToggleHistory} className="text-xs">
          <History className="mr-1.5 h-3.5 w-3.5" />
          {showHistory ? "Hide history" : "Audit history"}
        </Button>

        {auditId && (
          <Button
            variant="outline"
            size="sm"
            onClick={handleDownloadPdf}
            loading={pdfLoading}
            loadingText="Generating…"
            className="text-xs"
          >
            <Download className="mr-1.5 h-3.5 w-3.5" />
            Download PDF
          </Button>
        )}
      </div>

      {showHistory && (
        <PortalAuditHistory
          projectId={projectId}
          items={historyItems}
          total={historyTotal}
          page={historyPage}
          pageSize={10}
          loading={historyLoading}
          error={historyError}
          onRetry={() => loadHistory(historyRetryPage)}
          onPageChange={loadHistory}
          onSelectAudit={handleSelectAudit}
        />
      )}
    </div>
  );
}

export { PortalApprovalButtons };
export type { PortalApprovalInfo };
