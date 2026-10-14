import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AUDIT_DRAFT_STORAGE_KEY } from "@/types/auditWorkspace";
import { useAuditForm } from "@/hooks/useAuditForm";

const { preflightAuditUrlMock, toastSuccessMock, toastWarningMock, toastInfoMock } = vi.hoisted(
  () => ({
    preflightAuditUrlMock: vi.fn(),
    toastSuccessMock: vi.fn(),
    toastWarningMock: vi.fn(),
    toastInfoMock: vi.fn(),
  })
);

vi.mock("@/services/auditService", () => ({
  preflightAuditUrl: preflightAuditUrlMock,
}));

vi.mock("sonner", () => ({
  toast: { success: toastSuccessMock, warning: toastWarningMock, info: toastInfoMock },
}));

describe("useAuditForm model selection", () => {
  beforeEach(() => {
    window.localStorage.clear();
    toastSuccessMock.mockReset();
    toastWarningMock.mockReset();
    toastInfoMock.mockReset();
    preflightAuditUrlMock.mockReset();
    preflightAuditUrlMock.mockResolvedValue({ ok: true });
  });

  it("switches to a single provider on normal click semantics", () => {
    const { result } = renderHook(() =>
      useAuditForm({
        getAuthHeaders: async () => ({}),
      })
    );

    act(() => {
      result.current.toggleModelSelection("openai", { mode: "single" });
    });

    expect(result.current.form.provider).toBe("openai");
    expect(result.current.form.selectedModels).toEqual(["openai"]);
  });

  it("supports consensus toggling when requested explicitly", () => {
    const { result } = renderHook(() =>
      useAuditForm({
        getAuthHeaders: async () => ({}),
      })
    );

    act(() => {
      result.current.toggleModelSelection("google", { mode: "single" });
      result.current.toggleModelSelection("openai", { mode: "toggle" });
    });

    expect(result.current.form.provider).toBe("google");
    expect(result.current.form.selectedModels).toEqual(["google", "openai"]);

    act(() => {
      result.current.toggleModelSelection("google", { mode: "toggle" });
    });

    expect(result.current.form.provider).toBe("openai");
    expect(result.current.form.selectedModels).toEqual(["openai"]);
  });

  it("normalizes legacy tier aliases into fast/smart", () => {
    const { result } = renderHook(() =>
      useAuditForm({
        getAuthHeaders: async () => ({}),
      })
    );

    act(() => {
      result.current.setFormValue("tier", "standard");
    });
    expect(result.current.form.tier).toBe("fast");

    act(() => {
      result.current.setFormValue("tier", "smart");
    });
    expect(result.current.form.tier).toBe("smart");

    act(() => {
      result.current.setFormValue("tier", "deep_judgment");
    });
    expect(result.current.form.tier).toBe("deep_judgment");
  });

  it("copies website URL into brand target URL when switching target mode", () => {
    const { result } = renderHook(() =>
      useAuditForm({
        getAuthHeaders: async () => ({}),
      })
    );

    act(() => {
      result.current.setFormValue("url", "https://thothgraph.com");
      result.current.setFormValue("auditTargetType", "brand");
    });

    expect(result.current.form.auditTargetType).toBe("brand");
    expect(result.current.form.targetUrl).toBe("https://thothgraph.com");
  });

  it("uses targetUrl for preflight in brand mode", async () => {
    const { result } = renderHook(() =>
      useAuditForm({
        getAuthHeaders: async () => ({}),
      })
    );

    act(() => {
      result.current.setFormValue("auditTargetType", "brand");
      result.current.setFormValue("targetName", "Qiko Signal");
      result.current.setFormValue("targetUrl", "https://thothgraph.com");
    });

    await act(async () => {
      const ok = await result.current.verifyUrlPreflight();
      expect(ok).toBe(true);
    });

    expect(preflightAuditUrlMock).toHaveBeenCalledWith("https://thothgraph.com", {});
  });

  it("fails validation when brand fields are missing", async () => {
    const { result } = renderHook(() =>
      useAuditForm({
        getAuthHeaders: async () => ({}),
      })
    );

    act(() => {
      result.current.setFormValue("auditTargetType", "brand");
      result.current.setFormValue("url", "");
      result.current.setFormValue("targetUrl", "");
      result.current.setFormValue("targetName", "");
    });

    await act(async () => {
      const valid = await result.current.validateForm();
      expect(valid).toBe(false);
    });

    expect(result.current.formErrors.targetName?.message).toBe(
      "Brand name is required for brand assessments."
    );
    expect(result.current.formErrors.targetUrl?.message).toBeUndefined();
  });

  it("allows brand validation without a website URL when a target name is present", async () => {
    const { result } = renderHook(() =>
      useAuditForm({
        getAuthHeaders: async () => ({}),
      })
    );

    act(() => {
      result.current.setFormValue("auditTargetType", "brand");
      result.current.setFormValue("url", "");
      result.current.setFormValue("targetUrl", "");
      result.current.setFormValue("targetName", "Qiko Signal");
    });

    await act(async () => {
      const valid = await result.current.validateForm();
      expect(valid).toBe(true);
    });

    expect(result.current.formErrors.targetName?.message).toBeUndefined();
    expect(result.current.formErrors.targetUrl?.message).toBeUndefined();
  });

  it("falls back to site classification without calling entities extract when classification is confident", async () => {
    const fetchSpy = vi
      .spyOn(globalThis, "fetch")
      .mockImplementation(async (input: RequestInfo | URL) => {
        const requestUrl = String(input);

        if (requestUrl.includes("/api/v1/audit/pre-scan")) {
          return new Response(
            JSON.stringify({
              detail: "Unable to fetch content from URL: https://app.thothgraph.com",
            }),
            { status: 400, headers: { "Content-Type": "application/json" } }
          );
        }

        if (requestUrl.includes("/api/v1/site/classify")) {
          return new Response(JSON.stringify({ category: "Local Business", confidence: 0.92 }), {
            status: 200,
            headers: { "Content-Type": "application/json" },
          });
        }

        if (requestUrl.includes("/api/v1/entities/extract")) {
          return new Response(
            JSON.stringify({ detail: "Should not be called in this scenario." }),
            {
              status: 500,
              headers: { "Content-Type": "application/json" },
            }
          );
        }

        throw new Error(`Unexpected fetch call: ${requestUrl}`);
      });

    const { result } = renderHook(() =>
      useAuditForm({
        getAuthHeaders: async () => ({}),
      })
    );

    act(() => {
      result.current.setFormValue("url", "https://app.thothgraph.com");
    });

    await act(async () => {
      await result.current.runUrlAutoDetection(true);
    });

    expect(result.current.form.category).toBe("SaaS - B2B Software Platform");
    expect(result.current.form.language).toBe("en");
    expect(result.current.form.market).toBe("");
    expect(
      fetchSpy.mock.calls.some(([input]) => String(input).includes("/api/v1/entities/extract"))
    ).toBe(false);

    fetchSpy.mockRestore();
  });
});

