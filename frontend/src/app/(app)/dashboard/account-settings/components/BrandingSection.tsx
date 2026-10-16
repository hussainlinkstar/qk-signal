"use client";

import React, { useRef } from "react";
import { useAccountSettings } from "../useAccountSettings";
import { cx } from "@/components/ui/utils";
import { DEFAULT_PRIMARY_COLOR, DEFAULT_SECONDARY_COLOR } from "../utils";

type BrandingSectionProps = {
  settings: ReturnType<typeof useAccountSettings>;
};

const BrandingSection: React.FC<BrandingSectionProps> = ({ settings }) => {
  const {
    isSignedIn,
    isBootLoading,
    hasWhiteLabel,
    planType,
    logoUrl,
    logoFileName,
    isUploadingBrandingLogo,
    handleUploadBrandingLogo,
    handleRemoveBrandingLogo,
    primaryColor,
    setPrimaryColor,
    secondaryColor,
    setSecondaryColor,
    brandingMessage,
    brandingError,
    isSavingBranding,
    handleSaveBranding,
  } = settings;

  const fileInputRef = useRef<HTMLInputElement | null>(null);

  const effectivePrimary = primaryColor || DEFAULT_PRIMARY_COLOR;
  const effectiveSecondary = secondaryColor || DEFAULT_SECONDARY_COLOR;
  const reportPaletteSummary = `${effectivePrimary} / ${effectiveSecondary}`;

  const onFileSelected = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) {
      void handleUploadBrandingLogo(file);
    }
    e.target.value = "";
  };

  const openFileDialog = () => {
    if (!hasWhiteLabel || isUploadingBrandingLogo) return;
    fileInputRef.current?.click();
  };

  return (
    <div className="flex flex-col gap-4">
      {/* ── Report Branding ── */}
      <div className="rounded-[22px] border-0 bg-white px-[22px] py-[18px]">
        <div className="mb-1 flex items-center justify-between gap-4">
          <h3 className="m-0 font-(family-name:--disp) text-[15px] font-bold tracking-[-0.01em]">
            Report Branding
          </h3>
          <span
            className={cx(
              "rounded-[6px] px-2 py-[3px] font-(family-name:--mono) text-[10.5px] uppercase tracking-[0.04em]",
              hasWhiteLabel ? "bg-(--good-s) text-(--good)" : "bg-(--line-2) text-(--t-2)"
            )}
          >
            {hasWhiteLabel ? "Available" : "Executive"}
          </span>
        </div>
        <p className="m-0 mb-[18px] text-[12.5px] leading-[1.5] text-(--t-3)">
          Customize the logo and color palette applied to PDF reports and shared audit exports.
        </p>

        {!hasWhiteLabel && (
          <p className="m-0 mb-[18px] text-[12.5px] leading-[1.5] text-(--warn)">
            Report branding is unlocked on Executive. Your current plan{" "}
            <b>{planType?.replaceAll("_", " ") || "current workspace plan"}</b> can still export
            reports, but the default Qiko Signal presentation remains active.
          </p>
        )}

        <div className="mb-[18px] grid grid-cols-1 gap-4 md:grid-cols-3">
          <div>
            <span className="mb-2 block font-(family-name:--mono) text-[10.5px] uppercase tracking-[0.08em] text-(--t-3)">
              Report identity
            </span>
            <div className="text-[13px] font-semibold">Logo and palette</div>
            <p className="mt-1 mb-0 text-[12.5px] leading-[1.45] text-(--t-3)">
              Upload your report logo and configure the accent colors applied to PDF exports, report
              covers, and client-facing share pages.
            </p>
          </div>
          <div>
            <span className="mb-2 block font-(family-name:--mono) text-[10.5px] uppercase tracking-[0.08em] text-(--t-3)">
              Applies to
            </span>
            <div className="text-[13px] font-semibold">Reports and exports</div>
            <p className="mt-1 mb-0 text-[12.5px] leading-[1.45] text-(--t-3)">
              Used on report covers, section accents, and branded client-facing report surfaces.
            </p>
          </div>
          <div>
            <span className="mb-2 block font-(family-name:--mono) text-[10.5px] uppercase tracking-[0.08em] text-(--t-3)">
              Current palette
            </span>
            <div className="font-(family-name:--mono) text-[13px] font-semibold">
              {reportPaletteSummary}
            </div>
            <p className="mt-1 mb-0 text-[12.5px] leading-[1.45] text-(--t-3)">
              Pair a stronger primary with a softer secondary to keep report blocks balanced.
            </p>
          </div>
        </div>

        <div className="mb-4">
          <span className="mb-2 block font-(family-name:--mono) text-[10.5px] uppercase tracking-[0.08em] text-(--t-3)">
            Report logo
          </span>
          <input
            ref={fileInputRef}
            type="file"
            accept="image/png,image/jpeg,image/webp,image/svg+xml"
            onChange={onFileSelected}
            disabled={!hasWhiteLabel || isUploadingBrandingLogo}
            className="hidden"
          />
          <div
            className={cx(
              "flex flex-col items-center justify-center gap-2 rounded-[12px] border-[1.5px] border-dashed border-(--line) p-[26px] text-center text-(--t-3) hover:border-(--purple) hover:text-(--purple)",
              hasWhiteLabel ? "cursor-pointer" : "cursor-not-allowed opacity-55"
            )}
            onClick={openFileDialog}
          >
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" width="24" height="24">
              <path d="M12 16V4M8 8l4-4 4 4" />
              <path d="M4 16v2a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-2" />
            </svg>
            <b>
              {isUploadingBrandingLogo
                ? "Uploading…"
                : logoFileName || (logoUrl ? "Logo uploaded" : "Drop logo here or click to upload")}
            </b>
            <span>PNG, JPG, WEBP, or SVG up to 2 MB. Upload first, then save branding.</span>
          </div>
          {logoUrl && (
            <div className="mt-2.5">
              <button
                type="button"
                className="inline-flex h-[38px] cursor-pointer items-center gap-2 rounded-full border-0 bg-[#FEECEC] px-[15px] py-0 font-(family-name:--body-font) text-[13.5px] font-semibold text-(--bad) hover:bg-[#E8ECF3]"
                onClick={handleRemoveBrandingLogo}
                disabled={!hasWhiteLabel || isUploadingBrandingLogo}
              >
                Remove logo
              </button>
            </div>
          )}
        </div>

        <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
          <div className="mb-4 last:mb-0">
            <span className="mb-2 block font-(family-name:--mono) text-[10.5px] uppercase tracking-[0.08em] text-(--t-3)">
              Primary color
            </span>
            <div className="flex items-center gap-2.5">
              <span
                className="h-[34px] w-[34px] flex-none rounded-[9px] border-0 bg-(--sw)"
                style={{ "--sw": effectivePrimary } as React.CSSProperties}
              />
              <input
                className="field-focus-ring h-11 w-full rounded-[14px] border border-(--line) bg-white px-[13px] py-0 font-(family-name:--body-font) text-[13.5px] text-(--t-1) outline-none placeholder:text-(--t-3) disabled:border-transparent disabled:bg-(--line-2) disabled:text-(--t-3)"
                type="text"
                value={primaryColor}
                onChange={(e) => setPrimaryColor(e.target.value)}
                disabled={!hasWhiteLabel}
              />
            </div>
          </div>
          <div className="mb-4 last:mb-0">
            <span className="mb-2 block font-(family-name:--mono) text-[10.5px] uppercase tracking-[0.08em] text-(--t-3)">
              Secondary color
            </span>
            <div className="flex items-center gap-2.5">
              <span
                className="h-[34px] w-[34px] flex-none rounded-[9px] border-0 bg-(--sw)"
                style={{ "--sw": effectiveSecondary } as React.CSSProperties}
              />
              <input
                className="field-focus-ring h-11 w-full rounded-[14px] border border-(--line) bg-white px-[13px] py-0 font-(family-name:--body-font) text-[13.5px] text-(--t-1) outline-none placeholder:text-(--t-3) disabled:border-transparent disabled:bg-(--line-2) disabled:text-(--t-3)"
                type="text"
                value={secondaryColor}
                onChange={(e) => setSecondaryColor(e.target.value)}
                disabled={!hasWhiteLabel}
              />
            </div>
          </div>
        </div>

        <div className="mt-[18px] flex items-center justify-end gap-3">
          {brandingMessage && (
            <span className="text-[13px] font-semibold text-(--good)">{brandingMessage}</span>
          )}
          {brandingError && (
            <span className="text-[13px] font-semibold text-(--bad)">{brandingError}</span>
          )}
          <button
            type="button"
            className="inline-flex h-[38px] cursor-pointer items-center gap-2 rounded-full border-0 bg-[#111827] px-[15px] py-0 font-(family-name:--body-font) text-[13.5px] font-semibold text-white hover:bg-black"
            onClick={handleSaveBranding}
            disabled={!isSignedIn || isBootLoading || isUploadingBrandingLogo || isSavingBranding}
          >
            {isSavingBranding ? "Saving…" : "Save branding"}
          </button>
        </div>
      </div>

      {/* ── Guidance ── */}
      <div className="rounded-[22px] border-0 bg-white px-[22px] py-[18px]">
        <h3 className="m-0 mb-[3px] font-(family-name:--disp) text-[15px] font-bold tracking-[-0.01em]">
          Keep report branding predictable
        </h3>
        <p className="m-0 mb-[18px] text-[12.5px] leading-[1.5] text-(--t-3)">
          Three quick rules for clean, legible report exports.
        </p>
        <div className="flex gap-[13px] border-t border-t-(--line-2) py-3.5 first:border-t-0 max-md:flex-wrap">
          <span className="flex h-6 w-6 flex-none items-center justify-center rounded-full bg-(--ink) font-(family-name:--disp) text-[12px] font-bold text-white">
            1
          </span>
          <div>
            <p className="m-0 text-[13px] leading-[1.5] text-(--t-2)">
              Use a horizontal logo with clear space so report covers stay legible in both PDF and
              portal contexts.
            </p>
          </div>
        </div>
        <div className="flex gap-[13px] border-t border-t-(--line-2) py-3.5 first:border-t-0 max-md:flex-wrap">
          <span className="flex h-6 w-6 flex-none items-center justify-center rounded-full bg-(--ink) font-(family-name:--disp) text-[12px] font-bold text-white">
            2
          </span>
          <div>
            <p className="m-0 text-[13px] leading-[1.5] text-(--t-2)">
              Pair a stronger primary with a softer secondary accent to avoid heavy monochrome
              report blocks.
            </p>
          </div>
        </div>
        <div className="flex gap-[13px] border-t border-t-(--line-2) py-3.5 first:border-t-0 max-md:flex-wrap">
          <span className="flex h-6 w-6 flex-none items-center justify-center rounded-full bg-(--ink) font-(family-name:--disp) text-[12px] font-bold text-white">
            3
          </span>
          <div>
            <p className="m-0 text-[13px] leading-[1.5] text-(--t-2)">
              Save after upload or palette changes. Unsaved edits stay local to this browser
              session.
            </p>
          </div>
        </div>
      </div>
    </div>
  );
};

export default BrandingSection;
