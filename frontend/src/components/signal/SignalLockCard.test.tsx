import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import SignalLockCard from "./SignalLockCard";

// signal-MVP `.lockcard` contract (see signal-mvp-xsell-upgrade-spec §2):
// 380px centred card, radius 16, padding 22px 24px, the 0 24px 60px -24px
// shadow, mono purple eyebrow, Satoshi 18/800 title, 13px/1.5 body and a
// full-width primary CTA. The CTA links to the real billing surface - no
// client-side unlock control may exist.
describe("SignalLockCard", () => {
  it("renders the approved lockcard structure", () => {
    const { container } = render(
      <SignalLockCard
        eyebrow="SPECIALIST PLAN"
        title="Unlock your action plan"
        body="Upgrade to unlock."
        ctaLabel="Upgrade"
        ctaHref="/dashboard/billing"
      />
    );

    const card = container.firstElementChild as HTMLElement;
    expect(card.className).toContain("max-w-[380px]");
    expect(card.className).toContain("rounded-2xl");
    expect(card.className).toContain("px-6");
    expect(card.className).toContain("py-[22px]");
    expect(card.className).toContain("text-center");
    expect(card.className).toContain("shadow-[0_24px_60px_-24px_rgba(12,15,22,0.4)]");

    const eyebrow = screen.getByText("SPECIALIST PLAN");
    expect(eyebrow.className).toContain("font-(family-name:--mono)");
    expect(eyebrow.className).toContain("text-[10.5px]");
    expect(eyebrow.className).toContain("uppercase");
    expect(eyebrow.className).toContain("tracking-[0.14em]");
    expect(eyebrow.className).toContain("text-(--purple)");

    const title = screen.getByRole("heading", { name: "Unlock your action plan" });
    expect(title.className).toContain("font-(family-name:--disp)");
    expect(title.className).toContain("text-[18px]");
    expect(title.className).toContain("font-extrabold");
    expect(title.className).toContain("tracking-[-0.02em]");

    const body = screen.getByText("Upgrade to unlock.");
    expect(body.className).toContain("text-[13px]");
    expect(body.className).toContain("leading-[1.5]");
    expect(body.className).toContain("mb-4");
  });

  it("points the full-width CTA at a real route, never a client-side unlock", () => {
    render(
      <SignalLockCard
        eyebrow="SPECIALIST PLAN"
        title="Unlock your action plan"
        body="Upgrade to unlock."
        ctaLabel="Upgrade"
        ctaHref="/dashboard/billing?section=plans"
      />
    );

    const cta = screen.getByRole("link", { name: "Upgrade" });
    expect(cta).toHaveAttribute("href", "/dashboard/billing?section=plans");
    expect(cta.className).toContain("w-full");
    expect(cta.className).toContain("bg-(--ink)");
    expect(cta.className).toContain("max-md:min-h-11");
    // The mock's "Preview (demo)" button removes the locked class client-side;
    // no such control exists here.
    expect(screen.queryByRole("button")).toBeNull();
  });
});
