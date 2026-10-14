import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";

const renderSwitcher = async (rtlEnabled: boolean) => {
  vi.doMock("@/lib/i18nFlags", async () => {
    const actual = await vi.importActual<typeof import("@/lib/i18nFlags")>("@/lib/i18nFlags");
    return { ...actual, RTL_ENABLED: rtlEnabled };
  });
  const { default: LanguageSwitcher } = await import("@/components/LanguageSwitcher");
  return render(<LanguageSwitcher />);
};

describe("LanguageSwitcher", () => {
  beforeEach(() => {
    vi.resetModules();
  });

  afterEach(() => {
    vi.doUnmock("@/lib/i18nFlags");
  });

  it("renders nothing when the RTL flag is off", async () => {
    const { container } = await renderSwitcher(false);
    expect(container).toBeEmptyDOMElement();
  });

  it("renders en and ar options, and no Romanian, when the RTL flag is on", async () => {
    await renderSwitcher(true);

    const group = screen.getByRole("group", { name: "Language" });
    expect(group).toBeInTheDocument();

    expect(screen.getByRole("button", { name: "English" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Arabic" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Romanian" })).not.toBeInTheDocument();
  });

  describe("flag default (env read at module load, unmocked)", () => {
    const ENV = "NEXT_PUBLIC_ENABLE_RTL";

    afterEach(() => {
      delete process.env[ENV];
      vi.resetModules();
    });

    it("is on when NEXT_PUBLIC_ENABLE_RTL is unset", async () => {
      delete process.env[ENV];
      vi.resetModules();
      const { RTL_ENABLED } = await import("@/lib/i18nFlags");
      expect(RTL_ENABLED).toBe(true);
    });

    it('is off only when NEXT_PUBLIC_ENABLE_RTL is "false"', async () => {
      process.env[ENV] = "false";
      vi.resetModules();
      const { RTL_ENABLED } = await import("@/lib/i18nFlags");
      expect(RTL_ENABLED).toBe(false);
    });

    it("renders the switcher with the env unset (shipped default)", async () => {
      delete process.env[ENV];
      vi.resetModules();
      const { default: LanguageSwitcher } = await import("@/components/LanguageSwitcher");
      render(<LanguageSwitcher />);
      expect(screen.getByRole("group", { name: "Language" })).toBeInTheDocument();
      expect(screen.getByRole("button", { name: "Arabic" })).toBeInTheDocument();
    });

    it('renders nothing with the env set to "false" (kill switch)', async () => {
      process.env[ENV] = "false";
      vi.resetModules();
      const { default: LanguageSwitcher } = await import("@/components/LanguageSwitcher");
      const { container } = render(<LanguageSwitcher />);
      expect(container).toBeEmptyDOMElement();
    });
  });
});
