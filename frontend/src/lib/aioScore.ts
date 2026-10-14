// Shared AIO headline so every surface shows the same number for the same
// audit (SIGNAL-1000). Canonical scores first: the raw section values were
// previously preferred with `??`, which does not fall through 0, so an audit
// with a real 0 in one sub-score showed a different AIO on different screens.
//
// SIGV2-1308: rounded once, at the end.
//
// QA found one project reading 49 on the workspace overview and 50 on its own
// dashboard, at the same moment. Both numbers were computed correctly and from
// the same two inputs; they disagreed because they rounded at different
// stages. The overview averages the raw values and rounds for display. This
// rounded each part first, then averaged, then rounded again.
//
// With aeo 48.6 and geo 49.6 that is the whole gap: averaging raw gives 49.1
// and so 49, while rounding first gives 49 and 50, whose mean is 49.5 and so
// 50. Half a point of rounding error, and a customer with no way to reconcile
// two screens of their own product.
//
// Rounding is now a display step and happens exactly once, which is the only
// version of this that stays fixed.

const asFiniteNumber = (v: number | null | undefined): number | null =>
  typeof v === "number" && Number.isFinite(v) ? v : null;

export type AioScoreReport = {
  scores?: { aeo?: number | null; geo?: number | null } | null;
  aeo?: { answerability_score?: number | null } | null;
  geo?: { visibility_index?: number | null } | null;
};

export const computeAioScore = (
  report: AioScoreReport | null | undefined,
  latest?: { aeo?: number | null; geo?: number | null } | null
): number | null => {
  const aeo = asFiniteNumber(
    report?.scores?.aeo ?? latest?.aeo ?? report?.aeo?.answerability_score
  );
  const geo = asFiniteNumber(report?.scores?.geo ?? latest?.geo ?? report?.geo?.visibility_index);
  const parts = [aeo, geo].filter((v): v is number => typeof v === "number");
  if (parts.length === 0) return null;
  return Math.round(parts.reduce((a, b) => a + b, 0) / parts.length);
};
