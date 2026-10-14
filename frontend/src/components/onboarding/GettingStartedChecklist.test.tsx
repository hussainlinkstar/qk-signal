import React from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import GettingStartedChecklist from "@/components/onboarding/GettingStartedChecklist";

const items = [
  { id: "email", title: "Verify email", description: "Verify it", completed: true },
  { id: "project", title: "Create project", description: "Create it", completed: true },
  {
    id: "audit",
    title: "Run first audit",
    description: "Run it",
    completed: false,
    href: "/dashboard/audit",
  },
  {
    id: "report",
    title: "Review report",
    description: "Review it",
    completed: false,
    href: "/dashboard/reports",
  },
  {
    id: "invite",
    title: "Invite member",
    description: "Invite one",
    completed: false,
    optional: true,
    href: "/dashboard/settings",
  },
];

describe("GettingStartedChecklist compact returning-workspace state", () => {
  it("shows progress and only the next required action", () => {
    render(<GettingStartedChecklist items={items} onDismiss={vi.fn()} />);

    expect(
      screen.getByRole("progressbar", { name: "2 of 4 required steps completed" })
    ).toBeInTheDocument();
    expect(screen.getByText("Run first audit")).toBeInTheDocument();
    expect(screen.queryByText("Verify email")).not.toBeInTheDocument();
    expect(screen.queryByText("Create project")).not.toBeInTheDocument();
    expect(screen.queryByText("Review report")).not.toBeInTheDocument();
    expect(screen.queryByText("Invite member")).not.toBeInTheDocument();
  });

  it("retains the dismiss action", () => {
    const onDismiss = vi.fn();
    render(<GettingStartedChecklist items={items} onDismiss={onDismiss} />);

    fireEvent.click(screen.getByRole("button", { name: "Dismiss" }));
    expect(onDismiss).toHaveBeenCalledOnce();
  });
});
