import React from "react";
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi, beforeEach } from "vitest";

import ActiveAuditChip from "@/components/app/ActiveAuditChip";
import type { ActiveAuditJob } from "@/hooks/useActiveAudits";

/* ------------------------------------------------------------------ */
/*  Mocks                                                             */
/* ------------------------------------------------------------------ */

const useActiveAuditsMock = vi.fn<
  () => {
    activeJobs: ActiveAuditJob[];
    hasActiveAudits: boolean;
    isLoading: boolean;
    refetch: () => void;
  }
>();

vi.mock("@/hooks/useActiveAudits", () => ({
  useActiveAudits: (...args: unknown[]) => useActiveAuditsMock(...(args as [])),
}));

vi.mock("next/link", () => ({
  __esModule: true,
  default: ({
    href,
    children,
    ...rest
  }: {
    href: string;
    children: React.ReactNode;
    [key: string]: unknown;
  }) => React.createElement("a", { href, ...rest }, children),
}));

/* ------------------------------------------------------------------ */
/*  Helpers                                                           */
/* ------------------------------------------------------------------ */

function makeJob(overrides: Partial<ActiveAuditJob> = {}): ActiveAuditJob {
  return {
    job_id: "job-1",
    status: "running",
    audit_target_type: "website",
    target_name: "example.com",
    target_url: "https://example.com",
    tier: "basic",
    tier_display: "Fast Audit",
    started_at: "2024-01-01T00:00:00Z",
    last_heartbeat: "2024-01-01T00:01:00Z",
    stale: false,
    stale_reason: null,
    project_id: null,
    ...overrides,
  };
}

/* ------------------------------------------------------------------ */
/*  Tests                                                             */
/* ------------------------------------------------------------------ */

