import React, { useState } from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import SignalTabs, { SignalTabPanel } from "@/components/signal/SignalTabs";

const tabs = [
  { id: "overview", label: "Overview" },
  { id: "visibility", label: "Visibility", count: 4 },
  { id: "recommendations", label: "Recommendations" },
];

function TabsHarness() {
  const [activeId, setActiveId] = useState("overview");

  return (
    <>
      <SignalTabs tabs={tabs} activeId={activeId} onChange={setActiveId} />
      {tabs.map((tab) => (
        <SignalTabPanel key={tab.id} id={tab.id} activeId={activeId}>
          {tab.label} panel
        </SignalTabPanel>
      ))}
    </>
  );
}

describe("SignalTabs accessibility", () => {
  let scrollIntoView: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    scrollIntoView = vi.fn();
    Object.defineProperty(HTMLElement.prototype, "scrollIntoView", {
      configurable: true,
      value: scrollIntoView,
    });
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("uses a soft pill tab row with a white active pill on the lilac well", () => {
    render(<TabsHarness />);
    expect(screen.getByRole("tablist")).toHaveClass("rounded-[16px]", "bg-(--well,#EEF1F6)");
    expect(screen.getByRole("tab", { name: "Overview" })).toHaveClass(
      "rounded-full",
      "bg-white",
      "text-(--purple-deep,var(--purple))"
    );
  });

  it("links each selected tab to its labelled tabpanel", () => {
    render(<TabsHarness />);

    const tablist = screen.getByRole("tablist");
    const selectedTab = screen.getByRole("tab", { name: "Overview" });
    const panel = screen.getByRole("tabpanel", { name: "Overview" });

    expect(tablist).toContainElement(selectedTab);
    expect(selectedTab.id).not.toBe("");
    expect(panel.id).not.toBe("");
    expect(selectedTab).toHaveAttribute("aria-controls", panel.id);
    expect(panel).toHaveAttribute("aria-labelledby", selectedTab.id);
  });

  it("keeps the tab row in a local horizontal scroller", () => {
    render(<TabsHarness />);

    const tablist = screen.getByRole("tablist");
    expect(tablist).toHaveClass("overflow-x-auto");
    screen.getAllByRole("tab").forEach((tab) => expect(tab).toHaveClass("shrink-0"));
  });

  it("updates IDs and ARIA relationships after selecting a second tab", () => {
    render(<TabsHarness />);

    const firstTab = screen.getByRole("tab", { name: "Overview" });
    const firstTabId = firstTab.id;
    fireEvent.click(screen.getByRole("tab", { name: /Visibility/ }));

    const selectedTab = screen.getByRole("tab", { name: /Visibility/ });
    const selectedPanel = screen.getByRole("tabpanel", { name: /Visibility/ });

    expect(selectedTab.id).not.toBe("");
    expect(selectedTab.id).not.toBe(firstTabId);
    expect(selectedPanel.id).not.toBe("");
    expect(selectedTab).toHaveAttribute("aria-selected", "true");
    expect(selectedTab).toHaveAttribute("aria-controls", selectedPanel.id);
    expect(selectedPanel).toHaveAttribute("aria-labelledby", selectedTab.id);
    expect(screen.queryByRole("tabpanel", { name: "Overview" })).not.toBeInTheDocument();
  });

  it("uses roving tabindex so only the selected tab is tabbable", () => {
    render(<TabsHarness />);

    expect(screen.getByRole("tab", { name: "Overview" })).toHaveAttribute("tabindex", "0");
    expect(screen.getByRole("tab", { name: /Visibility/ })).toHaveAttribute("tabindex", "-1");
    expect(screen.getByRole("tab", { name: "Recommendations" })).toHaveAttribute("tabindex", "-1");
  });

  it("wraps focus and selection with ArrowLeft and ArrowRight", () => {
    render(<TabsHarness />);

    const overview = screen.getByRole("tab", { name: "Overview" });
    const recommendations = screen.getByRole("tab", { name: "Recommendations" });

    overview.focus();
    fireEvent.keyDown(overview, { key: "ArrowLeft" });

    expect(recommendations).toHaveFocus();
    expect(recommendations).toHaveAttribute("aria-selected", "true");
    expect(recommendations).toHaveAttribute("tabindex", "0");
    expect(overview).toHaveAttribute("tabindex", "-1");

    fireEvent.keyDown(recommendations, { key: "ArrowRight" });

    expect(overview).toHaveFocus();
    expect(overview).toHaveAttribute("aria-selected", "true");
  });

  it("follows the visual arrow direction in RTL", () => {
    render(
      <div dir="rtl">
        <TabsHarness />
      </div>
    );
    const overview = screen.getByRole("tab", { name: "Overview" });
    overview.focus();
    fireEvent.keyDown(overview, { key: "ArrowLeft" });
    expect(screen.getByRole("tab", { name: /Visibility/ })).toHaveFocus();
    fireEvent.keyDown(screen.getByRole("tab", { name: /Visibility/ }), { key: "ArrowRight" });
    expect(overview).toHaveFocus();
  });

  it("moves focus and selection to the first and last tabs with Home and End", () => {
    render(<TabsHarness />);

    const overview = screen.getByRole("tab", { name: "Overview" });
    const visibility = screen.getByRole("tab", { name: /Visibility/ });
    const recommendations = screen.getByRole("tab", { name: "Recommendations" });

    visibility.focus();
    fireEvent.keyDown(visibility, { key: "End" });
    expect(recommendations).toHaveFocus();
    expect(recommendations).toHaveAttribute("aria-selected", "true");

    fireEvent.keyDown(recommendations, { key: "Home" });
    expect(overview).toHaveFocus();
    expect(overview).toHaveAttribute("aria-selected", "true");
  });

  it("scrolls initial and programmatic selections into the local overflow view", () => {
    const onChange = vi.fn();
    const { rerender } = render(
      <SignalTabs tabs={tabs} activeId="recommendations" onChange={onChange} />
    );

    expect(scrollIntoView).toHaveBeenCalledWith(
      expect.objectContaining({ block: "nearest", inline: "nearest" })
    );
    scrollIntoView.mockClear();

    rerender(<SignalTabs tabs={tabs} activeId="visibility" onChange={onChange} />);

    expect(scrollIntoView).toHaveBeenCalledTimes(1);
  });

  it("scrolls a newly selected tab into the local overflow view", () => {
    render(<TabsHarness />);
    scrollIntoView.mockClear();

    fireEvent.click(screen.getByRole("tab", { name: /Visibility/ }));

    expect(scrollIntoView).toHaveBeenCalledTimes(1);
    expect(scrollIntoView).toHaveBeenCalledWith(
      expect.objectContaining({ block: "nearest", inline: "nearest" })
    );
  });
});

