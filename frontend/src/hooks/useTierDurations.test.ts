import { renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { getTierDurations } from "@/services/auditService";
import { formatTierDurationRange, useTierDurations } from "@/hooks/useTierDurations";

vi.mock("@/services/auditService", async () => {
  const actual =
    await vi.importActual<typeof import("@/services/auditService")>("@/services/auditService");
  return {
    ...actual,
    getTierDurations: vi.fn(),
  };
});

const PAYLOAD = {
  statistic: "p25_p75_minutes",
  min_sample_size: 20,
  window_days: 90,
  tiers: {
    fast: {
      low_minutes: 4,
      high_minutes: 9,
      median_minutes: 6,
      sample_size: 41,
      window_days: 90,
      computed_at: "2026-10-13T08:00:00Z",
    },
    smart: {
      low_minutes: 12,
      high_minutes: 21,
      median_minutes: 16,
      sample_size: 58,
      window_days: 90,
      computed_at: "2026-10-13T08:00:00Z",
    },
  },
};

describe("useTierDurations", () => {
  beforeEach(() => {
    vi.mocked(getTierDurations).mockReset();
  });

  it("serves the published tiers once the read lands", async () => {
    vi.mocked(getTierDurations).mockResolvedValue(PAYLOAD);
    const getAuthHeaders = vi.fn().mockResolvedValue({ Authorization: "Bearer t" });

    const { result } = renderHook(() => useTierDurations({ isSignedIn: true, getAuthHeaders }));

    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(getTierDurations).toHaveBeenCalledWith({ Authorization: "Bearer t" });
    expect(result.current.durations).toEqual(PAYLOAD.tiers);
  });

  it("fetches nothing for a signed-out visitor", async () => {
    const { result } = renderHook(() =>
      useTierDurations({ isSignedIn: false, getAuthHeaders: vi.fn() })
    );

    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(getTierDurations).not.toHaveBeenCalled();
    expect(result.current.durations).toBeNull();
  });

  // SIGV2-1177: a failed read means no figure, never an invented one and
  // never a blocker. The surfaces simply state no duration.
  it("states nothing when the read fails", async () => {
    vi.mocked(getTierDurations).mockRejectedValue(new Error("endpoint unreachable"));

    const { result } = renderHook(() =>
      useTierDurations({ isSignedIn: true, getAuthHeaders: vi.fn().mockResolvedValue({}) })
    );

    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.durations).toBeNull();
  });
});

describe("formatTierDurationRange", () => {
  it("renders the quartile range in whole minutes", () => {
    expect(formatTierDurationRange(PAYLOAD.tiers.fast)).toBe("4-9 min");
    expect(formatTierDurationRange(PAYLOAD.tiers.smart)).toBe("12-21 min");
  });

  it("renders a single figure when the quartiles round to the same minute", () => {
    expect(
      formatTierDurationRange({ ...PAYLOAD.tiers.fast, low_minutes: 6, high_minutes: 6 })
    ).toBe("6 min");
  });
});
