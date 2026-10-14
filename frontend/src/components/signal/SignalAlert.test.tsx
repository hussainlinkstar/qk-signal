import { act, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import SignalAlert from "./SignalAlert";
import SignalInlineNote from "./SignalInlineNote";

afterEach(() => {
  vi.useRealTimers();
});

/**
 * The shared alert and inline-error presentation (SIGV2-1171). The approved
 * anatomy lives in Signal Components.html `#sec-alerts` and `#sec-notify`;
 * these assertions pin the parts a surface can get wrong silently - the role a
 * failure announces itself with, the glyph that distinguishes it from a
 * confirmation without relying on colour, and the approved tinted fill.
 */
describe("SignalAlert", () => {
  it("renders the approved card anatomy with a separate glyph badge and description", () => {
    const { container } = render(
      <SignalAlert tone="success" title="Scan complete">
        Results are ready.
      </SignalAlert>
    );
    expect(container.querySelector('[data-slot="alert"]')).toHaveAttribute(
      "data-signal-alert",
      "success"
    );
    expect(container.querySelector('[data-slot="alert-title"]')).toHaveTextContent("Scan complete");
    expect(container.querySelector('[data-slot="alert-description"]')).toHaveTextContent(
      "Results are ready."
    );
    expect(container.querySelector('[data-slot="alert-icon"] svg')).not.toBeNull();
  });
  it("announces a failure as an alert without the caller asking", () => {
    render(
      <SignalAlert tone="danger" title="Plan change failed">
        We could not reach the billing provider.
      </SignalAlert>
    );

    const alert = screen.getByRole("alert");
    expect(alert).toHaveAttribute("data-signal-alert", "danger");
    expect(alert).toHaveTextContent("Plan change failed");
    expect(alert).toHaveTextContent("We could not reach the billing provider.");
  });

  it("announces a warning as an alert too", () => {
    render(
      <SignalAlert tone="warning" title="Almost out of scans">
        90% of this month&apos;s volume is used.
      </SignalAlert>
    );
    expect(screen.getByRole("alert")).toHaveAttribute("data-signal-alert", "warning");
  });

  it("keeps a confirmation out of the way as a status", () => {
    render(
      <SignalAlert tone="success" title="Connected">
        GA4 is sending data.
      </SignalAlert>
    );
    expect(screen.getByRole("status")).toHaveAttribute("data-signal-alert", "success");
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("never downgrades a failure when a caller passes the role explicitly", () => {
    render(
      <SignalAlert tone="danger" role="alert" title="Save failed">
        body
      </SignalAlert>
    );
    expect(screen.getByRole("alert")).toBeInTheDocument();
  });

  it("gives each tone its own approved glyph, so colour is never the only cue", () => {
    const shapes = new Set<string>();
    for (const tone of ["info", "success", "warning", "danger"] as const) {
      const { container, unmount } = render(
        <SignalAlert tone={tone} title={tone}>
          body
        </SignalAlert>
      );
      const svg = container.querySelector("svg");
      expect(svg).not.toBeNull();
      // The path geometry differs per approved glyph: circled "i", circled
      // check, triangle, circled cross.
      shapes.add(
        Array.from(svg!.children)
          .map((child) => child.getAttribute("d") ?? child.tagName)
          .join("|")
      );
      unmount();
    }
    expect(shapes.size).toBe(4);
  });

  // SIGV2-1222: the tinted fill and the 1px edge moved out of the utility
  // list and into the `[data-signal-alert="<tone>"]` rules in globals.css,
  // because the edge is now an animated gradient painted into the border box
  // and a `border-color` utility fights it. What a component test can still
  // hold is the handle those rules key off, and that no utility sneaks the
  // old border width back in on top of the gradient.
  it("names its tone on the element the gradient edge keys off", () => {
    for (const tone of ["info", "success", "warning", "danger"] as const) {
      const { container, unmount } = render(
        <SignalAlert tone={tone} title="t">
          b
        </SignalAlert>
      );
      const el = container.querySelector("[data-signal-alert]")!;
      expect(el.getAttribute("data-signal-alert")).toBe(tone);
      expect(el.className).toContain("rounded-(--r-md)");
      expect(el.className).not.toMatch(/(^|\s)border(\s|$)/);
      expect(el.className).not.toContain("bg-(--");
      unmount();
    }
  });

  // SIGV2-1171 made an autosave failure persist instead of flashing past, and
  // SIGV2-1222 added a Close control to the same surface. A Close control is
  // not permission to time a failure out: there is no timer in this component
  // and there must never be one. This fails the moment anyone adds one.
  it("never dismisses itself, however long it is left alone", () => {
    vi.useFakeTimers();
    const onDismiss = vi.fn();
    render(
      <SignalAlert tone="danger" title="Draft not saved" onDismiss={onDismiss}>
        We could not save your draft.
      </SignalAlert>
    );

    act(() => {
      vi.advanceTimersByTime(10 * 60 * 1000);
    });

    expect(screen.getByRole("alert")).toHaveTextContent("Draft not saved");
    expect(onDismiss).not.toHaveBeenCalled();
  });

  it("labels the close control, in the catalogue language", () => {
    render(
      <SignalAlert tone="danger" title="t" onDismiss={() => {}}>
        b
      </SignalAlert>
    );
    expect(screen.getByRole("button", { name: "Dismiss notification" })).toBeInTheDocument();
  });

  it("renders the machine-readable reference on its own line", () => {
    render(
      <SignalAlert tone="danger" title="Plan change failed" reference="409 subscription_stale">
        body
      </SignalAlert>
    );
    expect(screen.getByText("Reference: 409 subscription_stale")).toBeInTheDocument();
  });

  it("omits the reference line when there is nothing to quote", () => {
    render(
      <SignalAlert tone="danger" title="t" reference="   ">
        b
      </SignalAlert>
    );
    expect(screen.queryByText(/Reference:/)).toBeNull();
  });

  it("dismisses when the surface offers it", async () => {
    const onDismiss = vi.fn();
    render(
      <SignalAlert tone="info" title="t" onDismiss={onDismiss} dismissLabel="Dismiss">
        b
      </SignalAlert>
    );
    screen.getByRole("button", { name: "Dismiss" }).click();
    expect(onDismiss).toHaveBeenCalledOnce();
  });
});

describe("SignalInlineNote", () => {
  it("announces a field-level failure as an alert", () => {
    render(<SignalInlineNote tone="danger">That address did not resolve.</SignalInlineNote>);
    const note = screen.getByRole("alert");
    expect(note).toHaveAttribute("data-signal-inline-note", "danger");
    expect(note).toHaveTextContent("That address did not resolve.");
  });

  it("uses the approved .note-inline metrics and the tone's own colour", () => {
    const { container } = render(<SignalInlineNote tone="warning">note</SignalInlineNote>);
    const className = container.querySelector("[data-signal-inline-note]")!.className;
    expect(className).toContain("text-[12.5px]");
    expect(className).toContain("font-medium");
    expect(className).toContain("gap-2");
    expect(className).toContain("text-(--warn)");
  });

  it("keeps a confirmation polite", () => {
    render(<SignalInlineNote tone="success">Saved.</SignalInlineNote>);
    expect(screen.getByRole("status")).toBeInTheDocument();
  });
});
