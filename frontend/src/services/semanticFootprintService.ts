import type {
  EntityCategory,
  EntityGraphApiResponse,
  GraphCategory,
  GraphRelationType,
  KnowledgeGraphPayload,
  SemanticGapPayload,
  SiteMapPayload,
} from "@/types/semanticFootprint";
import { requestJson } from "@/services/http";

type SiteMapApiEntity = {
  name?: unknown;
  normalized_key?: unknown;
  normalizedKey?: unknown;
  frequency?: unknown;
  avg_relevance_score?: unknown;
  avgRelevanceScore?: unknown;
  relevance_score?: unknown;
  relevanceScore?: unknown;
  count?: unknown;
  category?: unknown;
};

type ProjectSummaryApiResponse = {
  id?: unknown;
  audit_count?: unknown;
  last_audit_at?: unknown;
};

type ProjectLatestAuditApiResponse = {
  id?: unknown;
  project_id?: unknown;
  created_at?: unknown;
  full_report?: unknown;
};

const GRAPH_CATEGORIES: GraphCategory[] = ["Person", "Organization", "Concept", "Product"];
const GRAPH_RELATIONS: GraphRelationType[] = ["MENTIONED_IN", "RELATED_TO"];
const ENTITY_CATEGORIES: EntityCategory[] = [
  "brand",
  "product",
  "service",
  "person",
  "location",
  "topic",
  "other",
];

const mapGraphCategory = (value: unknown): GraphCategory => {
  const normalized = String(value ?? "")
    .trim()
    .toLowerCase();
  if (normalized === "person") return "Person";
  if (normalized === "organization" || normalized === "org" || normalized === "localbusiness") {
    return "Organization";
  }
  if (normalized === "product") return "Product";
  return "Concept";
};

const mapGraphRelation = (value: unknown): GraphRelationType => {
  const normalized = String(value ?? "")
    .trim()
    .toUpperCase();
  return GRAPH_RELATIONS.includes(normalized as GraphRelationType)
    ? (normalized as GraphRelationType)
    : "RELATED_TO";
};

const mapEntityCategory = (value: unknown): EntityCategory => {
  const normalized = String(value ?? "")
    .trim()
    .toLowerCase();
  return ENTITY_CATEGORIES.includes(normalized as EntityCategory)
    ? (normalized as EntityCategory)
    : "other";
};

const normalizeEntityKey = (value: string): string =>
  value
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "");

const mapSiteMapEntity = (entity: SiteMapApiEntity) => {
  const name = String(entity.name ?? "").trim();
  const normalizedKey = String(
    entity.normalizedKey ?? entity.normalized_key ?? normalizeEntityKey(name)
  ).trim();
  const frequencyRaw = Number(entity.frequency ?? entity.count ?? 1);
  const relevanceRaw = Number(
    entity.avgRelevanceScore ??
      entity.avg_relevance_score ??
      entity.relevance_score ??
      entity.relevanceScore ??
      0
  );

  return {
    name,
    normalizedKey,
    frequency: Number.isFinite(frequencyRaw) ? frequencyRaw : 1,
    avgRelevanceScore: Number.isFinite(relevanceRaw) ? relevanceRaw : 0,
    category: mapEntityCategory(entity.category),
  };
};

const extractEntitiesFromAuditReport = (report: unknown): SiteMapApiEntity[] => {
  if (!report || typeof report !== "object" || Array.isArray(report)) {
    return [];
  }

  const payload = report as { entities?: unknown };
  if (!Array.isArray(payload.entities)) {
    return [];
  }

  return payload.entities
    .map((entry) => {
      if (typeof entry === "string") {
        return {
          name: entry,
          normalized_key: normalizeEntityKey(entry),
        } satisfies SiteMapApiEntity;
      }
      if (entry && typeof entry === "object" && !Array.isArray(entry)) {
        return entry as SiteMapApiEntity;
      }
      return null;
    })
    .filter((entry): entry is SiteMapApiEntity => entry !== null);
};

