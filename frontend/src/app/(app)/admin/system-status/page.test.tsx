import React from "react";
import { render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import AdminSystemStatusPage from "@/app/(app)/admin/system-status/page";

const authState = {
  getToken: vi.fn(async () => "token-123"),
};

const adminAccessState = {
  isAdmin: true,
  isLoading: false,
};

vi.mock("@/components/auth/custom-auth", () => ({
  useAuth: () => authState,
}));

vi.mock("@/components/admin/AdminGuardProvider", () => ({
  useAdminAccess: () => adminAccessState,
}));

const jsonResponse = (payload: unknown) =>
  new Response(JSON.stringify(payload), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });

class FakeEventSource {
  onmessage: ((event: MessageEvent<string>) => void) | null = null;
  onerror: (() => void) | null = null;

  constructor(_url: string) {}

  addEventListener(_type: string, _listener: EventListener) {
    return undefined;
  }

  close() {
    return undefined;
  }
}

const originalEventSource = globalThis.EventSource;

describe("AdminSystemStatusPage", () => {
  beforeEach(() => {
    globalThis.EventSource = FakeEventSource as unknown as typeof EventSource;
  });

  afterEach(() => {
    globalThis.EventSource = originalEventSource;
    vi.restoreAllMocks();
  });

  it("renders the system status dashboard for admin users", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      jsonResponse({
        services: {
          database: {
            name: "PostgreSQL Database",
            status: "Operational",
            details: "",
          },
          cache: {
            name: "Redis Cache",
            status: "Operational",
            details: "",
          },
          scraper: {
            name: "Firecrawl API",
            status: "Operational",
            details: "",
          },
          bing: {
            name: "Bing Search",
            status: "Operational",
            details: "",
          },
          perplexity: {
            name: "Perplexity API",
            status: "Operational",
            details: "",
          },
        },
        audit_metrics: {
          jobs_started: 2,
          jobs_succeeded: 2,
          jobs_failed: 0,
          job_attempts_total: 2,
          job_retries: 0,
          job_duration_seconds_total: 12.5,
        },
      })
    );

    render(<AdminSystemStatusPage />);

    expect(await screen.findByText("Service health")).toBeInTheDocument();
    expect(screen.getByText("PostgreSQL Database")).toBeInTheDocument();
    expect(screen.getByText("Redis Cache")).toBeInTheDocument();
    expect(screen.getByText("Bing Search")).toBeInTheDocument();
    expect(screen.getByText("Perplexity API")).toBeInTheDocument();
  });
});
