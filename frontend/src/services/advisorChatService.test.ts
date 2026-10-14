import { afterEach, describe, expect, it, vi } from "vitest";

import { fetchAdvisorChatHistory, sendAdvisorChat } from "./advisorChatService";

afterEach(() => {
  vi.restoreAllMocks();
});

describe("sendAdvisorChat", () => {
  it("posts the message + history to the audit-scoped proxy endpoint", async () => {
    const fetchMock = vi
      .fn()
      .mockImplementation(async (input: RequestInfo | URL, init?: RequestInit) => {
        expect(String(input)).toBe("/api/audits/42/advisor-chat");
        expect(init?.method).toBe("POST");
        expect(init?.body).toBe(
          JSON.stringify({
            message: "Why am I losing comparison queries?",
            history: [{ role: "user", content: "Earlier question" }],
          })
        );
        return {
          ok: true,
          status: 200,
          json: async () => ({
            reply: "You are missing comparison schema.",
            citations: ["finding-12", "finding-7"],
          }),
        };
      });
    vi.stubGlobal("fetch", fetchMock);

    const result = await sendAdvisorChat(
      42,
      {
        message: "Why am I losing comparison queries?",
        history: [{ role: "user", content: "Earlier question" }],
      },
      { Authorization: "Bearer token" }
    );

    expect(result.reply).toBe("You are missing comparison schema.");
    expect(result.citations).toEqual(["finding-12", "finding-7"]);
  });

  it("surfaces a 402 plan-gate as an HttpRequestError", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: false,
      status: 402,
      json: async () => ({ detail: "Advisor chat is available on Standard." }),
    });
    vi.stubGlobal("fetch", fetchMock);

    await expect(sendAdvisorChat(42, { message: "hi" }, {})).rejects.toMatchObject({ status: 402 });
  });

  it("surfaces a 403 non-owner error as an HttpRequestError", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: false,
      status: 403,
      json: async () => ({ detail: "Not your audit." }),
    });
    vi.stubGlobal("fetch", fetchMock);

    await expect(sendAdvisorChat(42, { message: "hi" }, {})).rejects.toMatchObject({ status: 403 });
  });
});

describe("fetchAdvisorChatHistory", () => {
  it("GETs the audit-scoped history proxy endpoint and returns the turns", async () => {
    const fetchMock = vi
      .fn()
      .mockImplementation(async (input: RequestInfo | URL, init?: RequestInit) => {
        expect(String(input)).toBe("/api/audits/42/advisor-chat/history");
        expect(init?.method).toBe("GET");
        expect(init?.body).toBeUndefined();
        return {
          ok: true,
          status: 200,
          json: async () => ({
            messages: [
              { role: "user", content: "Earlier question", citations: [] },
              { role: "assistant", content: "Earlier reply", citations: ["finding-3"] },
            ],
          }),
        };
      });
    vi.stubGlobal("fetch", fetchMock);

    const result = await fetchAdvisorChatHistory(42, { Authorization: "Bearer token" });

    expect(result.messages).toHaveLength(2);
    expect(result.messages[0]).toEqual({
      role: "user",
      content: "Earlier question",
      citations: [],
    });
    expect(result.messages[1].citations).toEqual(["finding-3"]);
  });

  it("surfaces a 402 plan-gate as an HttpRequestError", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: false,
      status: 402,
      json: async () => ({ detail: "Advisor chat is available on Standard." }),
    });
    vi.stubGlobal("fetch", fetchMock);

    await expect(fetchAdvisorChatHistory(42, {})).rejects.toMatchObject({ status: 402 });
  });
});
