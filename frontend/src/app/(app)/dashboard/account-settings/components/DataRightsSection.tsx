"use client";

import React from "react";
import { useTranslation } from "react-i18next";
import Modal from "@/components/ui/Modal";
import { useAccountSettings } from "../useAccountSettings";

type DataRightsSectionProps = {
  settings: ReturnType<typeof useAccountSettings>;
};

const CARD = "rounded-[22px] border-0 bg-white px-[22px] py-[18px]";
const CARD_TITLE =
  "m-0 mb-[3px] font-(family-name:--disp) text-[15px] font-bold tracking-[-0.01em]";
const CARD_DESC = "m-0 mb-[18px] text-[12.5px] leading-[1.5] text-(--t-3)";
const TH =
  "border-b border-b-(--line) px-4 py-[11px] text-start font-(family-name:--mono) text-[10px] font-normal uppercase tracking-[0.06em] text-(--t-3)";
const TD = "border-b border-b-(--line-2) px-4 py-[13px] align-middle text-[13px]";
const ROW =
  "flex items-center justify-between gap-4 border-t border-t-(--line-2) py-3.5 first:border-t-0 max-md:flex-wrap max-md:items-start";
const ROW_TITLE = "text-[13.5px] font-semibold";
const ROW_DESC = "mt-0.5 max-w-[560px] text-[12px] leading-[1.45] text-(--t-3)";
const BTN_GHOST =
  "inline-flex h-[38px] cursor-pointer items-center gap-2 rounded-full border-0 bg-[#EEF1F6] px-[15px] py-0 font-(family-name:--body-font) text-[13.5px] font-semibold text-(--t-1) hover:bg-[#E8ECF3] disabled:cursor-not-allowed disabled:opacity-55";
const BTN_DESTRUCTIVE =
  "inline-flex h-[38px] cursor-pointer items-center gap-2 rounded-full border-0 bg-[#FEECEC] px-[15px] py-0 font-(family-name:--body-font) text-[13.5px] font-semibold text-(--bad) hover:bg-[#E8ECF3] disabled:cursor-not-allowed disabled:opacity-55";

/**
 * The approved `.confirm` chip.
 *
 * Legal has not signed off the retention periods or the processing regions,
 * and the approved design is explicit that they must render as a visible
 * placeholder rather than as a fact: "Retention periods and the DPO contact in
 * the privacy section render as visible [CONFIRM] placeholders, on purpose, so
 * a guess is never mistaken for policy" (Qiko-Signal-MVP-TBR/README.md),
 * restated at the top of signal-mvp-privacy-copy.md. A plausible-looking
 * number here would be a policy claim nobody has made, which is worse than an
 * obvious gap.
 */
const Confirm: React.FC<{ label?: string }> = ({ label = "[CONFIRM]" }) => (
  <span className="rounded-[5px] border border-dashed border-(--warn) bg-(--warn-s) px-1.5 py-px font-(family-name:--mono) text-[11px] whitespace-nowrap text-(--warn)">
    {label}
  </span>
);

/**
 * Renders a translated string that carries a single `{{confirm}}` token as
 * text with the [CONFIRM] chip inlined, so the chip travels with the sentence
 * in both reading directions instead of being positioned in English order.
 */
const WithConfirm: React.FC<{ template: string }> = ({ template }) => {
  const [before, after = ""] = template.split("{{confirm}}");
  return (
    <>
      {before}
      <Confirm />
      {after}
    </>
  );
};

const BulletList: React.FC<{ heading: string; tone: "good" | "warn"; items: string[] }> = ({
  heading,
  tone,
  items,
}) => (
  <div className="rounded-[12px] border-0 bg-[#EEF1F6] px-4 py-3.5">
    <div
      className={`mb-2 font-(family-name:--mono) text-[10.5px] uppercase tracking-[0.09em] ${
        tone === "good" ? "text-(--good)" : "text-(--warn)"
      }`}
    >
      {heading}
    </div>
    <ul className="m-0 flex list-none flex-col gap-[7px] p-0">
      {items.map((item) => (
        <li
          key={item}
          className="relative text-[12.5px] leading-[1.45] text-(--t-1) ps-3.5 before:absolute before:start-0 before:top-[7px] before:h-[5px] before:w-[5px] before:rounded-full before:bg-(--t-3) before:content-['']"
        >
          {item}
        </li>
      ))}
    </ul>
  </div>
);

/**
 * My Profile, Data tab (SIGV2-1039).
 *
 * Scope is fixed by the MVP revision note: this models only what is actually
 * built, namely "Export your data" and "Delete your account", plus the
 * retention and sub-processor disclosures. The eight unbuilt request actions,
 * the privacy-regime selector and the consent record are deliberately out and
 * must not be reintroduced from signal-mvp-ui-inventory.md, which predates the
 * revision. Copy is verbatim from signal-mvp-privacy-copy.md.
 *
 * One approved line is deliberately absent. The design closes the retention
 * table with "Report retention on your plan is currently set to 30 days.
 * Change this in Workspace Settings", and neither half of that is true of the
 * product: `OperationalSetting.report_retention_days` is a single
 * instance-wide value a staff member edits under /admin/audit-retention, it is
 * not a per-plan or per-workspace setting, and Workspace Settings has no
 * control for it. Rendering it would point a paying customer at a control that
 * does not exist.
 */
