import React from "react";
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import Button, { buttonClasses } from "@/components/ui/Button";
import Card from "@/components/ui/Card";
import { GlassCard } from "@/components/ui/GlassComponents";
import { RADIUS_CARD_CLASS } from "@/components/ui/radiusTokens";
import SelectField from "@/components/ui/SelectField";
import TextAreaField from "@/components/ui/TextAreaField";
import TextField from "@/components/ui/TextField";

describe("shared UI foundation primitives", () => {
  it("uses the MVP field dimensions while retaining sentence-case auth labels", () => {
    render(
      <>
        <TextField variant="auth" label="Email" error="Enter a valid email." />
        <TextField label="Project" />
        <Button variant="auth" loading loadingText="Signing in...">
          Sign in
        </Button>
      </>
    );

    expect(screen.getByLabelText("Email")).toHaveClass("h-11", "rounded-(--r-md)");
    expect(screen.getByLabelText("Email")).toHaveAttribute("aria-invalid", "true");
    expect(screen.getByText("Email")).toHaveClass("text-[13px]", "tracking-normal");
    expect(screen.getByText("Email")).not.toHaveClass("uppercase");
    expect(screen.getByLabelText("Project")).toHaveClass("h-11", "px-[13px]");
    expect(screen.getByRole("button", { name: "Signing in..." })).toBeDisabled();
    expect(buttonClasses({ variant: "auth" })).toContain("bg-(image:--auth-gradient)");
    expect(buttonClasses({ variant: "auth" })).toContain(
      "bg-[color:var(--auth-primary,var(--blue))]"
    );
    expect(buttonClasses({ variant: "auth" })).toContain("rounded-full");
  });

  it("matches the MVP button size scale and merges caller overrides", () => {
    expect(buttonClasses({ size: "sm" })).toContain("h-[30px]");
    expect(buttonClasses({ size: "md" })).toContain("h-[38px]");
    expect(buttonClasses({ size: "lg" })).toContain("h-11");
    const overridden = buttonClasses({ size: "md", className: "h-12 px-2" });
    expect(overridden).toContain("h-12");
    expect(overridden).not.toContain("h-[38px]");
    expect(overridden).not.toContain("px-[15px]");
  });

  it("keeps the approved button variants on the shared contract", () => {
    expect(buttonClasses({ variant: "outline" })).toContain("bg-(--surface-subtle)");
    expect(buttonClasses({ variant: "primary" })).toContain("bg-primary");
    expect(buttonClasses({ variant: "ghost" })).toContain("bg-(--surface-subtle)");

    render(
      <>
        <Button variant="outline">Outline</Button>
        <Button variant="primary">Primary</Button>
        <Button variant="ghost">Ghost</Button>
      </>
    );

    expect(screen.getByRole("button", { name: "Outline" }).className).toContain(
      "bg-(--surface-subtle)"
    );
    expect(screen.getByRole("button", { name: "Primary" }).className).toContain("bg-primary");
    expect(screen.getByRole("button", { name: "Ghost" }).className).toContain(
      "bg-(--surface-subtle)"
    );
  });

  it("keeps Card glass surfaces and GlassCard on the same shared contract", () => {
    const { getByTestId } = render(
      <>
        <Card data-testid="card-glass" variant="glass">
          Card
        </Card>
        <GlassCard data-testid="glass-card">Glass</GlassCard>
      </>
    );

    expect(getByTestId("card-glass").className).toContain("glass-surface");
    expect(getByTestId("glass-card").className).toContain("glass-surface");

    // Assert the shared token rather than a literal. This used to hardcode
    // rounded-(--r-md) and broke when the card radius token moved to
    // --r-lg, which is a token change and not a broken contract. Comparing both
    // against RADIUS_CARD_CLASS is what "the same shared contract" means.
    expect(getByTestId("glass-card").className).toContain(RADIUS_CARD_CLASS);
    expect(getByTestId("card-glass").className).toContain(RADIUS_CARD_CLASS);
  });

  it("renders shared label, helper, error, disabled, and read-only states across fields", () => {
    render(
      <div>
        <TextField id="project-name" label="Project name" helperText="Used in exports." />
        <SelectField id="market" label="Market" error="Select a market.">
          <option>Romania</option>
        </SelectField>
        <TextField id="source" label="Source" disabled value="GSC" readOnly={false} />
        <TextAreaField id="brief" label="Brief" defaultValue="Entity summary" readOnly />
      </div>
    );

    expect(screen.getByLabelText("Project name")).toHaveAttribute(
      "aria-describedby",
      "project-name-message"
    );
    expect(screen.getByText("Used in exports.")).toBeInTheDocument();

    expect(screen.getByLabelText("Market")).toHaveAttribute("aria-invalid", "true");
    expect(screen.getByText("Select a market.")).toBeInTheDocument();

    expect(screen.getByLabelText("Source")).toBeDisabled();
    expect(screen.getByLabelText("Brief")).toHaveAttribute("readonly");
  });
});
