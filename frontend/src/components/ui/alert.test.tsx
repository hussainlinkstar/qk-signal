import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { Alert, AlertDescription, AlertTitle } from "./alert";

// shadcn Alert anatomy: cva variant on data-slot="alert", grid icon column
// that collapses without a child svg, AlertTitle/AlertDescription slots.
describe("ui/Alert (shadcn primitive)", () => {
  it("renders the canonical slots", () => {
    render(
      <Alert>
        <svg data-testid="icon" />
        <AlertTitle>Heads up</AlertTitle>
        <AlertDescription>
          <p>Body copy</p>
        </AlertDescription>
      </Alert>
    );

    expect(screen.getByRole("alert")).toHaveAttribute("data-slot", "alert");
    const title = screen.getByText("Heads up");
    expect(title).toHaveAttribute("data-slot", "alert-title");
    expect(title.className).toContain("col-start-2");
    expect(title.className).toContain("font-medium");
    const desc = screen.getByText("Body copy").closest("[data-slot='alert-description']");
    expect(desc).not.toBeNull();
    expect((desc as HTMLElement).className).toContain("col-start-2");
    expect((desc as HTMLElement).className).toContain("text-sm");
  });

  it("applies the shadcn grid anatomy", () => {
    render(<Alert />);
    const el = screen.getByRole("alert");
    expect(el.className).toContain("grid-cols-[0_1fr]");
    expect(el.className).toContain("has-[>svg]:grid-cols-[calc(var(--spacing)*4)_1fr]");
    expect(el.className).toContain("gap-x-3");
    expect(el.className).toContain("items-start");
    expect(el.className).toContain("[&>svg]:size-4");
  });

  it("exposes the approved variants", () => {
    for (const variant of ["default", "brand", "warning", "destructive", "success"] as const) {
      const { unmount } = render(<Alert variant={variant} data-testid={`a-${variant}`} />);
      const el = screen.getByTestId(`a-${variant}`);
      expect(el.className.length).toBeGreaterThan(0);
      if (variant === "brand") {
        expect(el.className).toContain("border-(--line)");
        expect(el.className).toContain("bg-(--panel)");
        expect(el.className).toContain("[&>svg]:text-(--brand)");
      }
      unmount();
    }
  });

  // SIGV2-1222: a status takes the animated gradient edge, a neutral panel
  // does not. `default` and `brand` are structural or promotional notices,
  // not a report that something happened, and spending a moving element on
  // one of those is how an alert treatment stops meaning anything.
  it("gives the three status variants the shared alert tone, and the other two none", () => {
    const statuses = { warning: "warning", destructive: "danger", success: "success" } as const;
    for (const [variant, tone] of Object.entries(statuses)) {
      const { unmount } = render(
        <Alert variant={variant as keyof typeof statuses} data-testid="a" />
      );
      expect(screen.getByTestId("a")).toHaveAttribute("data-signal-alert", tone);
      unmount();
    }
    for (const variant of ["default", "brand"] as const) {
      const { unmount } = render(<Alert variant={variant} data-testid="a" />);
      expect(screen.getByTestId("a")).not.toHaveAttribute("data-signal-alert");
      unmount();
    }
    const { unmount } = render(<Alert data-testid="a" />);
    expect(screen.getByTestId("a")).not.toHaveAttribute("data-signal-alert");
    unmount();
  });
});
