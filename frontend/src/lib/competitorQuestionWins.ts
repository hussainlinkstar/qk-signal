import type { CompetitorSnippetComparison } from "@/types/auditResult";

export type TrackedCompetitor = {
  id: number;
  normalized_domain: string;
  display_name: string;
};

export type WinningQuestion = {
  query: string;
  excerpt: string | null;
  timestamp: string | null;
};

export type CompetitorWinSummary = {
  competitorId: number;
  wins: number;
  considered: number;
  questions: WinningQuestion[];
};

export type QuestionWinsResult = {
  totalQuestions: number;
  measuredQuestions: number;
  notMeasured: number;
  nobodyNamed: number;
  ties: number;
  siteWins: number;
  unattributedWins: number;
  perCompetitor: CompetitorWinSummary[];
};

const normalizeDomain = (value: string | null | undefined): string =>
  (value ?? "")
    .trim()
    .toLowerCase()
    .replace(/^https?:\/\//, "")
    .replace(/^www\./, "")
    .replace(/\/.*$/, "");

const isMissingMeasurement = (comparison: CompetitorSnippetComparison): boolean =>
  comparison.winner_reason === "missing_site_data" ||
  comparison.winner_reason === "missing_competitor_data";

type ComparisonCompetitorEntry = NonNullable<CompetitorSnippetComparison["competitors"]>[number];

const entryMatchesTracked = (
  entry: ComparisonCompetitorEntry,
  tracked: TrackedCompetitor
): boolean => {
  const entryDomain = normalizeDomain(entry.domain);
  if (entryDomain && entryDomain === normalizeDomain(tracked.normalized_domain)) return true;
  const entryName = (entry.display_name ?? "").trim().toLowerCase();
  return !!entryName && entryName === tracked.display_name.trim().toLowerCase();
};

type WinningEvidence = {
  domain: string | null;
  displayName: string | null;
  excerpt: string | null;
  timestamp: string | null;
};

const findWinningEvidence = (comparison: CompetitorSnippetComparison): WinningEvidence | null => {
  const winner = comparison.competitor;
  if (!winner) return null;

  const candidates = (comparison.competitors ?? []).filter(
    (entry) =>
      entry.answer_excerpt === winner.answer_excerpt &&
      entry.answer_relevance === winner.answer_relevance &&
      (winner.domain === null || normalizeDomain(entry.domain) === normalizeDomain(winner.domain))
  );

  // A domain is enough to identify the winner. Without it, picking between
  // several equally-matching entries would be guessing, so accept only a
  // unique candidate.
  const matchingEntry = winner.domain
    ? candidates.find((entry) => normalizeDomain(entry.domain) === normalizeDomain(winner.domain))
    : candidates.length === 1
      ? candidates[0]
      : null;

  return {
    domain: winner.domain ?? matchingEntry?.domain ?? null,
    displayName: matchingEntry?.display_name ?? null,
    excerpt: winner.answer_excerpt,
    timestamp: winner.selected_audit_timestamp ?? matchingEntry?.selected_audit_timestamp ?? null,
  };
};

const matchTrackedCompetitor = (
  evidence: WinningEvidence,
  tracked: TrackedCompetitor[]
): TrackedCompetitor | null => {
  const winnerDomain = normalizeDomain(evidence.domain);
  if (winnerDomain) {
    const byDomain = tracked.find(
      (item) => normalizeDomain(item.normalized_domain) === winnerDomain
    );
    if (byDomain) return byDomain;
  }
  const winnerName = (evidence.displayName ?? "").trim().toLowerCase();
  if (winnerName) {
    const byName = tracked.find((item) => item.display_name.trim().toLowerCase() === winnerName);
    if (byName) return byName;
  }
  return null;
};

export const deriveCompetitorQuestionWins = (
  comparisons: CompetitorSnippetComparison[] | null | undefined,
  tracked: TrackedCompetitor[]
): QuestionWinsResult => {
  const perCompetitor = new Map<number, CompetitorWinSummary>(
    tracked.map((item) => [
      item.id,
      { competitorId: item.id, wins: 0, considered: 0, questions: [] },
    ])
  );

  const result: QuestionWinsResult = {
    totalQuestions: comparisons?.length ?? 0,
    measuredQuestions: 0,
    notMeasured: 0,
    nobodyNamed: 0,
    ties: 0,
    siteWins: 0,
    unattributedWins: 0,
    perCompetitor: [],
  };

  for (const comparison of comparisons ?? []) {
    if (isMissingMeasurement(comparison)) {
      result.notMeasured += 1;
      continue;
    }

    result.measuredQuestions += 1;

    let winningMatch: TrackedCompetitor | null = null;
    let winningEvidence: WinningEvidence | null = null;
    if (comparison.winner === "competitor") {
      winningEvidence = findWinningEvidence(comparison);
      winningMatch = winningEvidence ? matchTrackedCompetitor(winningEvidence, tracked) : null;
      if (!winningMatch) {
        result.unattributedWins += 1;
      }
    }

    for (const item of tracked) {
      const summary = perCompetitor.get(item.id);
      if (!summary) continue;
      const isListed = (comparison.competitors ?? []).some((entry) =>
        entryMatchesTracked(entry, item)
      );
      const isWinner = winningMatch?.id === item.id;
      if (isListed || isWinner) {
        summary.considered += 1;
      }
    }

    if (comparison.winner === "no_data") {
      result.nobodyNamed += 1;
      continue;
    }
    if (comparison.winner === "tie") {
      result.ties += 1;
      continue;
    }
    if (comparison.winner === "site") {
      result.siteWins += 1;
      continue;
    }

    if (winningMatch && winningEvidence) {
      const summary = perCompetitor.get(winningMatch.id);
      if (summary) {
        summary.wins += 1;
        summary.questions.push({
          query: comparison.query,
          excerpt: winningEvidence.excerpt,
          timestamp: winningEvidence.timestamp,
        });
      }
    }
  }

  for (const item of tracked) {
    const summary = perCompetitor.get(item.id);
    if (summary) {
      result.perCompetitor.push(summary);
    }
  }

  return result;
};
