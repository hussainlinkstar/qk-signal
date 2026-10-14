import { expect, gotoAndSettle, visualTest } from "./visual-fixtures";

// ---------------------------------------------------------------------------
// SIGV2-1226: Tab must be able to leave a live toast.
//
// Sonner's toaster list records the element focus arrived from and calls
// .focus() on it again the moment focus leaves the list. It cannot tell a
// deliberate visit from a Tab passing through, so for the whole life of a
// toast every attempt to move on is answered by putting focus back. A
// keyboard user is held in place until the toast expires.
//
// No unit test can see this. The trap is the browser's own focus sequencing:
// a real Tab, a real focusout with a real relatedTarget, and a programmatic
// .focus() racing it. jsdom does not reproduce the ordering, which is why the
// defect survived until a focus walk reported it had reached exactly one
// element. So the assertion lives here, in a real browser, pressing real Tab
// keys, and it measures the thing that actually matters: how many distinct
// elements a walk can reach while a toast is on screen.
//
// Two properties are asserted together, because fixing one by breaking the
// other is not a fix:
//   - focus can leave the toaster and keep going (the defect)
//   - focus can still reach the toaster (a notification no keyboard user can
//     reach is its own accessibility failure)
//
// No screenshots. This spec records no baseline and must not move a pixel.
// ---------------------------------------------------------------------------

const TOAST = "[data-sonner-toast]";
const STRONG_PASSWORD = "Str0ng!Passw0rd";

type FocusStep = { inToaster: boolean; id: string };

/**
 * Raise a real toast with no backend in the loop.
 *
 * /reset-password with no `token` in the query string fails its own guard and
 * calls toast.error directly, so the toast is deterministic and owes nothing
 * to the stub fixtures.
 */
async function raiseToast(page: import("@playwright/test").Page) {
  await gotoAndSettle(page, "/reset-password");

  await page.locator("#password").fill(STRONG_PASSWORD);
  await page.locator("#confirm-password").fill(STRONG_PASSWORD);
  await page.locator('button[type="submit"]').click();

  // Sonner adds a toast from inside a setTimeout, and the visual fixture
  // installs a paused clock, so without this the toast would never mount.
  // Advancing by 50ms and no more also means the 5s duration never elapses:
  // the toast stays alive for the whole walk, which is the state under test,
  // rather than expiring halfway through and quietly making the suite green.
  await page.clock.runFor(50);
  await expect(page.locator(TOAST)).toBeVisible();
}

/** Press Tab `steps` times, recording where focus actually landed each time. */
async function tabWalk(page: import("@playwright/test").Page, steps: number) {
  const walk: FocusStep[] = [];
  for (let i = 0; i < steps; i++) {
    await page.keyboard.press("Tab");
    walk.push(
      await page.evaluate(() => {
        const el = document.activeElement as HTMLElement | null;
        if (!el || el === document.body) return { inToaster: false, id: "body" };
        const className = typeof el.className === "string" ? el.className : "";
        return {
          inToaster: !!el.closest("[data-sonner-toaster]"),
          // Identity, not description: the walk needs to tell "moved on" from
          // "pulled back to the same control".
          id: `${el.tagName}#${el.id}.${className.slice(0, 40)}`,
        };
      })
    );
  }
  return walk;
}

visualTest.describe("toast focus release (SIGV2-1226)", () => {
  visualTest("Tab leaves a live toast and keeps going", async ({ page }) => {
    await raiseToast(page);

    const walk = await tabWalk(page, 12);

    // The toast is still on screen: this is a walk past a live toast, not a
    // walk past one that expired while we were counting.
    await expect(page.locator(TOAST)).toBeVisible();

    const entered = walk.findIndex((step) => step.inToaster);
    expect(entered, `focus never reached the toaster: ${JSON.stringify(walk)}`).toBeGreaterThan(-1);

    // Everything after the last stop inside the toaster. With the trap in
    // place the walk oscillates between the toaster and the one element it is
    // thrown back to, so this tail is empty or a single repeated control.
    const lastInToaster = walk.map((s) => s.inToaster).lastIndexOf(true);
    const afterToaster = walk.slice(lastInToaster + 1);

    expect(
      afterToaster.some((step) => step.inToaster),
      `focus was pulled back into the toaster: ${JSON.stringify(walk)}`
    ).toBe(false);

    const distinctAfter = new Set(afterToaster.map((step) => step.id));
    expect(
      distinctAfter.size,
      `focus did not move on after the toast: ${JSON.stringify(walk)}`
    ).toBeGreaterThanOrEqual(3);

    // The symptom that exposed this: a walk that reached exactly one element.
    const distinctOutside = new Set(
      walk.filter((step) => !step.inToaster && step.id !== "body").map((step) => step.id)
    );
    expect(
      distinctOutside.size,
      `the walk reached ${distinctOutside.size} distinct elements outside the toaster`
    ).toBeGreaterThanOrEqual(3);
  });

  visualTest("the toast is still reachable by keyboard", async ({ page }) => {
    await raiseToast(page);

    // Releasing the trap must not make the notification unreachable. The
    // close button is the control a keyboard user needs.
    const walk = await tabWalk(page, 12);
    expect(
      walk.some((step) => step.inToaster),
      `the toast could not be reached by Tab: ${JSON.stringify(walk)}`
    ).toBe(true);

    const closeButton = page.locator(`${TOAST} [data-close-button]`);
    await expect(closeButton).toBeVisible();
    await closeButton.focus();
    expect(await closeButton.evaluate((el) => document.activeElement === el)).toBe(true);

    // And it still dismisses from the keyboard.
    await page.keyboard.press("Enter");
    await page.clock.runFor(400);
    await expect(page.locator(TOAST)).toHaveCount(0);
  });

  visualTest("the SIGV2-1171 glyph and duration are untouched", async ({ page }) => {
    await raiseToast(page);

    const toast = page.locator(TOAST).first();
    // Tone is carried by a glyph, not colour alone (WCAG 1.4.1).
    await expect(toast.locator("[data-icon] .thoth-toast-icon")).toHaveCount(1);
    await expect(toast).toHaveAttribute("data-type", "error");

    // The wrapper is display:contents, so the stack is positioned exactly as
    // before and nothing it does can reach a screenshot.
    const toasterDisplay = await page
      .locator("[data-sonner-toaster]")
      .evaluate((el) => getComputedStyle(el).position);
    expect(toasterDisplay).toBe("fixed");

    // Still auto-dismissing on its own 5s clock, not made persistent.
    await page.clock.runFor(6000);
    await expect(page.locator(TOAST)).toHaveCount(0);
  });
});
