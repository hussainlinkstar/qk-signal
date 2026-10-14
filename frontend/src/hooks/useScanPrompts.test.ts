import { renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useScanPrompts } from "@/hooks/useScanPrompts";
import type { SearchTypeCoverageEntry } from "@/types/monitoring";

const { fetchVisibilityQueriesMock } = vi.hoisted(() => ({
  fetchVisibilityQueriesMock: vi.fn(),
}));

vi.mock("@/services/monitoringService", () => ({
  fetchVisibilityQueries: (...args: unknown[]) => fetchVisibilityQueriesMock(...args),
}));

const COVERAGE: SearchTypeCoverageEntry[] = [
  {
    id: "brand",
    label: "Brand",
    premium: false,
    prompt_count: 1,
    covered: true,
    suggested_prompt: null,
  },
  {
    id: "comparison",
    label: "Comparison",
    premium: false,
    prompt_count: 0,
    covered: false,
    suggested_prompt: "how does Signal compare to a rank tracker",
  },
];

const PAYLOAD = {
  project_id: 42,
  queries: [
    {
      id: 1,
      project_id: 42,
      query_text: "best boutique hotels near the harbour",
      query_type: "aeo" as const,
      providers: ["openai" as const],
      is_active: true,
      created_at: null,
      updated_at: null,
    },
  ],
  coverage: COVERAGE,
  entitlements: {
    plan: "plan_standard",
    plan_label: "Standard",
    max_queries: 10,
    used_queries: 1,
    remaining_queries: 9,
    allowed_providers: ["openai" as const],
    is_locked: false,
    estimated_cost_per_check: {},
  },
};

const authHeaders = vi.fn().mockResolvedValue({ Authorization: "Bearer t" });

describe("useScanPrompts", () => {
  beforeEach(() => {
    vi.mocked(fetchVisibilityQueriesMock).mockReset();
  });

  // SIGV2-1186: the same response carries which of the five scored types no
  // prompt maps to, and the setup surface states that before the launch.
  it("passes the served search-type coverage through with the prompts", async () => {
    vi.mocked(fetchVisibilityQueriesMock).mockResolvedValue(PAYLOAD);

    const { result } = renderHook(() =>
      useScanPrompts({ projectId: 42, isSignedIn: true, getAuthHeaders: authHeaders })
    );

    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(fetchVisibilityQueriesMock).toHaveBeenCalledWith(
      42,
      { Authorization: "Bearer t" },
      false
    );
    expect(result.current.coverage).toEqual(COVERAGE);
  });

  it("keeps coverage empty when the response omits it", async () => {
    const { coverage: _omitted, ...withoutCoverage } = PAYLOAD;
    vi.mocked(fetchVisibilityQueriesMock).mockResolvedValue(withoutCoverage);

    const { result } = renderHook(() =>
      useScanPrompts({ projectId: 42, isSignedIn: true, getAuthHeaders: authHeaders })
    );

    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.coverage).toEqual([]);
  });

  // A failed read means no coverage claim, never a stale or invented one.
  it("clears coverage when the read fails", async () => {
    vi.mocked(fetchVisibilityQueriesMock).mockRejectedValue(new Error("endpoint unreachable"));

    const { result } = renderHook(() =>
      useScanPrompts({ projectId: 42, isSignedIn: true, getAuthHeaders: authHeaders })
    );

    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.coverage).toEqual([]);
    expect(result.current.error).toBe("endpoint unreachable");
  });

  it("fetches nothing, and claims no coverage, without a project or a session", async () => {
    const { result } = renderHook(() =>
      useScanPrompts({ projectId: undefined, isSignedIn: false, getAuthHeaders: authHeaders })
    );

    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(fetchVisibilityQueriesMock).not.toHaveBeenCalled();
    expect(result.current.coverage).toEqual([]);
  });
  // SIGV2-1287 -------------------------------------------------------------
  // Edward: "I then edited at the bottom, and saved, and all the prompts
  // disappeared". Nothing was deleted. The form derives its project from the
  // `projectId` query parameter and nothing else, so a navigation that did
  // not carry it forward turned the project to null, emptied the list, and
  // had the panel announce "this scan has no project yet" to someone whose
  // project held prompts. Indistinguishable from losing their work.
  it("keeps the project it was opened with when the URL stops naming one", async () => {
    fetchVisibilityQueriesMock.mockResolvedValue(PAYLOAD);

    const { result, rerender } = renderHook(
      ({ projectId }: { projectId?: number }) =>
        useScanPrompts({ projectId, isSignedIn: true, getAuthHeaders: authHeaders }),
      { initialProps: { projectId: 42 as number | undefined } }
    );

    await waitFor(() => expect(result.current.prompts).toHaveLength(1));
    expect(result.current.projectId).toBe(42);

    // The query parameter goes away. The project does not.
    rerender({ projectId: undefined });

    await waitFor(() => expect(result.current.projectId).toBe(42));
    expect(result.current.prompts).toHaveLength(1);
  });

  it("follows a deliberate change of project", async () => {
    fetchVisibilityQueriesMock.mockResolvedValue(PAYLOAD);

    const { result, rerender } = renderHook(
      ({ projectId }: { projectId?: number }) =>
        useScanPrompts({ projectId, isSignedIn: true, getAuthHeaders: authHeaders }),
      { initialProps: { projectId: 42 as number | undefined } }
    );

    await waitFor(() => expect(result.current.projectId).toBe(42));

    // A different id is a change of subject, not a lost parameter, so it wins.
    rerender({ projectId: 7 });

    await waitFor(() => expect(result.current.projectId).toBe(7));
  });

  it("starts with no project when it was never given one", async () => {
    const { result } = renderHook(() =>
      useScanPrompts({ isSignedIn: true, getAuthHeaders: authHeaders })
    );

    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.projectId).toBeNull();
    expect(result.current.prompts).toHaveLength(0);
    // And nothing is fetched on no project.
    expect(fetchVisibilityQueriesMock).not.toHaveBeenCalled();
  });
});
