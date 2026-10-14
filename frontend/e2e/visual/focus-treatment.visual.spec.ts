import { expect, gotoAndSettle, visualTest } from "./visual-fixtures";

// ---------------------------------------------------------------------------
// SIGV2-1217: keyboard focus, asserted as computed style in a real browser.
//
// The defect this spec exists to keep closed cannot be seen from markup. The
// global rule in globals.css read `outline: 2px solid transparent` for every
// a/button/input/select/textarea/[role=button], so any element that drew no
// ring of its own was focusable and completely invisible while focused: a
// WCAG 2.4.7 failure on 628 of the 713 interactive elements in src/.
//
// Nor can it be caught by checking that a focused element is styled at all.
// The old rule DID change the computed outline on focus, from `none` to
// `2px solid transparent`, and a computed `outline-color` is reported even
// when nothing is drawn (it resolves to currentColor), so reading the colour
// alone reports the text colour and proves nothing. Every element a Tab lands
// on is therefore measured twice, focused and then blurred, and an indicator
// only counts when the focused state draws something a person can see: an
// outline with a style, a width and a non-transparent colour, or a box-shadow
// that appears on the element or on the shell around it.
//
// Also asserted:
//   - a plain button, one carrying no focus utility of its own, draws the new
//     2px outline, and draws nothing at all for a pointer click
//   - nothing is ringed twice, and the check is not vacuous: the walk is
//     required to reach at least one element that draws its own ring
//   - the surfaces SIGV2-1201's two classes were adopted on no longer light
//     the @tailwindcss/forms blue on a click, and still show one chevron
//
// No screenshots: this spec records no baseline. Focus is not active at rest,
// so this ticket must not move a pixel baseline at all.
// ---------------------------------------------------------------------------

const FAKE_JWT =
  "eyJhbGciOiJIUzI1NiJ9." +
  Buffer.from(
    JSON.stringify({ sub: "1", exp: Math.floor(Date.now() / 1000) + 86400, type: "access" })
  ).toString("base64url") +
  ".x";

// The approved brand indigo, solid. The SIGV2-1217 note in globals.css records
// why the outline is not --ring (rgba(79,70,229,.28), about 1.3:1 on --panel).
const FOCUS_OUTLINE = "rgb(79, 70, 229)";
const APPROVED_RING = "rgba(79, 70, 229, 0.28)";
const FORMS_BLUE = "37, 99, 235";

// The audit start screen is where SIGV2-1217's adopted classes sit on controls
// that are visible AND enabled under the stub fixtures. The workspace settings
// page renders its own field `disabled` for a non-manager, and a disabled
// control cannot take focus, so it would prove nothing about focus at all.
const FIELDS_ROUTE = "/dashboard/audit?projectId=9";

async function signIn(page: import("@playwright/test").Page) {
  await page.context().addCookies(
    [
      { name: "auth_token", value: FAKE_JWT },
      { name: "auth_refresh_token", value: FAKE_JWT },
    ].map((c) => ({ ...c, url: "http://localhost:3123" }))
  );
  await page.addInitScript(() => {
    window.localStorage.setItem("active_workspace_id", "1");
  });
}

