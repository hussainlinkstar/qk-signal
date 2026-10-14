import fs from "node:fs";
import path from "node:path";

import { describe, expect, it } from "vitest";

const frontendRoot = path.resolve(__dirname, "../..");
const globalsCss = fs.readFileSync(path.join(frontendRoot, "src/app/globals.css"), "utf8");
// signal-mvp.css is deleted; its :root block lives verbatim in globals.css now,
// still unlayered and still what resolves outside [data-signal-theme].
const rootSlice = globalsCss.slice(
  globalsCss.lastIndexOf(":root {"),
  globalsCss.indexOf("}", globalsCss.lastIndexOf(":root {"))
);
const alertSettings = fs.readFileSync(
  path.join(frontendRoot, "src/components/settings/AlertSettings.tsx"),
  "utf8"
);

const tokenFrom = (source: string, name: string) => {
  const match = source.match(new RegExp(`--${name}:\\s*(#[0-9A-Fa-f]{6})`));
  if (!match) throw new Error(`Missing color token: ${name}`);
  return match[1];
};
const signalToken = (name: string) => tokenFrom(rootSlice, name);
const lightToken = (name: string) =>
  tokenFrom(globalsCss.slice(globalsCss.indexOf("[data-signal-theme]")), name);

const rgb = (hex: string) =>
  [1, 3, 5].map((index) => Number.parseInt(hex.slice(index, index + 2), 16));
const luminance = (color: string) => {
  const linear = rgb(color).map((value) => {
    const channel = value / 255;
    return channel <= 0.04045 ? channel / 12.92 : ((channel + 0.055) / 1.055) ** 2.4;
  });
  return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2];
};

const contrast = (foreground: string, background: string) => {
  const [lighter, darker] = [luminance(foreground), luminance(background)].sort((a, b) => b - a);
  return (lighter + 0.05) / (darker + 0.05);
};

