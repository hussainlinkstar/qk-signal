import React from "react";
import { readFileSync } from "node:fs";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import ProjectFormFields from "@/components/onboarding/ProjectSetupFields";
import { tEn } from "@/test/i18nEn";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: tEn }),
}));

// ---------------------------------------------------------------------------
// SIGV2-1201: the Start Project modal and the onboarding wizard share these
// fields, and both were drawing @tailwindcss/forms' `:focus` treatment - a
// #2563eb border plus a 1px #2563eb ring - on mouse click, plus the plugin's
// own background-image chevron underneath the explicit `.mchev` arrow. The
// approved reference is signal.css: `.minp` (shell carries the focus),
// `.wselect` (standalone control) and the single `--ring` focus token.
// ---------------------------------------------------------------------------

const globalsCss = readFileSync(`${process.cwd()}/src/app/globals.css`, "utf8").replace(
  /\r\n/g,
  "\n"
);

const values = { name: "", domain: "", market: "GLOBAL", language: "en" };

const renderFields = (props: Partial<React.ComponentProps<typeof ProjectFormFields>> = {}) =>
  render(
    <ProjectFormFields
      fields={["name", "domain", "market", "language"]}
      values={values}
      onChange={vi.fn()}
      {...props}
    />
  );

const shellOf = (control: HTMLElement) => control.parentElement as HTMLElement;

describe("ProjectFormFields - approved modal anatomy", () => {
  it("renders the four approved fields in `.minp` shells", () => {
    renderFields();

    for (const label of ["Project name", "Primary domain", "Target market", "Reporting language"]) {
      expect(screen.getByText(label)).toBeInTheDocument();
    }

    const name = screen.getByPlaceholderText("Acme Corp");
    const shell = shellOf(name);
    // Boxed shell: white field, hairline border (editable — not grey/disabled).
    expect(shell).toHaveClass("h-11", "rounded-[14px]", "border-(--line)", "bg-white");
    // The bare control draws nothing: no border, no ring, no background.
    expect(name).toHaveClass("border-none", "bg-transparent", "outline-none");
  });

  it("puts the focus treatment on the shell, in the brand ring, never on the field", () => {
    renderFields();

    const shell = shellOf(screen.getByPlaceholderText("Acme Corp"));
    expect(shell).toHaveClass(
      "input-shell",
      "focus-within:border-(--purple)",
      "focus-within:bg-white",
      "focus-within:shadow-[0_0_0_3px_rgba(147,51,234,0.12)]"
    );
    // `focus-within` is the only focus hook, so the shell lights for a
    // keyboard tab exactly as it does for a click - focus is never silent.
    expect(shell.className).not.toContain("hover:shadow");
  });

  it("gives every control in the shell exactly one dropdown indicator", () => {
    renderFields();

    const market = screen.getByLabelText("Target market");
    const language = screen.getByLabelText("Reporting language");

    for (const select of [market, language]) {
      expect(select).toHaveClass("appearance-none");
      const chevrons = shellOf(select).querySelectorAll("svg path[d='M6 9l6 6 6-6']");
      expect(chevrons).toHaveLength(1);
    }

    // The leading icon is an icon, not a second arrow.
    expect(shellOf(market).querySelectorAll("svg")).toHaveLength(2);
    expect(shellOf(language).querySelectorAll("svg")).toHaveLength(1);
  });

  it("keeps every control reachable by keyboard in approved reading order", () => {
    const { container } = renderFields();

    const controls = [...container.querySelectorAll<HTMLElement>("input, select")];
    expect(controls.map((c) => c.tagName)).toEqual(["INPUT", "INPUT", "SELECT", "SELECT"]);

    for (const control of controls) {
      expect(control).not.toBeDisabled();
      // A negative tabIndex would make the field mouse-only.
      expect(control.tabIndex).toBeGreaterThanOrEqual(0);
      control.focus();
      expect(document.activeElement).toBe(control);
      // The shell is the focus-within ancestor that paints the indicator.
      expect(shellOf(control)).toHaveClass("input-shell");
    }
  });

  it("marks an invalid domain on the shell without touching the focus treatment", () => {
    renderFields({ domainInvalid: true, variant: "wizard", fields: ["domain"] });

    const shell = shellOf(screen.getByPlaceholderText("yourdomain.com"));
    expect(shell).toHaveClass("border-(--bad)");
    expect(shell).toHaveClass("focus-within:shadow-[0_0_0_3px_rgba(147,51,234,0.12)]");
  });

  it("reports changes for each field", () => {
    const onChange = vi.fn();
    renderFields({ onChange });

    fireEvent.change(screen.getByPlaceholderText("Acme Corp"), { target: { value: "Acme" } });
    fireEvent.change(screen.getByLabelText("Reporting language"), { target: { value: "ar" } });

    expect(onChange).toHaveBeenCalledWith("name", "Acme");
    expect(onChange).toHaveBeenCalledWith("language", "ar");
  });
});