const soonTabs = [
  { id: "overview", label: "Overview" },
  { id: "keywords", label: "Keywords", soon: true },
  { id: "pages", label: "Pages", soon: true },
  { id: "factors", label: "Ranking factors" },
];

function SoonTabsHarness({ onChange }: { onChange?: (id: string) => void }) {
  const [activeId, setActiveId] = useState("overview");

  return (
    <>
      <SignalTabs
        tabs={soonTabs}
        activeId={activeId}
        onChange={(id) => {
          onChange?.(id);
          setActiveId(id);
        }}
      />
      {soonTabs.map((tab) => (
        <SignalTabPanel key={tab.id} id={tab.id} activeId={activeId}>
          {tab.label} panel
        </SignalTabPanel>
      ))}
    </>
  );
}

describe("SignalTabs SOON tabs", () => {
  beforeEach(() => {
    Object.defineProperty(HTMLElement.prototype, "scrollIntoView", {
      configurable: true,
      value: vi.fn(),
    });
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("badges an unbuilt tab with SOON without disabling it", () => {
    render(<SoonTabsHarness />);

    const keywords = screen.getByRole("tab", { name: /Keywords/ });

    expect(keywords).toHaveTextContent("SOON");
    // The badge warns before the click; it must not take the tab away. The
    // panel behind it carries the blurred, inert treatment, and a disabled tab
    // would stop the user ever reading that message.
    expect(keywords).toBeEnabled();
    expect(keywords).not.toHaveAttribute("aria-disabled");
  });

  it("is selectable by click and opens its panel", () => {
    const onChange = vi.fn();
    render(<SoonTabsHarness onChange={onChange} />);

    fireEvent.click(screen.getByRole("tab", { name: /Keywords/ }));

    expect(onChange).toHaveBeenCalledWith("keywords");
    const keywords = screen.getByRole("tab", { name: /Keywords/ });
    const panel = screen.getByRole("tabpanel", { name: /Keywords/ });

    expect(keywords).toHaveAttribute("aria-selected", "true");
    expect(keywords).toHaveAttribute("tabindex", "0");
    expect(keywords).toHaveAttribute("aria-controls", panel.id);
    expect(panel).toHaveTextContent("Keywords panel");
    expect(screen.getByRole("tab", { name: "Overview" })).toHaveAttribute("aria-selected", "false");
  });

  it("is reachable by arrow keys like any other tab", () => {
    render(<SoonTabsHarness />);

    const overview = screen.getByRole("tab", { name: "Overview" });
    const keywords = screen.getByRole("tab", { name: /Keywords/ });
    const pages = screen.getByRole("tab", { name: /Pages/ });

    overview.focus();
    fireEvent.keyDown(overview, { key: "ArrowRight" });

    // The SOON tab is the next one along, so that is where focus lands: no
    // skipping, no stranded keyboard user.
    expect(keywords).toHaveFocus();
    expect(keywords).toHaveAttribute("aria-selected", "true");

    fireEvent.keyDown(keywords, { key: "ArrowRight" });
    expect(pages).toHaveFocus();
    expect(pages).toHaveAttribute("aria-selected", "true");

    fireEvent.keyDown(pages, { key: "ArrowLeft" });
    expect(keywords).toHaveFocus();
    expect(keywords).toHaveAttribute("aria-selected", "true");
  });

  it("lets Home and End land on a SOON tab when it is first or last", () => {
    const homeAndEndSoon = [
      { id: "keywords", label: "Keywords", soon: true },
      { id: "overview", label: "Overview" },
      { id: "pages", label: "Pages", soon: true },
    ];
    const onChange = vi.fn();
    render(<SignalTabs tabs={homeAndEndSoon} activeId="overview" onChange={onChange} />);

    fireEvent.keyDown(screen.getByRole("tab", { name: "Overview" }), { key: "End" });
    expect(onChange).toHaveBeenLastCalledWith("pages");

    fireEvent.keyDown(screen.getByRole("tab", { name: "Overview" }), { key: "Home" });
    expect(onChange).toHaveBeenLastCalledWith("keywords");
  });

  it("keeps SOON out of the plan-upsell vocabulary", () => {
    render(<SoonTabsHarness />);

    const keywords = screen.getByRole("tab", { name: /Keywords/ });
    expect(keywords.textContent).not.toMatch(/upgrade|unlock|plan/i);
  });
});
