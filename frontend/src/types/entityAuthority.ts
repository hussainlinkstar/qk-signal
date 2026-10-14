export interface EntityAuthorityBreakdown {
  coverage: number;
  depth: number;
  consistency: number;
  uniqueness: number;
}

export interface EntityAuthoritySummary {
  project_id: number;
  authority_score: number;
  breakdown: EntityAuthorityBreakdown;
  target_entities: number;
  detected_entities: number;
  gap_count: number;
  computed_at: string;
  computation_version: string;
}

export interface EntityAuthorityGap {
  entity_key: string;
  entity_name: string;
  reason: string;
}

export interface EntityAuthorityTrendPoint {
  authority_score: number;
  coverage_score: number;
  depth_score: number;
  consistency_score: number;
  uniqueness_score: number;
  target_entity_count: number;
  detected_entity_count: number;
  gap_count: number;
  computed_at: string;
  computation_version: string;
}

export interface EntityAuthorityTrendResponse {
  project_id: number;
  points: EntityAuthorityTrendPoint[];
}

export interface EntityGraphNode {
  key: string;
  name: string;
  category: string;
  normalized_name: string;
  sourceURLs: string[];
  entity_key: string;
  relevance_score: number;
  mention_count: number;
  node_size: number;
  is_missing_target: boolean;
}

export interface EntityGraphEdge {
  from: string;
  to: string;
  relation: string;
  frequency: number;
  thickness: number;
}

export interface EntityGraphResponse {
  project_id: number;
  nodes: EntityGraphNode[];
  edges: EntityGraphEdge[];
  categories: string[];
  url_mentions: string[];
  missing_target_entities: EntityAuthorityGap[];
  audit_count: number;
}