const DataRightsSection: React.FC<DataRightsSectionProps> = ({ settings }) => {
  const { t } = useTranslation();
  const {
    isSignedIn,
    dataActionMessage,
    dataActionError,
    isExporting,
    isDeleting,
    isDeleteConfirmationOpen,
    openDeleteConfirmation,
    closeDeleteConfirmation,
    handleExport,
    handleDelete,
  } = settings;

  const erased = [
    t("myProfileData.delete.erasedProfile"),
    t("myProfileData.delete.erasedHistory"),
    t("myProfileData.delete.erasedPrompts"),
    t("myProfileData.delete.erasedAnalytics"),
    t("myProfileData.delete.erasedPreferences"),
  ];
  const retained = [
    t("myProfileData.delete.retainedInvoices"),
    t("myProfileData.delete.retainedRecord"),
    t("myProfileData.delete.retainedLegal"),
  ];

  return (
    <div className="flex flex-col gap-4">
      <div>
        <h2 className="m-0 font-(family-name:--disp) text-[22px] font-extrabold tracking-[-0.02em]">
          {t("myProfileData.heading")}
        </h2>
        <div className="mt-1 text-[13px] text-(--t-2)">{t("myProfileData.subheading")}</div>
      </div>

      {/* ── 1. What we keep ── */}
      <div className={CARD}>
        <h3 className={CARD_TITLE}>{t("myProfileData.retention.heading")}</h3>
        <p className={CARD_DESC}>{t("myProfileData.retention.description")}</p>
        <table className="w-full border-collapse">
          <thead>
            <tr>
              <th className={TH}>{t("myProfileData.retention.colData")}</th>
              <th className={TH}>{t("myProfileData.retention.colKeptFor")}</th>
              <th className={TH}>{t("myProfileData.retention.colWhy")}</th>
            </tr>
          </thead>
          <tbody className="[&>tr:last-child>td]:border-b-0">
            <tr>
              <td className={TD}>{t("myProfileData.retention.account")}</td>
              <td className={TD}>{t("myProfileData.retention.accountKept")}</td>
              <td className={TD}>{t("myProfileData.retention.accountWhy")}</td>
            </tr>
            <tr>
              <td className={TD}>{t("myProfileData.retention.audits")}</td>
              <td className={TD}>
                <WithConfirm template={t("myProfileData.retention.auditsKept")} />
              </td>
              <td className={TD}>{t("myProfileData.retention.auditsWhy")}</td>
            </tr>
            {/*
              SIGV2-1144: the invoice row carries a fact, not a chip. The
              entity is UAE, so the period is the statutory one the code now
              enforces per record: 5 years following the tax period the
              invoice relates to (Cabinet Decision 74/2023 Art. 3), extended
              by 4 years for an audit or dispute and 1 year from a voluntary
              disclosure. The remaining chips below stay chips because nobody
              has signed those periods off.
            */}
            <tr>
              <td className={TD}>{t("myProfileData.retention.invoices")}</td>
              <td className={TD}>{t("myProfileData.retention.invoicesKept")}</td>
              <td className={TD}>{t("myProfileData.retention.invoicesWhy")}</td>
            </tr>
            <tr>
              <td className={TD}>{t("myProfileData.retention.logs")}</td>
              <td className={TD}>
                <Confirm />
              </td>
              <td className={TD}>{t("myProfileData.retention.logsWhy")}</td>
            </tr>
            <tr>
              <td className={TD}>{t("myProfileData.retention.support")}</td>
              <td className={TD}>
                <Confirm />
              </td>
              <td className={TD}>{t("myProfileData.retention.supportWhy")}</td>
            </tr>
          </tbody>
        </table>
      </div>

      {/* ── 2. Where your data goes ── */}
      <div className={CARD}>
        <h3 className={CARD_TITLE}>{t("myProfileData.processors.heading")}</h3>
        <p className={CARD_DESC}>{t("myProfileData.processors.description")}</p>
        <div className={ROW}>
          <div>
            <div className={ROW_TITLE}>{t("myProfileData.processors.hosting")}</div>
            <div className={ROW_DESC}>{t("myProfileData.processors.hostingPurpose")}</div>
          </div>
          <Confirm label="[CONFIRM: region]" />
        </div>
        <div className={ROW}>
          <div>
            <div className={ROW_TITLE}>{t("myProfileData.processors.payments")}</div>
            <div className={ROW_DESC}>{t("myProfileData.processors.paymentsPurpose")}</div>
          </div>
          <Confirm label="[CONFIRM: region]" />
        </div>
        <div className={ROW}>
          <div>
            <div className={ROW_TITLE}>{t("myProfileData.processors.analytics")}</div>
            <div className={ROW_DESC}>{t("myProfileData.processors.analyticsPurpose")}</div>
          </div>
          <span className="font-(family-name:--mono) text-[10.5px] uppercase tracking-[0.08em] text-(--t-3)">
            {t("myProfileData.processors.analyticsRegion")}
          </span>
        </div>
        <div className={ROW}>
          <div>
            <div className={ROW_TITLE}>{t("myProfileData.processors.email")}</div>
            <div className={ROW_DESC}>{t("myProfileData.processors.emailPurpose")}</div>
          </div>
          <Confirm label="[CONFIRM: region]" />
        </div>
        <p className="mt-3 mb-0 text-[12px] leading-[1.5] text-(--t-3)">
          {t("myProfileData.processors.crossBorder")}
        </p>
      </div>

      {/* ── 3. Export ── */}
      <div className={CARD}>
        <h3 className={CARD_TITLE}>{t("myProfileData.export.heading")}</h3>
        <p className={CARD_DESC}>{t("myProfileData.export.description")}</p>
        <div className="flex flex-wrap items-center gap-3.5">
          <button
            type="button"
            className={BTN_GHOST}
            onClick={handleExport}
            disabled={isDeleting || !isSignedIn || isExporting}
          >
            {isExporting ? t("myProfileData.export.preparing") : t("myProfileData.export.action")}
          </button>
          <span className="m-0 text-[12px] leading-[1.5] text-(--t-3)">
            {t("myProfileData.export.note")}
          </span>
        </div>
      </div>

      {/* ── 4. Deleting your account ── */}
      <div className={CARD}>
        <h3 className={CARD_TITLE}>{t("myProfileData.delete.heading")}</h3>
        <p className={CARD_DESC}>{t("myProfileData.delete.description")}</p>
        <div className="my-3 grid grid-cols-1 gap-3.5 md:grid-cols-2">
          <BulletList
            heading={t("myProfileData.delete.erasedHeading")}
            tone="good"
            items={erased}
          />
          <BulletList
            heading={t("myProfileData.delete.retainedHeading")}
            tone="warn"
            items={retained}
          />
        </div>
        <p className="m-0 text-[12px] leading-[1.5] text-(--t-3)">
          {t("myProfileData.delete.warning")}
        </p>
        {/*
          SIGV2-1144: there is no grace period or email confirmation. The
          deletion is synchronous, and the code that ran it deletes the
          account's EmailOutbox in the same pass, so the old copy promised a
          pause and a confirmation email that could never happen. The receipt
          line is true: account_deletion_receipts is written in-transaction.
        */}
        <p className="mt-2 mb-[18px] text-[12px] leading-[1.5] text-(--t-3)">
          {t("myProfileData.delete.grace")}
        </p>
        <button
          type="button"
          className={BTN_DESTRUCTIVE}
          onClick={openDeleteConfirmation}
          disabled={isExporting || !isSignedIn || isDeleting}
        >
          {isDeleting ? t("myProfileData.delete.deleting") : t("myProfileData.delete.action")}
        </button>
      </div>

      {dataActionMessage && (
        <p className="m-0 text-[12.5px] leading-[1.5] text-(--good)">{dataActionMessage}</p>
      )}
      {dataActionError && (
        <p className="m-0 text-[12.5px] leading-[1.5] text-(--bad)">{dataActionError}</p>
      )}

      {/* ── Delete confirmation dialog ── */}
      <Modal
        open={isDeleteConfirmationOpen}
        onClose={closeDeleteConfirmation}
        panelClassName="w-full max-w-lg border-(--line) bg-(--panel)"
        ariaLabelledby="delete-account-title"
      >
        <div className="font-(family-name:--mono) text-[10.5px] uppercase tracking-[0.09em] text-(--t-3)">
          {t("myProfileData.delete.heading")}
        </div>
        <h3
          id="delete-account-title"
          className="mt-2 mb-1.5 font-(family-name:--disp) text-[18px] font-extrabold tracking-[-0.02em]"
        >
          {t("myProfileData.delete.dialogTitle")}
        </h3>
        <p className="m-0 mb-2.5 text-[13px] leading-[1.5] text-(--t-2)">
          {t("myProfileData.delete.dialogBodyOne")}
        </p>
        <p className="m-0 mb-[18px] text-[13px] leading-[1.5] text-(--t-2)">
          {t("myProfileData.delete.dialogBodyTwo")}
        </p>
        <div className="flex justify-end gap-2.5">
          <button type="button" className={BTN_GHOST} onClick={closeDeleteConfirmation}>
            {t("myProfileData.delete.cancel")}
          </button>
          <button
            type="button"
            className={BTN_DESTRUCTIVE}
            disabled={isDeleting}
            onClick={() => {
              void handleDelete();
            }}
          >
            {isDeleting ? t("myProfileData.delete.deleting") : t("myProfileData.delete.action")}
          </button>
        </div>
      </Modal>
    </div>
  );
};

export default DataRightsSection;
