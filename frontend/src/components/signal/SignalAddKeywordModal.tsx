"use client";

import React, { useState } from "react";
import Link from "next/link";
import { useTranslation } from "react-i18next";

import Modal from "@/components/ui/Modal";
import { createTargetKeyword } from "@/services/monitoringService";

export type SignalAddKeywordModalProps = {
  open: boolean;
  onClose: () => void;
  projectId: string;
  getAuthHeaders: () => Promise<HeadersInit>;
  onCreated: () => void | Promise<void>;
};

const fieldLabelCls =
  "mb-2 block font-(family-name:--mono) text-[10.5px] uppercase tracking-[0.08em] text-(--t-3)";
const inputCls =
  "h-11 w-full rounded-[10px] border border-(--line) bg-(--paper) px-3 text-[13.5px] text-(--t-1) outline-hidden focus:border-[#C7CDD6]";

/**
 * Add keyword, on the surface the approved design puts it: the Keywords tab of
 * the SEO detail page (`Signal SEO Detail.html`, "Tracked keywords"). Before
 * SIGV2-1145 the approved button navigated to a monitoring page the MVP does
 * not contain.
 *
 * Unlike prompts (SIGV2-1142) there is no plan allowance to state: tracked
 * keywords have no cap and no plan gate anywhere in the product, so this
 * dialog claims no allowance it cannot read. The refusals that do exist are
 * the API's own (a duplicate keyword, a project the caller cannot reach), and
 * each is shown here with the API's own sentence rather than swallowed.
 */
export default function SignalAddKeywordModal({
  open,
  onClose,
  projectId,
  getAuthHeaders,
  onCreated,
}: SignalAddKeywordModalProps) {
  const { t } = useTranslation();
  const [keyword, setKeyword] = useState("");
  const [submitting, setSubmitting] = useState(false);
  // `fromApi` separates a refusal the customer may need to act on elsewhere
  // (a keyword already tracked) from a field this dialog can fix on the spot.
  const [error, setError] = useState<{ message: string; fromApi: boolean } | null>(null);

  const reset = () => {
    setKeyword("");
    setError(null);
  };

  const handleClose = () => {
    if (submitting) return;
    reset();
    onClose();
  };

  const handleSubmit = async () => {
    if (!keyword.trim()) {
      setError({ message: t("signalAddKeyword.keywordRequired"), fromApi: false });
      return;
    }

    setSubmitting(true);
    setError(null);
    try {
      const headers = await getAuthHeaders();
      await createTargetKeyword(projectId, { keyword: keyword.trim() }, headers);
      await onCreated();
      reset();
      onClose();
    } catch (err) {
      // The API states why it refused, so its own sentence is shown here
      // instead of a generic failure or a toast that fades.
      setError({
        message: err instanceof Error && err.message ? err.message : t("signalAddKeyword.failed"),
        fromApi: true,
      });
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Modal
      open={open}
      onClose={handleClose}
      ariaLabelledby="signal-add-keyword-title"
      panelClassName="p-0! bg-transparent! border-0! shadow-none!"
    >
      <div
        data-signal-theme
        className="w-[560px] max-w-full rounded-[20px] border border-(--line) bg-(--panel) p-[28px_30px_26px] shadow-[0_40px_90px_-30px_rgba(12,15,22,0.5)]"
      >
        <p className="font-(family-name:--mono) text-[11px] uppercase tracking-[0.14em] text-(--t-3)">
          {t("signalAddKeyword.eyebrow")}
        </p>
        <h2
          id="signal-add-keyword-title"
          className="mt-2 font-(family-name:--disp) text-[23px] font-extrabold tracking-[-0.02em] text-(--t-1)"
        >
          {t("signalAddKeyword.title")}
        </h2>
        <p className="mb-[18px] mt-1.5 text-[13.5px] leading-normal text-(--t-2)">
          {t("signalAddKeyword.description")}
        </p>

        <label className="block">
          <span className={fieldLabelCls}>{t("signalAddKeyword.keywordLabel")}</span>
          <input
            value={keyword}
            onChange={(event) => setKeyword(event.target.value)}
            placeholder={t("signalAddKeyword.keywordPlaceholder")}
            maxLength={500}
            disabled={submitting}
            className={inputCls}
          />
        </label>

        <p className="mt-4 text-[11.5px] leading-[1.5] text-(--t-3)">
          {t("signalAddKeyword.unmeasuredNote")}
        </p>

        {error ? (
          <div
            role="alert"
            className="mt-3 rounded-[12px] border border-(--line) bg-(--paper) px-4 py-3 text-[12.5px] leading-[1.55] text-(--t-2)"
          >
            <p className="m-0 font-semibold text-(--t-1)">{error.message}</p>
            {error.fromApi ? (
              <Link
                href={`/dashboard/projects/${projectId}/monitoring#tracked-keywords`}
                className="mt-3 inline-flex h-8 items-center rounded-[10px] border border-(--line) bg-(--panel) px-[13px] text-[12.5px] font-semibold text-(--t-1) hover:border-[#D7DAE0]"
              >
                {t("signalAddKeyword.manageKeywords")}
              </Link>
            ) : null}
          </div>
        ) : null}

        <div className="mt-6 flex justify-end gap-2.5">
          <button
            type="button"
            onClick={handleClose}
            disabled={submitting}
            className="h-[38px] rounded-[10px] border border-(--line) bg-(--panel) px-[15px] text-[13.5px] font-semibold text-(--t-1) hover:border-[#D7DAE0] disabled:opacity-50"
          >
            {t("signalAddKeyword.cancel")}
          </button>
          <button
            type="button"
            onClick={() => void handleSubmit()}
            disabled={submitting}
            className="h-[38px] rounded-[10px] bg-(--ink) px-[15px] text-[13.5px] font-semibold text-white hover:bg-black disabled:cursor-not-allowed disabled:opacity-50"
          >
            {submitting ? t("signalAddKeyword.submitting") : t("signalAddKeyword.submit")}
          </button>
        </div>
      </div>
    </Modal>
  );
}
