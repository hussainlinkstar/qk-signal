import React from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { AuthInlineNotice, AuthRecoveryCard } from "./AuthPrimitives";

vi.mock("react-i18next", () => ({ useTranslation: () => ({ t: (key: string) => key }) }));

describe("Authentication status alerts", () => {
  it.each([
    ["success", "success", "status"],
    ["progress", "info", "status"],
    ["warning", "warning", "alert"],
    ["error", "danger", "alert"],
  ] as const)("uses the shared %s alert", (variant, tone, role) => {
    render(<AuthInlineNotice variant={variant} title="Account status" description="Details" />);
    const alert = screen.getByRole(role);
    expect(alert).toHaveAttribute("data-signal-alert", tone);
    expect(alert).toHaveTextContent("Account status");
    expect(alert).toHaveTextContent("Details");
    expect(alert.querySelector("svg")).not.toBeNull();
  });

  it("preserves recovery actions inside the shared failure alert", () => {
    const retry = vi.fn();
    render(
      <AuthRecoveryCard
        title="Session expired"
        description="Sign in again."
        primaryAction={{ label: "Retry", onClick: retry }}
        secondaryAction={{ label: "Sign in", href: "/login" }}
      />
    );
    expect(screen.getByRole("alert")).toHaveAttribute("data-signal-alert", "danger");
    expect(screen.getByRole("heading", { name: "Session expired", level: 2 })).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(retry).toHaveBeenCalledOnce();
    expect(screen.getByRole("link", { name: "Sign in" })).toHaveAttribute("href", "/login");
  });
});
