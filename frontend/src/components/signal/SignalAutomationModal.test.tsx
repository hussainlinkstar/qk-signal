import React from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import SignalAutomationModal from "@/components/signal/SignalAutomationModal";

const renderModal = () =>
  render(
    <SignalAutomationModal
      open
      onClose={vi.fn()}
      projectId="project-1"
      editing={null}
      getAuthHeaders={vi.fn(async () => ({}))}
    />
  );

const expectPairedFields = (firstName: string, secondName: string, grid: Element) => {
  const first = screen.getByLabelText(firstName, { exact: true });
  const second = screen.getByLabelText(secondName, { exact: true });

  expect(first.closest("label")?.parentElement).toBe(grid);
  expect(second.closest("label")?.parentElement).toBe(grid);
  expect(first.closest("label")).not.toHaveClass("col-span-2");
  expect(second.closest("label")).not.toHaveClass("col-span-2");
};

describe("SignalAutomationModal responsive field grid", () => {
  it("uses one column by default and restores two columns above the mobile breakpoint", () => {
    renderModal();

    const name = screen.getByLabelText("Name", { exact: true });
    const grid = name.closest("div.grid");
    expect(grid).not.toBeNull();
    expect(grid).toHaveClass("grid-cols-1", "sm:grid-cols-2");
    expect(name.closest("label")).toHaveClass("sm:col-span-2");
    expect(name.closest("label")).not.toHaveClass("col-span-2");
  });

  it("keeps trigger and action field pairs one-column on mobile without losing desktop pairing", () => {
    renderModal();

    const name = screen.getByLabelText("Name", { exact: true });
    const grid = name.closest("div.grid");
    expect(grid).not.toBeNull();

    fireEvent.change(screen.getByLabelText("Trigger", { exact: true }), {
      target: { value: "metric_threshold" },
    });
    expectPairedFields("Metric", "Condition", grid!);

    expectPairedFields("Recipient email", "Template key", grid!);

    fireEvent.change(screen.getByLabelText("Then", { exact: true }), {
      target: { value: "webhook" },
    });
    expectPairedFields("Webhook URL", "Method", grid!);

    fireEvent.change(screen.getByLabelText("Then", { exact: true }), {
      target: { value: "run_audit" },
    });
    expectPairedFields("Assessment tier", "Category (optional)", grid!);

    fireEvent.change(screen.getByLabelText("Then", { exact: true }), {
      target: { value: "create_jira_ticket" },
    });
    expectPairedFields("Jira project key", "Issue type", grid!);
  });
});
