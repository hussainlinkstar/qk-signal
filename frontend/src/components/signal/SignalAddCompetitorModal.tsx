"use client";

import { useState } from "react";
import Modal from "@/components/ui/Modal";
import {
  createProjectCompetitor,
  type ProjectCompetitorListItem,
} from "@/services/workspaceService";

export type SignalAddCompetitorModalProps = {
  open: boolean;
  onClose: () => void;
  projectId: string;
  getAuthHeaders: () => Promise<HeadersInit>;
  onCreated?: (competitor: ProjectCompetitorListItem) => void;
};

/**
 * Matches signal-MVP's `.modal-backdrop`/`.modal`/`.modal-grid` pattern (see
 * app.js's ADD_PROJECT_MODAL in signal-MVP for the reference markup). Calls the real
 * competitor benchmark CRUD (`createProjectCompetitor`) backing the Competitive
 * Intelligence leaderboard - no synthetic ids, no fabricated rows.
 */
export default function SignalAddCompetitorModal({
  open,
  onClose,
  projectId,
  getAuthHeaders,
  onCreated,
}: SignalAddCompetitorModalProps) {
  const [targetUrl, setTargetUrl] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const reset = () => {
    setTargetUrl("");
    setDisplayName("");
    setError(null);
  };

  const handleClose = () => {
    if (submitting) return;
    reset();
    onClose();
  };

  const handleSubmit = async () => {
    if (!targetUrl.trim()) {
      setError("Enter a competitor domain before adding it to this benchmark set.");
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      const headers = await getAuthHeaders();
      const competitor = await createProjectCompetitor(
        projectId,
        {
          target_url: targetUrl.trim(),
          display_name: displayName.trim() || null,
        },
        headers
      );
      onCreated?.(competitor);
      reset();
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to add competitor.");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Modal
      open={open}
      onClose={handleClose}
      panelClassName="p-0! bg-transparent! border-0! shadow-none!"
    >
      <div
        data-signal-theme
        className="w-[560px] max-w-full rounded-[20px] border-0 bg-white p-[28px_30px_26px] shadow-[0_40px_90px_-30px_rgba(12,15,22,0.5)]"
      >
        <p className="font-(family-name:--mono) text-[11px] uppercase tracking-[0.14em] text-(--t-3)">
          Competitive intelligence
        </p>
        <h2 className="mt-2 font-(family-name:--disp) text-[23px] font-extrabold tracking-[-0.02em] text-(--t-1)">
          Add competitor
        </h2>
        <p className="mb-[22px] mt-1.5 text-[13.5px] leading-normal text-(--t-2)">
          Track a rival domain to benchmark AIO &amp; SEO scores and surface head-to-head gaps.
        </p>

        <div className="grid grid-cols-1 gap-4">
          <label className="block">
            <span className="mb-2 block font-(family-name:--mono) text-[10.5px] uppercase tracking-[0.08em] text-(--t-3)">
              Competitor domain
            </span>
            <input
              value={targetUrl}
              onChange={(e) => setTargetUrl(e.target.value)}
              placeholder="https://competitor.com"
              className="h-11 w-full rounded-[14px] border-0 bg-[#EEF1F6] px-3 text-[13.5px] text-(--t-1) outline-hidden focus:bg-white"
            />
          </label>
          <label className="block">
            <span className="mb-2 block font-(family-name:--mono) text-[10.5px] uppercase tracking-[0.08em] text-(--t-3)">
              Label (optional)
            </span>
            <input
              value={displayName}
              onChange={(e) => setDisplayName(e.target.value)}
              placeholder="Example competitor"
              className="h-11 w-full rounded-[14px] border-0 bg-[#EEF1F6] px-3 text-[13.5px] text-(--t-1) outline-hidden focus:bg-white"
            />
          </label>
        </div>

        {error && <p className="mt-3 text-[12.5px] text-(--bad)">{error}</p>}

        <div className="mt-6 flex justify-end gap-2.5">
          <button
            type="button"
            onClick={handleClose}
            disabled={submitting}
            className="h-[38px] rounded-full border-0 bg-[#EEF1F6] px-[15px] text-[13.5px] font-semibold text-(--t-1) hover:bg-[#E8ECF3] disabled:opacity-50"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={handleSubmit}
            disabled={submitting}
            className="h-[38px] rounded-[10px] bg-(--ink) px-[15px] text-[13.5px] font-semibold text-white hover:bg-black disabled:opacity-50"
          >
            {submitting ? "Adding..." : "Add competitor"}
          </button>
        </div>
      </div>
    </Modal>
  );
}
