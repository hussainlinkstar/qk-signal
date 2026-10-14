export type AuditAnnotationTarget = {
  sectionPath: string;
  sourceRecommendationKey: string | null;
  title: string;
  description: string | null;
  category: string;
};

const normalizeText = (value: unknown, maxLength: number): string =>
  typeof value === "string" ? value.trim().slice(0, maxLength) : "";

const normalizeCategory = (value: unknown, fallback: string): string => {
  const normalized = normalizeText(value, 120);
  return normalized || fallback;
};

const appendTargetsFromList = (
  items: unknown,
  pathPrefix: string,
  fallbackCategory: string,
  targets: AuditAnnotationTarget[]
) => {
  if (!Array.isArray(items)) {
    return;
  }

  items.forEach((item, index) => {
    const sectionPath = `${pathPrefix}[${index}]`;
    if (typeof item === "string") {
      const title = normalizeText(item, 255);
      if (!title) {
        return;
      }
      targets.push({
        sectionPath,
        sourceRecommendationKey: null,
        title,
        description: null,
        category: fallbackCategory,
      });
      return;
    }

    if (!item || typeof item !== "object") {
      return;
    }

    const entry = item as Record<string, unknown>;
    const title = normalizeText(
      entry.title ?? entry.action ?? entry.name ?? entry.description,
      255
    );
    if (!title) {
      return;
    }

    const description = normalizeText(entry.description ?? entry.action, 4000) || null;
    targets.push({
      sectionPath,
      sourceRecommendationKey: null,
      title,
      description,
      category: normalizeCategory(entry.category, fallbackCategory),
    });
  });
};

export const extractAuditAnnotationTargets = (
  report: Record<string, unknown> | null | undefined
): AuditAnnotationTarget[] => {
  if (!report || typeof report !== "object") {
    return [];
  }

  const analysis =
    report.analysis && typeof report.analysis === "object"
      ? (report.analysis as Record<string, unknown>)
      : {};

  const targets: AuditAnnotationTarget[] = [];
  appendTargetsFromList(report.prioritized_actions, "prioritized_actions", "Technical", targets);
  appendTargetsFromList(report.priority_actions, "priority_actions", "Technical", targets);
  appendTargetsFromList(report.suggestions, "suggestions", "Technical", targets);
  appendTargetsFromList(analysis.recommendations, "analysis.recommendations", "Technical", targets);
  appendTargetsFromList(analysis.seo_findings, "analysis.seo_findings", "SEO", targets);
  appendTargetsFromList(analysis.geo_findings, "analysis.geo_findings", "AI visibility", targets);
  appendTargetsFromList(analysis.aeo_findings, "analysis.aeo_findings", "AI answers", targets);

  const deduped = new Map<string, AuditAnnotationTarget>();
  targets.forEach((target) => {
    if (!deduped.has(target.sectionPath)) {
      deduped.set(target.sectionPath, target);
    }
  });
  return Array.from(deduped.values());
};
