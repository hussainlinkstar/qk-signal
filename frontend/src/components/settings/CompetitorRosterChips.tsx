"use client";

import React, { useCallback, useEffect, useState } from "react";

import { useAuth } from "@/components/auth/custom-auth";
import { resolvePlanCapabilities } from "@/lib/planCapabilities";
import {
  deleteProjectCompetitor,
  fetchProjectCompetitors,
  type ProjectCompetitorListItem,
} from "@/services/workspaceService";

/**
 * The Product tab's read of the roster: the approved `.chips` list - one
 * removable `.comp` pill per tracked competitor plus the dashed add chip.
 * Adding lands on the Brand tab's Competitive Intelligence card, which owns
 * the full roster form, benchmark automation and digest cadence.
 */
export default function CompetitorRosterChips({
  projectId,
  onAddCompetitor,
}: {
  projectId: string;
  onAddCompetitor?: () => void;
}) {
  const { getToken, isLoading: authLoading, isSignedIn, user } = useAuth();
  const planLocked = !resolvePlanCapabilities(user?.subscription_plan).has_competitor_analysis;
  const [competitors, setCompetitors] = useState<ProjectCompetitorListItem[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [removingId, setRemovingId] = useState<number | null>(null);

  const load = useCallback(async () => {
    if (!projectId || authLoading || !isSignedIn || planLocked) {
      setLoaded(true);
      return;
    }
    try {
      const token = await getToken();
      const rows = await fetchProjectCompetitors(projectId, {
        Authorization: `Bearer ${token}`,
      });
      setCompetitors(rows);
    } catch {
      // A locked or unreachable roster renders as no chips; the Brand tab
      // card reports errors with its own machinery.
    } finally {
      setLoaded(true);
    }
  }, [authLoading, getToken, isSignedIn, planLocked, projectId]);

  useEffect(() => {
    void load();
  }, [load]);

  const remove = async (id: number) => {
    setRemovingId(id);
    try {
      const token = await getToken();
      await deleteProjectCompetitor(projectId, id, { Authorization: `Bearer ${token}` });
      setCompetitors((current) => current.filter((row) => row.id !== id));
    } finally {
      setRemovingId(null);
    }
  };

  if (!loaded) return null;

  return (
    <div className="flex flex-wrap gap-2 ltr:[direction:ltr]">
      {competitors.map((competitor) => (
        <span
          key={competitor.id}
          className="inline-flex h-8 items-center gap-2 rounded-[999px] border border-(--line) pr-1.5 pl-2.5 text-[13px] font-semibold text-(--t-1)"
        >
          {competitor.display_name}
          <button
            type="button"
            aria-label={`Remove ${competitor.display_name}`}
            disabled={removingId === competitor.id}
            className="flex h-[18px] w-[18px] cursor-pointer items-center justify-center rounded-full bg-(--line-2) text-(--t-3) hover:text-(--t-1) disabled:opacity-50 max-md:h-7 max-md:w-7"
            onClick={() => void remove(competitor.id)}
          >
            ×
          </button>
        </span>
      ))}
      <button
        type="button"
        className="inline-flex h-8 cursor-pointer items-center rounded-[999px] border border-dashed border-(--line) px-2.5 text-[13px] font-semibold text-(--t-2) hover:text-(--t-1) max-md:min-h-11"
        onClick={onAddCompetitor}
      >
        + Add competitor
      </button>
    </div>
  );
}
