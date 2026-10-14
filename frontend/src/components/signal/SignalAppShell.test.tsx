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
    // signal.css `.nav a.on`: the active row is 32px, `#EBEDFB`/`#3730A3`, 600.
    expect(destination).toHaveClass(
      "h-8",
      "focus-visible:ring-2",
      "bg-[#EBEDFB]",
      "font-semibold",
      "text-[#3730A3]"
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
    // signal.css `.ws-link`: 13.5px semibold indigo text on a bottom rule,
    // not a nav row.
    expect(back).toHaveClass("text-[13.5px]", "font-semibold", "text-[#4F46E5]");
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
