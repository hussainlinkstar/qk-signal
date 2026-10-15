import Link from "next/link";
import React from "react";

import { cx } from "@/components/ui/utils";

/**
 * signal-MVP `.lockgate` > `.lockcard`: the centred 380px upgrade card that
 * sits over blurred locked content. The host supplies the `.lockwrap`
 * structure (`blur-[6px] pointer-events-none select-none` content + centred
 * gate layer). Entitlement stays server-enforced - the card only links to the
 * real billing surface; the mock's client-side "Preview (demo)" control is
 * deliberately not reproduced.
 */
export default function SignalLockCard({
  eyebrow,
  title,
  body,
  ctaLabel,
  ctaHref,
  className,
}: {
  eyebrow: string;
  title: string;
  body: string;
  ctaLabel: string;
  ctaHref: string;
  className?: string;
}) {
  return (
    <div
      className={cx(
        "w-full max-w-[380px] rounded-[22px] border-0 bg-white px-6 py-[22px] text-center shadow-[0_20px_40px_-24px_rgba(15,23,42,0.28)]",
        className
      )}
    >
      <div className="font-(family-name:--mono) text-[10.5px] uppercase tracking-[0.14em] text-(--purple)">
        {eyebrow}
      </div>
      <h3 className="mx-0 mb-1.5 mt-2 font-(family-name:--disp) text-[18px] font-extrabold tracking-[-0.02em] text-(--t-1)">
        {title}
      </h3>
      <p className="mb-4 text-[13px] leading-[1.5] text-(--t-2)">{body}</p>
      <Link
        href={ctaHref}
        className="inline-flex h-[38px] w-full items-center justify-center rounded-[10px] bg-(--ink) px-[15px] font-(family-name:--body-font) text-[13.5px] font-semibold leading-none text-white transition-colors hover:bg-black focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-(--purple) focus-visible:ring-offset-2 max-md:min-h-11"
      >
        {ctaLabel}
      </Link>
    </div>
  );
}
