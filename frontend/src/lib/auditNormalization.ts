import {
  hasCanonicalFields,
  isCanonicalAuditReportPayload,
  normalizeAuditReport,
  type CanonicalAuditReport,
} from "@/lib/reportAdapters";

export type AuditModuleKey = "seo" | "geo" | "aeo";

export type AuditEvidenceStatus = "measured" | "fallback" | "missing";
export type AuditModuleHealth = "measured" | "partial" | "unavailable";
export type AuditNormalizationSource = "canonical" | "legacy" | "mismatched";

export type AuditEvidenceField = {
  key: string;
  label: string;
  status: AuditEvidenceStatus;
  source: string;
  value: unknown;
};

export type AuditModuleDiagnostics = {
  module: AuditModuleKey;
  status: AuditModuleHealth;
  summary: string;
  fields: AuditEvidenceField[];
  issues: string[];
};

export type AuditNormalizationDiagnostics = {
  degraded: boolean;
  source: AuditNormalizationSource;
  summary: string;
  issues: string[];
  serviceIssues: string[];
  modules: Record<AuditModuleKey, AuditModuleDiagnostics>;
  telemetryFingerprint: string;
};

export type NormalizeAuditReportWithDiagnosticsResult = {
  report: CanonicalAuditReport | null;
  diagnostics: AuditNormalizationDiagnostics;
};

type SourceSpec = {
  path: string[];
  source: string;
  status?: Extract<AuditEvidenceStatus, "measured" | "fallback">;
};

type FieldSpec = {
  key: string;
  label: string;
  required?: boolean;
  sources: SourceSpec[];
};

const reportedFingerprints = new Set<string>();

const toObject = (value: unknown): Record<string, unknown> =>
  typeof value === "object" && value !== null && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};

const readPath = (value: unknown, path: string[]): unknown => {
  let current: unknown = value;

  for (const segment of path) {
    if (!current || typeof current !== "object" || Array.isArray(current)) {
      return undefined;
    }
    current = (current as Record<string, unknown>)[segment];
  }

  return current;
};

const pathKey = (path: string[]) => path.join(".");

const hasUsableValue = (value: unknown): boolean => {
  if (value === null || value === undefined) return false;
  if (typeof value === "string") return value.trim().length > 0;
  if (typeof value === "number") return Number.isFinite(value);
  if (typeof value === "boolean") return true;
  if (Array.isArray(value)) return value.length > 0;
  if (typeof value === "object") return Object.keys(value as Record<string, unknown>).length > 0;
  return false;
};

const emptyModuleDiagnostics = (module: AuditModuleKey): AuditModuleDiagnostics => ({
  module,
  status: "unavailable",
  summary: "This module does not have usable audit evidence.",
  fields: [],
  issues: ["This module does not have usable audit evidence."],
});

