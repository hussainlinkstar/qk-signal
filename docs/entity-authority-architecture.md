# Entity Authority Architecture

Last updated: 2026-03-04

## Goal

Provide a deterministic, explainable `0-100` `Entity Authority Score` per project, with persisted component breakdown, historical trend snapshots, and knowledge graph drill-down.

## Inputs

- `Project.icp_roles` + `Project.usp` -> target entity set
- `Audit.full_report.analysis.entities_detected` + fallback entity lists -> detected entity signals
- `SiteEntityFact` rows -> stabilized entity keys/relevance by audit
- `ProjectCompetitorSnapshot.competitor_audit_id` and fallback competitor domains -> competitor entity baseline

## Scoring Model (`v1`)

`authority_score = 0.40 * coverage + 0.35 * depth + 0.15 * consistency + 0.10 * uniqueness`

All components are clamped to `0-100` and rounded to 2 decimals.

### 1) Coverage (40%)

- `coverage = (matched_target_entities / total_target_entities) * 100`
- If no targets are configured, coverage is `0`.

### 2) Depth (35%)

- Compute weighted relevance per detected entity:
  - entity weight: `log(frequency + 1)`
  - entity relevance: mean normalized relevance (`0-100`)
- `depth = sum(relevance * weight) / sum(weight)`
- If no detected entities, depth is `0`.

### 3) Consistency (15%)

- For each audit, compute entity presence ratio:
  - against target set when targets exist
  - otherwise against detected set
- Compute coefficient of variation: `CoV = stddev(ratios) / mean(ratios)`
- `consistency = (1 - min(max(CoV, 0), 1)) * 100`
- Single-audit projects return `100` when they have detected entities, otherwise `0`.

### 4) Uniqueness (10%)

- Collect competitor entity keys from competitor audits.
- `uniqueness = (project_only_entities / detected_entities) * 100`
- If competitor baseline is missing, uniqueness is `0` (conservative default).

## Persistence

`EntityAuthoritySnapshot` stores:

- `authority_score`
- `coverage_score`
- `depth_score`
- `consistency_score`
- `uniqueness_score`
- `target_entity_count`
- `detected_entity_count`
- `gap_count`
- `computation_version` (`v1`)
- `schema_version`
- `computed_at`

## API Surface

- `GET /api/v1/projects/{project_id}/entity-authority`
- `GET /api/v1/projects/{project_id}/entity-graph`
- `GET /api/v1/projects/{project_id}/entity-authority/gaps`
- `GET /api/v1/projects/{project_id}/entity-authority/trend`
- `POST /api/v1/projects/{project_id}/entity-authority/compute`

## Frontend Surface

- Route: `/dashboard/projects/[projectId]/entity-authority`
- Main states: loading, plan lock, no ICP, empty, success, error, degraded graph
- Main modules:
  - `EntityAuthorityScoreCard`
  - `EntityAuthorityBreakdown`
  - `EntityKnowledgeGraph`
  - `EntityGapTable`