describe("ActiveAuditChip", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders nothing when there are no active jobs", () => {
    useActiveAuditsMock.mockReturnValue({
      activeJobs: [],
      hasActiveAudits: false,
      isLoading: false,
      refetch: vi.fn(),
    });

    const { container } = render(<ActiveAuditChip />);
    expect(container.innerHTML).toBe("");
  });

  it("renders a link to /dashboard/audit?reattach=<jobId>", () => {
    const job = makeJob({ job_id: "abc-123" });
    useActiveAuditsMock.mockReturnValue({
      activeJobs: [job],
      hasActiveAudits: true,
      isLoading: false,
      refetch: vi.fn(),
    });

    render(<ActiveAuditChip />);

    const link = screen.getByRole("link");
    expect(link).toHaveAttribute("href", "/dashboard/audit?reattach=abc-123");
  });

  it("shows Activity icon with animate-pulse class for non-stale jobs", () => {
    useActiveAuditsMock.mockReturnValue({
      activeJobs: [makeJob({ stale: false })],
      hasActiveAudits: true,
      isLoading: false,
      refetch: vi.fn(),
    });

    render(<ActiveAuditChip />);

    const link = screen.getByRole("link");
    // Activity icon renders as an <svg>; AlertTriangle should not be present
    const svg = link.querySelector("svg");
    expect(svg).toBeTruthy();
    expect(svg!.classList.contains("animate-pulse")).toBe(true);
  });

  it("shows AlertTriangle icon (no pulse) when any job is stale", () => {
    useActiveAuditsMock.mockReturnValue({
      activeJobs: [
        makeJob({ job_id: "j1", stale: false }),
        makeJob({ job_id: "j2", stale: true, stale_reason: "heartbeat timeout" }),
      ],
      hasActiveAudits: true,
      isLoading: false,
      refetch: vi.fn(),
    });

    render(<ActiveAuditChip />);

    const link = screen.getByRole("link");
    const svg = link.querySelector("svg");
    expect(svg).toBeTruthy();
    // AlertTriangle should NOT have animate-pulse
    expect(svg!.classList.contains("animate-pulse")).toBe(false);
  });

  it("shows short label for a single job with target_name", () => {
    useActiveAuditsMock.mockReturnValue({
      activeJobs: [makeJob({ target_name: "my-site.com" })],
      hasActiveAudits: true,
      isLoading: false,
      refetch: vi.fn(),
    });

    render(<ActiveAuditChip />);

    expect(screen.getByText("my-site.com")).toBeInTheDocument();
  });

  it("truncates label longer than 24 characters", () => {
    const longName = "a-very-long-target-name-exceeding-limit.com";
    useActiveAuditsMock.mockReturnValue({
      activeJobs: [makeJob({ target_name: longName })],
      hasActiveAudits: true,
      isLoading: false,
      refetch: vi.fn(),
    });

    render(<ActiveAuditChip />);

    const expected = `${longName.slice(0, 22)}...`;
    expect(screen.getByText(expected)).toBeInTheDocument();
  });

  it("falls back to target_url when target_name is null", () => {
    useActiveAuditsMock.mockReturnValue({
      activeJobs: [makeJob({ target_name: null, target_url: "https://fallback.io" })],
      hasActiveAudits: true,
      isLoading: false,
      refetch: vi.fn(),
    });

    render(<ActiveAuditChip />);

    expect(screen.getByText("https://fallback.io")).toBeInTheDocument();
  });

  it("falls back to tier_display when both target_name and target_url are null", () => {
    useActiveAuditsMock.mockReturnValue({
      activeJobs: [makeJob({ target_name: null, target_url: null })],
      hasActiveAudits: true,
      isLoading: false,
      refetch: vi.fn(),
    });

    render(<ActiveAuditChip />);

    expect(screen.getByText("Fast Audit")).toBeInTheDocument();
  });

  it("shows count text for multiple active jobs", () => {
    useActiveAuditsMock.mockReturnValue({
      activeJobs: [makeJob({ job_id: "j1" }), makeJob({ job_id: "j2" }), makeJob({ job_id: "j3" })],
      hasActiveAudits: true,
      isLoading: false,
      refetch: vi.fn(),
    });

    render(<ActiveAuditChip />);

    expect(screen.getByText("3 audits")).toBeInTheDocument();
    // Mobile span shows just the count number
    expect(screen.getByText("3")).toBeInTheDocument();
  });

  it("sets title attribute with job info for a single job", () => {
    const job = makeJob({
      target_name: "example.com",
      status: "running",
    });
    useActiveAuditsMock.mockReturnValue({
      activeJobs: [job],
      hasActiveAudits: true,
      isLoading: false,
      refetch: vi.fn(),
    });

    render(<ActiveAuditChip />);

    const link = screen.getByRole("link");
    expect(link).toHaveAttribute("title", "example.com, running");
  });

  it("sets title attribute with count for multiple jobs", () => {
    useActiveAuditsMock.mockReturnValue({
      activeJobs: [makeJob({ job_id: "j1" }), makeJob({ job_id: "j2" })],
      hasActiveAudits: true,
      isLoading: false,
      refetch: vi.fn(),
    });

    render(<ActiveAuditChip />);

    const link = screen.getByRole("link");
    expect(link).toHaveAttribute("title", "2 audits in progress");
  });

  it("links to the first job when there are multiple active jobs", () => {
    useActiveAuditsMock.mockReturnValue({
      activeJobs: [makeJob({ job_id: "first-job" }), makeJob({ job_id: "second-job" })],
      hasActiveAudits: true,
      isLoading: false,
      refetch: vi.fn(),
    });

    render(<ActiveAuditChip />);

    const link = screen.getByRole("link");
    expect(link).toHaveAttribute("href", "/dashboard/audit?reattach=first-job");
  });

  it("applies amber styling when any job is stale", () => {
    useActiveAuditsMock.mockReturnValue({
      activeJobs: [makeJob({ stale: true })],
      hasActiveAudits: true,
      isLoading: false,
      refetch: vi.fn(),
    });

    render(<ActiveAuditChip />);

    const link = screen.getByRole("link");
    expect(link.className).toContain("border-amber-500/30");
  });

  it("applies primary styling when no jobs are stale", () => {
    useActiveAuditsMock.mockReturnValue({
      activeJobs: [makeJob({ stale: false })],
      hasActiveAudits: true,
      isLoading: false,
      refetch: vi.fn(),
    });

    render(<ActiveAuditChip />);

    const link = screen.getByRole("link");
    expect(link.className).toContain("border-primary/25");
  });
});
