import React from "react";
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import PasswordStrengthIndicator from "@/components/auth/PasswordStrengthIndicator";

describe("PasswordStrengthIndicator", () => {
  it("renders weak state when few requirements are met", () => {
    render(<PasswordStrengthIndicator password="abc" />);

    expect(screen.getByText("Weak")).toBeInTheDocument();
    expect(screen.getByText("1/5 requirements met")).toBeInTheDocument();
  });

  it("renders strong state when all requirements are met", () => {
    render(<PasswordStrengthIndicator password="ValidPass1!" />);

    expect(screen.getByText("Strong")).toBeInTheDocument();
    expect(screen.getByText("5/5 requirements met")).toBeInTheDocument();
  });
});