const normalizeGraphPayload = (
  payload: Partial<KnowledgeGraphPayload> | null | undefined
): KnowledgeGraphPayload => {
  const nodes = Array.isArray(payload?.nodes)
    ? payload.nodes.map((node) => ({
        key: String(node?.key ?? ""),
        name: String(node?.name ?? ""),
        type: String(node?.type ?? "Concept"),
        category: mapGraphCategory(node?.category ?? node?.type),
        normalized_name: String(node?.normalized_name ?? ""),
        sourceURLs: Array.isArray(node?.sourceURLs)
          ? node.sourceURLs.map((url) => String(url)).filter(Boolean)
          : [],
      }))
    : [];

  const edges = Array.isArray(payload?.edges)
    ? payload.edges.map((edge) => ({
        from: String((edge as { from?: unknown }).from ?? ""),
        to: String(edge?.to ?? ""),
        relation: mapGraphRelation(edge?.relation),
        source: String(edge?.source ?? "unknown"),
        page_url: String(edge?.page_url ?? ""),
      }))
    : [];

  const categories = Array.isArray(payload?.categories)
    ? payload.categories.map((category) => mapGraphCategory(category))
    : [];

  const urlMentions = Array.isArray(payload?.url_mentions)
    ? payload.url_mentions.map((url) => String(url)).filter(Boolean)
    : nodes.flatMap((node) => node.sourceURLs);

  return {
    nodes,
    edges,
    categories: Array.from(
      new Set(categories.length ? categories : nodes.map((node) => node.category))
    ).filter((category): category is GraphCategory =>
      GRAPH_CATEGORIES.includes(category as GraphCategory)
    ),
    url_mentions: Array.from(new Set(urlMentions)),
  };
};

export const fetchSiteMap = async (
  siteId: number,
  headers: HeadersInit = {}
): Promise<SiteMapPayload> => {
  const [projectPayload, latestAuditPayload] = await Promise.all([
    requestJson<ProjectSummaryApiResponse>({
      endpoint: `/api/projects/${siteId}`,
      method: "GET",
      headers,
      errorMessage: "Unable to load site map data.",
    }),
    requestJson<ProjectLatestAuditApiResponse | null>({
      endpoint: `/api/projects/${siteId}/audits/latest?include_full_report=true&audit_type=DEEP`,
      method: "GET",
      headers,
      errorMessage: "Unable to load site map data.",
    }),
  ]);

  if (!projectPayload || latestAuditPayload === null) {
    throw new Error("Unable to load site map data.");
  }

  const entities = extractEntitiesFromAuditReport(latestAuditPayload.full_report);

  return {
    siteId: Number(projectPayload.id ?? latestAuditPayload.project_id ?? siteId),
    auditCount: Number(projectPayload.audit_count ?? 0),
    lastSeenAt:
      projectPayload.last_audit_at == null
        ? latestAuditPayload.created_at == null
          ? null
          : String(latestAuditPayload.created_at)
        : String(projectPayload.last_audit_at),
    entities: entities.map(mapSiteMapEntity).filter((entity) => entity.name.length > 0),
  };
};

export const fetchSemanticGap = async (
  baseSiteId: number,
  competitorSiteId: number,
  headers: HeadersInit = {}
): Promise<SemanticGapPayload> => {
  const params = new URLSearchParams({
    base_site_id: String(baseSiteId),
    comp_site_id: String(competitorSiteId),
  });
  const payload = await requestJson<SemanticGapPayload>({
    endpoint: `/api/v1/competitors/semantic-gap?${params.toString()}`,
    method: "GET",
    headers,
    errorMessage: "Unable to load semantic gap data.",
  });

  return {
    ...payload,
    categories: Array.isArray(payload.categories) ? payload.categories : [],
    venn: Array.isArray(payload.venn) ? payload.venn : [],
    heatmap: Array.isArray(payload.heatmap) ? payload.heatmap : [],
    opportunities: Array.isArray(payload.opportunities) ? payload.opportunities : [],
    knowledgeGraph: normalizeGraphPayload(payload.knowledgeGraph),
    brandAssociations: Array.isArray(payload.brandAssociations) ? payload.brandAssociations : [],
  };
};

export const fetchEntityGraph = async (
  url: string,
  headers: HeadersInit = {}
): Promise<EntityGraphApiResponse> => {
  const payload = await requestJson<EntityGraphApiResponse>({
    endpoint: `/api/v1/entities/graph?url=${encodeURIComponent(url)}`,
    method: "GET",
    headers,
    errorMessage: "Unable to load entity graph data.",
  });

  return {
    url: String(payload.url ?? url),
    uniqueness:
      payload.uniqueness && typeof payload.uniqueness === "object" ? payload.uniqueness : {},
    ...normalizeGraphPayload(payload),
  };
};

export { mapGraphCategory, mapGraphRelation, normalizeGraphPayload };
