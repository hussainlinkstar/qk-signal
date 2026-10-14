import type { Metadata } from "next";
import localFont from "next/font/local";
import SignalBrandLockup from "@/components/signal/SignalBrandLockup";
import { BASE_PATH } from "@/lib/basePath";
import { GATE_PATH } from "@/lib/signalGate";
import WaitlistForm from "./WaitlistForm";

// Load brand fonts via next/font (CSP-safe: no external <link>, self-hosted).
const geistSans = localFont({
  src: "../fonts/geist-variable.woff2",
  weight: "100 900",
  style: "normal",
  variable: "--font-geist",
  display: "swap",
  declarations: [
    {
      prop: "unicode-range",
      value:
        "U+0020-007E,U+00A0-00AC,U+00AE-0113,U+0116-012B,U+012E-0137,U+0139-013E,U+0141-0148,U+014A-014D,U+0150-017E,U+018F,U+0192,U+01A0-01A1,U+01AF-01B0,U+01CD-01CE,U+01E4-01E9,U+0218-021B,U+0237,U+0259,U+02B9,U+02BC,U+02C6-02C8,U+02DA,U+02DC-02DD,U+0300-0301,U+0303-0304,U+0308-0309,U+0323,U+0400-045F,U+0462-0463,U+046A-046B,U+0472-0475,U+0490-0493,U+0496-0497,U+049A-049B,U+04A2-04A3,U+04AE-04B3,U+04B6-04B7,U+04BA-04BB,U+04C0,U+04CF,U+04D8-04D9,U+04E2-04E3,U+04E8-04E9,U+04EE-04EF,U+1E20-1E21,U+1E80-1E85,U+1E9E,U+1EA0-1EF9,U+2013-2014,U+2018-201A,U+201C-201E,U+2020,U+2022,U+2026,U+2032-2033,U+2039-203A,U+2044,U+20AA,U+20AC,U+20B1,U+20B4,U+20B9,U+20BD,U+2116,U+2122,U+2191,U+2193,U+2212,U+A78B-A78C",
    },
  ],
});
const geistMono = localFont({
  src: "../fonts/geist-mono-variable.woff2",
  weight: "100 900",
  style: "normal",
  variable: "--font-geist-mono",
  display: "swap",
  declarations: [
    {
      prop: "unicode-range",
      value:
        "U+0020-007E,U+00A0-00AC,U+00AE-0113,U+0116-012B,U+012E-0131,U+0134-0137,U+0139-013E,U+0141-0148,U+014A-014D,U+0150-017E,U+018F,U+0192,U+01A0-01A1,U+01AF-01B0,U+01CD-01CE,U+01E4-01E9,U+0218-021B,U+0237,U+0259,U+02B9,U+02BC,U+02C6-02C8,U+02DA,U+02DC-02DD,U+0300-0301,U+0303-0304,U+0308-0309,U+0323,U+0400-045F,U+0462-0463,U+046A-046B,U+0472-0475,U+0490-0493,U+0496-0497,U+049A-049B,U+04A2-04A3,U+04AE-04B3,U+04B6-04B7,U+04BA-04BB,U+04C0,U+04CF,U+04D8-04D9,U+04E2-04E3,U+04E8-04E9,U+04EE-04EF,U+1E20-1E21,U+1E80-1E85,U+1E9E,U+1EA0-1EF9,U+2013-2014,U+2018-201A,U+201C-201E,U+2020,U+2022,U+2026,U+2032-2033,U+2039-203A,U+2044,U+20AA,U+20AC,U+20B1,U+20B4,U+20B9,U+20BD,U+2116,U+2122,U+2191,U+2193,U+2212,U+2500-259F,U+A78B-A78C",
    },
  ],
});

export const metadata: Metadata = {
  title: "Qiko Signal · Coming soon",
  description:
    "Qiko Signal shows you how AI engines find, describe, and recommend your business. Join the waitlist to be first in when it goes live.",
  robots: { index: false, follow: false },
};

function safeNext(next: string | undefined): string {
  if (!next || !next.startsWith("/") || next.startsWith("//")) {
    return "/";
  }
  return next;
}