describe("Signal contrast tokens", () => {
  it("keeps light-theme muted and status text at WCAG AA contrast", () => {
    for (const background of [signalToken("panel"), signalToken("paper"), signalToken("line-2")]) {
      expect(contrast(lightToken("t-3"), background)).toBeGreaterThanOrEqual(4.5);
    }
    expect(contrast(lightToken("good"), signalToken("good-s"))).toBeGreaterThanOrEqual(4.5);
    expect(contrast(lightToken("warn"), signalToken("warn-s"))).toBeGreaterThanOrEqual(4.5);
    expect(contrast(lightToken("bad"), signalToken("bad-s"))).toBeGreaterThanOrEqual(4.5);
  });

  it("keeps dark-compatible root fallbacks outside the Signal theme", () => {
    expect(contrast(signalToken("t-3"), "#0A0D15")).toBeGreaterThanOrEqual(4.5);
    expect(globalsCss).toContain("[data-signal-theme]");
    expect(globalsCss).toContain("--text-secondary: var(--t-3)");
  });

  it("uses the delivered Qiko palette only within the authenticated theme", () => {
    const theme = globalsCss.match(/\n\[data-signal-theme\] \{([\s\S]*?)\n\}/)?.[1] ?? "";
    expect(tokenFrom(theme, "purple")).toBe("#9333ea");
    expect(tokenFrom(theme, "blue")).toBe("#2563eb");
    expect(tokenFrom(theme, "ink")).toBe("#0c0f16");
    expect(theme).toContain("--primary: var(--ink)");
    expect(theme).toContain("--primary-hover: #000000");
    expect(theme).toContain("--chart-1: var(--purple)");
    expect(theme).toContain("--chart-2: var(--blue)");
    expect(theme).toContain("--font-display: var(--font-satoshi), var(--font-sans)");
    expect(theme).toContain("--r: 16px");
    expect(theme).toContain("--chart-tooltip-radius: var(--r)");
    // --paper, not just white: checking #FFFFFF only is what let the
    // sub-AA #3164ff/#6a63dd ship unnoticed.
    for (const background of ["#FFFFFF", tokenFrom(theme, "paper")]) {
      expect(contrast(tokenFrom(theme, "purple"), background)).toBeGreaterThanOrEqual(4.5);
      expect(contrast(tokenFrom(theme, "blue"), background)).toBeGreaterThanOrEqual(4.5);
      expect(contrast(tokenFrom(theme, "primary-hover"), background)).toBeGreaterThanOrEqual(4.5);
    }
    expect(signalToken("purple")).toBe("#9333ea");
  });

  it("uses the shared primary token for page actions", () => {
    const button = fs.readFileSync(path.join(frontendRoot, "src/components/ui/Button.tsx"), "utf8");
    expect(button).toContain("bg-primary");
    expect(button).toContain("hover:bg-(--primary-hover)");
  });

  it("keeps gauges on the same palette as the shared charts", () => {
    for (const file of [
      // The project overview gauges live in VisibilityPanels since SIGV2-1035
      // extracted the approved ring markup out of the route file.
      "src/components/dashboard/VisibilityPanels.tsx",
      "src/app/(app)/dashboard/projects/[projectId]/ai-answers/page.tsx",
      "src/app/(app)/dashboard/overview/page.tsx",
    ]) {
      const source = fs.readFileSync(path.join(frontendRoot, file), "utf8");
      expect(source).toContain('stopColor="var(--blue)"');
      expect(source).toContain('stopColor="var(--purple)"');
      expect(source).not.toContain('stopColor="#2563EB"');
      expect(source).not.toContain('stopColor="#9333EA"');
    }
  });

  it.each([
    "page.tsx",
    "ai-answers/page.tsx",
    "google/page.tsx",
    "competitors/page.tsx",
    "fixes/page.tsx",
    "settings/page.tsx",
  ])("keeps the R1 route %s free of per-screen literal colours", (route) => {
    const source = fs.readFileSync(
      path.join(frontendRoot, "src/app/(app)/dashboard/projects/[projectId]", route),
      "utf8"
    );
    expect(/#[0-9a-f]{3,8}\b|(?:rgb|hsl)a?\(\s*[0-9]/i.test(source)).toBe(false);
  });

  it("keeps the Google screen free of hardcoded colours", () => {
    const source = fs.readFileSync(
      path.join(frontendRoot, "src/app/(app)/dashboard/projects/[projectId]/google/page.tsx"),
      "utf8"
    );
    expect(/#[0-9a-f]{3,8}\b|(?:rgb|hsl)a?\(\s*[0-9]/i.test(source)).toBe(false);
    expect(source).not.toContain("rgba(37,99,235,.10)");
  });

  it.each([
    "src/app/(auth)/login/page.tsx",
    "src/app/(auth)/register/page.tsx",
    "src/app/(auth)/forgot-password/page.tsx",
    "src/app/(auth)/reset-password/page.tsx",
    "src/app/(auth)/verify-email/page.tsx",
    "src/components/auth/AuthShell.tsx",
    "src/components/auth/AuthPrimitives.tsx",
    "src/components/auth/AuthFormSections.tsx",
    "src/components/auth/AuthCheckbox.tsx",
    "src/components/auth/SocialLogins.tsx",
    "src/components/auth/PasswordStrengthIndicator.tsx",
    "src/components/auth/PasskeySetupPrompt.tsx",
    "src/components/auth/LoginForm.tsx",
    "src/components/auth/RegisterForm.tsx",
    "src/components/auth/ForgotPasswordForm.tsx",
    "src/components/auth/ResetPasswordForm.tsx",
    "src/components/auth/VerifyEmailPageClient.tsx",
    "src/components/auth/custom-auth.tsx",
  ])("keeps the auth tree %s free of hardcoded colours", (file) => {
    const source = fs.readFileSync(path.join(frontendRoot, file), "utf8");
    expect(/#[0-9a-f]{3,8}\b|(?:rgb|hsl)a?\(\s*[0-9]/i.test(source)).toBe(false);
    expect(
      /(?:slate|zinc|stone|neutral|gray|cyan|purple|violet|fuchsia|rose|amber|emerald|teal|sky|indigo)-\d|text-white|bg-white\/|border-white\//.test(
        source
      )
    ).toBe(false);
  });

  it("opts the auth shell into the themed subtree", () => {
    const source = fs.readFileSync(
      path.join(frontendRoot, "src/components/auth/AuthShell.tsx"),
      "utf8"
    );
    expect(source).toContain("data-signal-theme");
    expect(source).not.toContain('variant="inverse"');
  });

  it("loads the Satoshi display font through next/font, not an external stylesheet", () => {
    const layout = fs.readFileSync(path.join(frontendRoot, "src/app/layout.tsx"), "utf8");
    expect(layout).toContain('from "next/font/local"');
    expect(layout).toContain('variable: "--font-satoshi"');
    expect(layout).not.toContain("api.fontshare.com");
    expect(layout).not.toContain("<link");
    for (const weight of ["400", "500", "700", "900"]) {
      expect(fs.existsSync(path.join(frontendRoot, `src/app/fonts/satoshi-${weight}.woff2`))).toBe(
        true
      );
    }
  });

  it("applies the brand display font to display surfaces in every theme", () => {
    const theme = globalsCss.match(/\n\[data-signal-theme\] \{([\s\S]*?)\n\}/)?.[1] ?? "";
    expect(theme).toContain("--disp: var(--font-satoshi), var(--font-sans)");
    expect(rootSlice).toContain("--disp: var(--font-satoshi), var(--font-sans)");
  });

  it("resolves small uppercase labels through the mono token, not the body font", () => {
    const wizard = fs.readFileSync(
      path.join(frontendRoot, "src/components/onboarding/OnboardingWizard.tsx"),
      "utf8"
    );
    // SIGV2-1054: --font-roboto-mono lives on <body>, so a bare indirection
    // was guaranteed-invalid at :root and mono labels computed as Inter.
    expect(rootSlice).toContain('--mono: var(--font-roboto-mono, "Roboto Mono")');
    expect(globalsCss).toMatch(/--font-mono:\s*var\(--mono\)/);
    for (const label of wizard.matchAll(/className="([^"]*uppercase[^"]*)"/g)) {
      expect(label[1]).toContain("font-mono");
    }
  });

  it("keeps uppercase display headings on the display font, not the mono token", () => {
    expect(globalsCss).not.toMatch(/class\*="uppercase"/);
    expect(globalsCss).toMatch(/--font-display:\s*var\(--font-display\)/);
  });

  it("renders the onboarding form error on the accessible danger tokens", () => {
    const source = fs.readFileSync(
      path.join(frontendRoot, "src/components/onboarding/OnboardingWizard.tsx"),
      "utf8"
    );
    expect(source).toContain('<SignalAlert tone="danger"');
    expect(source).not.toMatch(/danger\/\d/);
    expect(globalsCss).toMatch(
      /\[data-signal-alert="danger"\]\s*\{[^}]*--al-fill:\s*var\(--bad-s\)/
    );
    expect(source).not.toMatch(/rose-\d/);
    expect(contrast(lightToken("bad"), signalToken("bad-s"))).toBeGreaterThanOrEqual(4.5);
    expect(contrast(lightToken("bad"), "#FFFFFF")).toBeGreaterThanOrEqual(4.5);
  });

  it("keeps the approved ink action compliant in normal and hover states", () => {
    // The alert-rule actions use the approved `.btn.pri` treatment: white text
    // on --ink, with black on hover. Both are far past WCAG AA on their own.
    expect(contrast("#FFFFFF", lightToken("ink"))).toBeGreaterThanOrEqual(4.5);
    expect(contrast("#FFFFFF", "#000000")).toBeGreaterThanOrEqual(4.5);
    expect(alertSettings).toContain("bg-(--ink)");
    expect(alertSettings).toContain("hover:bg-black");
    expect(alertSettings).not.toMatch(/emerald-\d/);
  });
});
