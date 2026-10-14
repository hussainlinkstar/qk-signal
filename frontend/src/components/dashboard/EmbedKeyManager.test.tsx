import React from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import EmbedKeyManager from "@/components/dashboard/EmbedKeyManager";

vi.mock("@/components/ui/GlassComponents", () => ({
  GlassCard: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
}));

vi.mock("@/components/ui/Button", () => ({
  default: ({
    children,
    loading: _loading,
    loadingText: _loadingText,
    ...props
  }: React.ButtonHTMLAttributes<HTMLButtonElement> & {
    loading?: boolean;
    loadingText?: string;
  }) => <button {...props}>{children}</button>,
}));

vi.mock("@/components/ui/TextField", () => ({
  default: ({
    label,
    ...props
  }: React.InputHTMLAttributes<HTMLInputElement> & { label: string }) => (
    <label>
      {label}
      <input {...props} />
    </label>
  ),
}));

describe("EmbedKeyManager", () => {
  it("starts with empty real values and uses examples only as placeholders", () => {
    render(
      <EmbedKeyManager
        items={[]}
        creating={false}
        revokingKeyId={null}
        latestRawKey={null}
        onCreate={vi.fn()}
        onRevoke={vi.fn()}
      />
    );

    expect(screen.getByLabelText("Key Label")).toHaveValue("");
    expect(screen.getByLabelText("Key Label")).toHaveAttribute("placeholder", "Homepage Widget");
    expect(screen.getByLabelText("Allowed Origins (comma separated)")).toHaveValue("");
    expect(screen.getByLabelText("Allowed Origins (comma separated)")).toHaveAttribute(
      "placeholder",
      "https://agency.com, https://www.agency.com"
    );
  });

  it("submits only user-entered origins and clears them after creation", async () => {
    const onCreate = vi.fn().mockResolvedValue(undefined);
    render(
      <EmbedKeyManager
        items={[]}
        creating={false}
        revokingKeyId={null}
        latestRawKey={null}
        onCreate={onCreate}
        onRevoke={vi.fn()}
      />
    );

    fireEvent.change(screen.getByLabelText("Key Label"), {
      target: { value: "Homepage lead form" },
    });
    fireEvent.change(screen.getByLabelText("Allowed Origins (comma separated)"), {
      target: { value: "https://client.example, https://www.client.example" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Create Embed Key" }));

    await waitFor(() =>
      expect(onCreate).toHaveBeenCalledWith({
        label: "Homepage lead form",
        allowed_origins: ["https://client.example", "https://www.client.example"],
        daily_limit: 100,
      })
    );
    expect(screen.getByLabelText("Key Label")).toHaveValue("");
    expect(screen.getByLabelText("Allowed Origins (comma separated)")).toHaveValue("");
  });
});