/** Tab through a page and measure what each focused element actually draws. */
async function walk(page: import("@playwright/test").Page, steps: number) {
  const report = {
    reached: 0,
    invisible: [] as string[],
    doubled: [] as string[],
    plainButtonsWithOutline: 0,
    ownRingReached: 0,
  };

  // No click before the first Tab. A pointer interaction switches the
  // browser's focus-visible heuristic off and the run would prove nothing.
  for (let i = 0; i < steps; i++) {
    await page.keyboard.press("Tab");
    const step = await page.evaluate(() => {
      const el = document.activeElement as HTMLElement | null;
      if (!el || el === document.body) return null;

      // A toaster can mount in the same task as this Tab, ahead of the
      // observer's microtask. Focus inside one is the walk visiting the
      // notification, not the surface: drop the toaster and move on rather
      // than letting its focus-restore trap the sequence.
      const toaster = el.closest("[data-sonner-toaster], li.thoth-toast");
      if (toaster) {
        toaster.remove();
        return null;
      }

      const read = (node: HTMLElement) => {
        const s = getComputedStyle(node);
        return {
          outlineStyle: s.outlineStyle,
          outlineWidth: s.outlineWidth,
          outlineColor: s.outlineColor,
          boxShadow: s.boxShadow,
        };
      };

      const className = typeof el.className === "string" ? el.className : "";
      const rect = el.getBoundingClientRect();
      const shell = el.parentElement;
      // Only the elements the globals.css rule names. A Sonner toast <li> is
      // focusable via tabindex and is not one of them.
      const governed = el.matches('a, button, input, select, textarea, [role="button"]');
      // Identity, not description: two adjacent nav links are identical in
      // tag, class and computed style, so comparing descriptions would read
      // them as the walk standing still. A revisit means the tab order has
      // wrapped (or a toast has pulled focus back), and the walk is done.
      const revisit = el.dataset.focusWalk !== undefined;
      el.dataset.focusWalk = "1";

      const focused = { self: read(el), shell: shell ? read(shell) : null };
      // Measure the resting state of the SAME element, then put focus back.
      // Chromium keeps :focus-visible across a programmatic refocus when the
      // element it left matched it, so the Tab sequence carries on intact.
      el.blur();
      const resting = { self: read(el), shell: shell ? read(shell) : null };
      el.focus();

      const outlineDrawn =
        focused.self.outlineStyle !== "none" &&
        parseFloat(focused.self.outlineWidth) > 0 &&
        focused.self.outlineColor !== "rgba(0, 0, 0, 0)" &&
        focused.self.outlineColor !== "transparent";

      const ownRingAppeared =
        focused.self.boxShadow !== "none" && focused.self.boxShadow !== resting.self.boxShadow;
      const shellRingAppeared =
        !!focused.shell &&
        !!resting.shell &&
        focused.shell.boxShadow !== "none" &&
        focused.shell.boxShadow !== resting.shell.boxShadow;

      return {
        tag: el.tagName,
        className,
        governed,
        revisit,
        sized: rect.width > 0 && rect.height > 0,
        outlineDrawn,
        ownRingAppeared,
        shellRingAppeared,
        describe:
          `${el.tagName}.${className.slice(0, 70)} ` +
          `outline=${focused.self.outlineStyle} ${focused.self.outlineWidth} ${focused.self.outlineColor} ` +
          `shadow=${focused.self.boxShadow.slice(0, 50)}`,
      };
    });

    if (!step) continue;
    if (step.revisit) break;
    if (!step.governed) continue;
    // A zero-size element paints nothing; `sr-only` controls are clipped by
    // `clip` on purpose and light a visible sibling instead.
    if (!step.sized || step.className.includes("sr-only")) continue;

    report.reached += 1;
    if (!step.outlineDrawn && !step.ownRingAppeared && !step.shellRingAppeared) {
      report.invisible.push(step.describe);
    }
    if (step.outlineDrawn && step.ownRingAppeared) {
      report.doubled.push(step.describe);
    }
    if (step.ownRingAppeared || step.shellRingAppeared) {
      report.ownRingReached += 1;
    }
    if (step.tag === "BUTTON" && !/focus|signal-button/.test(step.className) && step.outlineDrawn) {
      report.plainButtonsWithOutline += 1;
    }
  }

  return report;
}

visualTest.describe("global keyboard focus indicator", () => {
  for (const route of ["/dashboard/settings", FIELDS_ROUTE]) {
    visualTest(
      `every element a Tab lands on is visible while focused: ${route}`,
      async ({ page }) => {
        await signIn(page);
        await gotoAndSettle(page, route);
        // A toast is a transient notification, not part of the surface under
        // test, and it both takes a tab stop and returns focus to itself.
        // Removing it from the DOM is not a user interaction, so the browser's
        // focus-visible modality is still untouched when the first Tab lands.
        // The observer stays armed for the whole walk: a toast that mounts
        // after this point (debounced autosaves, late async work) used to
        // escape the one-shot removal and trap the walk on SIGV2-1224.
        await page.evaluate(() => {
          const dropToasts = () => {
            document
              .querySelectorAll("[data-sonner-toaster], li.thoth-toast")
              .forEach((n) => n.remove());
          };
          dropToasts();
          new MutationObserver(dropToasts).observe(document.body, {
            childList: true,
            subtree: true,
          });
        });

        const report = await walk(page, 80);

        expect(report.reached).toBeGreaterThan(10);
        expect(report.invisible).toEqual([]);
        // The population this ticket is about. Before the fix, every button that
        // carried no focus utility of its own was invisible while focused.
        expect(report.plainButtonsWithOutline).toBeGreaterThan(0);
        // Nothing is ringed twice, and the walk really did pass over elements
        // that draw their own ring, so that check is not vacuously true.
        expect(report.ownRingReached).toBeGreaterThan(0);
        expect(report.doubled).toEqual([]);
      }
    );
  }

  visualTest("a plain button draws the outline, and only for the keyboard", async ({ page }) => {
    await signIn(page);
    await gotoAndSettle(page, "/dashboard/settings");

    const index = await page
      .locator("button")
      .evaluateAll((els) =>
        els.findIndex(
          (el) =>
            !/focus|signal-button/.test(el.className) &&
            el.getBoundingClientRect().width > 0 &&
            !(el as HTMLButtonElement).disabled
        )
      );
    expect(index).toBeGreaterThanOrEqual(0);
    const button = page.locator("button").nth(index);

    // Keyboard modality first, then move focus programmatically: Chromium
    // matches :focus-visible on a programmatic focus when the element it just
    // left matched it, and a Tab always sets keyboard modality.
    await page.keyboard.press("Tab");
    const keyboard = await button.evaluate((el) => {
      (el as HTMLElement).focus();
      const s = getComputedStyle(el);
      return {
        focused: document.activeElement === el,
        outlineStyle: s.outlineStyle,
        outlineWidth: s.outlineWidth,
        outlineColor: s.outlineColor,
        offset: s.outlineOffset,
      };
    });
    expect(keyboard.focused).toBe(true);
    expect(keyboard.outlineStyle).toBe("solid");
    expect(keyboard.outlineWidth).toBe("2px");
    expect(keyboard.outlineColor).toBe(FOCUS_OUTLINE);
    expect(keyboard.offset).toBe("2px");

    // Pointer focus draws nothing, exactly as the approved design has it.
    //
    // Measured from inside the button's own `focus` handler during a real
    // mouse click, which is the only way to read it honestly. Clicking a
    // non-focusable element first does not establish pointer modality:
    // Chromium carries the focus-visible flag across a programmatic focus
    // from the last element that had it, so the ring would still be reported.
    // And reading the style after the click returns whatever the handler
    // focused next, which for this button is an item in the menu it opens.
    //
    // `outlineStyle`, not `outlineColor`: a computed outline-color is reported
    // even when no outline is drawn, so the colour alone proves nothing.
    await button.evaluate((el) => {
      (window as unknown as { __focusProbe?: unknown }).__focusProbe = undefined;
      // The keyboard half above left this very button focused, so a click on
      // it would fire no `focus` event at all and the probe would never run.
      (document.activeElement as HTMLElement | null)?.blur();
      el.addEventListener(
        "focus",
        () => {
          (window as unknown as { __focusProbe?: unknown }).__focusProbe = {
            focusVisible: el.matches(":focus-visible"),
            outlineStyle: getComputedStyle(el).outlineStyle,
          };
        },
        { once: true }
      );
    });
    await button.click();
    const pointer = await page.evaluate(
      () =>
        (
          window as unknown as {
            __focusProbe?: { focusVisible: boolean; outlineStyle: string };
          }
        ).__focusProbe
    );
    expect(pointer).toBeDefined();
    expect(pointer!.focusVisible).toBe(false);
    expect(pointer!.outlineStyle).toBe("none");
  });
});

