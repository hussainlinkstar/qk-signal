import { describe, expect, it } from "vitest";
import { sanitizeSystemStatusPayload } from "./system-status";

describe("sanitizeSystemStatusPayload", () => {
  it("redacts sensitive service details and normalizes service names", () => {
    const payload = sanitizeSystemStatusPayload(
      {
        services: {
          database: {
            name: "PostgreSQL Cluster",
            status: "operational",
            details: "PostgreSQL is healthy.",
          },
          cache: {
            name: "Redis Cache",
            status: "degraded",
            details: "Redis latency spike detected.",
          },
          dataforseo: {
            name: "DataForSEO API",
            status: "not_configured",
            details: "DATAFORSEO_LOGIN / DATAFORSEO_PASSWORD is not configured.",
          },
        },
      },
      "public"
    );

    expect(payload.services.database).toMatchObject({
      name: "Database",
      status: "Operational",
      details: "Healthy and responding normally.",
    });

    expect(payload.services.cache).toMatchObject({
      name: "Cache Service",
      status: "Degraded Performance",
      details: "Elevated latency detected. Mitigation is in progress.",
    });

    expect(payload.services.dataforseo).toMatchObject({
      name: "DataForSEO",
      status: "Not Configured",
      details: "Service is not configured in this environment.",
    });
  });

  it("keeps non-sensitive admin details and redacts sensitive ones", () => {
    const payload = sanitizeSystemStatusPayload(
      {
        services: {
          database: {
            name: "Primary Database",
            status: "major_outage",
            details: "PostgreSQL connection refused.",
          },
          openai_ai: {
            name: "OpenAI Gateway",
            status: "degraded_performance",
            details: "Increased upstream latency on requests.",
          },
        },
        audit_metrics: {
          jobs_started: 10,
          jobs_succeeded: 7,
          jobs_failed: 3,
          job_attempts_total: 12,
          job_retries: 2,
          job_duration_seconds_total: 31.5,
        },
      },
      "admin"
    );

    expect(payload.services.database?.details).toBe(
      "Service disruption detected. Recovery is in progress."
    );
    expect(payload.services.openai_ai?.details).toBe("Increased upstream latency on requests.");
    expect(payload.audit_metrics?.jobs_started).toBe(10);
    expect(payload.audit_metrics?.job_duration_seconds_total).toBe(31.5);
  });

  it("omits audit metrics for public payloads", () => {
    const payload = sanitizeSystemStatusPayload(
      {
        services: {
          scraper: {
            name: "Scraper",
            status: "ok",
          },
        },
        audit_metrics: {
          jobs_started: 3,
        },
      },
      "public"
    );

    expect(payload.audit_metrics).toBeUndefined();
    expect(payload.services.scraper?.status).toBe("Operational");
  });
});
