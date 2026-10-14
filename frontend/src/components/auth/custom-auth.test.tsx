import React from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { UserButton } from "@/components/auth/custom-auth";

const pushMock = vi.fn();
const logoutMock = vi.fn(async () => undefined);

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: pushMock }),
}));

vi.mock("@/contexts/AuthContext", () => ({
  useAuth: () => ({
    user: {
      id: "1",
      email: "user@example.com",
      name: "Jane Doe",
    },
    isLoading: false,
    isSignedIn: true,
    logout: logoutMock,
  }),
}));

describe("UserButton", () => {
  beforeEach(() => {
    pushMock.mockReset();
    logoutMock.mockClear();
  });

  it("renders clear navigation and sign-out labels in the account menu", async () => {
    render(<UserButton />);

    fireEvent.click(screen.getByRole("button"));

    expect(screen.getByText("Signed in as")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /dashboard/i })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /account settings/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /sign out/i })).toBeInTheDocument();
    expect(screen.queryByText("Control Center")).not.toBeInTheDocument();
    expect(screen.queryByText("Parameters")).not.toBeInTheDocument();
    expect(screen.queryByText("Terminate Link")).not.toBeInTheDocument();
  });
});
