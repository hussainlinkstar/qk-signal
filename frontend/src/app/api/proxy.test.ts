import { afterEach, describe, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";

import { proxyRequest } from "./proxy";

describe("proxyRequest", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("logs forwarded generate-complex payloads when the backend returns 422", async () => {
    const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});
    const fetchSpy = vi.spyOn(global, "fetch").mockResolvedValue(
      new Response(
        JSON.stringify({
          detail: [
            {
              loc: ["body", "report_options", "primary_color"],
              msg: "primary_color must be a valid hex color (e.g. #0EA5E9).",
            },
          ],
        }),
        {
          status: 422,
          headers: {
            "Content-Type": "application/json",
            "X-Request-ID": "req-422",
          },
        }
      )
    );

    const requestBody = {
      audit_ids: [301],
      template_type: "Executive",
      report_options: {
        mode: "individual",
        sections: ["overview"],
        primary_color: "blue",
      },
    };

    const request = new NextRequest("http://localhost:3000/api/v1/reports/generate-complex", {
      method: "POST",
      headers: {
        "content-type": "application/json",
      },
      body: JSON.stringify(requestBody),
    });

    const response = await proxyRequest(request, "/reports/generate-complex", { timeoutMs: 1000 });

    expect(response.status).toBe(422);
    expect(fetchSpy).toHaveBeenCalledWith(
      new URL("http://localhost:8000/api/v1/reports/generate-complex"),
      expect.objectContaining({
        method: "POST",
      })
    );
    expect(warnSpy).toHaveBeenCalledWith(
      "BFF proxy generate-complex validation failure",
      expect.objectContaining({
        method: "POST",
        requestId: "req-422",
        targetUrl: "http://localhost:8000/api/v1/reports/generate-complex",
        requestBody,
        responseBody: {
          detail: [
            {
              loc: ["body", "report_options", "primary_color"],
              msg: "primary_color must be a valid hex color (e.g. #0EA5E9).",
            },
          ],
        },
      })
    );
  });
});
