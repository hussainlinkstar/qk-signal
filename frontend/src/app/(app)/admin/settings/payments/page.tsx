"use client";

import React, { useCallback, useEffect, useMemo, useState } from "react";
import {
  Activity,
  AlertTriangle,
  CheckCircle,
  CreditCard,
  Key,
  Receipt,
  RefreshCw,
  Save,
  ShieldCheck,
  TrendingUp,
} from "lucide-react";
import { toast } from "sonner";
import { useAuth } from "@/components/auth/custom-auth";
import { useAdminAccess } from "@/components/admin/AdminGuardProvider";
import DashboardPageIntro from "@/components/dashboard/DashboardPageIntro";
import { useWorkspacePageHeader } from "@/components/dashboard/workspacePageHeader";
import SignalTabs from "@/components/signal/SignalTabs";
import Button from "@/components/ui/Button";
import TextField from "@/components/ui/TextField";
import SelectField from "@/components/ui/SelectField";
import ToggleSwitch from "@/components/ui/ToggleSwitch";
import { Spinner } from "@/components/ui/Loading";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { cx } from "@/components/ui/utils";
import { formatDateTime } from "@/lib/dateFormat";
import type { BillingPlanId, CommitmentTierId } from "@/types/billing";
import { PLAN_DISPLAY_NAMES, PUBLIC_PLAN_TYPES } from "@/lib/planCapabilities";

/* ── Types ──────────────────────────────────────────────────────── */

type BillingMode = "test" | "live";
type CatalogScope = "plans" | "commitments" | "all";
type CatalogAction = "reused" | "created" | "warning" | "error";
type ValidationStatus = "valid" | "unconfigured" | "missing" | "mismatch";

type BillingPriceConfig = {
  plan: BillingPlanId;
  configured: boolean;
  active_price_id: string | null;
  test_price_id: string | null;
  live_price_id: string | null;
};

type BillingModeConfig = {
  mode: BillingMode;
  secret_configured: boolean;
  webhook_configured: boolean;
  secret_hint: string | null;
  webhook_hint: string | null;
};

type CommitmentPriceConfig = {
  tier: CommitmentTierId;
  configured: boolean;
  active_price_id: string | null;
  test_price_id: string | null;
  live_price_id: string | null;
};

type CommitmentOveragePriceConfig = {
  configured: boolean;
  active_price_id: string | null;
  test_price_id: string | null;
  live_price_id: string | null;
};

type BillingConfigResponse = {
  billing_enabled: boolean;
  webhook_configured: boolean;
  stripe_mode: BillingMode;
  stripe_mode_source: string;
  has_runtime_override: boolean;
  modes: BillingModeConfig[];
  price_ids: BillingPriceConfig[];
  commitment_price_ids: CommitmentPriceConfig[];
  commitment_overage_price_ids: CommitmentOveragePriceConfig;
};

type BillingOverviewResponse = {
  stripe_mode: BillingMode;
  billing_enabled: boolean;
  stripe_connected: boolean;
  stripe_error: string | null;
  total_subscriptions: number;
  active_subscriptions: number;
  total_invoices: number;
  paid_invoices: number;
  open_invoices: number;
  monthly_recurring_revenue_estimate: number;
  latest_invoice_at: string | null;
};

type BillingSyncResponse = {
  stripe_mode: BillingMode;
  subscriptions_processed: number;
  invoices_processed: number;
  records_skipped: number;
  errors: string[];
};

type BillingCatalogItem = {
  kind: "plan" | "plan_annual" | "commitment_fixed" | "commitment_overage";
  key: string;
  product_id: string | null;
  price_id: string | null;
  action: CatalogAction;
  message: string | null;
};

type BillingCatalogValidationItem = {
  kind: "plan" | "plan_annual" | "commitment_fixed" | "commitment_overage";
  key: string;
  configured_price_id: string | null;
  status: ValidationStatus;
  message: string | null;
  expected: Record<string, unknown>;
  actual: Record<string, unknown>;
};

type BillingCatalogSyncResponse = {
  mode: BillingMode;
  scope: CatalogScope;
  dry_run: boolean;
  result: {
    items: BillingCatalogItem[];
    plan_price_ids: Record<string, string>;
    commitment_price_ids: Record<string, string>;
    commitment_overage_price_id: string | null;
    warnings: string[];
  };
  config: BillingConfigResponse;
};

type BillingCatalogValidateResponse = {
  mode: BillingMode;
  scope: CatalogScope;
  results: BillingCatalogValidationItem[];
  config: BillingConfigResponse;
};

type PaymentSettingsForm = {
  billingEnabled: boolean;
  stripeMode: BillingMode;
  testSecretKey: string;
  liveSecretKey: string;
  testWebhookSecret: string;
  liveWebhookSecret: string;
  testPriceIds: Record<string, string>;
  livePriceIds: Record<string, string>;
  testCommitmentPriceIds: Record<CommitmentTierId, string>;
  liveCommitmentPriceIds: Record<CommitmentTierId, string>;
  testCommitmentOveragePriceId: string;
  liveCommitmentOveragePriceId: string;
};

/* ── Constants ──────────────────────────────────────────────────── */

const PLAN_LABELS = PLAN_DISPLAY_NAMES;
const PRICEABLE_PLAN_IDS: readonly BillingPlanId[] = PUBLIC_PLAN_TYPES;

