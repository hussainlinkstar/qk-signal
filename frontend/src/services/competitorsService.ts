import {
  createProjectCompetitor,
  deleteProjectCompetitor,
  fetchProjectById,
  fetchProjectCompetitors,
  fetchProjectLatestAudit,
  type ProjectAuditHistoryEntry,
  type ProjectCompetitorListItem,
  type ProjectDetails,
} from "@/services/workspaceService";
import { requestJson } from "@/services/http";

export type CompetitorMatrixRow = {
  id: number;
  name: string;
  geo_score: number;
  aeo_score: number;
  seo_score: number;
  gap_to_you: number;
};

export type CommonEntity = {
  entity: string;
  site_citations: number;
  comp_citations: number;
};

export type MissingAnswer = {
  query: string;
  competitor_citations: string[];
};

export type CompetitorComparePayload = {
  labels: string[];
  site_scores: number[];
  comp_scores: number[];
  base_site?: string | null;
  comp_site?: string | null;
  common_entities: CommonEntity[];
  missing_answers: MissingAnswer[];
};

export type SiteCompetitorLinkPayload = {
  competitor_domain: string;
  display_name?: string;
};

export type SiteCompetitorLinkResponse = ProjectCompetitorListItem;

export type DiscoveredCompetitor = {
  name: string;
  source: string;
  shared_entities: string[];
  entity_overlap_score: number;
  confidence_score: number;
};

export type CompetitorDiscoveryResponse = {
  site: string;
  category: string;
  market: string;
  cached: boolean;
  competitors: DiscoveredCompetitor[];
};

export type DiscoveryLinkResult = {
  linked: SiteCompetitorLinkResponse[];
};

type ProjectScopedCompetitor = {
  id: number;
  name: string;
  geo_score: number;
  aeo_score: number;
  seo_score: number;
  gap_to_you: number;
  common_entities: CommonEntity[];
  missing_answers: MissingAnswer[];
};

const asObject = (value: unknown): Record<string, unknown> =>
  value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};

const asArray = <T>(value: unknown): T[] => (Array.isArray(value) ? (value as T[]) : []);

const toNumber = (value: unknown, fallback = 0): number => {
  if (typeof value === "number" && Number.isFinite(value)) {
    return value;
  }
  if (typeof value === "string") {
    const parsed = Number(value);
    if (Number.isFinite(parsed)) {
      return parsed;
    }
  }
  return fallback;
};

