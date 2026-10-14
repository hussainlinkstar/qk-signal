import { describe, expect, it } from "vitest";

import { parseErrorDetail } from "./http";

describe("parseErrorDetail", () => {
  it("returns string detail responses unchanged", async () => {
    const response = new Response(JSON.stringify({ detail: "No matching audits found." }), {
      status: 404,
      headers: {
        "Content-Type": "application/json",
      },
    });

    await expect(parseErrorDetail(response, "fallback")).resolves.toBe("No matching audits found.");
  });

  it("formats FastAPI validation error arrays into a readable message", async () => {
    const response = new Response(
      JSON.stringify({
        detail: [
          {
            loc: ["body", "report_options", "primary_color"],
            msg: "primary_color must be a valid hex color (e.g. #0EA5E9).",
          },
          {
            loc: ["body", "template_type"],
            msg: "Input should be 'Technical', 'Executive' or 'Comparative'",
          },
        ],
      }),
      {
        status: 422,
        headers: {
          "Content-Type": "application/json",
        },
      }
    );

    await expect(parseErrorDetail(response, "fallback")).resolves.toBe(
      "primary_color must be a valid hex color (e.g. #0EA5E9). | Template type must be 'Technical', 'Executive' or 'Comparative'."
    );
  });

  it("rewrites schema validation strings in plain English without the field path", async () => {
    const response = new Response(
      JSON.stringify({
        detail: [
          {
            loc: ["body", "target_country"],
            msg: "String should have at most 2 characters",
          },
        ],
      }),
      {
        status: 422,
        headers: { "Content-Type": "application/json" },
      }
    );

    const message = await parseErrorDetail(response, "fallback");

    expect(message).toBe("Target country must be at most 2 characters.");
    expect(message).not.toContain("body.");
    expect(message).not.toContain("String should");
  });
});