export default async function GatePage({
  searchParams,
}: {
  searchParams: Promise<{ next?: string; error?: string }>;
}) {
  const params = await searchParams;
  const next = safeNext(params.next);
  const hasError = params.error === "1";

  return (
    <div className={`qcs ${geistSans.variable} ${geistMono.variable}`}>
      <header className="sticky top-0 z-50 border-b [border-bottom-color:#18223a] bg-[rgba(6,8,15,0.72)] backdrop-blur-[12px]">
        <div className="mx-auto flex max-w-[1120px] items-center justify-between gap-4 px-6 py-[15px]">
          <div className="flex items-center gap-[14px]">
            <a
              className="text-[19px] font-bold tracking-[-0.02em]"
              href={`${BASE_PATH}${GATE_PATH}`}
              aria-label="Qiko Signal"
            >
              <SignalBrandLockup size="auth" />
            </a>
            <span className="inline-flex items-center gap-2 rounded-[999px] border border-[#16384a] bg-[rgba(20,55,70,0.35)] px-[13px] py-[7px] font-(family-name:--mono) text-[11px] font-semibold uppercase tracking-[0.14em] text-(--eye) max-[780px]:hidden">
              Coming soon
            </span>
          </div>
          <a
            href="#waitlist"
            className="inline-flex cursor-pointer items-center gap-2 whitespace-nowrap rounded-[999px] border border-[#283349] bg-[rgba(255,255,255,0.04)] px-[18px] py-[10px] text-[14px] font-semibold text-(--ink) transition-[transform,box-shadow,background] hover:bg-[rgba(255,255,255,0.08)] focus-visible:outline-2 focus-visible:outline-offset-[3px] focus-visible:outline-(--cyan)"
          >
            Join waitlist
          </a>
        </div>
      </header>

      <section className="relative overflow-hidden px-6 pb-[78px] pt-24 text-center max-[780px]:px-[22px] max-[780px]:pb-[60px] max-[780px]:pt-[72px]">
        <div className="pointer-events-none absolute -top-40 left-1/2 h-[520px] w-[760px] -translate-x-1/2 rounded-[50%] bg-[radial-gradient(circle,rgba(34,160,245,0.2),transparent_65%)] motion-reduce:hidden" />
        <div className="pointer-events-none absolute -right-[140px] top-10 h-[460px] w-[460px] rounded-[50%] bg-[radial-gradient(circle,rgba(52,211,153,0.12),transparent_65%)] motion-reduce:hidden" />
        <div className="relative z-[1] mx-auto max-w-[860px]">
          <span
            className="font-(family-name:--mono) text-[12.5px] font-semibold uppercase tracking-[0.18em] text-(--eye)"
            data-reveal
          >
            Qiko Signal · launching soon
          </span>
          <h1
            data-reveal
            className="mx-auto my-[22px] max-w-[16ch] text-balance text-[clamp(40px,6.2vw,74px)] font-bold leading-[1.02] tracking-[-0.03em]"
          >
            Find out if AI{" "}
            <span className="bg-(image:--grad) bg-clip-text text-transparent">recommends you</span>.
          </h1>
          <p
            className="mx-auto mb-[34px] max-w-[60ch] text-[clamp(17px,2vw,19px)] leading-[1.6] text-(--muted)"
            data-reveal
          >
            Search is moving from a list of links to a single answer chosen by AI. Signal scans your
            brand across the engines people now ask first, gives you two scores, shows where
            competitors are winning, and tells you what to fix. Join the waitlist to be first in
            when it goes live.
          </p>
          <div className="flex flex-wrap justify-center gap-[14px]" data-reveal>
            <a
              href="#waitlist"
              className="inline-flex cursor-pointer items-center gap-2 whitespace-nowrap rounded-[999px] border border-transparent px-[26px] py-[15px] text-[15.5px] font-bold transition-[transform,box-shadow,background] focus-visible:outline-2 focus-visible:outline-offset-[3px] focus-visible:outline-(--cyan) text-white bg-(image:--grad) shadow-[0_14px_38px_-12px_rgba(79,143,247,0.75)] hover:-translate-y-px hover:shadow-[0_18px_44px_-12px_rgba(79,143,247,0.85)]"
            >
              Join waitlist <span aria-hidden="true">→</span>
            </a>
            <a
              href="#how"
              className="inline-flex cursor-pointer items-center gap-2 whitespace-nowrap rounded-[999px] border border-[#283349] bg-[rgba(255,255,255,0.04)] px-[26px] py-[15px] text-[15.5px] font-semibold text-(--ink) transition-[transform,box-shadow,background] hover:bg-[rgba(255,255,255,0.08)] focus-visible:outline-2 focus-visible:outline-offset-[3px] focus-visible:outline-(--cyan)"
            >
              How does it work
            </a>
          </div>
          <div
            className="mt-[34px] font-(family-name:--mono) text-[12.5px] tracking-[0.02em] text-(--faint) [&_b]:font-medium [&_b]:text-(--muted-2)"
            data-reveal
          >
            Checked across <b>a controlled panel of leading AI models</b>
          </div>
        </div>
      </section>

      <section id="how" className="px-6 pb-[30px] pt-[70px]">
        <div className="mx-auto max-w-[1120px] px-6">
          <div className="mx-auto mb-11 max-w-[64ch] text-center">
            <span
              className="font-(family-name:--mono) text-[12.5px] font-semibold uppercase tracking-[0.18em] text-(--eye)"
              data-reveal
            >
              How it works
            </span>
            <h2
              data-reveal
              className="mx-auto mb-4 mt-3.5 max-w-[20ch] text-balance text-[clamp(30px,4vw,46px)] font-bold leading-[1.08] tracking-[-0.025em]"
            >
              One scan. Two scores. A clear list of fixes.
            </h2>
            <p data-reveal className="text-[17px] leading-[1.6] text-(--muted)">
              Signal looks at how people actually search for a business like yours, then tells you
              in plain language where you stand and what it is costing you.
            </p>
          </div>
          <div className="steps grid grid-cols-3 gap-[18px] max-[780px]:flex max-[780px]:snap-x max-[780px]:snap-mandatory max-[780px]:overflow-x-auto max-[780px]:overscroll-x-contain max-[780px]:gap-[14px] max-[780px]:pb-3">
            <div
              className="relative flex flex-col rounded-[18px] border border-(--line-soft) bg-[linear-gradient(165deg,var(--card-a),var(--card-b))] px-6 pb-7 pt-[26px] max-[780px]:flex-[0_0_85%] max-[780px]:snap-start max-[780px]:flex-row max-[780px]:items-start max-[780px]:gap-[18px] max-[780px]:px-5 max-[780px]:py-[22px]"
              data-reveal
            >
              <div className="max-[780px]:flex max-[780px]:flex-none max-[780px]:flex-col">
                <div className="mb-4 font-(family-name:--mono) text-xs font-semibold leading-[18px] tracking-[0.1em] text-(--eye)">
                  01
                </div>
                <div className="mb-4 grid h-11 w-11 place-items-center rounded-[12px] border border-[rgba(45,212,218,0.22)] bg-[linear-gradient(150deg,rgba(34,211,238,0.2),rgba(79,143,247,0.04))] max-[780px]:mb-3">
                  <svg width="20" height="20" viewBox="0 0 24 24" fill="none">
                    <circle cx="11" cy="11" r="7" stroke="#22D3EE" strokeWidth="2" />
                    <line
                      x1="16"
                      y1="16"
                      x2="20"
                      y2="20"
                      stroke="#4F8FF7"
                      strokeWidth="2"
                      strokeLinecap="round"
                    />
                  </svg>
                </div>
                <h3 className="mb-[9px] text-[18.5px] font-semibold tracking-[-0.01em] max-[780px]:mb-0">
                  Scan
                </h3>
              </div>
              <p className="text-[14.5px] leading-[1.6] text-(--muted-2) max-[780px]:min-w-0 max-[780px]:flex-1">
                Signal checks how you show up across the AI engines people now ask first, and across
                traditional search, in one pass.
              </p>
            </div>
            <div
              className="relative flex flex-col rounded-[18px] border border-(--line-soft) bg-[linear-gradient(165deg,var(--card-a),var(--card-b))] px-6 pb-7 pt-[26px] max-[780px]:flex-[0_0_85%] max-[780px]:snap-start max-[780px]:flex-row max-[780px]:items-start max-[780px]:gap-[18px] max-[780px]:px-5 max-[780px]:py-[22px]"
              data-reveal
            >
              <div className="max-[780px]:flex max-[780px]:flex-none max-[780px]:flex-col">
                <div className="mb-4 font-(family-name:--mono) text-xs font-semibold leading-[18px] tracking-[0.1em] text-(--eye)">
                  02
                </div>
                <div className="mb-4 grid h-11 w-11 place-items-center rounded-[12px] border border-[rgba(45,212,218,0.22)] bg-[linear-gradient(150deg,rgba(34,211,238,0.2),rgba(79,143,247,0.04))] max-[780px]:mb-3">
                  <svg width="20" height="20" viewBox="0 0 24 24" fill="none">
                    <path
                      d="M5 15l4-5 3 3 5-7"
                      stroke="#4F8FF7"
                      strokeWidth="2"
                      strokeLinecap="round"
                      strokeLinejoin="round"
                    />
                    <line
                      x1="4"
                      y1="20"
                      x2="20"
                      y2="20"
                      stroke="#A855F7"
                      strokeWidth="2"
                      strokeLinecap="round"
                    />
                  </svg>
                </div>
                <h3 className="mb-[9px] text-[18.5px] font-semibold tracking-[-0.01em] max-[780px]:mb-0">
                  Score
                </h3>
              </div>
              <p className="text-[14.5px] leading-[1.6] text-(--muted-2) max-[780px]:min-w-0 max-[780px]:flex-1">
                You get an SEO score for traditional search and an AIO score for AI search, plus
                where competitors are being recommended instead of you.
              </p>
            </div>
            <div
              className="relative flex flex-col rounded-[18px] border border-(--line-soft) bg-[linear-gradient(165deg,var(--card-a),var(--card-b))] px-6 pb-7 pt-[26px] max-[780px]:flex-[0_0_85%] max-[780px]:snap-start max-[780px]:flex-row max-[780px]:items-start max-[780px]:gap-[18px] max-[780px]:px-5 max-[780px]:py-[22px]"
              data-reveal
            >
              <div className="max-[780px]:flex max-[780px]:flex-none max-[780px]:flex-col">
                <div className="mb-4 font-(family-name:--mono) text-xs font-semibold leading-[18px] tracking-[0.1em] text-(--eye)">
                  03
                </div>
                <div className="mb-4 grid h-11 w-11 place-items-center rounded-[12px] border border-[rgba(45,212,218,0.22)] bg-[linear-gradient(150deg,rgba(34,211,238,0.2),rgba(79,143,247,0.04))] max-[780px]:mb-3">
                  <svg width="20" height="20" viewBox="0 0 24 24" fill="none">
                    <path
                      d="M12 3l2.2 5.9L20 11l-5.8 2.1L12 19l-2.2-5.9L4 11l5.8-2.1z"
                      fill="none"
                      stroke="#34d399"
                      strokeWidth="2"
                      strokeLinejoin="round"
                    />
                  </svg>
                </div>
                <h3 className="mb-[9px] text-[18.5px] font-semibold tracking-[-0.01em] max-[780px]:mb-0">
                  Act
                </h3>
              </div>
              <p className="text-[14.5px] leading-[1.6] text-(--muted-2) max-[780px]:min-w-0 max-[780px]:flex-1">
                You get prioritised fixes in plain language, ranked by impact, so you know exactly
                what to do next to get seen.
              </p>
            </div>
          </div>
          <div
            className="mx-auto mt-[26px] flex max-w-[820px] items-start gap-[14px] rounded-[14px] border border-(--line-soft) border-l-[3px] border-l-(--green) bg-[linear-gradient(165deg,var(--card-a),var(--card-b))] px-[22px] py-5 max-[780px]:flex-col max-[780px]:items-center max-[780px]:text-center"
            data-reveal
          >
            <span className="mt-px flex-none rounded-[7px] bg-[rgba(52,211,153,0.12)] px-2.5 py-[5px] font-(family-name:--mono) text-[11px] font-semibold uppercase tracking-[0.06em] text-[#7fe0c0]">
              Why trust it
            </span>
            <p className="m-0 text-[14.5px] leading-[1.6] text-(--muted-2) [&_b]:font-semibold [&_b]:text-(--ink)">
              Every finding is <b>cross-examined</b>. Specialist agents generate findings, separate
              critics challenge them, and a judge decides what holds up across multiple AI
              providers. Nothing is guessed by a single model.
            </p>
          </div>
        </div>
      </section>

      <section id="waitlist" className="px-6 pb-10 pt-[74px]">
        <div
          className="relative mx-auto max-w-[1120px] overflow-hidden rounded-[26px] border border-[#1f2c48] bg-[linear-gradient(160deg,#0f1830,#0a1020)] px-10 py-14 max-[780px]:px-[22px] max-[780px]:py-11"
          data-reveal
        >
          <div className="absolute inset-0 bg-[linear-gradient(#13203a_1px,transparent_1px),linear-gradient(90deg,#13203a_1px,transparent_1px)] bg-[size:42px_42px] opacity-40 [mask-image:radial-gradient(circle_at_50%_30%,#000,transparent_72%)]" />
          <div className="relative z-[1] mx-auto max-w-[560px] text-center">
            <WaitlistForm />
          </div>
        </div>
      </section>

      <footer className="mt-[60px] border-t border-t-[#11192b] bg-[#070a12]">
        <div className="mx-auto flex max-w-[1120px] flex-wrap items-center justify-between gap-[14px] px-6 py-[34px]">
          <a
            className="text-[19px] font-bold tracking-[-0.02em]"
            href={`${BASE_PATH}${GATE_PATH}`}
            aria-label="Qiko Signal"
          >
            <SignalBrandLockup />
          </a>
          <span className="font-(family-name:--mono) text-xs leading-[18px] text-(--muted-3)">
            Signal is part of Qiko
          </span>
          <small className="text-[13px] text-(--faint)">© 2026 Qiko. All rights reserved.</small>
          <a
            href="#team-access"
            className="font-(family-name:--mono) text-[11px] uppercase tracking-[0.16em] text-(--faint) opacity-55 transition-[opacity,color] hover:text-(--muted) hover:opacity-100"
          >
            Team access
          </a>
        </div>
      </footer>

      {/* Team access — subtle footer trigger opens this CSS-only modal
          (:target, no JS, CSP-safe). The team enters the preview password here. */}
      <div
        id="team-access"
        className={
          hasError
            ? "fixed inset-0 z-[100] flex items-center justify-center p-6"
            : "fixed inset-0 z-[100] hidden items-center justify-center p-6 target:flex"
        }
      >
        <a
          href={`${BASE_PATH}${GATE_PATH}`}
          className="absolute inset-0 bg-[rgba(4,6,12,0.72)] backdrop-blur-[4px]"
          aria-label="Close"
        />
        <div
          className="relative z-[1] w-full max-w-[400px] rounded-[18px] border border-[#1f2c48] bg-[linear-gradient(160deg,#0f1830,#0a1020)] px-7 pb-7 pt-8 text-center shadow-[0_30px_80px_-20px_rgba(0,0,0,0.7)]"
          role="dialog"
          aria-modal="true"
          aria-label="Team access"
        >
          <a
            href={`${BASE_PATH}${GATE_PATH}`}
            className="absolute right-4 top-3 text-[1.4rem] leading-none text-(--muted-2) hover:text-(--ink)"
            aria-label="Close"
          >
            ×
          </a>
          <span className="font-(family-name:--mono) text-[12.5px] font-semibold uppercase tracking-[0.18em] text-(--eye)">
            Team access
          </span>
          <h3 className="mx-0 mb-5 mt-2.5 text-[1.15rem] font-bold tracking-[-0.01em]">
            Enter the preview password
          </h3>
          <form
            className="flex flex-col gap-3"
            action={`${BASE_PATH}${GATE_PATH}/submit`}
            method="post"
          >
            <input type="hidden" name="next" value={next} />
            <label htmlFor="password" className="sr-only border-(--ink)">
              Preview password
            </label>
            <input
              className="w-full rounded-[10px]! border! border-(--line)! bg-[#0c1626]! px-3.5! py-3! font-(family-name:--sans)! text-[0.9rem]! text-(--ink)! outline-none focus:border-(--blue)!"
              id="password"
              name="password"
              type="password"
              autoComplete="current-password"
              required
              placeholder="Preview password"
            />
            <button
              className="inline-flex cursor-pointer items-center gap-2 whitespace-nowrap rounded-full rounded-[999px]! border border-transparent px-[26px] py-[15px] text-[15.5px] font-bold transition-[transform,box-shadow,background] focus-visible:outline-2 focus-visible:outline-offset-[3px] focus-visible:outline-(--cyan) text-white bg-(image:--grad) shadow-[0_14px_38px_-12px_rgba(79,143,247,0.75)] hover:-translate-y-px hover:shadow-[0_18px_44px_-12px_rgba(79,143,247,0.85)]"
              type="submit"
            >
              Enter
            </button>
          </form>
          {hasError ? (
            <p className="mx-0 mb-0 mt-1 text-[0.82rem] text-[#fb7185]">
              Incorrect password. Try again.
            </p>
          ) : null}
        </div>
      </div>
    </div>
  );
}
