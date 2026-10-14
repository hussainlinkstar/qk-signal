import React from "react";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import ThothChatWidget from "@/components/marketing/ThothChatWidget";

vi.mock("next/navigation", () => ({
  usePathname: () => "/dashboard/overview",
}));

vi.mock("sonner", () => ({
  toast: { error: vi.fn() },
}));

const DISABLED_LABEL = "Ask Qiko is coming soon";
const ENABLED_LABEL = "Open Ask Qiko support chat";

beforeEach(() => {
  Object.defineProperty(window, "innerWidth", {
    configurable: true,
    writable: true,
    value: 390,
  });
  window.dispatchEvent(new Event("resize"));
});

// Ask Qiko currently ships switched off, and nothing in the app mounts the
// widget, so these cases describe the component as rendered here: the launcher
// is present but disabled and the chat cannot be opened.
describe("ThothChatWidget while Ask Qiko is switched off", () => {
  it("keeps the launcher visible but disabled, and marks it SOON", () => {
    render(<ThothChatWidget />);

    const launcher = screen.getByRole("button", { name: DISABLED_LABEL });

    expect(launcher).toBeVisible();
    expect(launcher).toBeDisabled();
    expect(within(launcher).getByText("Ask Qiko")).toBeInTheDocument();
    expect(within(launcher).getByText("SOON")).toBeInTheDocument();
    expect(launcher).toHaveAttribute("title", DISABLED_LABEL);
    expect(launcher).not.toHaveAttribute("aria-expanded");
    expect(launcher).not.toHaveAttribute("aria-controls");
  });

  it("keeps the SOON badge readable even though the launcher is dimmed", () => {
    // A parent `opacity` creates a stacking context, so nothing inside can be
    // more opaque than it. The launcher used to carry `opacity-70`, which
    // multiplied with the badge's own `text-white/75` down to an effective 0.45
    // and dropped the 9px SOON text to a 4.4 contrast ratio, under WCAG AA.
    // The badge is the only thing telling the user why the button is dead, so
    // it must not be dimmed: the icon and label carry the muted look instead.
    render(<ThothChatWidget />);

    const launcher = screen.getByRole("button", { name: "Ask Qiko is coming soon" });
    expect(launcher.className).not.toMatch(/\bopacity-\d+/);

    const badge = screen.getByText("SOON");
    expect(badge.className).toContain("text-white");
    expect(badge.className).not.toMatch(/text-white\/\d+/);
    expect(badge.className).not.toMatch(/\bopacity-\d+/);
  });

  it("does not open the chat panel when clicked", () => {
    render(<ThothChatWidget />);

    fireEvent.click(screen.getByRole("button", { name: DISABLED_LABEL }));

    expect(screen.queryByPlaceholderText("Ask Qiko...")).not.toBeInTheDocument();
  });

  it("keeps the compact 48px square launcher geometry at narrow widths", () => {
    render(<ThothChatWidget />);

    const launcher = screen.getByRole("button", { name: DISABLED_LABEL });

    // Unchanged from the enabled launcher so the mobile space the dashboard
    // reserves for it still matches.
    expect(launcher).toHaveClass("h-12", "w-12", "p-0");
    expect(within(launcher).getByText("Ask Qiko").className.split(/\s+/)).toContain("hidden");
  });
});

// Panel behaviour is still covered so the chat can be switched back on safely.
describe("ThothChatWidget mobile launcher when enabled", () => {
  it("uses 44px close and minimize targets in the open panel", () => {
    render(<ThothChatWidget enabled />);
    fireEvent.click(screen.getByRole("button", { name: ENABLED_LABEL }));

    expect(screen.getByRole("button", { name: "Minimize Ask Qiko chat" })).toHaveClass(
      "min-h-11",
      "min-w-11"
    );
    expect(screen.getByRole("button", { name: "Close Ask Qiko chat" })).toHaveClass(
      "min-h-11",
      "min-w-11"
    );
  });

  it("uses dynamic viewport height and safe-area offsets for the open panel", () => {
    render(<ThothChatWidget enabled />);
    const launcher = screen.getByRole("button", { name: ENABLED_LABEL });
    fireEvent.click(launcher);

    const panel = screen.getByPlaceholderText("Ask Qiko...").closest("section");
    const widget = launcher.closest("div.fixed");

    expect(panel).toHaveClass("h-[min(72dvh,560px)]");
    expect(widget).toHaveClass(
      "bottom-[max(1.25rem,env(safe-area-inset-bottom))]",
      "right-[max(1.25rem,env(safe-area-inset-right))]"
    );
  });

  it("reports the controlled panel through aria-expanded and aria-controls", () => {
    render(<ThothChatWidget enabled />);

    const launcher = screen.getByRole("button", { name: ENABLED_LABEL });
    const panelId = launcher.getAttribute("aria-controls");

    expect(panelId).toBeTruthy();
    expect(launcher).toHaveAttribute("aria-expanded", "false");
    expect(document.getElementById(panelId as string)).not.toBeInTheDocument();

    fireEvent.click(launcher);

    expect(launcher).toHaveAttribute("aria-expanded", "true");
    expect(document.getElementById(panelId as string)).toBeInTheDocument();
  });

  it("closes on Escape and restores focus to the launcher", () => {
    render(<ThothChatWidget enabled />);

    const launcher = screen.getByRole("button", { name: ENABLED_LABEL });
    launcher.focus();
    fireEvent.click(launcher);

    const input = screen.getByPlaceholderText("Ask Qiko...");
    input.focus();
    fireEvent.keyDown(document, { key: "Escape" });

    expect(screen.queryByPlaceholderText("Ask Qiko...")).not.toBeInTheDocument();
    expect(launcher).toHaveFocus();
  });
});
