import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { describe, expect, it } from "vitest";

import { normalizeAuditHistoryPayload } from "@/lib/dashboardHistoryAdapters";
import { isAuditResult } from "./auditResult";

const loadCanonicalFixture = () => {
  const fixturePath = resolve(process.cwd(), "../contracts/canonical_audit_payload.sample.json");
  return JSON.parse(readFileSync(fixturePath, "utf-8")) as unknown;
};

const cloneFixture = <T>(fixture: T): T => JSON.parse(JSON.stringify(fixture)) as T;

describe("audit result contract", () => {
  it("accepts the canonical backend payload sample in the frontend type guard", () => {
    const fixture = loadCanonicalFixture();
    expect(isAuditResult(fixture)).toBe(true);
  });

  it("preserves canonical payload fields through history normalization", () => {
    const fixture = loadCanonicalFixture();
    const normalized = normalizeAuditHistoryPayload([
      { id: 42, status: "completed", full_report: fixture },
    ]);

    expect(normalized).toHaveLength(1);
    expect(normalized[0]?.scores.overall).toBe(73);
    expect(normalized[0]?.metadata.intent).toBe("informational");
    expect(normalized[0]?.metadata.query_type).toBe("informational");
    expect(normalized[0]?.hallucination?.flagged_claims).toBe(1);
    expect(normalized[0]?.hallucination?.omitted_claims).toBe(1);
    expect(normalized[0]?.hallucination?.field_summaries?.[0]?.field_path).toBe("summary");
  });

  it("accepts canonical payloads when nullable section scores are null", () => {
    const fixture = cloneFixture(loadCanonicalFixture()) as Record<string, any>;
    fixture.seo.performance = null;
    fixture.geo.visibility_index = null;
    fixture.aeo.answerability_score = null;

    expect(isAuditResult(fixture)).toBe(true);
  });

  it("keeps canonical payloads with nullable section scores out of legacy coercion", () => {
    const fixture = cloneFixture(loadCanonicalFixture()) as Record<string, any>;
    fixture.seo.performance = null;
    fixture.geo.visibility_index = null;
    fixture.aeo.answerability_score = null;

    const normalized = normalizeAuditHistoryPayload([
      { id: 77, status: "completed", full_report: fixture },
    ]);

    expect(normalized).toHaveLength(1);
    expect(normalized[0]?.seo.performance).toBeNull();
    expect(normalized[0]?.geo.visibility_index).toBeNull();
    expect(normalized[0]?.aeo.answerability_score).toBeNull();
    expect(normalized[0]?.metadata.version).toBe("2.0");
  });

  it("rejects canonical payloads that are missing schema_version", () => {
    const fixture = cloneFixture(loadCanonicalFixture()) as Record<string, any>;
    delete fixture.schema_version;

    expect(isAuditResult(fixture)).toBe(false);
  });
});