// SIGV2-1160: the scan setup autosave must keep persisting the draft without
// interrupting the customer on every change.
describe("useAuditForm draft autosave", () => {
  beforeEach(() => {
    window.localStorage.clear();
    toastSuccessMock.mockReset();
    toastWarningMock.mockReset();
    toastInfoMock.mockReset();
    preflightAuditUrlMock.mockReset();
    preflightAuditUrlMock.mockResolvedValue({ ok: true });
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  // Past the 700ms debounce, and well past the 8s throttle the per-change
  // toast used to be gated on, so a reintroduced throttle fails these tests
  // instead of hiding behind a short clock.
  const flushAutosave = () => {
    act(() => {
      vi.advanceTimersByTime(9_000);
    });
  };

  // SIGV2-1224: opening the page and touching nothing is not a save. The
  // autosave used to compare the initial form against an empty baseline, so
  // every visit persisted a default draft and announced it.
  it("stays silent and writes nothing when the form was never touched", () => {
    renderHook(() =>
      useAuditForm({
        getAuthHeaders: async () => ({}),
      })
    );
    flushAutosave();

    expect(toastSuccessMock).not.toHaveBeenCalled();
    expect(window.localStorage.getItem(AUDIT_DRAFT_STORAGE_KEY)).toBeNull();
  });

  it("keeps saving every change to the draft", () => {
    const { result } = renderHook(() =>
      useAuditForm({
        getAuthHeaders: async () => ({}),
      })
    );

    act(() => {
      result.current.setFormValue("url", "https://northwind.example");
    });
    flushAutosave();

    expect(JSON.parse(window.localStorage.getItem(AUDIT_DRAFT_STORAGE_KEY) ?? "{}").url).toBe(
      "https://northwind.example"
    );

    act(() => {
      result.current.setFormValue("targetName", "Northwind");
    });
    flushAutosave();

    const stored = JSON.parse(window.localStorage.getItem(AUDIT_DRAFT_STORAGE_KEY) ?? "{}");
    expect(stored.url).toBe("https://northwind.example");
    expect(stored.targetName).toBe("Northwind");
  });

  it("confirms the save once per visit instead of on every change", () => {
    const { result } = renderHook(() =>
      useAuditForm({
        getAuthHeaders: async () => ({}),
      })
    );

    act(() => {
      result.current.setFormValue("url", "https://northwind.example");
    });
    flushAutosave();

    expect(toastSuccessMock).toHaveBeenCalledTimes(1);
    expect(toastSuccessMock).toHaveBeenCalledWith("Assessment draft saved.", {
      id: "audit-draft-saved",
    });

    act(() => {
      result.current.setFormValue("targetName", "Northwind");
    });
    flushAutosave();
    act(() => {
      result.current.setFormValue("tier", "smart");
    });
    flushAutosave();
    act(() => {
      result.current.setFormValue("market", "United States");
    });
    flushAutosave();

    expect(toastSuccessMock).toHaveBeenCalledTimes(1);
  });

  // SIGV2-1171: a failed save is reported persistently to the page, not as a
  // toast that fades; a later successful write clears the flag again.
  it("flags a failed save and clears the flag when a later write lands", () => {
    // jsdom's localStorage is a MemoryStorage, not a Storage, so the spy goes
    // on the object itself rather than Storage.prototype.
    const setItemSpy = vi.spyOn(window.localStorage, "setItem").mockImplementation(() => {
      throw new DOMException("quota", "QuotaExceededError");
    });
    try {
      const { result } = renderHook(() =>
        useAuditForm({
          getAuthHeaders: async () => ({}),
        })
      );

      act(() => {
        result.current.setFormValue("url", "https://northwind.example");
      });
      flushAutosave();

      expect(result.current.draftSaveFailed).toBe(true);
      expect(toastWarningMock).not.toHaveBeenCalled();

      setItemSpy.mockRestore();
      act(() => {
        result.current.setFormValue("targetName", "Northwind");
      });
      flushAutosave();

      expect(result.current.draftSaveFailed).toBe(false);
    } finally {
      setItemSpy.mockRestore();
    }
  });
});

// SIGV2-1170: a launch link's explicit target outranks a stored draft. The
// earlier order restored the draft first and only prefilled empty fields, so
// `?url=test.com` opened the form showing a different project's site.
describe("useAuditForm draft restore precedence", () => {
  const storeDraft = (draft: Record<string, unknown>) =>
    window.localStorage.setItem(AUDIT_DRAFT_STORAGE_KEY, JSON.stringify(draft));

  beforeEach(() => {
    window.localStorage.clear();
    toastSuccessMock.mockReset();
    toastWarningMock.mockReset();
    toastInfoMock.mockReset();
    preflightAuditUrlMock.mockReset();
    preflightAuditUrlMock.mockResolvedValue({ ok: true });
  });

  it("restores a stored draft when the link names no target", () => {
    storeDraft({ url: "https://josepehmews.com", targetUrl: "https://josepehmews.com" });

    const { result } = renderHook(() =>
      useAuditForm({
        getAuthHeaders: async () => ({}),
      })
    );

    expect(result.current.form.url).toBe("https://josepehmews.com");
    expect(toastSuccessMock).toHaveBeenCalledWith("Assessment draft restored.", {
      id: "audit-draft-restored",
    });
  });

  it("restores the draft when the link names the same target", () => {
    storeDraft({ url: "https://test.com", targetUrl: "https://test.com" });

    const { result } = renderHook(() =>
      useAuditForm({
        getAuthHeaders: async () => ({}),
        linkTarget: "test.com",
      })
    );

    expect(result.current.form.url).toBe("https://test.com");
    expect(toastInfoMock).not.toHaveBeenCalled();
    expect(toastSuccessMock).not.toHaveBeenCalledWith(
      expect.stringContaining("set aside"),
      expect.anything()
    );
  });

  it("sets a different site's draft aside and says so", () => {
    storeDraft({ url: "https://josepehmews.com", targetUrl: "https://josepehmews.com" });

    const { result } = renderHook(() =>
      useAuditForm({
        getAuthHeaders: async () => ({}),
        linkTarget: "https://test.com",
      })
    );

    // The link's target wins: the stale draft's site is never restored.
    expect(result.current.form.url).toBe("");
    expect(result.current.form.targetUrl).toBe("");
    // SIGV2-1171: nothing succeeded here. A draft the customer wrote was put
    // aside, which is information, and claiming it as a success is the tone
    // collapse that leaves a real success and a real failure looking alike.
    expect(toastInfoMock).toHaveBeenCalledWith(
      "Saved draft for https://josepehmews.com set aside - this link opens https://test.com.",
      { id: "audit-draft-set-aside" }
    );
    expect(toastSuccessMock).not.toHaveBeenCalled();
  });

  it("sets a brand draft aside when the link names a different brand", () => {
    // A brand-mode draft compares on its target name, not its URL.
    storeDraft({
      auditTargetType: "brand",
      targetName: "Josepeh Mews",
      url: "",
      targetUrl: "",
    });

    const { result } = renderHook(() =>
      useAuditForm({
        getAuthHeaders: async () => ({}),
        linkTarget: "Qiko Signal",
      })
    );

    expect(result.current.form.targetName).toBe("");
    expect(toastInfoMock).toHaveBeenCalledWith(
      "Saved draft for Josepeh Mews set aside - this link opens Qiko Signal.",
      { id: "audit-draft-set-aside" }
    );
    expect(toastSuccessMock).not.toHaveBeenCalled();
  });
});
