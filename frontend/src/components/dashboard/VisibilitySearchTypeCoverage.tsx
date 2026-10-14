"use client";

import React, { useState } from "react";

import Badge from "@/components/ui/Badge";
import Button from "@/components/ui/Button";
import Card from "@/components/ui/Card";
import {
  CARD_CONTAINER_PRESETS,
  CARD_LABEL_CLASS,
  CARD_SUBSECTION_CLASS,
  DASHBOARD_CARD_CLASS,
} from "@/components/ui/cardStyleTokens";
import { TYPO } from "@/components/ui/typographyTokens";
import { SEARCH_TYPE_DESCRIPTIONS } from "@/components/dashboard/visibilityUtils";
import type { SearchTypeCoverageEntry } from "@/types/monitoring";

export type VisibilitySearchTypeCoverageProps = {
  coverage: SearchTypeCoverageEntry[];
  loading?: boolean;
  /** Fill every gap at once. Omit to hide the action (e.g. read-only roles). */
  onGenerateAll?: () => Promise<void> | void;
  /** Fill one gap, pre-filled with the suggestion shown next to it. */
  onFillGap?: (entry: SearchTypeCoverageEntry) => Promise<void> | void;
  /** Stated as served by the API (plan locked, cap reached), never inferred here. */
  capReached?: boolean;
  locked?: boolean;
};

/**
 * Search-type coverage, stated before a scan runs (SIGV2-1186).
 *
 * The defect this answers: the five search-type cards on the AIO drilldown each
 * reported a score or "unmeasured", and nothing told the customer that a type
 * read as unmeasured because none of their prompts was about it. Edward put it
 * plainly: if nothing they asked leads to an answer about their buyers'
 * problems, we cannot rank them on it. So the gap is named here, with the
 * prompt that would close it, on the surface where prompts are managed, rather
 * than being discovered after a scan has already run.
 *
 * It renders only what the API serves. `suggested_prompt` comes from the
 * backend's own base-prompt catalogue, so the sentence offered here is exactly
 * the one that would be stored. Nothing is estimated and no score is shown:
 * this component is about what is *measured*, not how well.
 */
export default function VisibilitySearchTypeCoverage({
  coverage,
  loading = false,
  onGenerateAll,
  onFillGap,
  capReached = false,
  locked = false,
}: VisibilitySearchTypeCoverageProps) {
  const [busy, setBusy] = useState<string | null>(null);

  const covered = coverage.filter((entry) => entry.covered).length;
  const gaps = coverage.filter((entry) => !entry.covered);

  const run = async (key: string, action: () => Promise<void> | void) => {
    setBusy(key);
    try {
      await action();
    } finally {
      setBusy(null);
    }
  };

  return (
    <Card
      className={`${CARD_CONTAINER_PRESETS.primary} ${DASHBOARD_CARD_CLASS} border-(--border) bg-(--card)`}
    >
      <div className="space-y-2">
        <p className={CARD_LABEL_CLASS}>Search types</p>
        <h2 className={TYPO.sectionTitle}>What your prompts actually cover</h2>
        <p className="text-sm text-(--muted-foreground)">
          A search type is only scored when at least one of your prompts asks about it. A type with
          no prompt is not a low score, it is nothing measured.
        </p>
      </div>

      {loading ? (
        <div
          className={`${CARD_SUBSECTION_CLASS} border border-(--border) bg-(--card) text-sm text-(--muted-foreground)`}
          role="status"
        >
          Loading search-type coverage...
        </div>
      ) : coverage.length === 0 ? (
        <div
          className={`${CARD_SUBSECTION_CLASS} border border-dashed border-(--border) bg-(--card) text-sm text-(--muted-foreground)`}
        >
          Search-type coverage is not available for this project.
        </div>
      ) : (
        <>
          <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
            <p className="text-sm font-semibold text-(--foreground)" data-testid="coverage-summary">
              {covered} of {coverage.length} search types covered
            </p>
            {gaps.length > 0 && onGenerateAll ? (
              <Button
                variant="outline"
                size="sm"
                onClick={() => void run("all", onGenerateAll)}
                disabled={busy !== null || locked || capReached}
                loading={busy === "all"}
                loadingText="Adding prompts"
              >
                Add a prompt for each gap
              </Button>
            ) : null}
          </div>

          {gaps.length > 0 && (locked || capReached) ? (
            <p className="text-xs text-(--muted-foreground)" role="status">
              {locked
                ? "Prompt tracking is not included on this plan, so these gaps cannot be filled yet."
                : "Your prompt allowance is fully used, so a gap can only be filled by removing another prompt or moving to a plan that tracks more."}
            </p>
          ) : null}

          <ul className="space-y-3">
            {coverage.map((entry) => (
              <li
                key={entry.id}
                className={`${CARD_SUBSECTION_CLASS} border border-(--border) bg-(--card)`}
                data-testid={`coverage-${entry.id}`}
              >
                <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
                  <div className="space-y-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <h3 className="text-sm font-semibold text-(--foreground)">{entry.label}</h3>
                      <Badge color={entry.covered ? "success" : "warning"}>
                        {entry.covered
                          ? `${entry.prompt_count} ${entry.prompt_count === 1 ? "prompt" : "prompts"}`
                          : "No prompt yet"}
                      </Badge>
                      {entry.premium ? <Badge color="default">Higher plans</Badge> : null}
                    </div>
                    <p className="text-xs text-(--muted-foreground)">
                      {SEARCH_TYPE_DESCRIPTIONS[entry.id]}
                    </p>
                    {!entry.covered && entry.suggested_prompt ? (
                      <p className="text-xs text-(--foreground)">
                        Suggested prompt:{" "}
                        <span className="font-medium">{entry.suggested_prompt}</span>
                      </p>
                    ) : null}
                  </div>

                  {!entry.covered && entry.suggested_prompt && onFillGap ? (
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => void run(entry.id, () => onFillGap(entry))}
                      disabled={busy !== null || locked || capReached}
                      loading={busy === entry.id}
                      loadingText="Adding"
                    >
                      Add this prompt
                    </Button>
                  ) : null}
                </div>
              </li>
            ))}
          </ul>
        </>
      )}
    </Card>
  );
}
