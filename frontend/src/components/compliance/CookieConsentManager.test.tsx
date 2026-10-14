import React from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";
import CookieConsentManager from "@/components/compliance/CookieConsentManager";
import { CookieConsentProvider, useCookieConsent } from "@/contexts/CookieConsentContext";
import "@/i18n";
import {
  COOKIE_CONSENT_STORAGE_KEY,
  createConsentRecord,
  persistConsentRecord,
} from "@/lib/cookieConsent";

const OpenSettingsButton = () => {
  const { openSettings } = useCookieConsent();
  return (
    <button type="button" onClick={openSettings}>
      open-settings
    </button>
  );
};

const renderConsentUi = () =>
  render(
    <CookieConsentProvider>
      <CookieConsentManager />
      <OpenSettingsButton />
    </CookieConsentProvider>
  );

describe("CookieConsentManager", () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  it("renders the banner for first-time visitors and stores consent after accept all", async () => {
    renderConsentUi();

    expect(
      await screen.findByText("We use cookies to improve your experience")
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Accept all" }));

    await waitFor(() => {
      expect(
        screen.queryByText("We use cookies to improve your experience")
      ).not.toBeInTheDocument();
    });

    const rawStored = window.localStorage.getItem(COOKIE_CONSENT_STORAGE_KEY);
    expect(rawStored).not.toBeNull();
    const stored = JSON.parse(rawStored ?? "{}") as {
      preferences: { analytics: boolean; marketing: boolean; preferences: boolean };
    };
    expect(stored.preferences.analytics).toBe(true);
    expect(stored.preferences.marketing).toBe(true);
    expect(stored.preferences.preferences).toBe(true);
  });

  it("uses the compact MVP preferences dialog with labelled switches", async () => {
    renderConsentUi();
    fireEvent.click(screen.getByRole("button", { name: "open-settings" }));
    const dialog = await screen.findByRole("dialog", { name: "Cookie preference settings" });
    expect(dialog).toHaveClass("w-[460px]");
    const switches = screen.getAllByRole("switch");
    expect(switches).toHaveLength(4);
    switches.forEach((control) => expect(control).toHaveAccessibleName());
    expect(switches[0]).toBeDisabled();
    expect(switches[0]).toHaveAttribute("aria-checked", "true");
    // Necessary is the only category on by default. Every optional one starts off:
    // a pre-ticked toggle for a non-essential category is not valid consent.
    expect(switches[1]).toHaveAttribute("aria-checked", "false");
    expect(switches[2]).toHaveAttribute("aria-checked", "false");
    expect(switches[3]).toHaveAttribute("aria-checked", "false");
  });

  it("saving the dialog untouched grants nothing optional", async () => {
    renderConsentUi();
    fireEvent.click(screen.getByRole("button", { name: "open-settings" }));
    await screen.findByRole("dialog", { name: "Cookie preference settings" });
    fireEvent.click(screen.getByRole("button", { name: "Save preferences" }));

    await waitFor(() => {
      expect(window.localStorage.getItem(COOKIE_CONSENT_STORAGE_KEY)).not.toBeNull();
    });
    const stored = JSON.parse(window.localStorage.getItem(COOKIE_CONSENT_STORAGE_KEY) ?? "{}") as {
      preferences: {
        necessary: boolean;
        analytics: boolean;
        marketing: boolean;
        preferences: boolean;
      };
    };
    expect(stored.preferences.analytics).toBe(false);
    expect(stored.preferences.marketing).toBe(false);
    expect(stored.preferences.preferences).toBe(false);
    expect(stored.preferences.necessary).toBe(true);
  });

  it("opens settings via context action even when consent already exists", async () => {
    persistConsentRecord(
      createConsentRecord("save-preferences", {
        preferences: true,
        analytics: false,
        marketing: false,
      })
    );

    renderConsentUi();

    fireEvent.click(screen.getByRole("button", { name: "open-settings" }));

    expect(
      await screen.findByRole("dialog", { name: "Cookie preference settings" })
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Close settings" }));

    await waitFor(() => {
      expect(
        screen.queryByRole("dialog", { name: "Cookie preference settings" })
      ).not.toBeInTheDocument();
    });
  });
});