const MODULE_FIELD_SPECS: Record<AuditModuleKey, FieldSpec[]> = {
  seo: [
    {
      key: "overall",
      label: "SEO integrity",
      required: true,
      sources: [
        { path: ["scores", "seo"], source: "Canonical score: scores.seo" },
        {
          path: ["analysis", "seo_score", "score"],
          source: "Legacy analysis score: analysis.seo_score.score",
          status: "fallback",
        },
        {
          path: ["analysis", "seo_score"],
          source: "Legacy analysis score: analysis.seo_score",
          status: "fallback",
        },
      ],
    },
    {
      key: "onpage",
      label: "On-page synthesis",
      required: true,
      sources: [{ path: ["seo", "onpage"], source: "Canonical section: seo.onpage" }],
    },
    {
      key: "performance",
      label: "Performance ops",
      required: true,
      sources: [
        { path: ["seo", "performance"], source: "Canonical section: seo.performance" },
        {
          path: ["technical_signals", "performance", "score"],
          source: "Technical evidence: technical_signals.performance.score",
          status: "fallback",
        },
        {
          path: ["performance", "performance_score"],
          source: "Legacy performance: performance.performance_score",
          status: "fallback",
        },
        {
          path: ["site", "performance", "performance_score"],
          source: "Legacy site performance: site.performance.performance_score",
          status: "fallback",
        },
      ],
    },
    {
      key: "indexing",
      label: "Indexing health",
      required: true,
      sources: [{ path: ["seo", "indexing"], source: "Canonical section: seo.indexing" }],
    },
  ],
  geo: [
    {
      key: "overall",
      label: "AI visibility influence",
      required: true,
      sources: [
        { path: ["scores", "geo"], source: "Canonical score: scores.geo" },
        { path: ["geo", "visibility_index"], source: "Canonical section: geo.visibility_index" },
        {
          path: ["analysis", "geo_score", "score"],
          source: "Legacy analysis score: analysis.geo_score.score",
          status: "fallback",
        },
        {
          path: ["analysis", "geo_score"],
          source: "Legacy analysis score: analysis.geo_score",
          status: "fallback",
        },
      ],
    },
    {
      key: "citation_share",
      label: "Citation share",
      required: true,
      sources: [
        { path: ["geo", "citation_share"], source: "Canonical section: geo.citation_share" },
        {
          path: ["geo", "citation_consistency_score"],
          source: "Canonical AI visibility signal: geo.citation_consistency_score",
          status: "fallback",
        },
        {
          path: ["analysis", "citability_score"],
          source: "Legacy analysis signal: analysis.citability_score",
          status: "fallback",
        },
      ],
    },
    {
      key: "brand_anchor",
      label: "Brand anchor",
      required: true,
      sources: [
        { path: ["geo", "brand_anchor"], source: "Canonical section: geo.brand_anchor" },
        {
          path: ["geo", "entity_matching_score"],
          source: "Canonical AI visibility signal: geo.entity_matching_score",
          status: "fallback",
        },
        {
          path: ["analysis", "entity_matching_score"],
          source: "Legacy analysis signal: analysis.entity_matching_score",
          status: "fallback",
        },
      ],
    },
    {
      key: "spatial_logic",
      label: "Spatial logic",
      required: false,
      sources: [
        { path: ["geo", "spatial_content"], source: "Canonical section: geo.spatial_content" },
        {
          path: ["geo", "relevance_score"],
          source: "Canonical AI visibility signal: geo.relevance_score",
          status: "fallback",
        },
      ],
    },
  ],
  aeo: [
    {
      key: "overall",
      label: "Answer engine index",
      required: true,
      sources: [
        { path: ["scores", "aeo"], source: "Canonical score: scores.aeo" },
        {
          path: ["aeo", "answerability_score"],
          source: "Canonical section: aeo.answerability_score",
        },
        {
          path: ["analysis", "aeo_score", "score"],
          source: "Legacy analysis score: analysis.aeo_score.score",
          status: "fallback",
        },
        {
          path: ["analysis", "aeo_score"],
          source: "Legacy analysis score: analysis.aeo_score",
          status: "fallback",
        },
      ],
    },
    {
      key: "answerability",
      label: "Answerability",
      required: true,
      sources: [
        {
          path: ["aeo", "answerability_score"],
          source: "Canonical section: aeo.answerability_score",
        },
        {
          path: ["analysis", "aeo_score", "score"],
          source: "Legacy analysis score: analysis.aeo_score.score",
          status: "fallback",
        },
      ],
    },
    {
      key: "extractable_pages",
      label: "Extractable units",
      required: true,
      sources: [
        { path: ["aeo", "extractable_pages"], source: "Canonical section: aeo.extractable_pages" },
        {
          path: ["analysis", "extractable_pages"],
          source: "Legacy analysis field: analysis.extractable_pages",
          status: "fallback",
        },
      ],
    },
    {
      key: "schema_coverage",
      label: "Schema coverage",
      required: false,
      sources: [
        {
          path: ["aeo", "schema_coverage", "coverage_percent"],
          source: "Canonical section: aeo.schema_coverage.coverage_percent",
        },
        {
          path: ["aeo", "schema_health", "coverage_percent"],
          source: "Canonical section: aeo.schema_health.coverage_percent",
          status: "fallback",
        },
        {
          path: ["aeo", "schema_health", "score"],
          source: "Canonical section: aeo.schema_health.score",
          status: "fallback",
        },
      ],
    },
  ],
};

