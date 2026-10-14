import React from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import ColorPickerField from "@/components/ui/ColorPickerField";

describe("ColorPickerField", () => {
  it("renders the active value and supports preset clicks", () => {
    const onChange = vi.fn();

    render(
      <ColorPickerField
        label="Primary Accent"
        value="#FF4D2D"
        presets={["#FF4D2D", "#14B8A6"]}
        onChange={onChange}
      />
    );

    expect(screen.getByText("#FF4D2D")).toBeInTheDocument();
    expect(screen.getByText("Quick Palette")).toBeInTheDocument();
    expect(screen.getByText("Preset")).toBeInTheDocument();

    const presetButton = screen.getByRole("button", { name: "Primary Accent #14B8A6" });

    expect(presetButton).toHaveAttribute("aria-pressed", "false");

    fireEvent.click(presetButton);

    expect(onChange).toHaveBeenCalledWith("#14B8A6");
  });

  it("emits uppercase values from the native color input", () => {
    const onChange = vi.fn();

    render(
      <ColorPickerField
        label="Secondary Accent"
        value="#e2e8f0"
        presets={["#E2E8F0"]}
        onChange={onChange}
      />
    );

    fireEvent.change(screen.getByLabelText("Secondary Accent color picker"), {
      target: { value: "#123abc" },
    });

    expect(onChange).toHaveBeenCalledWith("#123ABC");
  });

  it("accepts direct hex entry and normalizes missing hash characters", () => {
    const onChange = vi.fn();

    render(
      <ColorPickerField
        label="Secondary Accent"
        value="#E2E8F0"
        presets={["#E2E8F0"]}
        onChange={onChange}
      />
    );

    fireEvent.change(screen.getByLabelText("Secondary Accent hex value"), {
      target: { value: "123abc" },
    });
    fireEvent.keyDown(screen.getByLabelText("Secondary Accent hex value"), {
      key: "Enter",
    });

    expect(onChange).toHaveBeenCalledWith("#123ABC");
  });
});
