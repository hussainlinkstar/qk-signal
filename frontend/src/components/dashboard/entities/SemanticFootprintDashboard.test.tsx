import React from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import SemanticFootprintDashboard from "@/components/dashboard/entities/SemanticFootprintDashboard";

const fetchSiteMapMock = vi.fn();
const fetchSemanticGapMock = vi.fn();
const fetchCompetitorMatrixMock = vi.fn();
const searchParamsState = new URLSearchParams();
const routerPush = vi.fn();
const getTokenMock = vi.fn(async () => "token-123");
let authHeadersEnabledState = false;

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: routerPush }),
  usePathname: () => "/dashboard/entities",
  useSearchParams: () => searchParamsState,
}));

vi.mock("@/components/auth/custom-auth", () => ({
  useAuth: () => ({ isSignedIn: true, getToken: getTokenMock }),
}));

vi.mock("@/contexts/AuthContext", () => ({
  useAuthHeadersEnabled: () => authHeadersEnabledState,
}));

vi.mock("@/services/competitorsService", async () => {
  const actual = await vi.importActual("@/services/competitorsService");
  return {
    ...actual,
    fetchCompetitorMatrix: (...args: unknown[]) => fetchCompetitorMatrixMock(...args),
  };
});

vi.mock("@/services/semanticFootprintService", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/services/semanticFootprintService")>();
  return {
    ...actual,
    fetchSiteMap: (...args: unknown[]) => fetchSiteMapMock(...args),
    fetchSemanticGap: (...args: unknown[]) => fetchSemanticGapMock(...args),
  };
});

describe("SemanticFootprintDashboard", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    routerPush.mockReset();
    authHeadersEnabledState = false;
    getTokenMock.mockResolvedValue("token-123");
    searchParamsState.delete("siteId");
    searchParamsState.delete("competitorSiteId");
    fetchCompetitorMatrixMock.mockResolvedValue([]);
  });

  it("renders loading then empty state", async () => {
    searchParamsState.set("siteId", "1");
    searchParamsState.set("competitorSiteId", "2");

    fetchSiteMapMock.mockResolvedValue({
      siteId: 1,
      auditCount: 0,
      lastSeenAt: null,
      entities: [],
    });
    fetchSemanticGapMock.mockResolvedValue({
      siteId: 1,
      generatedAt: "2026-01-01T00:00:00Z",
      categories: [],
      venn: [],
      heatmap: [],
      opportunities: [],
      knowledgeGraph: { nodes: [], edges: [] },
      brandAssociations: [],
    });

    render(<SemanticFootprintDashboard />);

    expect(screen.getByText("Loading semantic footprint dashboard...")).toBeInTheDocument();

    await waitFor(() => {
      expect(screen.getByText("No overlap data available.")).toBeInTheDocument();
    });
    expect(
      screen.getByText("No matching site map entities for the selected filters.")
    ).toBeInTheDocument();
    expect(fetchSiteMapMock).toHaveBeenCalledWith(1, { Authorization: "Bearer token-123" });
    expect(fetchSemanticGapMock).toHaveBeenCalledWith(1, 2, { Authorization: "Bearer token-123" });
    expect(fetchCompetitorMatrixMock).toHaveBeenCalledWith(1, {
      Authorization: "Bearer token-123",
    });
  });

  it("renders error state when service fails", async () => {
    searchParamsState.set("siteId", "1");
    searchParamsState.set("competitorSiteId", "2");
    fetchSiteMapMock.mockRejectedValue(new Error("boom"));
    fetchSemanticGapMock.mockResolvedValue({});

    render(<SemanticFootprintDashboard />);

    await waitFor(() => {
      expect(screen.getByText("boom")).toBeInTheDocument();
    });
  });

  it("renders guidance when site or competitor is missing", async () => {
    render(<SemanticFootprintDashboard />);

    await waitFor(() => {
      expect(
        screen.getByText("Select a site to load semantic footprint data.")
      ).toBeInTheDocument();
    });
    expect(screen.getByText("Select a site to load semantic footprint data.")).toHaveClass(
      "text-(--purple)"
    );
    expect(fetchSiteMapMock).not.toHaveBeenCalled();
    expect(fetchSemanticGapMock).not.toHaveBeenCalled();
    expect(fetchCompetitorMatrixMock).not.toHaveBeenCalled();
  });

  it("renders competitor guidance when site is selected without competitor", async () => {
    searchParamsState.set("siteId", "1");

    render(<SemanticFootprintDashboard />);

    await waitFor(() => {
      expect(
        screen.getByText("Select a competitor to compare semantic footprint gaps.")
      ).toBeInTheDocument();
    });
    expect(screen.getByText("Select a competitor to compare semantic footprint gaps.")).toHaveClass(
      "text-(--purple)"
    );
    expect(fetchSiteMapMock).not.toHaveBeenCalled();
    expect(fetchSemanticGapMock).not.toHaveBeenCalled();
    expect(fetchCompetitorMatrixMock).toHaveBeenCalledWith(1, {
      Authorization: "Bearer token-123",
    });
  });

  it("renders Entities competitor selector and updates query params", async () => {
    searchParamsState.set("siteId", "1");
    fetchCompetitorMatrixMock.mockResolvedValue([{ id: 7, name: "rival.test" }]);

    render(<SemanticFootprintDashboard />);

    const selector = await screen.findByLabelText("Compare with competitor");
    await waitFor(() => {
      expect(screen.getByRole("option", { name: "rival.test" })).toBeInTheDocument();
    });

    fireEvent.change(selector, { target: { value: "7" } });
    expect(routerPush).toHaveBeenCalledWith("/dashboard/entities?siteId=1&competitorSiteId=7");
  });

  it("passes auth headers to semantic footprint requests when token auth is enabled", async () => {
    authHeadersEnabledState = true;
    searchParamsState.set("siteId", "1");
    searchParamsState.set("competitorSiteId", "2");

    fetchSiteMapMock.mockResolvedValue({
      siteId: 1,
      auditCount: 0,
      lastSeenAt: null,
      entities: [],
    });
    fetchSemanticGapMock.mockResolvedValue({
      siteId: 1,
      generatedAt: "2026-01-01T00:00:00Z",
      categories: [],
      venn: [],
      heatmap: [],
      opportunities: [],
      knowledgeGraph: { nodes: [], edges: [] },
      brandAssociations: [],
    });

    render(<SemanticFootprintDashboard />);

    await waitFor(() => {
      expect(fetchSiteMapMock).toHaveBeenCalledWith(1, { Authorization: "Bearer token-123" });
    });
    expect(fetchSemanticGapMock).toHaveBeenCalledWith(1, 2, { Authorization: "Bearer token-123" });
  });
});
