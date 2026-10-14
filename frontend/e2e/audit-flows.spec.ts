import { createHmac } from "node:crypto";
import { expect, test, type APIRequestContext, type Page } from "@playwright/test";
import { buildTestUser, loginUser, registerAndLogin } from "./helpers";

const AUDIT_TARGET_URL = process.env.E2E_AUDIT_URL ?? "https://thothgraph.com";
const AUDIT_WAIT_TIMEOUT_MS = Number(process.env.E2E_AUDIT_TIMEOUT_MS ?? 12 * 60 * 1000);
// Per-test timeout for tests that run real audits
const AUDIT_TEST_TIMEOUT_MS = AUDIT_WAIT_TIMEOUT_MS + 60_000;

type DataExportResponse = {
  credits: number;
};

type AuditRecordResponse = {
  id: number;
  url: string;
  full_report?: Record<string, unknown> | null;
};

function escapeRegex(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function getNestedValue(payload: unknown, path: string): unknown {
  if (!payload || typeof payload !== "object") {
    return undefined;
  }

  return path.split(".").reduce<unknown>((cursor, segment) => {
    if (!cursor || typeof cursor !== "object") {
      return undefined;
    }
    return (cursor as Record<string, unknown>)[segment];
  }, payload);
}

function pickNumber(payload: unknown, paths: string[]): number | null {
  for (const path of paths) {
    const candidate = getNestedValue(payload, path);
    if (typeof candidate === "number" && Number.isFinite(candidate)) {
      return candidate;
    }
    if (typeof candidate === "string") {
      const parsed = Number.parseFloat(candidate);
      if (Number.isFinite(parsed)) {
        return parsed;
      }
    }
  }
  return null;
}

function pickString(payload: unknown, paths: string[]): string | null {
  for (const path of paths) {
    const candidate = getNestedValue(payload, path);
    if (typeof candidate === "string" && candidate.trim()) {
      return candidate.trim();
    }
  }
  return null;
}

function collectRecommendations(payload: Record<string, unknown>): string[] {
  const rawSources: unknown[] = [
    getNestedValue(payload, "suggestions"),
    getNestedValue(payload, "seo.suggestions"),
    getNestedValue(payload, "geo.suggestions"),
    getNestedValue(payload, "aeo.suggestions"),
    getNestedValue(payload, "seo.recommendations"),
    getNestedValue(payload, "geo.recommendations"),
    getNestedValue(payload, "aeo.recommendations"),
    getNestedValue(payload, "analysis.recommendations"),
    getNestedValue(payload, "analysis.seo_score.recommendations"),
    getNestedValue(payload, "analysis.aeo_score.recommendations"),
    getNestedValue(payload, "analysis.geo_score.recommendations"),
  ];

  const recommendations = new Set<string>();
  for (const source of rawSources) {
    if (!Array.isArray(source)) {
      continue;
    }
    for (const entry of source) {
      if (typeof entry === "string" && entry.trim()) {
        recommendations.add(entry.trim());
        continue;
      }
      if (entry && typeof entry === "object") {
        const row = entry as Record<string, unknown>;
        const candidate = row.action ?? row.title;
        if (typeof candidate === "string" && candidate.trim()) {
          recommendations.add(candidate.trim());
        }
      }
    }
  }

  return Array.from(recommendations);
}

function extractEntities(payload: Record<string, unknown>): string[] {
  const candidates: unknown[] = [
    getNestedValue(payload, "entities"),
    getNestedValue(payload, "entities.items"),
    getNestedValue(payload, "entities.entities"),
    getNestedValue(payload, "analysis.entities_detected"),
    getNestedValue(payload, "analysis.entity_data.entities"),
    getNestedValue(payload, "analysis.entity_data.entities_detected"),
  ];

  for (const candidate of candidates) {
    if (!Array.isArray(candidate)) {
      continue;
    }
    const normalized = candidate
      .map((entry) => {
        if (typeof entry === "string") {
          return entry.trim();
        }
        if (entry && typeof entry === "object") {
          const row = entry as Record<string, unknown>;
          const value = row.name ?? row.entity ?? row.label;
          if (typeof value === "string") {
            return value.trim();
          }
        }
        return "";
      })
      .filter(Boolean);

    if (normalized.length > 0) {
      return normalized;
    }
  }

  return [];
}

async function getAccessToken(page: Page): Promise<string> {
  const token = await page.evaluate(() => window.localStorage.getItem("auth_access_token"));
  expect(token, "Expected browser access token to exist after login").toBeTruthy();
  return token as string;
}

async function fetchAuthedJson<T>(
  request: APIRequestContext,
  path: string,
  accessToken: string,
  method: "GET" | "POST" | "PATCH" | "PUT" | "DELETE" = "GET",
  body?: unknown
): Promise<T> {
  const response = await request.fetch(path, {
    method,
    headers: {
      Authorization: `Bearer ${accessToken}`,
      ...(body ? { "Content-Type": "application/json" } : {}),
    },
    ...(body ? { data: body } : {}),
  });

  expect(response.ok(), `Expected ${method} ${path} to succeed but got ${response.status()}`).toBe(
    true
  );
  return (await response.json()) as T;
}

async function getRawCredits(request: APIRequestContext, accessToken: string): Promise<number> {
  const payload = await fetchAuthedJson<DataExportResponse>(
    request,
    "/api/users/me/data-export",
    accessToken
  );
  expect(typeof payload.credits).toBe("number");
  return payload.credits;
}

async function expectScoreCardValue(
  page: Page,
  label: string,
  expectedValue: number
): Promise<void> {
  const labelLocator = page
    .locator("p", { hasText: new RegExp(`^${escapeRegex(label)}$`) })
    .first();
  await expect(labelLocator).toBeVisible();
  const card = labelLocator.locator("xpath=..");
  await expect(card).toContainText(String(Math.round(expectedValue)));
}

function decodeBase32(value: string): Buffer {
  const alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567";
  const normalized = value
    .toUpperCase()
    .replace(/=+$/g, "")
    .replace(/[^A-Z2-7]/g, "");

  let bits = "";
  for (const char of normalized) {
    const index = alphabet.indexOf(char);
    if (index < 0) {
      continue;
    }
    bits += index.toString(2).padStart(5, "0");
  }

  const bytes: number[] = [];
  for (let i = 0; i + 8 <= bits.length; i += 8) {
    bytes.push(Number.parseInt(bits.slice(i, i + 8), 2));
  }

  return Buffer.from(bytes);
}

function generateTotp(secret: string, timestamp = Date.now()): string {
  const key = decodeBase32(secret);
  const counter = Math.floor(timestamp / 1000 / 30);
  const counterBuffer = Buffer.alloc(8);
  counterBuffer.writeBigUInt64BE(BigInt(counter), 0);

  const digest = createHmac("sha1", key).update(counterBuffer).digest();
  const offset = digest[digest.length - 1] & 0x0f;
  const binary =
    ((digest[offset] & 0x7f) << 24) |
    ((digest[offset + 1] & 0xff) << 16) |
    ((digest[offset + 2] & 0xff) << 8) |
    (digest[offset + 3] & 0xff);

  return String(binary % 1_000_000).padStart(6, "0");
}

test.describe.configure({ mode: "serial" });

test("Admin/User Account Flow: register, login, and session bootstrap", async ({
  page,
  request,
}) => {
  const user = buildTestUser();
  await registerAndLogin(page, user);

  await expect(page).toHaveURL(/\/dashboard\/overview/, { timeout: 30_000 });
  await expect(page.getByRole("heading", { name: /Site Selection Hub/i })).toBeVisible();

  const cookies = await page.context().cookies();
  const authCookie = cookies.find((cookie) => cookie.name === "auth_token");
  expect(authCookie?.value).toBeTruthy();

  const accessToken = await getAccessToken(page);
  const summary = await fetchAuthedJson<{ email: string; role: string; credits: number }>(
    request,
    "/api/users/me",
    accessToken
  );

  expect(summary.email).toBe(user.email);
  expect(summary.role.toLowerCase()).toContain("user");
  expect(typeof summary.credits).toBe("number");
});

test("Authenticated Audit Flow: run fast audit, verify internal credit deduction, and validate payload-to-UI mapping", async ({
  page,
  request,
}) => {
  test.setTimeout(AUDIT_TEST_TIMEOUT_MS);

  const user = buildTestUser();
  await registerAndLogin(page, user);
  const accessToken = await getAccessToken(page);

  await page.goto("/dashboard/audit");
  await expect(page.getByRole("heading", { name: /Audit Workspace/i })).toBeVisible();

  const initialCredits = await getRawCredits(request, accessToken);

  await page.locator("#audit-url").evaluate((node, value) => {
    const input = node as HTMLInputElement;
    input.value = String(value);
    input.dispatchEvent(new Event("input", { bubbles: true }));
  }, AUDIT_TARGET_URL);

  const auditRecordResponsePromise = page.waitForResponse(
    (response) => {
      if (response.request().method() !== "GET" || response.status() !== 200) {
        return false;
      }
      const pathname = new URL(response.url()).pathname;
      return /\/api\/audits\/\d+$/.test(pathname);
    },
    { timeout: AUDIT_WAIT_TIMEOUT_MS }
  );

  const runAuditButton = page.getByRole("button", { name: /Initialize Neural Scan/i });
  await expect(runAuditButton).toBeEnabled();
  await runAuditButton.click();

  const auditRecordResponse = await auditRecordResponsePromise;
  const auditRecord = (await auditRecordResponse.json()) as AuditRecordResponse;
  const report = (auditRecord.full_report ?? {}) as Record<string, unknown>;

  await expect(page.getByText(/Verified by Qiko Signal NeuralCore/i)).toBeVisible({
    timeout: AUDIT_WAIT_TIMEOUT_MS,
  });

  const finalCredits = await getRawCredits(request, accessToken);
  // Internal credit accounting still books a cost for the run; the estimate
  // copy is scan-framed so only the balance drop is asserted.
  expect(finalCredits).toBeLessThan(initialCredits);

  for (const key of ["site", "seo", "geo", "aeo", "scores", "metadata"]) {
    expect(report, `Missing required canonical section '${key}' in audit payload`).toHaveProperty(
      key
    );
  }

  const expectedSeo = pickNumber(report, [
    "scores.seo",
    "seo.onpage",
    "analysis.seo_score.score",
    "analysis.seo_score",
    "seo_score",
  ]);
  const expectedAeo = pickNumber(report, [
    "scores.aeo",
    "aeo.answerability_score",
    "analysis.aeo_score.score",
    "analysis.aeo_score",
    "aeo_score",
  ]);
  const expectedGeo = pickNumber(report, [
    "scores.geo",
    "geo.visibility_index",
    "analysis.geo_score.score",
    "analysis.geo_score",
    "geo_score",
  ]);

  if (expectedSeo !== null) {
    await expectScoreCardValue(page, "SEO Score", expectedSeo);
  }
  if (expectedAeo !== null) {
    await expectScoreCardValue(page, "AEO Score", expectedAeo);
  }
  if (expectedGeo !== null) {
    await expectScoreCardValue(page, "GEO Score", expectedGeo);
  }

  const networkVersion = pickString(report, [
    "network.http_version",
    "metadata.technical_signals.network.http_version",
    "site.network.http_version",
  ]);
  if (networkVersion) {
    await expect(
      page.getByText(new RegExp(`Network:\\s*${escapeRegex(networkVersion)}`, "i")).first()
    ).toBeVisible();
  }

  const recommendations = collectRecommendations(report);
  if (recommendations.length > 0) {
    await expect(page.getByRole("heading", { name: /Top Recommendations/i })).toBeVisible();
    const snippet = recommendations[0].slice(0, 40);
    await expect(page.getByText(new RegExp(escapeRegex(snippet), "i")).first()).toBeVisible();
  }

  await page.getByRole("button", { name: /^SEO$/i }).click();
  await expect(page.getByRole("heading", { name: /Core Web Vitals/i })).toBeVisible();

  await page.getByRole("button", { name: /^AEO$/i }).click();
  await expect(page.getByRole("heading", { name: /Readiness Score/i })).toBeVisible();

  await page.getByRole("button", { name: /^GEO$/i }).click();
  await expect(
    page.getByRole("heading", { name: /Generative Engine Optimization/i })
  ).toBeVisible();

  await page.getByRole("button", { name: /^Entities$/i }).click();
  await expect(page.getByRole("heading", { name: /Entity Stats/i })).toBeVisible();

  const entities = extractEntities(report);
  if (entities.length > 0) {
    await expect(
      page.getByText(new RegExp(`^${entities.length}\\s+detected$`, "i")).first()
    ).toBeVisible();
    await expect(page.getByText(new RegExp(escapeRegex(entities[0]), "i")).first()).toBeVisible();
  }
});

test("Audit form edge case: invalid URL blocks submission and shows validation feedback", async ({
  page,
}) => {
  const user = buildTestUser();
  await registerAndLogin(page, user);

  await page.goto("/dashboard/audit");
  await page.waitForLoadState("domcontentloaded");
  await expect(page.getByRole("heading", { name: /Audit Workspace/i })).toBeVisible();

  await page.locator("#audit-url").fill("invalid-url");
  await page.getByRole("button", { name: /Initialize Neural Scan/i }).click();

  await expect(page.getByText(/Please enter a valid URL/i)).toBeVisible();
});

test("MFA flow: enable MFA from account settings and complete MFA login challenge", async ({
  page,
}) => {
  test.setTimeout(AUDIT_TEST_TIMEOUT_MS);

  const user = buildTestUser();
  await registerAndLogin(page, user);

  await page.goto("/dashboard/account-settings");
  await expect(page.getByRole("heading", { name: /Account Settings/i })).toBeVisible();

  await page.getByRole("button", { name: /Generate MFA setup/i }).click();
  const secretInput = page.locator('label:has-text("Manual setup key") + input');
  await expect(secretInput).toBeVisible({ timeout: 20_000 });

  const secret = (await secretInput.inputValue()).replace(/\s+/g, "");
  expect(secret).toMatch(/^[A-Z2-7]{16,}$/);

  const mfaCodeInput = page.locator('label:has-text("Authenticator code") + input');
  await mfaCodeInput.fill(generateTotp(secret));
  await page.getByRole("button", { name: /Enable MFA/i }).click();
  if (
    await page
      .getByText(/Invalid MFA code/i)
      .isVisible({ timeout: 2000 })
      .catch(() => false)
  ) {
    await mfaCodeInput.fill(generateTotp(secret, Date.now() + 1_000));
    await page.getByRole("button", { name: /Enable MFA/i }).click();
  }
  await expect(page.getByText(/Multi-factor authentication enabled/i)).toBeVisible();

  await page.request.post("/api/auth/logout");
  await page.evaluate(() => {
    window.localStorage.clear();
    window.sessionStorage.clear();
  });

  await loginUser(page, user);
  const loginCodeInput = page.getByPlaceholder("123456");
  await expect(loginCodeInput).toBeVisible();
  await loginCodeInput.fill(generateTotp(secret));
  await page.getByRole("button", { name: /Verify and Sign In/i }).click();
  if (
    await page
      .getByText(/Invalid MFA code/i)
      .isVisible({ timeout: 2000 })
      .catch(() => false)
  ) {
    await loginCodeInput.fill(generateTotp(secret, Date.now() + 1_000));
    await page.getByRole("button", { name: /Verify and Sign In/i }).click();
  }

  await expect(page).toHaveURL(/\/dashboard\/overview/, { timeout: 30_000 });
  await expect(page.getByRole("heading", { name: /Site Selection Hub/i })).toBeVisible();
});
