import React from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import SignalAppShell from "@/components/signal/SignalAppShell";

const renderShell = (shellClassName?: string) =>
  render(
    <SignalAppShell
      brandHref="/dashboard"
      brandName="Qiko"
      sections={[]}
      shellClassName={shellClassName}
    >
      <main>Content</main>
    </SignalAppShell>
  );

describe("SignalAppShell dashboard geometry", () => {
  it("renders nav rows with the approved metrics and visible keyboard focus", () => {
    render(
      <SignalAppShell
        brandHref="/dashboard"
        brandName="Qiko"
        sections={[
          {
            label: "Your visibility",
            items: [
              {
                name: "Who gets recommended instead",
                href: "/dashboard/projects/42/competitors",
                icon: <span />,
                active: true,
              },
            ],
          },
        ]}
      >
        <main>Content</main>
      </SignalAppShell>
    );

    expect(screen.getByRole("navigation", { name: "Main navigation" })).toBeInTheDocument();
    const destination = screen.getByRole("link", { name: "Who gets recommended instead" });
    expect(destination).toHaveAttribute("aria-current", "page");
    expect(destination).toHaveClass(
      "h-11",
      "focus-visible:ring-2",
      "font-semibold",
      "bg-[#E8F1FF]",
      "text-[#1D4ED8]"
    );
    const brand = screen.getByRole("link", { name: "Qiko" });
    expect(brand).toHaveClass("focus-visible:ring-2");
    expect(brand.querySelector("img")?.getAttribute("src")).toContain("qiko-logo.png");
    expect(brand).toHaveTextContent("Signal");
    expect(screen.getByTestId("signal-app-shell")).toHaveClass("leading-[normal]");
  });

  it("renders the approved top link under the brand when provided", () => {
    render(
      <SignalAppShell
        brandHref="/dashboard"
        brandName="Qiko"
        topLink={{
          label: "Workspace overview",
          href: "/dashboard",
          icon: <span data-testid="top-link-icon" />,
        }}
        sections={[]}
      >
        <main>Content</main>
      </SignalAppShell>
    );

    const back = screen.getByRole("link", { name: "Workspace overview" });
    expect(back).toHaveAttribute("href", "/dashboard");
    expect(back).not.toHaveAttribute("aria-current");
    expect(back).toHaveClass("text-[13.5px]", "font-medium", "text-[#4B5563]");
  });

  it("announces SOON entries as unavailable, not merely grey", () => {
    render(
      <SignalAppShell
        brandHref="/dashboard"
        brandName="Qiko"
        sections={[
          {
            label: "Automation",
            items: [
              {
                name: "Tasks",
                href: "/dashboard/projects/1/tasks",
                icon: <span />,
                disabled: true,
                badge: "Soon",
              },
            ],
          },
        ]}
      >
        <main>Content</main>
      </SignalAppShell>
    );

    const soon = screen.getByTitle("Tasks");
    expect(soon).toHaveAttribute("aria-disabled", "true");
    // An entry that cannot be activated claims no role: it is not a link.
    expect(soon).not.toHaveAttribute("role");
    expect(soon).not.toHaveAttribute("href");
    expect(screen.getByText("Soon")).toBeInTheDocument();
  });

  it("renders action items like Sign out as buttons, never links", () => {
    const onSelect = vi.fn();
    render(
      <SignalAppShell
        brandHref="/dashboard"
        brandName="Qiko"
        sections={[
          {
            label: "Account",
            items: [{ name: "Sign out", icon: <span />, onSelect }],
          },
        ]}
      >
        <main>Content</main>
      </SignalAppShell>
    );

    const signOut = screen.getByRole("button", { name: "Sign out" });
    fireEvent.click(signOut);
    expect(onSelect).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole("link", { name: "Sign out" })).not.toBeInTheDocument();
  });

  it("accepts a dashboard-only centered shell cap", () => {
    renderShell("mx-auto max-w-[1560px]");

    expect(screen.getByTestId("signal-app-shell")).toHaveClass("mx-auto", "max-w-[1560px]");
  });

  it("does not cap consumers that omit the dashboard shell class", () => {
    renderShell();

    expect(screen.getByTestId("signal-app-shell")).not.toHaveClass("max-w-[1560px]");
  });
});
