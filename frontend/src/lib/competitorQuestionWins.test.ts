import { describe, expect, it } from "vitest";

import { deriveCompetitorQuestionWins, type TrackedCompetitor } from "./competitorQuestionWins";
import type { CompetitorSnippetComparison } from "@/types/auditResult";

const site = {
  domain: "mysite.com",
  answer_relevance: 40,
  answer_excerpt: "Our answer",
};

const comparison = (
  overrides: Partial<CompetitorSnippetComparison>
): CompetitorSnippetComparison => ({
  query: "Which hotel is best?",
  winner: "site",
  site,
  competitor: null,
  ...overrides,
});

const TRACKED: TrackedCompetitor[] = [
  { id: 7, normalized_domain: "coastline-resorts.com", display_name: "Coastline Resorts" },
  { id: 8, normalized_domain: "harbourview.co", display_name: "Harbour View" },
];

const competitorWinner = (
  domain: string | null,
  excerpt = "Their answer",
  extra: Partial<CompetitorSnippetComparison> = {}
): CompetitorSnippetComparison =>
  comparison({
    winner: "competitor",
    competitor: {
      domain,
      answer_relevance: 90,
      answer_excerpt: excerpt,
      selected_audit_timestamp: "2026-01-05T00:00:00.000Z",
    },
    ...extra,
  });

describe("deriveCompetitorQuestionWins", () => {
  it("returns empty results for an empty comparisons array", () => {
    const result = deriveCompetitorQuestionWins([], TRACKED);

    expect(result.totalQuestions).toBe(0);
    expect(result.measuredQuestions).toBe(0);
    expect(result.perCompetitor).toHaveLength(2);
    expect(result.perCompetitor.every((c) => c.wins === 0 && c.considered === 0)).toBe(true);
  });

  it("counts a win only when the winner is an identifiable tracked competitor", () => {
    const result = deriveCompetitorQuestionWins(
      [competitorWinner("coastline-resorts.com")],
      TRACKED
    );

    const coastline = result.perCompetitor.find((c) => c.competitorId === 7);
    expect(coastline?.wins).toBe(1);
    expect(coastline?.considered).toBe(1);
    expect(coastline?.questions[0]).toEqual({
      query: "Which hotel is best?",
      excerpt: "Their answer",
      timestamp: "2026-01-05T00:00:00.000Z",
    });
    expect(result.perCompetitor.find((c) => c.competitorId === 8)?.wins).toBe(0);
  });

  it("only counts questions the competitor was actually assessed on as considered", () => {
    const result = deriveCompetitorQuestionWins(
      [
        competitorWinner("coastline-resorts.com"),
        comparison({
          winner: "site",
          competitors: [
            {
              domain: "harbourview.co",
              answer_relevance: 50,
              answer_excerpt: "Harbour answer",
            },
          ],
        }),
        comparison({
          winner: "tie",
          competitors: [
            {
              domain: "coastline-resorts.com",
              answer_relevance: 60,
              answer_excerpt: "Coastline answer",
            },
            {
              domain: "harbourview.co",
              answer_relevance: 55,
              answer_excerpt: "Harbour answer 2",
            },
          ],
        }),
      ],
      TRACKED
    );

    expect(result.measuredQuestions).toBe(3);
    const coastline = result.perCompetitor.find((c) => c.competitorId === 7);
    const harbour = result.perCompetitor.find((c) => c.competitorId === 8);
    // Coastline was the winner of one and listed in one more: 2 assessed.
    expect(coastline?.considered).toBe(2);
    // Harbour View was listed in two: 2 assessed, no wins.
    expect(harbour?.considered).toBe(2);
    expect(harbour?.wins).toBe(0);
  });

  it("leaves considered at zero for a competitor absent from every comparison", () => {
    const result = deriveCompetitorQuestionWins(
      [competitorWinner("coastline-resorts.com")],
      TRACKED
    );

    expect(result.perCompetitor.find((c) => c.competitorId === 8)?.considered).toBe(0);
  });

  it("matches winners by domain ignoring protocol, www and case", () => {
    const result = deriveCompetitorQuestionWins(
      [competitorWinner("HTTPS://WWW.Coastline-Resorts.COM/")],
      TRACKED
    );

    expect(result.perCompetitor.find((c) => c.competitorId === 7)?.wins).toBe(1);
  });

  it("falls back to a case-insensitive display-name match when the domain is absent", () => {
    const result = deriveCompetitorQuestionWins(
      [
        competitorWinner(null, "Their answer", {
          competitors: [
            {
              domain: null,
              display_name: "COASTLINE RESORTS",
              answer_relevance: 90,
              answer_excerpt: "Their answer",
              selected_audit_timestamp: "2026-01-05T00:00:00.000Z",
            },
          ],
        }),
      ],
      TRACKED
    );

    expect(result.perCompetitor.find((c) => c.competitorId === 7)?.wins).toBe(1);
  });

  it("counts a winner it cannot identify as unattributed, never guessing", () => {
    const result = deriveCompetitorQuestionWins(
      [competitorWinner("untracked-rival.com"), competitorWinner(null)],
      TRACKED
    );

    expect(result.unattributedWins).toBe(2);
    expect(result.perCompetitor.every((c) => c.wins === 0)).toBe(true);
  });

  it("treats a domainless winner with several identical candidates as unattributed", () => {
    const result = deriveCompetitorQuestionWins(
      [
        competitorWinner(null, "Same answer", {
          competitors: [
            {
              domain: "coastline-resorts.com",
              display_name: "Coastline Resorts",
              answer_relevance: 90,
              answer_excerpt: "Same answer",
            },
            {
              domain: "harbourview.co",
              display_name: "Harbour View",
              answer_relevance: 90,
              answer_excerpt: "Same answer",
            },
          ],
        }),
      ],
      TRACKED
    );

    expect(result.unattributedWins).toBe(1);
    expect(result.perCompetitor.every((c) => c.wins === 0)).toBe(true);
  });

  it("excludes missing measurements from wins and reports them separately", () => {
    const result = deriveCompetitorQuestionWins(
      [
        competitorWinner("coastline-resorts.com", "x", {
          winner_reason: "missing_site_data",
        }),
        competitorWinner("coastline-resorts.com", "x", {
          winner_reason: "missing_competitor_data",
        }),
        competitorWinner("coastline-resorts.com"),
      ],
      TRACKED
    );

    expect(result.notMeasured).toBe(2);
    expect(result.measuredQuestions).toBe(1);
    expect(result.perCompetitor.find((c) => c.competitorId === 7)?.wins).toBe(1);
  });

  it("counts no_data and tie as neither wins nor losses", () => {
    const result = deriveCompetitorQuestionWins(
      [comparison({ winner: "no_data" }), comparison({ winner: "tie" })],
      TRACKED
    );

    expect(result.nobodyNamed).toBe(1);
    expect(result.ties).toBe(1);
    expect(result.perCompetitor.every((c) => c.wins === 0)).toBe(true);
    expect(result.siteWins).toBe(0);
  });

  it("lets winner take precedence when result_state disagrees", () => {
    const result = deriveCompetitorQuestionWins(
      [comparison({ winner: "site", result_state: "lost" })],
      TRACKED
    );

    expect(result.siteWins).toBe(1);
    expect(result.perCompetitor.every((c) => c.wins === 0)).toBe(true);
    expect(result.unattributedWins).toBe(0);
  });
});
