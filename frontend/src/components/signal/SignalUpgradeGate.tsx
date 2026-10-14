"use client";

import Link from "next/link";
import React, { useId } from "react";
import { Check, X } from "lucide-react";

import Modal from "@/components/ui/Modal";

export type SignalUpgradeGateProps = {
  open: boolean;
  onClose: () => void;
  title: string;
  description: string;
  planLabel: string;
  upgradeHref: string;
  upgradeLabel: string;
  fallbackHref?: string;
  /**
   * Pass `false` when the page behind the gate is blurred and inert. Dismissing
   * the gate there used to leave the user on an unreadable, non-interactive page
   * with no way back, so the only exits become Upgrade and the fallback link.
   */
  dismissible?: boolean;
  children?: React.ReactNode;
};

// signal-MVP `.gate` > `.gcard`: 460px radius-20 panel, `--ink` banner with a
// mono plan tag, `.bd` body with check feature rows, a full-width 46px
// gradient CTA and a centred demo/back link. The mock's client-side
// classList unlock is not reproduced - the secondary link navigates away,
// it never reveals gated content.
export default function SignalUpgradeGate({
  open,
  onClose,
  title,
  description,
  planLabel,
  upgradeHref,
  upgradeLabel,
  fallbackHref = "/dashboard",
  dismissible = true,
  children,
}: SignalUpgradeGateProps) {
  const reactId = useId().replace(/:/g, "");
  const titleId = `signal-upgrade-title-${reactId}`;
  const descriptionId = `signal-upgrade-description-${reactId}`;
  const safeFallbackHref = fallbackHref.startsWith("/dashboard") ? fallbackHref : "/dashboard";

  return (
    <Modal
      open={open}
      onClose={dismissible ? onClose : () => {}}
      closeOnBackdrop={dismissible}
      closeOnEscape={dismissible}
      ariaLabelledby={titleId}
      ariaDescribedby={descriptionId}
      /* Mounting must not land focus on the upgrade action: it is a purchase,
         and its focus ring then appeared unprompted on every open. */
      initialFocusPanel
      /* Approved `.gate`: light --gate-veil wash + blur(3px) over the blurred
         page. The dark scrim read as a blackout on the light shell. gate-veil
         is a @utility so it wins over DialogOverlay's backdrop-surface;
         --gate-veil falls back to --overlay-backdrop off-theme. */
      className="gate-veil p-3"
      panelClassName="w-full max-w-[460px] overflow-hidden rounded-[20px] border-(--line) bg-(--panel) p-0 shadow-[0_30px_80px_-30px_rgba(12,15,22,0.4)]"
    >
      {dismissible ? (
        <button
          type="button"
          onClick={onClose}
          aria-label="Close upgrade information"
          className="absolute end-3 top-3 z-10 inline-flex min-h-11 min-w-11 items-center justify-center rounded-lg text-white/70 transition-colors hover:text-white focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-(--purple)"
        >
          <X className="h-5 w-5" aria-hidden="true" />
        </button>
      ) : null}

      {/* `.gcard .banner`: --ink, white, padding 26px 28px. */}
      <div className="bg-(--ink) px-7 pb-[26px] pt-[26px] text-white">
        <p className="font-(family-name:--mono) text-[10.5px] uppercase tracking-[0.14em] text-(--cyan)">
          {planLabel}
        </p>
        <h2
          id={titleId}
          className="mb-2 mt-2.5 font-(family-name:--disp) text-[23px] font-black tracking-[-0.02em]"
        >
          {title}
        </h2>
        <p
          id={descriptionId}
          className="m-0 max-w-[340px] text-[13.5px] leading-[1.55] text-white/80"
        >
          {description}
        </p>
      </div>

      {/* `.gcard .bd`: padding 22px 28px 26px. */}
      <div className="px-7 pb-[26px] pt-[22px]">
        {children ? (
          <div className="mb-4 flex gap-3">
            <Check
              className="mt-px h-[18px] w-[18px] flex-none text-(--purple)"
              strokeWidth={2}
              aria-hidden="true"
            />
            <div className="text-[13px] leading-[1.45] text-(--t-2) [&_b]:font-semibold [&_b]:text-(--t-1)">
              {children}
            </div>
          </div>
        ) : null}

        <Link
          href={upgradeHref}
          className="flex h-[46px] w-full items-center justify-center rounded-[12px] bg-(image:--grad) font-(family-name:--body-font) text-[14.5px] font-bold text-white transition-[filter] hover:brightness-[1.06] focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-(--purple)"
        >
          {upgradeLabel}
        </Link>

        <Link
          href={safeFallbackHref}
          className="mt-3 flex min-h-11 w-full items-center justify-center text-[12.5px] text-(--t-3) transition-colors hover:text-(--t-2) hover:underline focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-(--purple)"
        >
          Back to dashboard
        </Link>
        {dismissible ? (
          <button
            type="button"
            onClick={onClose}
            className="flex min-h-11 w-full items-center justify-center text-[12.5px] text-(--t-3) transition-colors hover:text-(--t-2) hover:underline"
          >
            Not now
          </button>
        ) : null}
      </div>
    </Modal>
  );
}