const resolveFieldEvidence = (
  raw: Record<string, unknown>,
  spec: FieldSpec,
  injectedPaths: Set<string>
): AuditEvidenceField => {
  for (const source of spec.sources) {
    const value = readPath(raw, source.path);
    if (!hasUsableValue(value)) {
      continue;
    }

    const injected = injectedPaths.has(pathKey(source.path));
    return {
      key: spec.key,
      label: spec.label,
      status: injected ? "fallback" : (source.status ?? "measured"),
      source: injected ? `Audit history row: ${pathKey(source.path)}` : source.source,
      value,
    };
  }

  return {
    key: spec.key,
    label: spec.label,
    status: "missing",
    source: "No safe source available",
    value: null,
  };
};

const summarizeModuleDiagnostics = (
  module: AuditModuleKey,
  fields: AuditEvidenceField[]
): AuditModuleDiagnostics => {
  const missingRequiredFields = fields
    .filter(
      (field) =>
        field.status === "missing" &&
        MODULE_FIELD_SPECS[module].some((spec) => spec.key === field.key && spec.required)
    )
    .map((field) => field.label);
  const fallbackFields = fields
    .filter((field) => field.status === "fallback")
    .map((field) => field.label);
  const measuredCount = fields.filter((field) => field.status === "measured").length;

  let status: AuditModuleHealth = "measured";
  if (missingRequiredFields.length === fields.filter((field) => field.label).length) {
    status = "unavailable";
  } else if (missingRequiredFields.length > 0 || fallbackFields.length > 0) {
    status = "partial";
  }

  const issues: string[] = [];
  if (missingRequiredFields.length > 0) {
    issues.push(
      `Missing required evidence for ${missingRequiredFields.join(", ")}. Those cards stay unavailable instead of inferred.`
    );
  }
  if (fallbackFields.length > 0) {
    issues.push(
      `Legacy or injected fallback data was used for ${fallbackFields.join(", ")}. Verify these values before sharing them.`
    );
  }
  if (measuredCount === 0 && issues.length === 0) {
    issues.push("No safe evidence sources were available for this module.");
  }

  return {
    module,
    status,
    summary:
      issues[0] ??
      (status === "measured"
        ? "All primary cards are backed by direct audit evidence."
        : "Evidence is incomplete for this module."),
    fields,
    issues,
  };
};

const collectServiceIssues = (normalized: CanonicalAuditReport): string[] => {
  const metadata = toObject(normalized.metadata);
  const serviceStatus = toObject(metadata.service_status);
  const serviceErrors = toObject(metadata.service_errors);
  const issues: string[] = [];

  Object.entries(serviceStatus).forEach(([key, value]) => {
    const normalizedValue = String(value ?? "")
      .trim()
      .toLowerCase();
    if (!normalizedValue || normalizedValue === "ok" || normalizedValue === "healthy") {
      return;
    }
    issues.push(`${key} status is ${normalizedValue}. Some checks may be skipped or incomplete.`);
  });

  Object.entries(serviceErrors).forEach(([key, value]) => {
    const message = String(value ?? "").trim();
    if (!message) {
      return;
    }
    issues.push(`${key} reported: ${message}`);
  });

  if (metadata.audit_outcome === "degraded") {
    issues.push(
      "The audit finished in a degraded state. Review missing sources before trusting recommendations."
    );
  }

  if (metadata.scores_available === false) {
    issues.push("The backend marked this audit as having unavailable scores.");
  }

  return issues;
};

const buildDiagnostics = (
  raw: Record<string, unknown>,
  normalized: CanonicalAuditReport,
  source: AuditNormalizationSource,
  injectedPaths: Set<string>
): AuditNormalizationDiagnostics => {
  const modules = {
    seo: summarizeModuleDiagnostics(
      "seo",
      MODULE_FIELD_SPECS.seo.map((spec) => resolveFieldEvidence(raw, spec, injectedPaths))
    ),
    geo: summarizeModuleDiagnostics(
      "geo",
      MODULE_FIELD_SPECS.geo.map((spec) => resolveFieldEvidence(raw, spec, injectedPaths))
    ),
    aeo: summarizeModuleDiagnostics(
      "aeo",
      MODULE_FIELD_SPECS.aeo.map((spec) => resolveFieldEvidence(raw, spec, injectedPaths))
    ),
  } satisfies Record<AuditModuleKey, AuditModuleDiagnostics>;

  const serviceIssues = collectServiceIssues(normalized);
  const issues = [
    ...(source === "legacy"
      ? [
          "This audit used a legacy report shape. The UI is showing only fields that still map cleanly to the current contract.",
        ]
      : []),
    ...Object.values(modules).flatMap((module) => module.issues),
    ...serviceIssues,
  ];

  const degraded = source !== "canonical" || issues.length > 0;
  const telemetryFingerprint = JSON.stringify({
    schemaVersion: normalized.schema_version,
    source,
    issues,
    moduleStates: {
      seo: modules.seo.status,
      geo: modules.geo.status,
      aeo: modules.aeo.status,
    },
  });

  return {
    degraded,
    source,
    summary:
      issues[0] ??
      "Direct audit evidence is available for the primary module cards and recommendation context.",
    issues,
    serviceIssues,
    modules,
    telemetryFingerprint,
  };
};

