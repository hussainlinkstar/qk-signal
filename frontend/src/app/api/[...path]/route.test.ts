import { beforeEach, describe, expect, it, vi } from "vitest";

const { proxyRequestMock } = vi.hoisted(() => ({
  proxyRequestMock: vi.fn(),
}));

vi.mock("../proxy", () => ({
  PROXY_TIMEOUTS: {
    default: 90000,
    short: 5000,
  },
  proxyRequest: proxyRequestMock,
}));

import { GET } from "./route";

describe("catch-all api route timeout selection", () => {
  beforeEach(() => {
    proxyRequestMock.mockReset();
  });

  it("uses default timeout for strategic insights generation", async () => {
    proxyRequestMock.mockResolvedValue(new Response(null, { status: 200 }));

    await GET({} as never, { params: Promise.resolve({ path: ["ai", "strategic-insights"] }) });

    expect(proxyRequestMock).toHaveBeenCalledWith(expect.anything(), "/ai/strategic-insights", {
      timeoutMs: 90000,
    });
  });

  it("keeps short timeout for lightweight non-AI endpoints", async () => {
    proxyRequestMock.mockResolvedValue(new Response(null, { status: 200 }));

    await GET({} as never, { params: Promise.resolve({ path: ["audit", "jobs"] }) });

    expect(proxyRequestMock).toHaveBeenCalledWith(expect.anything(), "/audit/jobs", {
      timeoutMs: 5000,
    });
  });
});