const COMMITMENT_LABELS: Record<CommitmentTierId, string> = {
  growth: "Growth",
  scale: "Scale",
  enterprise: "Enterprise",
};

const EMPTY_FORM: PaymentSettingsForm = {
  billingEnabled: true,
  stripeMode: "test",
  testSecretKey: "",
  liveSecretKey: "",
  testWebhookSecret: "",
  liveWebhookSecret: "",
  testPriceIds: {
    plan_starter: "",
    plan_standard: "",
    plan_specialist: "",
    plan_executive: "",
  },
  livePriceIds: {
    plan_starter: "",
    plan_standard: "",
    plan_specialist: "",
    plan_executive: "",
  },
  testCommitmentPriceIds: { growth: "", scale: "", enterprise: "" },
  liveCommitmentPriceIds: { growth: "", scale: "", enterprise: "" },
  testCommitmentOveragePriceId: "",
  liveCommitmentOveragePriceId: "",
};

type TabKey = "runtime" | "credentials" | "pricing" | "catalog";

const TABS: { key: TabKey; label: string }[] = [
  { key: "runtime", label: "Runtime" },
  { key: "credentials", label: "Credentials" },
  { key: "pricing", label: "Pricing" },
  { key: "catalog", label: "Catalog" },
];

/* ── Helpers ─────────────────────────────────────────────────────── */

const parseApiError = async (response: Response, fallback: string) => {
  const payload = (await response.json().catch(() => null)) as {
    detail?: unknown;
    message?: unknown;
  } | null;
  if (typeof payload?.detail === "string" && payload.detail.trim()) return payload.detail;
  if (typeof payload?.message === "string" && payload.message.trim()) return payload.message;
  return fallback;
};

const formatCurrency = (value: number) =>
  new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 0,
  }).format(value);

const CHIP =
  "inline-flex items-center rounded-md px-2 py-[3px] font-(family-name:--mono) text-[10.5px] uppercase tracking-[0.04em]";
const CHIP_GOOD = `${CHIP} text-(--good) bg-(--good-s)`;
const CHIP_WARN = `${CHIP} text-(--warn) bg-(--warn-s)`;
const CHIP_BAD = `${CHIP} text-(--bad) bg-(--bad-s)`;
const CHIP_NEUTRAL = `${CHIP} text-(--t-2) bg-(--line-2)`;

const statusChipClass = (value: CatalogAction | ValidationStatus) => {
  switch (value) {
    case "created":
    case "valid":
      return CHIP_GOOD;
    case "warning":
    case "unconfigured":
      return CHIP_WARN;
    case "missing":
    case "mismatch":
    case "error":
      return CHIP_BAD;
    case "reused":
    default:
      return CHIP_NEUTRAL;
  }
};

const catalogKindLabel = (kind: BillingCatalogItem["kind"]) => {
  switch (kind) {
    case "plan":
      return "Plan";
    case "plan_annual":
      return "Plan (annual)";
    case "commitment_fixed":
      return "Commitment";
    case "commitment_overage":
      return "Overage";
    default:
      return kind;
  }
};

/* ── Stat Card ───────────────────────────────────────────────────── */

const CARD = "rounded-[22px] border-0 bg-white px-[22px] py-[18px]";
const CARD_TITLE =
  "m-0 font-(family-name:--disp) text-[15px] font-bold tracking-[-0.01em] text-(--t-1)";
const CAPTION = "text-[12.5px] leading-[1.5] text-(--t-2)";
const MICRO_LABEL =
  "font-(family-name:--mono) text-[10.5px] uppercase tracking-[0.08em] text-(--t-3)";
const TH =
  "border-b border-(--line) px-4 py-[11px] text-left font-(family-name:--mono) text-[10px] font-normal uppercase tracking-[0.06em] text-(--t-3)";
const TD = "border-b border-(--line-2) px-4 py-[11px] align-middle text-[13px] text-(--t-1)";
const TROW = "transition-colors hover:bg-(--paper)";

function StatCard({
  label,
  value,
  icon,
  color = "text-(--t-1)",
  subtext,
}: {
  label: string;
  value: React.ReactNode;
  icon: React.ReactNode;
  color?: string;
  subtext?: string;
}) {
  return (
    <div className="flex items-center gap-4 rounded-[12px] border-0 bg-[#EEF1F6] px-[18px] py-4">
      <div
        className={cx(
          "flex h-10 w-10 shrink-0 items-center justify-center rounded-[10px] bg-(--line-2)",
          color
        )}
      >
        {icon}
      </div>
      <div className="min-w-0">
        <div className="truncate font-(family-name:--disp) text-[28px] font-extrabold tracking-[-0.02em] text-(--t-1)">
          {value}
        </div>
        <div className={cx(MICRO_LABEL, "mt-0.5")}>{label}</div>
        {subtext && <p className={cx(CAPTION, "mt-0.5 truncate")}>{subtext}</p>}
      </div>
    </div>
  );
}

/* ── Inline table input class ────────────────────────────────────── */

const INLINE_INPUT = cx(
  "h-9 w-full rounded-(--r-md) border-0 bg-[#EEF1F6] px-3 font-(family-name:--mono) text-[12.5px]",
  "text-(--t-1) placeholder:text-(--t-3)",
  "field-focus-ring outline-none focus:border-[#c7cdd6]",
  "disabled:cursor-not-allowed disabled:bg-(--line-2) disabled:text-(--t-3) transition-colors"
);

/* ── Main Page ───────────────────────────────────────────────────── */

