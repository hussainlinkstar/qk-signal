import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import ProjectPortalPage from "@/app/(portal)/portal/projects/[projectId]/page";

const serverFetchMock = vi.fn();
const notFoundMock = vi.fn(() => {
  throw new Error("NEXT_NOT_FOUND");
});

vi.mock("@/utils/server-fetch", () => ({
  serverFetch: (...args: unknown[]) => serverFetchMock(...args),
}));

vi.mock("next/navigation", () => ({
  notFound: () => notFoundMock(),
}));

vi.mock("@/components/portal/PortalAnnotationThread", () => ({
  default: () => null,
}));
vi.mock("@/components/portal/PortalTrendChart", () => ({
  default: () => null,
}));
vi.mock("@/components/portal/PortalProjectActions", () => ({
  default: () => null,
}));
vi.mock("@/components/portal/PortalApprovalButtons", () => ({
  PortalApprovalButtons: () => null,
}));

const response = (status: number, body: unknown = {}) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });

const pageProps = {
  params: Promise.resolve({ projectId: "42" }),
  searchParams: Promise.resolve({}),
};

describe("ProjectPortalPage", () => {
  beforeEach(() => {
    serverFetchMock.mockReset();
    notFoundMock.mockClear();
  });

  it("throws on a backend 5xx so the portal error boundary can render", async () => {
    serverFetchMock
      .mockResolvedValueOnce(response(503))
      .mockResolvedValueOnce(response(200, []))
      .mockResolvedValueOnce(response(200, {}));

    await expect(ProjectPortalPage(pageProps)).rejects.toThrow("Unable to load portal dashboard");
    expect(notFoundMock).not.toHaveBeenCalled();
  });

  it("shows no-audit placeholders instead of a ready status", async () => {
    serverFetchMock
      .mockResolvedValueOnce(
        response(200, {
          project: {
            id: 42,
            workspace_id: 1,
            name: "Example project",
            domain_url: "https://example.com",
            language: "en",
            latest_seo_score: null,
            latest_geo_score: null,
            latest_aeo_score: null,
            last_audit_at: null,
          },
          latest_audit: null,
          latest_report: null,
          trends: [],
          recommendations: [],
        })
      )
      .mockResolvedValueOnce(response(200, []))
      .mockResolvedValueOnce(response(200, {}));

    render(await ProjectPortalPage(pageProps));

    expect(screen.getByText("No audit")).toBeInTheDocument();
    expect(screen.getAllByText("N/A")).toHaveLength(3);
    expect(screen.queryByText("READY")).not.toBeInTheDocument();
  });
});
