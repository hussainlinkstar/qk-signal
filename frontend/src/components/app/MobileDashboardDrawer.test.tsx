import React from "react";
import { createEvent, fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import MobileDashboardDrawer from "./MobileDashboardDrawer";
import Modal from "@/components/ui/Modal";

vi.mock("next/navigation", () => ({
  usePathname: () => "/dashboard",
  useSearchParams: () => new URLSearchParams(),
}));
vi.mock("@/components/app/SidebarWorkspaceMenu", () => ({
  default: () => <button>Account menu</button>,
}));

function openDrawer() {
  render(
    <MobileDashboardDrawer
      primarySections={[]}
      isProjectContext={false}
      isStaff={false}
      email="preview@example.com"
      onLogout={vi.fn()}
    />
  );
  const trigger = screen.getByRole("button", { name: "Open dashboard menu" });
  fireEvent.click(trigger);
  return trigger;
}

describe("MobileDashboardDrawer keyboard navigation", () => {
  it("wraps Tab and Shift+Tab inside the open menu", () => {
    openDrawer();
    const first = screen.getByRole("link", { name: "Qiko Signal" });
    const last = screen.getByRole("button", { name: "Account menu" });
    expect(first).toHaveFocus();
    last.focus();
    const forward = createEvent.keyDown(document, { key: "Tab" });
    fireEvent(document, forward);
    expect(forward.defaultPrevented).toBe(true);
    expect(first).toHaveFocus();
    const backward = createEvent.keyDown(document, { key: "Tab", shiftKey: true });
    fireEvent(document, backward);
    expect(backward.defaultPrevented).toBe(true);
    expect(last).toHaveFocus();
  });

  it("lets a child modal handle Escape without closing the drawer", () => {
    openDrawer();
    const closeModal = vi.fn();
    const modal = render(
      <Modal open onClose={closeModal}>
        <button>Secondary control</button>
      </Modal>
    );
    expect(screen.getByRole("button", { name: "Secondary control" })).toHaveFocus();
    fireEvent.keyDown(document, { key: "Escape" });
    expect(closeModal).toHaveBeenCalledTimes(1);
    // The drawer stays mounted but is aria-hidden while a modal sits above it.
    expect(
      screen.getByRole("dialog", { name: "Dashboard navigation", hidden: true })
    ).toBeInTheDocument();
    modal.unmount();
    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(document.body.style.overflow).not.toBe("hidden");
    expect(document.body).not.toHaveAttribute("data-scroll-locked");
  });

  it("uses the same Qiko brand asset as the desktop shell", () => {
    openDrawer();
    const brand = screen.getByRole("link", { name: "Qiko Signal" });
    expect(brand.querySelector("img")?.getAttribute("src")).toContain("qiko-logo.png");
    expect(brand).toHaveTextContent("Signal");
  });

  it("closes with Escape and restores focus to the trigger", () => {
    const trigger = openDrawer();
    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(trigger).toHaveFocus();
    expect(document.body.style.overflow).not.toBe("hidden");
  });
});
