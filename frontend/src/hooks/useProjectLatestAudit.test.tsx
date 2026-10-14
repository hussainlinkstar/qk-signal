import { renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useProjectLatestAudit } from "@/hooks/useProjectLatestAudit";
import { fetchProjectById, fetchProjectLatestAudit } from "@/services/workspaceService";

vi.mock("@/components/auth/custom-auth", () => ({
  useAuth: () => ({
    getToken: vi.fn().mockResolvedValue("token-123"),
    isSignedIn: true,
    isLoading: false,
  }),
}));

vi.mock("@/services/workspaceService", () => ({
  fetchProjectById: vi.fn(),
  fetchProjectLatestAudit: vi.fn(),
  fetchProjectLatestAuditSelection: vi.fn(),
}));

const deferred = <T,>() => {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => {
    resolve = done;
  });
  return { promise, resolve };
};

describe("useProjectLatestAudit", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("ignores a stale project response after navigating to another project", async () => {
    const projectA = deferred<any>();
    const auditA = deferred<any>();
    vi.mocked(fetchProjectById).mockImplementation((projectId) =>
      projectId === "1" ? projectA.promise : Promise.resolve({ id: 2, name: "Project B" } as any)
    );
    vi.mocked(fetchProjectLatestAudit).mockImplementation((projectId) =>
      projectId === "1" ? auditA.promise : Promise.resolve({ id: 202, project_id: 2 } as any)
    );

    const { result, rerender } = renderHook(({ projectId }) => useProjectLatestAudit(projectId), {
      initialProps: { projectId: "1" },
    });

    rerender({ projectId: "2" });
    await waitFor(() => expect(result.current.project?.id).toBe(2));

    projectA.resolve({ id: 1, name: "Project A" } as any);
    auditA.resolve({ id: 101, project_id: 1 } as any);
    await Promise.resolve();
    await Promise.resolve();

    expect(result.current.project?.id).toBe(2);
    expect(result.current.latestAudit?.project_id).toBe(2);
  });
});
