import { expect, gotoAndSettle, visualTest } from "./visual-fixtures";

// ---------------------------------------------------------------------------
// SIGV2-1201: the Start Project modal's focus and select treatment, asserted
// as computed style in a real browser rather than as pixels.
//
// A jsdom test can only check class names, and the defect this ticket reports
// lives in the cascade: @tailwindcss/forms styles every bare input and select
// on `:focus` (mouse included) with a #2563eb border plus a 1px #2563eb ring,
// and paints its own background-image chevron under the explicit `.mchev`
// arrow. Both are base-layer rules no amount of markup reading would reveal.
//
// What the approved signal.css specifies, and what is asserted here:
//   - the bare field inside `.minp` draws no ring and no border of its own
//   - the shell lights instead: --panel ground, #C9CEF7 border, 3px --ring
//   - that holds for a pointer click and for a keyboard tab, so focus is
//     never invisible to a keyboard user
//   - a select inside the shell has exactly one chevron
//
// No screenshots: this spec records no baseline.
// ---------------------------------------------------------------------------

const FAKE_JWT =
  "eyJhbGciOiJIUzI1NiJ9." +
  Buffer.from(
    JSON.stringify({ sub: "1", exp: Math.floor(Date.now() / 1000) + 86400, type: "access" })
  ).toString("base64url") +
  ".x";

// The approved indigo focus token: --ring is rgba(79,70,229,.28) under
// [data-signal-theme], never the forms plugin's blue.
const APPROVED_RING = "rgba(79, 70, 229, 0.28) 0px 0px 0px 3px";
const FORMS_BLUE = "37, 99, 235";

async function openModal(page: import("@playwright/test").Page) {
  await page.context().addCookies(
    [
      { name: "auth_token", value: FAKE_JWT },
      { name: "auth_refresh_token", value: FAKE_JWT },
    ].map((c) => ({ ...c, url: "http://localhost:3123" }))
  );
  await page.addInitScript(() => {
    window.localStorage.setItem("active_workspace_id", "1");
  });
  await gotoAndSettle(page, "/dashboard/overview");
  const trigger = page.locator("button.border-dashed").first();
  await expect(trigger).toBeVisible({ timeout: 30000 });
  await trigger.click();
  const dialog = page.locator("[role='dialog']");
  await expect(dialog).toBeVisible({ timeout: 15000 });
  return dialog;
}

visualTest.describe("Start Project modal focus treatment", () => {
  visualTest(
    "a pointer click lights the shell, never a blue ring on the field",
    async ({ page }) => {
      const dialog = await openModal(page);
      const field = dialog.locator("input[type='text']").first();
      await field.click();

      const state = await field.evaluate((el) => {
        const own = getComputedStyle(el);
        const shell = getComputedStyle(el.parentElement as HTMLElement);
        return {
          fieldShadow: own.boxShadow,
          fieldBorder: own.borderColor,
          shellShadow: shell.boxShadow,
          shellBorder: shell.borderColor,
          shellBackground: shell.backgroundColor,
        };
      });

      expect(state.fieldShadow).toBe("none");
      expect(state.fieldBorder).not.toContain(FORMS_BLUE);
      expect(state.shellShadow).toContain(APPROVED_RING);
      expect(state.shellBorder).toBe("rgb(201, 206, 247)");
      expect(state.shellBackground).toBe("rgb(255, 255, 255)");
    }
  );

  visualTest("every control is reachable by keyboard and lights when it is", async ({ page }) => {
    const dialog = await openModal(page);
    const controlCount = await dialog.locator("input, select").count();
    expect(controlCount).toBe(4);

    const seen: string[] = [];
    for (let i = 0; i < controlCount; i++) {
      const focused = await page.evaluate(() => {
        const el = document.activeElement as HTMLElement | null;
        if (!el) return null;
        const shell = el.parentElement as HTMLElement | null;
        return {
          tag: el.tagName,
          inShell: shell?.classList.contains("input-shell") ?? false,
          ownShadow: getComputedStyle(el).boxShadow,
          shellShadow: shell ? getComputedStyle(shell).boxShadow : "",
        };
      });
      expect(focused).not.toBeNull();
      expect(focused!.inShell).toBe(true);
      // The ring is on the shell, and it is there for keyboard focus too.
      expect(focused!.ownShadow).toBe("none");
      expect(focused!.shellShadow).toContain(APPROVED_RING);
      seen.push(focused!.tag);
      await page.keyboard.press("Tab");
    }

    expect(seen).toEqual(["INPUT", "INPUT", "SELECT", "SELECT"]);

    // Tab lands on the actions next, and they stay visible too.
    const button = await page.evaluate(() => {
      const el = document.activeElement as HTMLElement;
      return { tag: el.tagName, shadow: getComputedStyle(el).boxShadow };
    });
    expect(button.tag).toBe("BUTTON");
    expect(button.shadow).toContain(APPROVED_RING);
  });

  visualTest("each select shows exactly one chevron", async ({ page }) => {
    const dialog = await openModal(page);

    const selects = await dialog.locator("select").evaluateAll((els) =>
      els.map((el) => {
        const shell = el.parentElement as HTMLElement;
        return {
          // The forms plugin's own arrow and its 2.5rem reservation are gone.
          backgroundImage: getComputedStyle(el).backgroundImage,
          paddingInlineEnd: getComputedStyle(el).paddingInlineEnd,
          appearance: getComputedStyle(el).appearance,
          chevrons: shell.querySelectorAll("svg path[d='M6 9l6 6 6-6']").length,
        };
      })
    );

    expect(selects).toHaveLength(2);
    for (const select of selects) {
      expect(select.backgroundImage).toBe("none");
      expect(select.paddingInlineEnd).toBe("0px");
      expect(select.appearance).toBe("none");
      expect(select.chevrons).toBe(1);
    }
  });
});
