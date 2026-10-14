import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import ToastFocusRelease from "./ToastFocusRelease";

// SIGV2-1226. The focus trap itself cannot be reproduced here: it needs a real
// Tab, a real focusout carrying a relatedTarget, and a programmatic .focus()
// racing it, which is why the browser assertion in
// e2e/visual/toast-focus-release.visual.spec.ts is the one that proves the fix.
//
// What this file guards is the single assumption that fix rests on: a
// capture-phase handler on an ancestor runs before a descendant's onFocus and
// onBlur, and stopPropagation() keeps the event from ever reaching them. That
// is how sonner's record-and-restore is suppressed without forking it. If a
// React upgrade changed the dispatch order, the trap would quietly come back
// and only the slow browser suite would notice. This fails in seconds instead.

describe("ToastFocusRelease (SIGV2-1226)", () => {
  it("keeps focus and blur from reaching the toaster's own handlers", () => {
    const onFocus = vi.fn();
    const onBlur = vi.fn();

    render(
      <>
        <button type="button">outside</button>
        <ToastFocusRelease>
          {/* Stands in for sonner's <ol data-sonner-toaster>, which records
              the previously focused element here and refocuses it on blur. */}
          <div onFocus={onFocus} onBlur={onBlur}>
            <button type="button">inside the toast</button>
          </div>
        </ToastFocusRelease>
      </>
    );

    const outside = screen.getByRole("button", { name: "outside" });
    const inside = screen.getByRole("button", { name: "inside the toast" });

    inside.focus();
    expect(onFocus).not.toHaveBeenCalled();

    outside.focus();
    expect(onBlur).not.toHaveBeenCalled();

    // Focus really did move and stay moved: the point is to suppress the
    // bookkeeping, not to block focus.
    expect(document.activeElement).toBe(outside);
  });

  it("adds no box of its own, so it cannot move the toast stack", () => {
    const { container } = render(
      <ToastFocusRelease>
        <span>toast stack</span>
      </ToastFocusRelease>
    );

    const wrapper = container.firstElementChild as HTMLElement;
    expect(wrapper.style.display).toBe("contents");
  });
});
