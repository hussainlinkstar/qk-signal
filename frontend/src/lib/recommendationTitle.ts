const ELLIPSES = /[\u2026]|\.\.\.$/;

const normalize = (value: string): string =>
  value
    .replace(ELLIPSES, "")
    .replace(/\s+/g, " ")
    .replace(/[.!?,;:]+$/, "")
    .trim()
    .toLowerCase();

/**
 * True when a card headline carries no information the body text does not.
 *
 * Findings coming from the AI experts only have a `description`; the backend
 * derives the headline from it (`score_utils._finding_title`), and when the
 * first sentence is longer than the 90-character budget it falls back to a
 * word-boundary cut plus an ellipsis. Rendering both then shows a visibly
 * clipped heading directly above the same sentence in full, which reads as
 * broken text rather than a summary.
 */
export const isTitleRedundantWithDescription = (
  title: string | null | undefined,
  description: string | null | undefined
): boolean => {
  const normalizedTitle = normalize(title ?? "");
  const normalizedDescription = normalize(description ?? "");
  if (!normalizedTitle || !normalizedDescription) return false;
  return (
    normalizedDescription === normalizedTitle || normalizedDescription.startsWith(normalizedTitle)
  );
};
