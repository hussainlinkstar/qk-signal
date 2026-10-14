import { afterEach, describe, expect, it, vi } from "vitest";

import { HttpLlmProvider } from "./httpLlmProvider";

afterEach(() => {
  vi.restoreAllMocks();
});

describe("HttpLlmProvider", () => {
  it("posts audit context payload to the strategic insights adapter and returns content", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ content: '{"executive_summary":"ok"}' }),
    });
    vi.stubGlobal("fetch", fetchMock);

    const provider = new HttpLlmProvider();
    const response = await provider.complete({ audit_id: 42, project_id: 7 });

    expect(response).toEqual({ content: '{"executive_summary":"ok"}' });
    expect(fetchMock).toHaveBeenCalledWith("/api/ai/strategic-insights", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ audit_id: 42, project_id: 7 }),
    });
  });

  it("uses payload.detail when the adapter returns an upstream-friendly error shape", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: false,
      json: async () => ({ detail: "Provider unavailable right now." }),
    });
    vi.stubGlobal("fetch", fetchMock);

    const provider = new HttpLlmProvider();

    await expect(provider.complete({ audit_id: 42 })).rejects.toThrow(
      "Provider unavailable right now."
    );
  });
});
