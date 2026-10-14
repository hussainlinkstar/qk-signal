import React from "react";
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import SignalAppFooter from "@/components/signal/SignalAppFooter";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

vi.mock("@/contexts/CookieConsentContext", () => ({
  useCookieConsent: () => ({ openSettings: vi.fn() }),
}));

describe("SignalAppFooter brand", () => {
  it("renders the approved footer Qiko wordmark at its natural ratio", () => {
    render(<SignalAppFooter />);

    const logo = screen.getByAltText("Qiko");
    expect(logo).toBeInTheDocument();
    expect(logo.getAttribute("src")).toContain("qiko-logo.png");
    expect(logo).toHaveClass("h-[18px]", "w-auto");
  });
});