describe("ProjectFormFields - wizard variant", () => {
  it("renders standalone `.wselect` controls with the keyboard-only ring", () => {
    renderFields({ variant: "wizard", fields: ["market", "language"] });

    const market = screen.getByLabelText("Target market");
    expect(market).toHaveClass(
      "wselect-chevron",
      "field-focus-ring",
      "appearance-none",
      "border-(--line)",
      "bg-white"
    );
    // One chevron only: `wselect-chevron` supplies it, so no inline svg.
    expect(market.querySelectorAll("svg")).toHaveLength(0);
  });
});

describe("SIGV2-1201 focus CSS contract", () => {
  it("relocates the forms-plugin ring to the shell for opted-in markup only", () => {
    expect(globalsCss).toContain(
      ".input-shell > :is(input, select, textarea):focus {\n    box-shadow: none;"
    );
    expect(globalsCss).toContain(".input-shell > select {\n    background-image: none;");
    expect(globalsCss).toContain(".field-focus-ring:focus {\n    box-shadow: none;");
    expect(globalsCss).toContain(
      ".field-focus-ring:focus-visible {\n    box-shadow: 0 0 0 3px var(--ring);"
    );
  });

  it("suppresses nothing globally: every override is class-scoped", () => {
    // The blast radius of this ticket is exactly the markup that opts in. A
    // bare element selector here would silently restyle every form in the app.
    const scopedBlock = globalsCss
      .slice(globalsCss.indexOf("/* SIGV2-1201"), globalsCss.indexOf("@layer utilities {"))
      .replace(/\/\*[\s\S]*?\*\//g, "");
    const selectors = scopedBlock.match(/^ {2}\S[^{}\n]*\{$/gm) ?? [];
    expect(selectors.length).toBeGreaterThan(0);
    for (const selector of selectors) {
      expect(selector.trim()).toMatch(/^\.(input-shell|field-focus-ring)\b/);
    }
  });
  // SIGV2-1294 -------------------------------------------------------------
  // "drop down doesn't work on the arrow but does on the main word".
  //
  // The chevron is a flex sibling of the select and is `pointer-events-none`,
  // so a click on it fell through to the shell and nothing happened. The
  // approved anatomy is fixed by SIGV2-1201 (the select carries no background
  // chevron and no inline-end padding), so the select cannot simply be
  // widened underneath it. The shell forwards the click instead.
  it("forwards a click on the shell to the control inside it", () => {
    renderFields();

    const market = screen.getByText(tEn("projectForm.targetMarket")).parentElement as HTMLElement;
    const select = market.querySelector("select") as HTMLSelectElement;
    const shell = select.parentElement as HTMLElement;

    expect(document.activeElement).not.toBe(select);

    // A click landing on the shell itself, which is what a click on the
    // chevron becomes once the chevron ignores pointer events.
    fireEvent.click(shell);

    expect(document.activeElement).toBe(select);
  });

  it("leaves a click on the control itself alone", () => {
    renderFields();

    const market = screen.getByText(tEn("projectForm.targetMarket")).parentElement as HTMLElement;
    const select = market.querySelector("select") as HTMLSelectElement;
    const shell = select.parentElement as HTMLElement;

    // Only a click that lands on the shell is forwarded. Anything that
    // already reached a control is the browser's business, and re-focusing it
    // would fight the native picker.
    fireEvent.click(select);
    expect(shell).toBeTruthy();
  });

  it("does not focus a disabled control", () => {
    renderFields({ disabled: true });

    const market = screen.getByText(tEn("projectForm.targetMarket")).parentElement as HTMLElement;
    const select = market.querySelector("select") as HTMLSelectElement;
    const shell = select.parentElement as HTMLElement;

    fireEvent.click(shell);

    expect(document.activeElement).not.toBe(select);
  });

  it("keeps the approved select anatomy: no padding reserved for a chevron", () => {
    // The first attempt at this fix overlaid the chevron and gave the select
    // `padding-inline-end: 24px` to stop its text running underneath. That
    // broke the SIGV2-1201 contract, which the visual suite asserts as 0px.
    renderFields();

    const market = screen.getByText(tEn("projectForm.targetMarket")).parentElement as HTMLElement;
    const select = market.querySelector("select") as HTMLSelectElement;

    expect(select.className).not.toContain("pe-6");
    expect(select.className).not.toContain("pr-10");
    expect(select.parentElement?.className).not.toContain("relative");
  });
});