export default function AdminPaymentSettingsPage() {
  const { getToken, isSignedIn } = useAuth();
  const { isAdmin, isLoading: isGuardLoading } = useAdminAccess();
  const [activeTab, setActiveTab] = useState<TabKey>("runtime");

  const [config, setConfig] = useState<BillingConfigResponse | null>(null);
  const [overview, setOverview] = useState<BillingOverviewResponse | null>(null);
  const [form, setForm] = useState<PaymentSettingsForm>(EMPTY_FORM);
  const [catalogMode, setCatalogMode] = useState<BillingMode>("test");
  const [catalogDryRun, setCatalogDryRun] = useState(false);
  const [catalogResults, setCatalogResults] = useState<BillingCatalogItem[]>([]);
  const [validationResults, setValidationResults] = useState<BillingCatalogValidationItem[]>([]);
  const [catalogWarnings, setCatalogWarnings] = useState<string[]>([]);
  const [error, setError] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const [isSyncing, setIsSyncing] = useState(false);
  const [isCatalogWorking, setIsCatalogWorking] = useState(false);

  const getAuthHeaders = useCallback(async () => {
    const token = await getToken();
    if (!token) throw new Error("You must be signed in to access admin billing.");
    return { Authorization: `Bearer ${token}`, "Content-Type": "application/json" };
  }, [getToken]);

  const hydrateForm = useCallback((payload: BillingConfigResponse) => {
    const next: PaymentSettingsForm = {
      ...EMPTY_FORM,
      billingEnabled: payload.billing_enabled,
      stripeMode: payload.stripe_mode,
    };
    for (const p of payload.price_ids ?? []) {
      if (!PRICEABLE_PLAN_IDS.includes(p.plan)) continue;
      next.testPriceIds[p.plan] = p.test_price_id ?? "";
      next.livePriceIds[p.plan] = p.live_price_id ?? "";
    }
    for (const c of payload.commitment_price_ids ?? []) {
      next.testCommitmentPriceIds[c.tier] = c.test_price_id ?? "";
      next.liveCommitmentPriceIds[c.tier] = c.live_price_id ?? "";
    }
    next.testCommitmentOveragePriceId = payload.commitment_overage_price_ids?.test_price_id ?? "";
    next.liveCommitmentOveragePriceId = payload.commitment_overage_price_ids?.live_price_id ?? "";
    setForm(next);
  }, []);

  const loadBillingData = useCallback(async () => {
    if (!isSignedIn) return;
    setIsLoading(true);
    setError("");
    try {
      const headers = await getAuthHeaders();
      const [cfgRes, ovRes] = await Promise.all([
        fetch("/api/admin/billing/config", { headers }),
        fetch("/api/admin/billing/overview", { headers }),
      ]);
      if (!cfgRes.ok)
        throw new Error(await parseApiError(cfgRes, "Unable to load payment configuration."));
      if (!ovRes.ok)
        throw new Error(await parseApiError(ovRes, "Unable to load payment overview."));
      const cfgPayload = (await cfgRes.json()) as BillingConfigResponse;
      const ovPayload = (await ovRes.json()) as BillingOverviewResponse;
      setConfig(cfgPayload);
      setOverview(ovPayload);
      setCatalogMode(cfgPayload.stripe_mode);
      hydrateForm(cfgPayload);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to load payment settings.");
    } finally {
      setIsLoading(false);
    }
  }, [getAuthHeaders, hydrateForm, isSignedIn]);

  useEffect(() => {
    void loadBillingData();
  }, [loadBillingData]);

  const controlsDisabled =
    !isAdmin || isGuardLoading || isLoading || isSaving || isSyncing || isCatalogWorking;

  const modeStatusMap = useMemo(() => {
    const map: Partial<Record<BillingMode, BillingModeConfig>> = {};
    for (const item of config?.modes ?? []) map[item.mode] = item;
    return map;
  }, [config?.modes]);

  const saveConfig = useCallback(async () => {
    setIsSaving(true);
    setError("");
    try {
      const headers = await getAuthHeaders();
      const body: Record<string, unknown> = {
        billing_enabled: form.billingEnabled,
        stripe_mode: form.stripeMode,
        test_price_ids: form.testPriceIds,
        live_price_ids: form.livePriceIds,
        test_commitment_price_ids: form.testCommitmentPriceIds,
        live_commitment_price_ids: form.liveCommitmentPriceIds,
        test_commitment_overage_price_id: form.testCommitmentOveragePriceId,
        live_commitment_overage_price_id: form.liveCommitmentOveragePriceId,
      };
      if (form.testSecretKey.trim()) body.test_secret_key = form.testSecretKey.trim();
      if (form.liveSecretKey.trim()) body.live_secret_key = form.liveSecretKey.trim();
      if (form.testWebhookSecret.trim()) body.test_webhook_secret = form.testWebhookSecret.trim();
      if (form.liveWebhookSecret.trim()) body.live_webhook_secret = form.liveWebhookSecret.trim();
      const res = await fetch("/api/admin/billing/config", {
        method: "PATCH",
        headers,
        body: JSON.stringify(body),
      });
      if (!res.ok) throw new Error(await parseApiError(res, "Unable to save payment settings."));
      const updated = (await res.json()) as BillingConfigResponse;
      setConfig(updated);
      hydrateForm(updated);
      toast.success("Payment settings saved successfully.");
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Unable to save payment settings.");
    } finally {
      setIsSaving(false);
    }
  }, [form, getAuthHeaders, hydrateForm]);

  const syncStripe = useCallback(async () => {
    setIsSyncing(true);
    setError("");
    try {
      const headers = await getAuthHeaders();
      const res = await fetch("/api/admin/billing/sync", { method: "POST", headers });
      if (!res.ok) throw new Error(await parseApiError(res, "Unable to sync Stripe billing data."));
      const payload = (await res.json()) as BillingSyncResponse;
      toast.success(
        `Sync completed (${payload.stripe_mode}). Subs: ${payload.subscriptions_processed}, invoices: ${payload.invoices_processed}, skipped: ${payload.records_skipped}.`
      );
      await loadBillingData();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Unable to sync Stripe billing data.");
    } finally {
      setIsSyncing(false);
    }
  }, [getAuthHeaders, loadBillingData]);

  const runCatalogSync = useCallback(
    async (scope: CatalogScope) => {
      setIsCatalogWorking(true);
      setError("");
      setCatalogWarnings([]);
      try {
        const headers = await getAuthHeaders();
        const res = await fetch("/api/admin/billing/catalog/sync", {
          method: "POST",
          headers,
          body: JSON.stringify({ mode: catalogMode, scope, dry_run: catalogDryRun }),
        });
        if (!res.ok)
          throw new Error(await parseApiError(res, "Unable to sync the Stripe catalog."));
        const payload = (await res.json()) as BillingCatalogSyncResponse;
        setCatalogResults(payload.result.items ?? []);
        setValidationResults([]);
        setCatalogWarnings(payload.result.warnings ?? []);
        toast.success(
          `${catalogDryRun ? "Dry run" : "Catalog sync"} completed for ${scope} in ${catalogMode} mode.`
        );
        setConfig(payload.config);
        if (!catalogDryRun) hydrateForm(payload.config);
      } catch (err) {
        toast.error(err instanceof Error ? err.message : "Unable to sync the Stripe catalog.");
      } finally {
        setIsCatalogWorking(false);
      }
    },
    [catalogDryRun, catalogMode, getAuthHeaders, hydrateForm]
  );

  const runCatalogValidation = useCallback(async () => {
    setIsCatalogWorking(true);
    setError("");
    setCatalogWarnings([]);
    try {
      const headers = await getAuthHeaders();
      const res = await fetch("/api/admin/billing/catalog/validate", {
        method: "POST",
        headers,
        body: JSON.stringify({ mode: catalogMode, scope: "all" }),
      });
      if (!res.ok)
        throw new Error(await parseApiError(res, "Unable to validate the Stripe catalog."));
      const payload = (await res.json()) as BillingCatalogValidateResponse;
      setValidationResults(payload.results ?? []);
      setCatalogResults([]);
      toast.success(`Catalog validation completed for ${catalogMode} mode.`);
      setConfig(payload.config);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Unable to validate the Stripe catalog.");
    } finally {
      setIsCatalogWorking(false);
    }
  }, [catalogMode, getAuthHeaders]);

  /* Page-scoped actions live in `.top`. */
  const { setHeader } = useWorkspacePageHeader();
  useEffect(() => {
    setHeader({
      actions: (
        <>
          <Button
            variant="ghost"
            size="sm"
            onClick={() => void loadBillingData()}
            disabled={controlsDisabled}
            aria-label="Refresh"
            title="Refresh"
            className="h-8 w-8 p-0"
          >
            <RefreshCw size={14} className={isLoading ? "animate-spin" : ""} />
          </Button>
          <Button
            variant="outline"
            size="sm"
            onClick={() => void syncStripe()}
            loading={isSyncing}
            disabled={controlsDisabled}
          >
            <Activity size={14} /> <span className="max-sm:hidden">Sync Records</span>
          </Button>
          <Button
            variant="primary"
            size="sm"
            onClick={() => void saveConfig()}
            loading={isSaving}
            disabled={controlsDisabled}
          >
            <Save size={14} /> <span className="max-sm:hidden">Save Settings</span>
          </Button>
        </>
      ),
    });
    return () => setHeader(null);
  }, [
    controlsDisabled,
    isLoading,
    isSaving,
    isSyncing,
    loadBillingData,
    saveConfig,
    setHeader,
    syncStripe,
  ]);

  /* ── Loading state ─────────────────────────────────────────── */

  if (isLoading && !config) {
    return (
      <>
        <DashboardPageIntro icon={CreditCard} title="Billing configuration">
          Stripe runtime mode, credentials, managed catalog sync, and billing telemetry.
        </DashboardPageIntro>
        <div className="flex justify-center py-20">
          <Spinner size="lg" label="Loading billing configuration..." />
        </div>
      </>
    );
  }

  /* ── Render ────────────────────────────────────────────────── */

  return (
    <>
      {/* ── Header ─────────────────────────────────────────────── */}
      <DashboardPageIntro icon={CreditCard} title="Billing configuration">
        Stripe runtime mode, credentials, managed catalog sync, and billing telemetry.
      </DashboardPageIntro>

      {/* ── Page-level error ───────────────────────────────────── */}
      {error && (
        <Alert variant="destructive">
          <AlertTriangle />
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}

      {/* ── KPI Bar ────────────────────────────────────────────── */}
      <div className="grid grid-cols-2 gap-3.5 md:grid-cols-3 xl:grid-cols-5">
        <StatCard
          label="Stripe Mode"
          value={
            <span className={config?.stripe_mode === "live" ? CHIP_GOOD : CHIP_WARN}>
              {config?.stripe_mode?.toUpperCase() ?? "N/A"}
            </span>
          }
          icon={<CreditCard size={18} />}
          color="text-(--purple)"
          subtext={`Source: ${config?.stripe_mode_source ?? "unknown"}`}
        />
        <StatCard
          label="Stripe Health"
          value={overview?.stripe_connected ? "Connected" : "Check needed"}
          icon={
            overview?.stripe_connected ? <CheckCircle size={18} /> : <AlertTriangle size={18} />
          }
          color={overview?.stripe_connected ? "text-(--good)" : "text-(--warn)"}
          subtext={overview?.stripe_error ?? "No runtime errors"}
        />
        <StatCard
          label="Subscriptions"
          value={`${overview?.active_subscriptions ?? 0} / ${overview?.total_subscriptions ?? 0}`}
          icon={<Receipt size={18} />}
          color="text-(--purple)"
          subtext="active / total"
        />
        <StatCard
          label="Invoices"
          value={`${overview?.paid_invoices ?? 0} / ${overview?.total_invoices ?? 0}`}
          icon={<ShieldCheck size={18} />}
          color="text-(--good)"
          subtext="paid / total"
        />
        <StatCard
          label="MRR Estimate"
          value={formatCurrency(overview?.monthly_recurring_revenue_estimate ?? 0)}
          icon={<TrendingUp size={18} />}
          color="text-(--purple)"
        />
      </div>

      {/* ── Tab Bar ────────────────────────────────────────────── */}
      <SignalTabs<TabKey>
        tabs={TABS.map((tab) => ({ id: tab.key, label: tab.label }))}
        activeId={activeTab}
        onChange={setActiveTab}
      />

      {/* ── Tab Content ────────────────────────────────────────── */}
      <div key={activeTab}>
        {activeTab === "runtime" && (
          <RuntimeTab
            form={form}
            setForm={setForm}
            overview={overview}
            config={config}
            controlsDisabled={controlsDisabled}
          />
        )}
        {activeTab === "credentials" && (
          <CredentialsTab
            form={form}
            setForm={setForm}
            modeStatusMap={modeStatusMap}
            controlsDisabled={controlsDisabled}
          />
        )}
        {activeTab === "pricing" && (
          <PricingTab form={form} setForm={setForm} controlsDisabled={controlsDisabled} />
        )}
        {activeTab === "catalog" && (
          <CatalogTab
            catalogMode={catalogMode}
            setCatalogMode={setCatalogMode}
            catalogDryRun={catalogDryRun}
            setCatalogDryRun={setCatalogDryRun}
            catalogResults={catalogResults}
            validationResults={validationResults}
            catalogWarnings={catalogWarnings}
            controlsDisabled={controlsDisabled}
            isCatalogWorking={isCatalogWorking}
            onSyncPlans={() => void runCatalogSync("plans")}
            onSyncCommitments={() => void runCatalogSync("commitments")}
            onSyncAll={() => void runCatalogSync("all")}
            onValidate={() => void runCatalogValidation()}
          />
        )}
      </div>
    </>
  );
}

/* ── Runtime Tab ─────────────────────────────────────────────────── */

function RuntimeTab({
  form,
  setForm,
  overview,
  config,
  controlsDisabled,
}: {
  form: PaymentSettingsForm;
  setForm: React.Dispatch<React.SetStateAction<PaymentSettingsForm>>;
  overview: BillingOverviewResponse | null;
  config: BillingConfigResponse | null;
  controlsDisabled: boolean;
}) {
  return (
    <div className="space-y-[22px]">
      <section className={CARD}>
        <h2 className={cx(CARD_TITLE, "mb-[14px]")}>Runtime controls</h2>
        <div className="grid gap-6 md:grid-cols-2">
          <SelectField
            label="Active Stripe mode"
            variant="auth"
            value={form.stripeMode}
            onChange={(e) =>
              setForm((prev) => ({ ...prev, stripeMode: e.target.value as BillingMode }))
            }
            disabled={controlsDisabled}
          >
            <option value="test">Test</option>
            <option value="live">Live</option>
          </SelectField>
          <div className="flex items-center pt-5">
            <ToggleSwitch
              checked={form.billingEnabled}
              onChange={(checked) => setForm((prev) => ({ ...prev, billingEnabled: checked }))}
              disabled={controlsDisabled}
              label="Enable billing flows"
              description="Accept payments and process subscriptions"
            />
          </div>
        </div>
      </section>

      <section className={CARD}>
        <h2 className={cx(CARD_TITLE, "mb-[14px]")}>Billing telemetry</h2>
        <div className="grid gap-3.5 md:grid-cols-2 xl:grid-cols-4">
          <div className="rounded-[12px] border-0 bg-[#EEF1F6] px-[18px] py-4">
            <div className="font-(family-name:--disp) text-[28px] font-extrabold tracking-[-0.02em]">
              {formatCurrency(overview?.monthly_recurring_revenue_estimate ?? 0)}
            </div>
            <div className={cx(MICRO_LABEL, "mt-0.5")}>MRR estimate</div>
          </div>
          <div className="rounded-[12px] border-0 bg-[#EEF1F6] px-[18px] py-4">
            <div className="font-(family-name:--disp) text-[28px] font-extrabold tracking-[-0.02em] text-(--warn)">
              {overview?.open_invoices ?? 0}
            </div>
            <div className={cx(MICRO_LABEL, "mt-0.5")}>Open invoices</div>
          </div>
          <div className="rounded-[12px] border-0 bg-[#EEF1F6] px-[18px] py-4">
            <div className="text-sm font-semibold text-(--t-1)">
              {overview?.latest_invoice_at ? formatDateTime(overview.latest_invoice_at) : "N/A"}
            </div>
            <div className={cx(MICRO_LABEL, "mt-0.5")}>Last invoice</div>
          </div>
          <div className="rounded-[12px] border-0 bg-[#EEF1F6] px-[18px] py-4">
            <div className="font-(family-name:--disp) text-[28px] font-extrabold tracking-[-0.02em]">
              {config?.has_runtime_override ? "Enabled" : "Disabled"}
            </div>
            <div className={cx(MICRO_LABEL, "mt-0.5")}>Runtime override</div>
          </div>
        </div>
      </section>
    </div>
  );
}

/* ── Credentials Tab ─────────────────────────────────────────────── */

function CredentialsTab({
  form,
  setForm,
  modeStatusMap,
  controlsDisabled,
}: {
  form: PaymentSettingsForm;
  setForm: React.Dispatch<React.SetStateAction<PaymentSettingsForm>>;
  modeStatusMap: Partial<Record<BillingMode, BillingModeConfig>>;
  controlsDisabled: boolean;
}) {
  return (
    <div className="grid gap-6 lg:grid-cols-2">
      <SecretPanel
        mode="test"
        secretHint={modeStatusMap.test?.secret_hint ?? null}
        webhookHint={modeStatusMap.test?.webhook_hint ?? null}
        secretConfigured={modeStatusMap.test?.secret_configured ?? false}
        webhookConfigured={modeStatusMap.test?.webhook_configured ?? false}
        secretValue={form.testSecretKey}
        webhookValue={form.testWebhookSecret}
        onSecretChange={(v) => setForm((prev) => ({ ...prev, testSecretKey: v }))}
        onWebhookChange={(v) => setForm((prev) => ({ ...prev, testWebhookSecret: v }))}
        disabled={controlsDisabled}
      />
      <SecretPanel
        mode="live"
        secretHint={modeStatusMap.live?.secret_hint ?? null}
        webhookHint={modeStatusMap.live?.webhook_hint ?? null}
        secretConfigured={modeStatusMap.live?.secret_configured ?? false}
        webhookConfigured={modeStatusMap.live?.webhook_configured ?? false}
        secretValue={form.liveSecretKey}
        webhookValue={form.liveWebhookSecret}
        onSecretChange={(v) => setForm((prev) => ({ ...prev, liveSecretKey: v }))}
        onWebhookChange={(v) => setForm((prev) => ({ ...prev, liveWebhookSecret: v }))}
        disabled={controlsDisabled}
      />
    </div>
  );
}

function SecretPanel({
  mode,
  secretHint,
  webhookHint,
  secretConfigured,
  webhookConfigured,
  secretValue,
  webhookValue,
  onSecretChange,
  onWebhookChange,
  disabled,
}: {
  mode: BillingMode;
  secretHint: string | null;
  webhookHint: string | null;
  secretConfigured: boolean;
  webhookConfigured: boolean;
  secretValue: string;
  webhookValue: string;
  onSecretChange: (v: string) => void;
  onWebhookChange: (v: string) => void;
  disabled: boolean;
}) {
  const isLive = mode === "live";
  return (
    <section className={cx(CARD, isLive && "border-(--purple)")}>
      <div className="mb-6 flex items-center gap-3">
        <div
          className={cx(
            "flex h-9 w-9 items-center justify-center rounded-[10px]",
            isLive ? "bg-(--purple-s) text-(--purple)" : "bg-(--warn-s) text-(--warn)"
          )}
        >
          <Key size={16} />
        </div>
        <div>
          <h3 className={CARD_TITLE}>{isLive ? "Live" : "Test"} mode secrets</h3>
          <div className="mt-1.5 flex flex-wrap items-center gap-2">
            <span className={secretConfigured ? CHIP_GOOD : CHIP_WARN}>
              Secret: {secretHint ?? "missing"}
            </span>
            <span className={webhookConfigured ? CHIP_GOOD : CHIP_WARN}>
              Webhook: {webhookHint ?? "missing"}
            </span>
          </div>
        </div>
      </div>
      <div className="space-y-4">
        <TextField
          label={`${isLive ? "Live" : "Test"} secret key`}
          variant="auth"
          type="password"
          value={secretValue}
          onChange={(e) => onSecretChange(e.target.value)}
          placeholder={`sk_${mode}_...`}
          disabled={disabled}
        />
        <TextField
          label={`${isLive ? "Live" : "Test"} webhook secret`}
          variant="auth"
          type="password"
          value={webhookValue}
          onChange={(e) => onWebhookChange(e.target.value)}
          placeholder="whsec_..."
          disabled={disabled}
        />
      </div>
    </section>
  );
}

/* ── Pricing Tab ─────────────────────────────────────────────────── */

function PricingTab({
  form,
  setForm,
  controlsDisabled,
}: {
  form: PaymentSettingsForm;
  setForm: React.Dispatch<React.SetStateAction<PaymentSettingsForm>>;
  controlsDisabled: boolean;
}) {
  return (
    <div className="space-y-[22px]">
      {/* Plan Price IDs */}
      <section className="overflow-hidden rounded-[22px] border-0 bg-white">
        <div className="border-b border-(--line) px-[22px] py-[18px]">
          <h2 className={CARD_TITLE}>Plan price IDs</h2>
          <p className={cx(CAPTION, "mt-1")}>
            Stripe price identifiers for each subscription plan.
          </p>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-left">
            <thead>
              <tr>
                <th className={cx(TH, "w-48")}>Plan</th>
                <th className={TH}>Test price ID</th>
                <th className={TH}>Live price ID</th>
              </tr>
            </thead>
            <tbody>
              {PRICEABLE_PLAN_IDS.map((plan) => (
                <tr key={plan} className={TROW}>
                  <td className={cx(TD, "font-semibold whitespace-nowrap")}>{PLAN_LABELS[plan]}</td>
                  <td className={TD}>
                    <input
                      type="text"
                      value={form.testPriceIds[plan]}
                      onChange={(e) =>
                        setForm((prev) => ({
                          ...prev,
                          testPriceIds: { ...prev.testPriceIds, [plan]: e.target.value },
                        }))
                      }
                      placeholder="price_..."
                      disabled={controlsDisabled}
                      className={INLINE_INPUT}
                      aria-label={`Test price ID for ${PLAN_LABELS[plan]}`}
                    />
                  </td>
                  <td className={TD}>
                    <input
                      type="text"
                      value={form.livePriceIds[plan]}
                      onChange={(e) =>
                        setForm((prev) => ({
                          ...prev,
                          livePriceIds: { ...prev.livePriceIds, [plan]: e.target.value },
                        }))
                      }
                      placeholder="price_..."
                      disabled={controlsDisabled}
                      className={INLINE_INPUT}
                      aria-label={`Live price ID for ${PLAN_LABELS[plan]}`}
                    />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      {/* Commitment Price IDs */}
      <section className="overflow-hidden rounded-[22px] border-0 bg-white">
        <div className="border-b border-(--line) px-[22px] py-[18px]">
          <h2 className={CARD_TITLE}>Commitment Price IDs</h2>
          <p className={cx(CAPTION, "mt-1")}>
            Stripe price identifiers for credit commitment tiers and overage metering.
          </p>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-left">
            <thead>
              <tr>
                <th className={cx(TH, "w-48")}>Tier</th>
                <th className={TH}>Test Price ID</th>
                <th className={TH}>Live Price ID</th>
              </tr>
            </thead>
            <tbody>
              {(Object.keys(COMMITMENT_LABELS) as CommitmentTierId[]).map((tier) => (
                <tr key={tier} className={TROW}>
                  <td className={cx(TD, "font-semibold text-(--t-1) whitespace-nowrap")}>
                    {COMMITMENT_LABELS[tier]}
                  </td>
                  <td className={TD}>
                    <input
                      type="text"
                      value={form.testCommitmentPriceIds[tier]}
                      onChange={(e) =>
                        setForm((prev) => ({
                          ...prev,
                          testCommitmentPriceIds: {
                            ...prev.testCommitmentPriceIds,
                            [tier]: e.target.value,
                          },
                        }))
                      }
                      placeholder="price_..."
                      disabled={controlsDisabled}
                      className={INLINE_INPUT}
                      aria-label={`Test price ID for ${COMMITMENT_LABELS[tier]}`}
                    />
                  </td>
                  <td className={TD}>
                    <input
                      type="text"
                      value={form.liveCommitmentPriceIds[tier]}
                      onChange={(e) =>
                        setForm((prev) => ({
                          ...prev,
                          liveCommitmentPriceIds: {
                            ...prev.liveCommitmentPriceIds,
                            [tier]: e.target.value,
                          },
                        }))
                      }
                      placeholder="price_..."
                      disabled={controlsDisabled}
                      className={INLINE_INPUT}
                      aria-label={`Live price ID for ${COMMITMENT_LABELS[tier]}`}
                    />
                  </td>
                </tr>
              ))}
              {/* Overage row */}
              <tr className={cx(TROW, "bg-(--paper)")}>
                <td className={cx(TD, "font-semibold text-(--warn) whitespace-nowrap")}>
                  Overage Meter
                </td>
                <td className={TD}>
                  <input
                    type="text"
                    value={form.testCommitmentOveragePriceId}
                    onChange={(e) =>
                      setForm((prev) => ({ ...prev, testCommitmentOveragePriceId: e.target.value }))
                    }
                    placeholder="price_..."
                    disabled={controlsDisabled}
                    className={INLINE_INPUT}
                    aria-label="Test overage meter price ID"
                  />
                </td>
                <td className={TD}>
                  <input
                    type="text"
                    value={form.liveCommitmentOveragePriceId}
                    onChange={(e) =>
                      setForm((prev) => ({ ...prev, liveCommitmentOveragePriceId: e.target.value }))
                    }
                    placeholder="price_..."
                    disabled={controlsDisabled}
                    className={INLINE_INPUT}
                    aria-label="Live overage meter price ID"
                  />
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}

/* ── Catalog Tab ─────────────────────────────────────────────────── */

function CatalogTab({
  catalogMode,
  setCatalogMode,
  catalogDryRun,
  setCatalogDryRun,
  catalogResults,
  validationResults,
  catalogWarnings,
  controlsDisabled,
  isCatalogWorking,
  onSyncPlans,
  onSyncCommitments,
  onSyncAll,
  onValidate,
}: {
  catalogMode: BillingMode;
  setCatalogMode: (m: BillingMode) => void;
  catalogDryRun: boolean;
  setCatalogDryRun: (v: boolean) => void;
  catalogResults: BillingCatalogItem[];
  validationResults: BillingCatalogValidationItem[];
  catalogWarnings: string[];
  controlsDisabled: boolean;
  isCatalogWorking: boolean;
  onSyncPlans: () => void;
  onSyncCommitments: () => void;
  onSyncAll: () => void;
  onValidate: () => void;
}) {
  return (
    <div className="space-y-[22px]">
      <section className={CARD}>
        <h2 className={cx(CARD_TITLE, "mb-2")}>Stripe catalog</h2>
        <p className={cx(CAPTION, "mb-6")}>
          Create or reuse managed Stripe products and prices from the canonical billing catalog.
        </p>

        <div className="flex flex-wrap items-end gap-6 mb-6">
          <div className="w-48">
            <SelectField
              label="Catalog mode"
              variant="auth"
              value={catalogMode}
              onChange={(e) => setCatalogMode(e.target.value as BillingMode)}
              disabled={controlsDisabled}
            >
              <option value="test">Test</option>
              <option value="live">Live</option>
            </SelectField>
          </div>
          <div className="pb-1">
            <ToggleSwitch
              checked={catalogDryRun}
              onChange={setCatalogDryRun}
              disabled={controlsDisabled}
              label="Dry run"
              description="Preview changes without applying"
            />
          </div>
        </div>

        <div className="flex flex-wrap gap-2">
          <Button
            variant="ghost"
            size="sm"
            onClick={onSyncPlans}
            loading={isCatalogWorking}
            disabled={controlsDisabled}
          >
            Sync Plans
          </Button>
          <Button
            variant="ghost"
            size="sm"
            onClick={onSyncCommitments}
            loading={isCatalogWorking}
            disabled={controlsDisabled}
          >
            Sync Commitments
          </Button>
          <Button
            variant="primary"
            size="sm"
            onClick={onSyncAll}
            loading={isCatalogWorking}
            disabled={controlsDisabled}
          >
            Sync All
          </Button>
          <Button
            variant="outline"
            size="sm"
            onClick={onValidate}
            loading={isCatalogWorking}
            disabled={controlsDisabled}
          >
            Validate Catalog
          </Button>
        </div>
      </section>

      {/* Warnings */}
      {catalogWarnings.length > 0 && (
        <Alert variant="warning">
          <AlertTriangle />
          <div>
            <AlertTitle>Catalog warnings</AlertTitle>
            <AlertDescription>
              <ul className="space-y-1">
                {catalogWarnings.map((w) => (
                  <li key={w}>{w}</li>
                ))}
              </ul>
            </AlertDescription>
          </div>
        </Alert>
      )}

      {/* Sync Results */}
      {catalogResults.length > 0 && (
        <section className="overflow-hidden rounded-[22px] border-0 bg-white">
          <div className="border-b border-(--line) px-[22px] py-[18px]">
            <h3 className={CARD_TITLE}>Sync results</h3>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-left">
              <thead>
                <tr>
                  <th className={TH}>Kind</th>
                  <th className={TH}>Key</th>
                  <th className={TH}>Action</th>
                  <th className={TH}>Product ID</th>
                  <th className={TH}>Price ID</th>
                  <th className={TH}>Message</th>
                </tr>
              </thead>
              <tbody>
                {catalogResults.map((item) => (
                  <tr key={`${item.kind}-${item.key}`} className={TROW}>
                    <td className={TD}>{catalogKindLabel(item.kind)}</td>
                    <td className={cx(TD, "font-semibold text-(--t-1)")}>{item.key}</td>
                    <td className={TD}>
                      <span className={statusChipClass(item.action)}>{item.action}</span>
                    </td>
                    <td className={cx(TD, "font-(family-name:--mono) text-xs text-(--t-3)")}>
                      {item.product_id ?? "-"}
                    </td>
                    <td className={cx(TD, "font-(family-name:--mono) text-xs text-(--t-3)")}>
                      {item.price_id ?? "-"}
                    </td>
                    <td className={cx(TD, CAPTION)}>{item.message ?? "-"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}

      {/* Validation Results */}
      {validationResults.length > 0 && (
        <section className="overflow-hidden rounded-[22px] border-0 bg-white">
          <div className="border-b border-(--line) px-[22px] py-[18px]">
            <h3 className={CARD_TITLE}>Validation results</h3>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-left">
              <thead>
                <tr>
                  <th className={TH}>Kind</th>
                  <th className={TH}>Key</th>
                  <th className={TH}>Status</th>
                  <th className={TH}>Price ID</th>
                  <th className={TH}>Message</th>
                </tr>
              </thead>
              <tbody>
                {validationResults.map((item) => (
                  <tr key={`${item.kind}-${item.key}`} className={TROW}>
                    <td className={TD}>{catalogKindLabel(item.kind)}</td>
                    <td className={cx(TD, "font-semibold text-(--t-1)")}>{item.key}</td>
                    <td className={TD}>
                      <span className={statusChipClass(item.status)}>{item.status}</span>
                    </td>
                    <td className={cx(TD, "font-(family-name:--mono) text-xs text-(--t-3)")}>
                      {item.configured_price_id ?? "-"}
                    </td>
                    <td className={cx(TD, CAPTION)}>{item.message ?? "-"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}
    </div>
  );
}
