export type ServiceHealthStatus =
  | "Operational"
  | "Degraded Performance"
  | "Major Outage"
  | "Not Configured"
  // Configured, but its health could not be verified. Reported instead of
  // "Operational" whenever a component has no working probe or its probe did
  // not complete, so the status page never claims health it has not checked.
  | "Unknown";

export type BackendService = {
  name: string;
  status: ServiceHealthStatus;
  details?: string;
};

export type AuditMetrics = {
  jobs_started: number;
  jobs_succeeded: number;
  jobs_failed: number;
  job_attempts_total: number;
  job_retries: number;
  job_duration_seconds_total: number;
};

export type SecurityPosture = {
  redis_auth: boolean;
  redis_tls: boolean;
  credential_boundary_role: string | null;
  credential_boundary_enforce: boolean;
};

export type SystemStatusPayload = {
  services: Record<string, BackendService>;
  audit_metrics?: AuditMetrics;
  available_models?: string[];
  security_posture?: SecurityPosture;
};

export type StatusAudience = "public" | "admin";

const DISPLAY_NAME_MAP: Record<string, string> = {
  database: "Database",
  cache: "Cache Service",
  scraper: "Content Scraper",
  project_data_sources: "Data Sources",
  stripe: "Stripe Billing",
  dataforseo: "DataForSEO",
  serpapi: "SerpAPI / Search",
  pagespeed: "PageSpeed Insights",
};

const SENSITIVE_SERVICES = new Set(["database", "cache", "scraper"]);
const KNOWN_STATUSES: ServiceHealthStatus[] = [
  "Operational",
  "Degraded Performance",
  "Major Outage",
  "Not Configured",
  "Unknown",
];

const STATUS_ALIAS_MAP: Record<string, ServiceHealthStatus> = {
  operational: "Operational",
  ok: "Operational",
  healthy: "Operational",
  degraded: "Degraded Performance",
  degraded_performance: "Degraded Performance",
  partial_outage: "Degraded Performance",
  outage: "Major Outage",
  major_outage: "Major Outage",
  down: "Major Outage",
  not_configured: "Not Configured",
  unconfigured: "Not Configured",
  disabled: "Not Configured",
  unknown: "Unknown",
  unverified: "Unknown",
};

const INFRA_TECH_PATTERN =
  /\b(redis|postgres(?:ql)?|mysql|mariadb|mongodb|sqlite|memcached|dynamodb|aurora|cockroach(?:db)?)\b/gi;

const toRecord = (value: unknown): Record<string, unknown> =>
  value && typeof value === "object" ? (value as Record<string, unknown>) : {};

const toFiniteNumber = (value: unknown): number =>
  typeof value === "number" && Number.isFinite(value) ? value : 0;

const normalizeServiceId = (serviceId: string): string => serviceId.trim().toLowerCase();

const safeServiceName = (serviceId: string, fallback?: string): string => {
  const normalized = normalizeServiceId(serviceId);
  if (DISPLAY_NAME_MAP[normalized]) {
    return DISPLAY_NAME_MAP[normalized];
  }

  if (typeof fallback === "string" && fallback.trim()) {
    return fallback.trim();
  }

  return normalized
    .split("_")
    .filter(Boolean)
    .map((segment) => segment.charAt(0).toUpperCase() + segment.slice(1))
    .join(" ");
};

export const normalizeServiceStatus = (value: unknown): ServiceHealthStatus => {
  if (typeof value !== "string") {
    return "Degraded Performance";
  }

  const trimmed = value.trim();
  if (KNOWN_STATUSES.includes(trimmed as ServiceHealthStatus)) {
    return trimmed as ServiceHealthStatus;
  }

  const normalized = trimmed.toLowerCase().replace(/\s+/g, "_");
  return STATUS_ALIAS_MAP[normalized] ?? "Degraded Performance";
};

const normalizeDetails = (value: unknown): string | undefined => {
  if (typeof value !== "string") {
    return undefined;
  }
  const cleaned = value.replace(INFRA_TECH_PATTERN, "managed service").trim();
  return cleaned || undefined;
};

const sensitiveDetailsByStatus: Record<ServiceHealthStatus, string> = {
  Operational: "Healthy and responding normally.",
  "Degraded Performance": "Elevated latency detected. Mitigation is in progress.",
  "Major Outage": "Service disruption detected. Recovery is in progress.",
  "Not Configured": "Service is not configured in this environment.",
  Unknown: "Health could not be verified, so this component is not reported as operational.",
};

const normalizeAuditMetrics = (value: unknown): AuditMetrics | undefined => {
  const source = toRecord(value);
  if (Object.keys(source).length === 0) {
    return undefined;
  }

  return {
    jobs_started: toFiniteNumber(source.jobs_started),
    jobs_succeeded: toFiniteNumber(source.jobs_succeeded),
    jobs_failed: toFiniteNumber(source.jobs_failed),
    job_attempts_total: toFiniteNumber(source.job_attempts_total),
    job_retries: toFiniteNumber(source.job_retries),
    job_duration_seconds_total: toFiniteNumber(source.job_duration_seconds_total),
  };
};

export const sanitizeSystemStatusPayload = (
  value: unknown,
  audience: StatusAudience
): SystemStatusPayload => {
  const source = toRecord(value);
  const sourceServices = toRecord(source.services);
  const services: Record<string, BackendService> = {};

  for (const [id, serviceValue] of Object.entries(sourceServices)) {
    const service = toRecord(serviceValue);
    const normalizedId = normalizeServiceId(id);
    const status = normalizeServiceStatus(service.status);
    const baseDetails = normalizeDetails(service.details);
    const isSensitive = SENSITIVE_SERVICES.has(normalizedId);

    const details =
      isSensitive || audience === "public"
        ? sensitiveDetailsByStatus[status]
        : (baseDetails ?? sensitiveDetailsByStatus[status]);

    services[id] = {
      name: safeServiceName(id, typeof service.name === "string" ? service.name : undefined),
      status,
      details,
    };
  }

  const payload: SystemStatusPayload = { services };

  if (Array.isArray(source.available_models)) {
    payload.available_models = source.available_models.map((m) => String(m));
  }

  if (audience === "admin") {
    const metrics = normalizeAuditMetrics(source.audit_metrics);
    if (metrics) {
      payload.audit_metrics = metrics;
    }
    const posture = source.security_posture;
    if (posture && typeof posture === "object") {
      const p = posture as Record<string, unknown>;
      payload.security_posture = {
        redis_auth: p.redis_auth === true,
        redis_tls: p.redis_tls === true,
        credential_boundary_role:
          typeof p.credential_boundary_role === "string" ? p.credential_boundary_role : null,
        credential_boundary_enforce: p.credential_boundary_enforce === true,
      };
    }
  }

  return payload;
};
