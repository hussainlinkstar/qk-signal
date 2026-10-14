import React from "react";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import PasskeySetupPrompt from "./PasskeySetupPrompt";

const mocks = vi.hoisted(() => ({
  user: { id: "1" },
  getToken: vi.fn().mockResolvedValue("local-test-session"),
  listPasskeys: vi.fn(),
  registerPasskey: vi.fn(),
  success: vi.fn(),
  error: vi.fn(),
  consent: { hasAnswered: true, isSettingsOpen: false },
}));

vi.mock("@/contexts/AuthContext", () => ({ useAuth: () => mocks }));
vi.mock("@/contexts/CookieConsentContext", () => ({ useCookieConsent: () => mocks.consent }));
vi.mock("@/services/passkey.service", () => ({
  listPasskeys: mocks.listPasskeys,
  registerPasskey: mocks.registerPasskey,
}));
vi.mock("sonner", () => ({ toast: { success: mocks.success, error: mocks.error } }));
vi.mock("@/components/ui/Modal", () => ({
  default: ({
    open,
    title,
    panelClassName,
    children,
  }: {
    open: boolean;
    title?: string;
    panelClassName?: string;
    children: React.ReactNode;
  }) =>
    open ? (
      <div role="dialog" aria-label={title} className={panelClassName}>
        {children}
      </div>
    ) : null,
}));

beforeEach(() => {
  vi.clearAllMocks();
  mocks.consent.hasAnswered = true;
  mocks.consent.isSettingsOpen = false;
  mocks.listPasskeys.mockResolvedValue([]);
  mocks.registerPasskey.mockResolvedValue({ id: 1 });
});

describe("PasskeySetupPrompt", () => {
  it.each([
    { hasAnswered: false, isSettingsOpen: false },
    { hasAnswered: true, isSettingsOpen: true },
  ])("waits for the cookie interface before prompting: %j", async (consent) => {
    Object.assign(mocks.consent, consent);
    const { rerender } = render(<PasskeySetupPrompt />);
    await act(async () => {});
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(mocks.listPasskeys).not.toHaveBeenCalled();
    Object.assign(mocks.consent, { hasAnswered: true, isSettingsOpen: false });
    rerender(<PasskeySetupPrompt />);
    expect(await screen.findByRole("button", { name: "Set up passkey" })).toBeVisible();
  });

  it("uses the compact MVP panel and a visible gradient CTA", async () => {
    render(<PasskeySetupPrompt />);
    const dialog = await screen.findByRole("dialog", { name: "Set up a passkey" });
    expect(dialog).toHaveClass("w-[420px]", "p-0!");
    expect(screen.getByRole("button", { name: "Set up passkey" })).toHaveClass(
      "bg-(image:--auth-gradient)"
    );
  });

  it("keeps the dismissal cooldown and does not register on Maybe later", async () => {
    render(<PasskeySetupPrompt />);
    fireEvent.click(await screen.findByRole("button", { name: "Maybe later" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(localStorage.getItem("passkey_prompt_dismissed_at")).not.toBeNull();
    expect(mocks.registerPasskey).not.toHaveBeenCalled();
  });

  it("preserves the registration flow and success notice", async () => {
    render(<PasskeySetupPrompt />);
    fireEvent.click(await screen.findByRole("button", { name: "Set up passkey" }));
    await waitFor(() =>
      expect(mocks.registerPasskey).toHaveBeenCalledWith("local-test-session", "My Passkey")
    );
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(mocks.success).toHaveBeenCalledWith("Passkey registered successfully.");
  });

  it("does not prompt users who already have a passkey", async () => {
    mocks.listPasskeys.mockResolvedValue([{ id: 1 }]);
    render(<PasskeySetupPrompt />);
    await waitFor(() => expect(mocks.listPasskeys).toHaveBeenCalled());
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });
});
