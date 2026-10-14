import React from "react";
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import DeveloperDocsPage from "@/app/(app)/dashboard/developer/docs/page";

const pathnameState = {
  pathname: "/dashboard/developer/docs",
};

vi.mock("next/link", () => ({
  default: ({ children, href }: { children: React.ReactNode; href: string }) => (
    <a href={href}>{children}</a>
  ),
}));

vi.mock("next/navigation", () => ({
  usePathname: () => pathnameState.pathname,
}));

describe("DeveloperDocsPage", () => {
  it("renders the quick-start API documentation surface", async () => {
    render(<DeveloperDocsPage />);

    expect(await screen.findByRole("heading", { name: /developer docs/i })).toBeInTheDocument();
    expect(screen.getByText("Authentication Headers")).toBeInTheDocument();
    expect(screen.getByText("Create Audit Request")).toBeInTheDocument();
    expect(screen.getByText("Error Envelope")).toBeInTheDocument();
    expect(screen.getByText("Code Samples")).toBeInTheDocument();
    expect(screen.getByText("Webhook Verification")).toBeInTheDocument();
    expect(screen.getByText("Connect an MCP Client")).toBeInTheDocument();
    expect(screen.getByText("MCP Endpoint")).toBeInTheDocument();
    expect(screen.getByText("Claude Desktop")).toBeInTheDocument();
    expect(screen.getByText("ChatGPT")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Hub" })).toHaveAttribute(
      "href",
      "/dashboard/developer"
    );
    expect(screen.getByRole("link", { name: "Quick Start" })).toHaveAttribute(
      "href",
      "/dashboard/developer/docs"
    );
    expect(screen.getByRole("link", { name: "API Reference" })).toHaveAttribute(
      "href",
      "/api-reference"
    );
  });
});
