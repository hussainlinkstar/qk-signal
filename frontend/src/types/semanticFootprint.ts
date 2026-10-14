export type EntityCategory =
  | "brand"
  | "product"
  | "service"
  | "person"
  | "location"
  | "topic"
  | "other";

export type GraphCategory = "Person" | "Organization" | "Concept" | "Product";

export type GraphRelationType = "MENTIONED_IN" | "RELATED_TO";

export type SemanticVennNode = {
  id: string;
  label: string;
  overlapScore: number;
  siteMentions: number;
  competitorMentions: number;
  category: EntityCategory;
};

export type EntityImportanceCell = {
  entity: string;
  category: EntityCategory;
  relevanceScore: number;
  confidenceScore: number;
  sourceUrl: string;
};

export type SemanticOpportunity = {
  id: string;
  entity: string;
  category: EntityCategory;
  opportunityScore: number;
  reasoning: string;
  suggestedAction: string;
  sourceUrls: string[];
};

export type KnowledgeGraphNode = {
  key: string;
  name: string;
  type: string;
  category: GraphCategory;
  normalized_name: string;
  sourceURLs: string[];
};

export type KnowledgeGraphEdge = {
  from: string;
  to: string;
  relation: GraphRelationType;
  source: string;
  page_url: string;
};

export type KnowledgeGraphPayload = {
  nodes: KnowledgeGraphNode[];
  edges: KnowledgeGraphEdge[];
  categories: GraphCategory[];
  url_mentions: string[];
};

export type BrandAssociation = {
  brand: string;
  sentiment: "positive" | "neutral" | "negative";
  strength: number;
  relatedEntities: string[];
  sourceUrls: string[];
};

export type SiteMapPayload = {
  siteId: number;
  auditCount: number;
  lastSeenAt: string | null;
  entities: Array<{
    name: string;
    normalizedKey: string;
    frequency: number;
    avgRelevanceScore: number;
    category: EntityCategory;
  }>;
};

export type SemanticGapPayload = {
  siteId: number;
  generatedAt: string;
  categories: EntityCategory[];
  venn: SemanticVennNode[];
  heatmap: EntityImportanceCell[];
  opportunities: SemanticOpportunity[];
  knowledgeGraph: KnowledgeGraphPayload;
  brandAssociations: BrandAssociation[];
};

export type EntityGraphApiResponse = {
  url: string;
  uniqueness: Record<string, unknown>;
} & KnowledgeGraphPayload;
