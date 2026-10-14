import { describe, expect, it, vi } from "vitest";

import ProjectGeoRedirect from "@/app/(app)/dashboard/projects/[projectId]/geo/page";
import { redirect } from "next/navigation";

vi.mock("next/navigation", () => ({
  redirect: vi.fn(),
}));

describe("ProjectGeoRedirect", () => {
  it("folds the legacy GEO route into the project's AI answers page", async () => {
    await ProjectGeoRedirect({ params: Promise.resolve({ projectId: "42" }) });

    expect(redirect).toHaveBeenCalledWith("/dashboard/projects/42/ai-answers");
  });
});
