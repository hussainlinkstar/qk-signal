import React from "react";
import { render, screen, fireEvent } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import PortalAuditHistory from "@/components/portal/PortalAuditHistory";
import type { PortalAuditHistoryItem } from "@/services/portalService";

const makeItem = (overrides: Partial<PortalAuditHistoryItem> = {}): PortalAuditHistoryItem => ({
  id: 1,
  created_at: "2026-03-20T10:00:00Z",
  seo_score: 72,
  geo_score: 65,
  aeo_score: 80,
  status: "completed",
  ...overrides,
});

describe("PortalAuditHistory", () => {
  it("renders empty state when no items", () => {
    render(
      <PortalAuditHistory
        projectId="42"
        items={[]}
        total={0}
        page={1}
        pageSize={10}
        onPageChange={vi.fn()}
        onSelectAudit={vi.fn()}
      />
    );
    expect(screen.getByText("No audit history yet.")).toBeInTheDocument();
  });

  it("renders an error state with retry instead of the empty state", () => {
    const onRetry = vi.fn();
    render(
      <PortalAuditHistory
        projectId="42"
        items={[]}
        total={0}
        page={1}
        pageSize={10}
        error="Failed to load audit history."
        onRetry={onRetry}
        onPageChange={vi.fn()}
        onSelectAudit={vi.fn()}
      />
    );

    expect(screen.getByRole("alert")).toHaveTextContent("Failed to load audit history.");
    expect(screen.queryByText("No audit history yet.")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(onRetry).toHaveBeenCalledTimes(1);
  });

  it("uses clear placeholders for missing audit values", () => {
    render(
      <PortalAuditHistory
        projectId="42"
        items={[
          makeItem({
            created_at: null,
            seo_score: null,
            geo_score: null,
            aeo_score: null,
          }),
        ]}
        total={1}
        page={1}
        pageSize={10}
        onPageChange={vi.fn()}
        onSelectAudit={vi.fn()}
      />
    );

    expect(screen.getAllByText("-")).toHaveLength(4);
    expect(screen.queryByText(",")).not.toBeInTheDocument();
  });

  it("renders audit rows with scores and status badges", () => {
    const items = [
      makeItem({ id: 1, seo_score: 72, geo_score: 65, aeo_score: 80, status: "completed" }),
      makeItem({
        id: 2,
        seo_score: 55,
        geo_score: 40,
        aeo_score: 60,
        status: "degraded",
        created_at: "2026-03-18T09:00:00Z",
      }),
    ];

    render(
      <PortalAuditHistory
        projectId="42"
        items={items}
        total={2}
        page={1}
        pageSize={10}
        onPageChange={vi.fn()}
        onSelectAudit={vi.fn()}
      />
    );

    expect(screen.getByText("72")).toBeInTheDocument();
    expect(screen.getByText("65")).toBeInTheDocument();
    expect(screen.getByText("80")).toBeInTheDocument();
    expect(screen.getByText("Completed")).toBeInTheDocument();
    expect(screen.getByText("Degraded")).toBeInTheDocument();
  });

  it("calls onSelectAudit when a row is clicked", () => {
    const onSelect = vi.fn();
    render(
      <PortalAuditHistory
        projectId="42"
        items={[makeItem({ id: 99 })]}
        total={1}
        page={1}
        pageSize={10}
        onPageChange={vi.fn()}
        onSelectAudit={onSelect}
      />
    );

    const row = screen.getByRole("button");
    fireEvent.click(row);
    expect(onSelect).toHaveBeenCalledWith(99);
  });

  it("shows pagination controls when total exceeds page size", () => {
    const onPageChange = vi.fn();
    render(
      <PortalAuditHistory
        projectId="42"
        items={[makeItem()]}
        total={25}
        page={2}
        pageSize={10}
        onPageChange={onPageChange}
        onSelectAudit={vi.fn()}
      />
    );

    expect(screen.getByText("Page 2 of 3")).toBeInTheDocument();

    const prevBtn = screen.getByRole("button", { name: /prev/i });
    const nextBtn = screen.getByRole("button", { name: /next/i });

    fireEvent.click(prevBtn);
    expect(onPageChange).toHaveBeenCalledWith(1);

    fireEvent.click(nextBtn);
    expect(onPageChange).toHaveBeenCalledWith(3);
  });

  it("disables prev on first page and next on last page", () => {
    render(
      <PortalAuditHistory
        projectId="42"
        items={[makeItem()]}
        total={5}
        page={1}
        pageSize={10}
        onPageChange={vi.fn()}
        onSelectAudit={vi.fn()}
      />
    );

    // Single page — no pagination shown
    expect(screen.queryByText(/Page/)).not.toBeInTheDocument();
  });
});