const normalizeCompetitorToken = (value: string): string =>
  value
    .trim()
    .replace(/^https?:\/\//i, "")
    .replace(/^www\./i, "")
    .replace(/\/+$/g, "")
    .toLowerCase();

const parseCompetitorLabel = (value: string): string => {
  const trimmed = value.trim();
  if (!trimmed) {
    return "";
  }

  try {
    const hostname = new URL(trimmed.startsWith("http") ? trimmed : `https://${trimmed}`).hostname;
    return hostname.replace(/^www\./i, "") || trimmed;
  } catch {
    return trimmed;
  }
};

const buildSyntheticCompetitorId = (seed: string): number => {
  const normalized = normalizeCompetitorToken(seed);
  let hash = 5381;
  for (let index = 0; index < normalized.length; index += 1) {
    hash = ((hash << 5) + hash + normalized.charCodeAt(index)) | 0;
  }
  const positive = Math.abs(hash >>> 0);
  return positive > 0 ? positive : 1;
};

const toProjectTargetScores = (
  project: ProjectDetails,
  latestAudit: ProjectAuditHistoryEntry | null
): { geo: number; aeo: number; seo: number; overall: number } => {
  const geo = toNumber(latestAudit?.geo_score ?? project.latest_geo_score, 0);
  const aeo = toNumber(latestAudit?.aeo_score ?? project.latest_aeo_score, 0);
  const seo = toNumber(latestAudit?.seo_score ?? project.latest_seo_score, 0);
  const overall = (geo + aeo + seo) / 3;
  return { geo, aeo, seo, overall };
};

const parseSharedEntities = (value: unknown): CommonEntity[] =>
  asArray<unknown>(value)
    .map((entry) => {
      if (typeof entry === "string") {
        return {
          entity: entry,
          site_citations: 0,
          comp_citations: 0,
        } satisfies CommonEntity;
      }

      const item = asObject(entry);
      const entity = String(item.entity ?? item.name ?? "").trim();
      if (!entity) {
        return null;
      }

      return {
        entity,
        site_citations: toNumber(item.site_citations, 0),
        comp_citations: toNumber(item.comp_citations, 0),
      } satisfies CommonEntity;
    })
    .filter((entry): entry is CommonEntity => Boolean(entry));

const parseMissingAnswers = (value: unknown): MissingAnswer[] =>
  asArray<unknown>(value)
    .map((entry) => {
      const item = asObject(entry);
      const query = String(item.query ?? "").trim();
      if (!query) {
        return null;
      }

      return {
        query,
        competitor_citations: asArray<string>(item.competitor_citations).filter(
          (citation) => typeof citation === "string" && citation.trim().length > 0
        ),
      } satisfies MissingAnswer;
    })
    .filter((entry): entry is MissingAnswer => Boolean(entry));

const extractReportCompetitors = (
  report: Record<string, unknown>,
  targetScores: { overall: number }
): ProjectScopedCompetitor[] => {
  const competitorsNode = report.competitors;
  const legacyCompetitors = Array.isArray(competitorsNode)
    ? (competitorsNode as Record<string, unknown>[])
    : asArray<Record<string, unknown>>(asObject(competitorsNode).items);

  const metadata = asObject(report.metadata);
  const competitorSummary = asObject(metadata.competitor_summary);
  const benchmarkRows = asArray<Record<string, unknown>>(
    asObject(competitorSummary.benchmark).rows
  );

  const benchmarkByName = new Map<string, Record<string, unknown>>();
  benchmarkRows.forEach((row) => {
    const name = String(row.name ?? "").trim();
    if (!name || row.is_target) {
      return;
    }
    benchmarkByName.set(normalizeCompetitorToken(name), row);
  });

  const byId = new Map<number, ProjectScopedCompetitor>();
  const upsert = (
    nameRaw: string,
    payload: {
      geo_score: number;
      aeo_score: number;
      seo_score: number;
      score: number;
      common_entities?: CommonEntity[];
      missing_answers?: MissingAnswer[];
    }
  ) => {
    const label = parseCompetitorLabel(nameRaw);
    if (!label) {
      return;
    }

    const id = buildSyntheticCompetitorId(label);
    const score = payload.score;
    const row: ProjectScopedCompetitor = {
      id,
      name: label,
      geo_score: payload.geo_score,
      aeo_score: payload.aeo_score,
      seo_score: payload.seo_score,
      gap_to_you: score - targetScores.overall,
      common_entities: payload.common_entities ?? [],
      missing_answers: payload.missing_answers ?? [],
    };
    byId.set(id, row);
  };

  legacyCompetitors.forEach((candidate) => {
    const name = String(candidate.name ?? candidate.domain ?? "").trim();
    if (!name) {
      return;
    }
    const benchmark =
      benchmarkByName.get(normalizeCompetitorToken(name)) ?? ({} as Record<string, unknown>);

    const geoScore = toNumber(candidate.geo_visibility ?? benchmark.geo_visibility, 0);
    const aeoScore = toNumber(candidate.aeo_score ?? benchmark.aeo_score, 0);
    const seoScore = toNumber(candidate.entity_strength ?? benchmark.entity_strength, 0);
    const score = toNumber(
      candidate.score ?? benchmark.overall_score,
      (geoScore + aeoScore + seoScore) / 3
    );

    upsert(name, {
      geo_score: geoScore,
      aeo_score: aeoScore,
      seo_score: seoScore,
      score,
      common_entities: parseSharedEntities(candidate.shared_entities ?? candidate.common_entities),
      missing_answers: parseMissingAnswers(candidate.missing_answers),
    });
  });

  benchmarkRows.forEach((benchmark) => {
    const name = String(benchmark.name ?? "").trim();
    if (!name || benchmark.is_target) {
      return;
    }

    const geoScore = toNumber(benchmark.geo_visibility, 0);
    const aeoScore = toNumber(benchmark.aeo_score, 0);
    const seoScore = toNumber(benchmark.entity_strength, 0);
    const score = toNumber(benchmark.overall_score, (geoScore + aeoScore + seoScore) / 3);
    upsert(name, {
      geo_score: geoScore,
      aeo_score: aeoScore,
      seo_score: seoScore,
      score,
    });
  });

  return Array.from(byId.values());
};

const buildProjectScopedCompetitors = (
  project: ProjectDetails,
  latestAudit: ProjectAuditHistoryEntry | null
): ProjectScopedCompetitor[] => {
  const targetScores = toProjectTargetScores(project, latestAudit);
  const report = asObject(latestAudit?.full_report);
  const reportRows = extractReportCompetitors(report, targetScores);

  const byId = new Map<number, ProjectScopedCompetitor>(reportRows.map((row) => [row.id, row]));
  asArray<string>(project.competitors).forEach((configuredCompetitor) => {
    const label = parseCompetitorLabel(configuredCompetitor);
    if (!label) {
      return;
    }
    const id = buildSyntheticCompetitorId(label);
    if (byId.has(id)) {
      return;
    }
    byId.set(id, {
      id,
      name: label,
      geo_score: 0,
      aeo_score: 0,
      seo_score: 0,
      gap_to_you: -targetScores.overall,
      common_entities: [],
      missing_answers: [],
    });
  });

  return Array.from(byId.values());
};

const loadProjectScopedContext = async (
  projectId: number,
  headers: HeadersInit
): Promise<{
  project: ProjectDetails;
  latestAudit: ProjectAuditHistoryEntry | null;
  rows: ProjectScopedCompetitor[];
}> => {
  const [project, latestAudit] = await Promise.all([
    fetchProjectById(projectId, headers),
    fetchProjectLatestAudit(projectId, headers, { includeFullReport: true }),
  ]);
  return {
    project,
    latestAudit,
    rows: buildProjectScopedCompetitors(project, latestAudit),
  };
};

const buildProjectScopedCompare = (
  project: ProjectDetails,
  latestAudit: ProjectAuditHistoryEntry | null,
  rows: ProjectScopedCompetitor[],
  competitorId: number
): CompetitorComparePayload => {
  const target = toProjectTargetScores(project, latestAudit);
  const competitor = rows.find((row) => row.id === competitorId);
  if (!competitor) {
    throw new Error("Competitor not found in project context.");
  }

  return {
    labels: ["AI visibility", "AI answers", "SEO"],
    site_scores: [target.geo, target.aeo, target.seo],
    comp_scores: [competitor.geo_score, competitor.aeo_score, competitor.seo_score],
    base_site: project.domain_url ?? project.name,
    comp_site: competitor.name,
    common_entities: competitor.common_entities,
    missing_answers: competitor.missing_answers,
  };
};

export const fetchCompetitorMatrix = async (
  siteId: number,
  headers: HeadersInit = {}
): Promise<CompetitorMatrixRow[]> => {
  const { rows } = await loadProjectScopedContext(siteId, headers);
  return rows.map((row) => ({
    id: row.id,
    name: row.name,
    geo_score: row.geo_score,
    aeo_score: row.aeo_score,
    seo_score: row.seo_score,
    gap_to_you: row.gap_to_you,
  }));
};

export const fetchCompetitorCompare = async (
  baseSiteId: number,
  competitorSiteId: number,
  headers: HeadersInit = {}
): Promise<CompetitorComparePayload> => {
  const { project, latestAudit, rows } = await loadProjectScopedContext(baseSiteId, headers);
  return buildProjectScopedCompare(project, latestAudit, rows, competitorSiteId);
};

export const linkCompetitorToSite = async (
  projectId: number,
  payload: SiteCompetitorLinkPayload,
  headers: HeadersInit = {}
): Promise<SiteCompetitorLinkResponse> => {
  const targetUrl = payload.competitor_domain.trim();
  if (!targetUrl) {
    throw new Error("Provide a competitor domain.");
  }

  return createProjectCompetitor(
    projectId,
    {
      target_url: targetUrl,
      display_name: payload.display_name?.trim() || null,
    },
    headers
  );
};

export const unlinkCompetitorFromSite = async (
  projectId: number,
  projectCompetitorId: number,
  headers: HeadersInit = {}
): Promise<void> => {
  await deleteProjectCompetitor(projectId, projectCompetitorId, headers);
};

type RunDiscoveryInput = {
  siteUrl: string;
  category: string;
  market: string;
  siteId?: number;
  linkResults?: boolean;
  competitorsToLink?: SiteCompetitorLinkPayload[];
};

export const linkDiscoveredCompetitors = async (
  projectId: number,
  competitors: SiteCompetitorLinkPayload[],
  headers: HeadersInit = {}
): Promise<DiscoveryLinkResult> => {
  const existing = await fetchProjectCompetitors(projectId, headers);
  const seen = new Set(existing.map((entry) => normalizeCompetitorToken(entry.normalized_domain)));
  const linked: SiteCompetitorLinkResponse[] = [];

  for (const entry of competitors) {
    const targetUrl = entry.competitor_domain.trim();
    const normalized = normalizeCompetitorToken(parseCompetitorLabel(targetUrl));
    if (!targetUrl || !normalized || seen.has(normalized)) {
      continue;
    }
    seen.add(normalized);
    linked.push(await linkCompetitorToSite(projectId, entry, headers));
  }

  return { linked };
};

export const runCompetitorDiscovery = async (
  input: RunDiscoveryInput,
  headers: HeadersInit = {}
): Promise<CompetitorDiscoveryResponse & { linked?: SiteCompetitorLinkResponse[] }> => {
  const data = await requestJson<CompetitorDiscoveryResponse>({
    endpoint: "/api/v1/competitors/discovery",
    method: "POST",
    headers,
    body: {
      site_url: input.siteUrl,
      category: input.category,
      market: input.market,
    },
    errorMessage: "Unable to discover competitors.",
  });

  const normalized: CompetitorDiscoveryResponse = {
    site: data.site ?? input.siteUrl,
    category: data.category ?? input.category,
    market: data.market ?? input.market,
    cached: Boolean(data.cached),
    competitors: Array.isArray(data.competitors) ? data.competitors : [],
  };

  if (!input.linkResults || !input.siteId) {
    return normalized;
  }

  const requestedLinks = input.competitorsToLink?.filter(
    (item) => item.competitor_domain.trim().length > 0
  );
  if (!requestedLinks?.length) {
    return normalized;
  }

  const linked = await linkDiscoveredCompetitors(input.siteId, requestedLinks, headers);
  return { ...normalized, linked: linked.linked };
};
