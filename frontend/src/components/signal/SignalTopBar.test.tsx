import React from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import "@/i18n";
import SignalTopBar from "./SignalTopBar";
import type { SignalNavSection } from "./SignalAppShell";

const pushMock = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: pushMock }),
}));

const sections: SignalNavSection[] = [
  {
    label: "Intelligence",
    items: [
      { name: "Dashboard", href: "/dashboard/projects/9", icon: null },
      { name: "Competitors", href: "/dashboard/projects/9/competitors", icon: null },
    ],
  },
];

function setup() {
  render(
    <SignalTopBar
      siteLabel="example.com"
      siteName="Example site"
      searchSections={sections}
      menu={<button>Open menu</button>}
    />
  );
}

describe("SignalTopBar", () => {
  it("shows the current website read-only; project switching lives in the sidebar", () => {
    setup();
    expect(screen.getByText("Example site")).toBeInTheDocument();
    expect(screen.getByText("example.com")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Open menu" })).toBeInTheDocument();
  });

  it("renders the approved inline .tsearch field with its ⌘K hint", () => {
    setup();
    expect(screen.getByRole("combobox")).toBeInTheDocument();
    expect(screen.getByText("⌘K")).toBeInTheDocument();
    // The panel stays closed until focus, like wireSearch.
    expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
  });

  it("keeps a single subtle focus treatment on the search wrapper", () => {
    setup();
    const input = screen.getByRole("combobox");
    fireEvent.focus(input);
    expect(input).toHaveClass("focus:ring-0", "focus:shadow-none");
    expect(input.parentElement?.className).toContain(
      "shadow-[0_0_0_2px_color-mix(in_srgb,var(--brand)_28%,transparent)]"
    );
    expect(input.parentElement?.className).not.toContain("shadow-[0_0_0_3px_var(--ring)]");
  });

  // The flex spacer these tests used to assert is gone. It approximated a
  // centred search by splitting the free space in two, which only centres the
  // field when the flanking content happens to balance. Measured across the
  // product it did not: nine distinct x positions at 1440. The bar is a
  // three-column grid now, so the field is centred on the bar itself.
  it.each([
    ["workspace", { siteLabel: "Workspace", workspaceDom: true }],
    ["project", { siteName: "northwind-hotels.com" }],
  ])("%s scope centres the search in its own grid column", (_scope, props) => {
    const { container } = render(<SignalTopBar {...props} searchSections={sections} />);
    const header = container.querySelector("header")!;
    // The centre track must be a definite size. With `auto` it sizes to its
    // content, and the field collapsed to its intrinsic 148px because the
    // percentage width had no definite size to resolve against.
    expect(header.className).toContain("md:grid-cols-[1fr_minmax(0,430px)_1fr]");
    // Below md the bar stays a flex row: a 430px centre track starves the side
    // columns at phone widths and squeezes out the lockup and language toggle.
    expect(header.className).toContain("flex");
    const column = screen.getByRole("combobox").closest('[role="search"]')!.parentElement!;
    expect(column.className).toContain("flex-1");
    expect(column.className).toContain("md:w-full");
    // Same three columns in both scopes, so the centre cannot shift per page.
    expect(header.children).toHaveLength(3);
    expect(header.children[1]).toBe(column);
  });

  it("keeps the centre column when a page opts out of the search", () => {
    const { container } = render(<SignalTopBar siteLabel="Workspace" workspaceDom hideSearch />);
    const header = container.querySelector("header")!;
    expect(header.children).toHaveLength(3);
    expect(screen.queryByRole("combobox")).not.toBeInTheDocument();
  });

  it("opens the inline listbox on focus and navigates on selection", async () => {
    setup();
    const input = screen.getByRole("combobox");
    fireEvent.focus(input);
    expect(await screen.findByRole("listbox")).toBeInTheDocument();
    expect(screen.getByText("Intelligence")).toBeInTheDocument();

    fireEvent.change(input, { target: { value: "comp" } });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(pushMock).toHaveBeenCalledWith("/dashboard/projects/9/competitors");
  });
});