visualTest.describe("forms-plugin opt-ins adopted by SIGV2-1217", () => {
  for (const selector of ["input.field-focus-ring", "select.field-focus-ring"]) {
    visualTest(`${selector} lights the approved ring, never the plugin blue`, async ({ page }) => {
      await signIn(page);
      await gotoAndSettle(page, FIELDS_ROUTE);

      const field = page.locator(`${selector}:not([disabled])`).first();
      await expect(field).toBeVisible({ timeout: 30000 });

      // Mouse click: the plugin used to paint a #2563eb border and a 1px ring
      // here, on `:focus`, which is the whole reason this ticket exists.
      //
      // The ring itself is still drawn on a click, and correctly so: Chromium
      // matches :focus-visible on a pointer click for a text input and for a
      // select, because they take keyboard input next. What the opt-in class
      // changes is WHICH ring, from the plugin's blue to the approved indigo.
      await field.click({ force: true });
      const clicked = await field.evaluate((el) => {
        const s = getComputedStyle(el);
        return {
          focused: document.activeElement === el,
          boxShadow: s.boxShadow,
          borderColor: s.borderColor,
        };
      });
      expect(clicked.focused).toBe(true);
      expect(clicked.boxShadow).not.toContain(FORMS_BLUE);
      expect(clicked.boxShadow).toContain(APPROVED_RING);
      expect(clicked.borderColor).not.toContain(FORMS_BLUE);

      // Keyboard focus: the approved indigo ring, 3px.
      await page.keyboard.press("Tab");
      const tabbed = await field.evaluate((el) => {
        (el as HTMLElement).focus();
        const s = getComputedStyle(el);
        return {
          focused: document.activeElement === el,
          boxShadow: s.boxShadow,
          borderColor: s.borderColor,
        };
      });
      expect(tabbed.focused).toBe(true);
      expect(tabbed.boxShadow).toContain(APPROVED_RING);
      expect(tabbed.boxShadow).toContain("3px");
      expect(tabbed.borderColor).not.toContain(FORMS_BLUE);
    });
  }

  visualTest("an opted-in select still shows exactly one chevron", async ({ page }) => {
    await signIn(page);
    await gotoAndSettle(page, FIELDS_ROUTE);

    await expect(page.locator("select.field-focus-ring").first()).toBeVisible({ timeout: 30000 });
    const selects = await page.locator("select.field-focus-ring").evaluateAll((els) =>
      els.map((el) => ({
        appearance: getComputedStyle(el).appearance,
        // `wselect-chevron` is a utility, so its background-image replaces the
        // plugin's rather than stacking with it: one arrow, not two.
        urls: getComputedStyle(el).backgroundImage.split("url(").length - 1,
        inlineSvgs: (el.parentElement?.querySelectorAll("svg").length ?? 0) > 0,
      }))
    );
    expect(selects.length).toBeGreaterThan(0);
    for (const select of selects) {
      expect(select.appearance).toBe("none");
      expect(select.urls).toBeLessThanOrEqual(1);
    }
  });
});
