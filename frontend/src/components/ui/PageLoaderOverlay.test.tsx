import React from "react";
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import PageLoaderOverlay from "@/components/ui/PageLoaderOverlay";

describe("PageLoaderOverlay", () => {
  it("renders child content without the overlay when idle", () => {
    render(
      <PageLoaderOverlay loading={false} label="Loading intelligence">
        <div>Visible content</div>
      </PageLoaderOverlay>
    );

    expect(screen.getByText("Visible content")).toBeInTheDocument();
    // No loader is rendered when idle.
    expect(screen.queryByText("Loading intelligence")).not.toBeInTheDocument();
  });

  it("shows the signal loader and marks the region busy while loading", () => {
    render(
      <PageLoaderOverlay
        loading
        label="Loading intelligence"
        detail="Pulling the latest project audit."
      >
        <div>Visible content</div>
      </PageLoaderOverlay>
    );

    expect(screen.getByText("Visible content")).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("Loading intelligence");
    expect(screen.getByText("Pulling the latest project audit.")).toBeInTheDocument();
    expect(screen.getByText("Visible content").parentElement).toHaveClass("blur-[5px]");
    expect(screen.getByText("Visible content").parentElement?.parentElement).toHaveAttribute(
      "aria-busy",
      "true"
    );
  });
});