const emitSchemaDriftTelemetry = (diagnostics: AuditNormalizationDiagnostics) => {
  if (!diagnostics.degraded || reportedFingerprints.has(diagnostics.telemetryFingerprint)) {
    return;
  }

  reportedFingerprints.add(diagnostics.telemetryFingerprint);

  const payload = {
    source: diagnostics.source,
    summary: diagnostics.summary,
    issues: diagnostics.issues,
    moduleStates: {
      seo: diagnostics.modules.seo.status,
      geo: diagnostics.modules.geo.status,
      aeo: diagnostics.modules.aeo.status,
    },
  };

  console.warn("[audit-schema-drift]", payload);
};

export const getAuditEvidenceNumber = (
  diagnostics: AuditModuleDiagnostics | null | undefined,
  key: string
): number | null => {
  const value = diagnostics?.fields.find((field) => field.key === key)?.value;
  if (typeof value === "number" && Number.isFinite(value)) {
    return value;
  }
  if (typeof value === "string") {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : null;
  }
  return null;
};

export const normalizeAuditReportWithDiagnostics = (
  rawReport: Record<string, unknown>,
  options: { injectedPaths?: Iterable<string> } = {}
): NormalizeAuditReportWithDiagnosticsResult => {
  const injectedPaths = new Set(options.injectedPaths ?? []);

  if (hasCanonicalFields(rawReport) && typeof rawReport.schema_version !== "string") {
    const diagnostics: AuditNormalizationDiagnostics = {
      degraded: true,
      source: "mismatched",
      summary: "Canonical-looking audit data is missing schema_version and cannot be trusted.",
      issues: ["Canonical-looking audit data is missing schema_version and was rejected."],
      serviceIssues: [],
      modules: {
        seo: emptyModuleDiagnostics("seo"),
        geo: emptyModuleDiagnostics("geo"),
        aeo: emptyModuleDiagnostics("aeo"),
      },
      telemetryFingerprint: JSON.stringify({
        source: "mismatched",
        issue: "missing_schema_version",
      }),
    };
    emitSchemaDriftTelemetry(diagnostics);
    return { report: null, diagnostics };
  }

  try {
    const normalized = normalizeAuditReport(rawReport as Record<string, any>);
    const source: AuditNormalizationSource = isCanonicalAuditReportPayload(
      rawReport as Record<string, any>
    )
      ? "canonical"
      : "legacy";
    const diagnostics = buildDiagnostics(rawReport, normalized, source, injectedPaths);
    emitSchemaDriftTelemetry(diagnostics);
    return { report: normalized, diagnostics };
  } catch (error) {
    const diagnostics: AuditNormalizationDiagnostics = {
      degraded: true,
      source: "mismatched",
      summary: "Audit data could not be normalized safely, so module metrics are unavailable.",
      issues: [
        error instanceof Error
          ? error.message
          : "Audit data could not be normalized safely, so module metrics are unavailable.",
      ],
      serviceIssues: [],
      modules: {
        seo: emptyModuleDiagnostics("seo"),
        geo: emptyModuleDiagnostics("geo"),
        aeo: emptyModuleDiagnostics("aeo"),
      },
      telemetryFingerprint: JSON.stringify({
        source: "mismatched",
        issue: error instanceof Error ? error.message : "unknown",
      }),
    };
    emitSchemaDriftTelemetry(diagnostics);
    return { report: null, diagnostics };
  }
};
