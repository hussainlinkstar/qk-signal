"use client";

import React, { useCallback, useEffect, useState } from "react";
import {
  Check,
  ChevronDown,
  ChevronUp,
  Crown,
  Flag,
  Layers,
  Minus,
  Plus,
  Search,
  Shield,
  Trash2,
  X,
} from "lucide-react";
import { useAuth } from "@/components/auth/custom-auth";
import DashboardPageIntro from "@/components/dashboard/DashboardPageIntro";
import Button from "@/components/ui/Button";
import { NativeSelect } from "@/components/ui/native-select";
import { cx } from "@/components/ui/utils";
import { toast } from "sonner";
import { PLAN_DISPLAY_NAMES, PUBLIC_PLAN_TYPES } from "@/lib/planCapabilities";

const CARD = "rounded-[22px] border-0 bg-white px-[22px] py-[18px]";
const CARD_TITLE =
  "m-0 flex items-center gap-2 font-(family-name:--disp) text-[15px] font-bold tracking-[-0.01em] text-(--t-1)";
const INSET = "rounded-(--r-md) border-0 bg-[#EEF1F6] px-[18px] py-4";
const FIELD_LABEL =
  "mb-2 block font-(family-name:--mono) text-[10.5px] uppercase tracking-[0.08em] text-(--t-3)";
const WINPUT =
  "field-focus-ring h-11 w-full rounded-(--r-md) border-0 bg-[#EEF1F6] px-[13px] text-[13.5px] text-(--t-1) outline-none placeholder:text-(--t-3) focus:border-[#c7cdd6] disabled:bg-(--line-2) disabled:text-(--t-3)";
const TH =
  "border-b border-(--line) px-4 py-[11px] text-left font-(family-name:--mono) text-[10px] font-normal uppercase tracking-[0.06em] text-(--t-3)";
const TD = "border-b border-(--line-2) px-4 py-[11px] align-middle text-[13px] text-(--t-1)";
const CHIP_WARN =
  "inline-flex items-center gap-1.5 rounded-md px-2 py-[3px] font-(family-name:--mono) text-[10.5px] uppercase tracking-[0.04em] text-(--warn) bg-(--warn-s)";

/* -------------------------------------------------------------------------- */
/*  Types                                                                     */
/* -------------------------------------------------------------------------- */

interface PlanInfo {
  display_name: string;
  monthly_price_usd: number;
  capabilities: Record<string, boolean | number>;
}

interface PlansResponse {
  plans: Record<string, PlanInfo>;
  capability_keys: string[];
  capability_descriptions: Record<string, string>;
  // SIGV2-1147: only these keys can be granted per workspace. Every other key
  // maps to the reason an override on it would do nothing.
  overridable_capability_keys?: string[];
  override_refusal_reasons?: Record<string, string>;
}

interface Override {
  id: number;
  workspace_id: number;
  workspace_name: string | null;
  capability_key: string;
  override_value: boolean | number | string;
  reason: string | null;
  created_by_email: string | null;
  expires_at: string | null;
  created_at: string;
  is_enforced?: boolean;
  enforcement_reason?: string;
}

interface FeatureFlag {
  id: number;
  key: string;
  description: string | null;
  is_enabled: boolean;
  rollout_percentage: number | null;
  created_at: string;
  updated_at: string;
}

interface EffectiveCapability {
  key: string;
  base_value: boolean | number;
  effective_value: boolean | number;
  is_overridden: boolean;
  override_id: number | null;
  is_enforced?: boolean;
  enforcement_reason?: string;
}

/* -------------------------------------------------------------------------- */
/*  Helper                                                                    */
/* -------------------------------------------------------------------------- */

const PLAN_ORDER = PUBLIC_PLAN_TYPES;
const PLAN_COLORS: Record<string, string> = {
  plan_starter: "text-(--t-2)",
  plan_standard: "text-(--t-2)",
  plan_specialist: "text-(--purple)",
  plan_executive: "text-(--purple)",
};

function formatCapValue(v: boolean | number | string | null | undefined) {
  if (v === true) return <Check size={16} className="text-(--good) mx-auto block" />;
  if (v === false) return <Minus size={16} className="text-(--t-3) mx-auto block" />;
  if (typeof v === "number") {
    if (v === -1)
      return <span className="text-xs font-bold text-(--good) block text-center">Unlimited</span>;
    return (
      <span className="font-(family-name:--mono) text-sm text-(--t-1) block text-center">
        {v.toLocaleString()}
      </span>
    );
  }
  return <span className="text-sm text-(--t-2) block text-center">{String(v ?? "-")}</span>;
}

/* -------------------------------------------------------------------------- */
/*  Section: Plan Comparison                                                  */
/* -------------------------------------------------------------------------- */

function PlanComparisonTable({ data }: { data: PlansResponse }) {
  const [expanded, setExpanded] = useState(true);
  const plans = PLAN_ORDER.filter((p) => p in data.plans);

  return (
    <section className="overflow-hidden rounded-[22px] border-0 bg-white">
      <button
        onClick={() => setExpanded(!expanded)}
        className="flex w-full items-center justify-between px-[22px] py-[18px]"
      >
        <h2 className={CARD_TITLE}>
          <Layers size={18} className="text-(--purple)" />
          Plan comparison
        </h2>
        {expanded ? (
          <ChevronUp size={18} className="text-(--t-2)" />
        ) : (
          <ChevronDown size={18} className="text-(--t-2)" />
        )}
      </button>

      {expanded && (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr>
                <th className={cx(TH, "sticky left-0 bg-(--panel) min-w-[200px]")}>Capability</th>
                {plans.map((p) => (
                  <th key={p} className={cx(TH, "text-center", PLAN_COLORS[p])}>
                    <div className="flex flex-col items-center gap-1">
                      <span className="font-bold normal-case tracking-normal font-(family-name:--disp) text-[13px]">
                        {PLAN_DISPLAY_NAMES[p]}
                      </span>
                      <span className="text-[10px] text-(--t-3)">
                        ${data.plans[p].monthly_price_usd}/mo
                      </span>
                    </div>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {data.capability_keys.map((key) => (
                <tr key={key} className="transition-colors hover:bg-(--paper)">
                  <td className={cx(TD, "sticky left-0 bg-(--panel)")}>
                    <span className="text-[12px] text-(--t-2)">
                      {data.capability_descriptions[key] || key}
                    </span>
                  </td>
                  {plans.map((p) => (
                    <td key={p} className={cx(TD, "text-center")}>
                      {formatCapValue(data.plans[p].capabilities[key])}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

/* -------------------------------------------------------------------------- */
/*  Section: Capability Overrides                                             */
/* -------------------------------------------------------------------------- */

function OverridesSection({
  overrides,
  capKeys,
  refusalReasons,
  onRefresh,
  token,
}: {
  overrides: Override[];
  capKeys: string[];
  refusalReasons: Record<string, string>;
  onRefresh: () => void;
  token: string;
}) {
  const [showCreate, setShowCreate] = useState(false);
  const [creating, setCreating] = useState(false);
  const [form, setForm] = useState({
    workspace_id: "",
    capability_key: capKeys[0] || "",
    reason: "",
  });

  // Effective preview state
  const [previewWsId, setPreviewWsId] = useState("");
  const [previewData, setPreviewData] = useState<EffectiveCapability[] | null>(null);
  const [previewName, setPreviewName] = useState("");
  const [previewPlan, setPreviewPlan] = useState("");
  const [loadingPreview, setLoadingPreview] = useState(false);

  const handleCreate = async () => {
    setCreating(true);
    try {
      // SIGV2-1147: every overridable capability is boolean and an override
      // exists only to grant it, so the value is not a free-text field any
      // more. Revoking is deleting the row.
      const res = await fetch("/api/admin/plans/overrides", {
        method: "POST",
        headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
        body: JSON.stringify({
          workspace_id: Number(form.workspace_id),
          capability_key: form.capability_key,
          override_value: true,
          reason: form.reason || null,
        }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || "Failed to create override");
      }
      toast.success("Capability granted");
      setShowCreate(false);
      setForm({
        workspace_id: "",
        capability_key: capKeys[0] || "",
        reason: "",
      });
      onRefresh();
    } catch (e: unknown) {
      toast.error(e instanceof Error ? e.message : "Error creating override");
    } finally {
      setCreating(false);
    }
  };

  const handleDelete = async (id: number) => {
    try {
      const res = await fetch(`/api/admin/plans/overrides/${id}`, {
        method: "DELETE",
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!res.ok) throw new Error("Failed to delete override");
      toast.success("Override removed");
      onRefresh();
    } catch {
      toast.error("Error deleting override");
    }
  };

  const loadPreview = async () => {
    if (!previewWsId) return;
    setLoadingPreview(true);
    try {
      const res = await fetch(`/api/admin/plans/workspace/${previewWsId}`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!res.ok) throw new Error("Workspace not found");
      const data = await res.json();
      setPreviewData(data.capabilities);
      setPreviewName(data.workspace_name);
      setPreviewPlan(data.plan_type);
    } catch (e: unknown) {
      toast.error(e instanceof Error ? e.message : "Error loading preview");
      setPreviewData(null);
    } finally {
      setLoadingPreview(false);
    }
  };

  return (
    <section className={cx(CARD, "space-y-5")}>
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <h2 className={CARD_TITLE}>
            <Shield size={18} className="text-(--warn)" />
            Capability overrides
          </h2>
          <span className="text-xs text-(--t-3)">{overrides.length} active</span>
        </div>
        <Button variant="ghost" size="sm" onClick={() => setShowCreate(!showCreate)}>
          {showCreate ? <X size={14} /> : <Plus size={14} />}
          <span className="ml-1">{showCreate ? "Cancel" : "New Override"}</span>
        </Button>
      </div>

      {/* Create form */}
      {showCreate && (
        <div className={cx(INSET, "grid grid-cols-1 gap-3 md:grid-cols-2")}>
          <div>
            <label className={FIELD_LABEL}>Workspace ID</label>
            <input
              type="number"
              value={form.workspace_id}
              onChange={(e) => setForm({ ...form, workspace_id: e.target.value })}
              className={WINPUT}
              placeholder="e.g. 42"
            />
          </div>
          <div>
            <label className={FIELD_LABEL}>Capability</label>
            <NativeSelect
              variant="auth"
              value={form.capability_key}
              onChange={(e) => setForm({ ...form, capability_key: e.target.value })}
              disabled={capKeys.length === 0}
            >
              {capKeys.map((k) => (
                <option key={k} value={k}>
                  {k}
                </option>
              ))}
            </NativeSelect>
          </div>
          <div>
            <label className={FIELD_LABEL}>Reason</label>
            <input
              type="text"
              value={form.reason}
              onChange={(e) => setForm({ ...form, reason: e.target.value })}
              className={WINPUT}
              placeholder="Optional reason"
            />
          </div>
          <p className="md:col-span-2 m-0 text-[12px] leading-[1.55] text-(--t-3)">
            Granting a capability here unlocks it for the workspace owner, on top of their plan.
            Only these {capKeys.length} capabilities can be granted per workspace. The other{" "}
            {Object.keys(refusalReasons).length} are decided by the plan alone, so an override on
            them would have no effect and is refused. To revoke a grant, delete the override.
          </p>
          <div className="md:col-span-2 flex justify-end">
            <Button
              variant="primary"
              size="sm"
              loading={creating}
              disabled={capKeys.length === 0}
              onClick={handleCreate}
            >
              Grant Capability
            </Button>
          </div>
        </div>
      )}

      {/* Overrides list */}
      {overrides.length === 0 ? (
        <p className="px-4 py-[26px] text-center text-[13px] text-(--t-3)">No active overrides</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr>
                <th className={TH}>Workspace</th>
                <th className={TH}>Capability</th>
                <th className={TH}>Value</th>
                <th className={TH}>Effect</th>
                <th className={TH}>Reason</th>
                <th className={TH}>Created by</th>
                <th className={TH}>Expires</th>
                <th className={TH}></th>
              </tr>
            </thead>
            <tbody>
              {overrides.map((ov) => (
                <tr key={ov.id} className="transition-colors hover:bg-(--paper)">
                  <td className={TD}>
                    <span className="font-(family-name:--mono) text-xs text-(--t-2)">
                      #{ov.workspace_id}
                    </span>
                    {ov.workspace_name && (
                      <span className="ml-2 text-xs text-(--t-1)">{ov.workspace_name}</span>
                    )}
                  </td>
                  <td className={cx(TD, "font-(family-name:--mono) text-xs")}>
                    {ov.capability_key}
                  </td>
                  <td className={cx(TD, "text-center")}>
                    {formatCapValue(ov.override_value as boolean | number)}
                  </td>
                  <td className={cx(TD, "max-w-[260px] text-xs")}>
                    {ov.is_enforced === false ? (
                      <span className={CHIP_WARN} title={ov.enforcement_reason || undefined}>
                        No effect
                      </span>
                    ) : (
                      <span className="text-(--t-2)">In force</span>
                    )}
                  </td>
                  <td className={cx(TD, "max-w-[200px] truncate text-xs text-(--t-2)")}>
                    {ov.reason || "-"}
                  </td>
                  <td className={cx(TD, "text-xs text-(--t-2)")}>{ov.created_by_email || "-"}</td>
                  <td className={cx(TD, "text-xs text-(--t-2)")}>
                    {ov.expires_at ? new Date(ov.expires_at).toLocaleDateString() : "Never"}
                  </td>
                  <td className={TD}>
                    <button
                      onClick={() => handleDelete(ov.id)}
                      className="rounded-(--r-sm) p-1.5 text-(--t-3) transition-colors hover:bg-(--bad-s) hover:text-(--bad)"
                      title="Delete override"
                    >
                      <Trash2 size={14} />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Effective preview */}
      <div className="space-y-3 border-t border-(--line) pt-5">
        <div className="flex items-center gap-3">
          <Search size={16} className="text-(--t-2)" />
          <h3 className="font-(family-name:--disp) text-[13px] font-bold text-(--t-1)">
            Effective capability preview
          </h3>
        </div>
        <div className="flex items-end gap-3">
          <div className="max-w-[200px] flex-1">
            <label className={FIELD_LABEL}>Workspace ID</label>
            <input
              type="number"
              value={previewWsId}
              onChange={(e) => setPreviewWsId(e.target.value)}
              className={WINPUT}
              placeholder="Workspace ID"
            />
          </div>
          <Button variant="ghost" size="sm" loading={loadingPreview} onClick={loadPreview}>
            Preview
          </Button>
        </div>

        {previewData && (
          <div className="overflow-hidden rounded-(--r-md) border-0 bg-[#EEF1F6]">
            <div className="flex items-center gap-3 border-b border-(--line) px-4 py-2">
              <span className="text-xs font-bold text-(--t-1)">{previewName}</span>
              <span className="font-(family-name:--mono) text-[10px] uppercase tracking-[0.06em] text-(--t-3)">
                Plan: {previewPlan}
              </span>
            </div>
            <div className="max-h-[300px] overflow-x-auto overflow-y-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr>
                    <th className={cx(TH, "sticky top-0 bg-(--paper)")}>Capability</th>
                    <th className={cx(TH, "sticky top-0 bg-(--paper) text-center")}>Base</th>
                    <th className={cx(TH, "sticky top-0 bg-(--paper) text-center")}>Effective</th>
                    <th className={cx(TH, "sticky top-0 bg-(--paper) text-center")}>Overridden</th>
                  </tr>
                </thead>
                <tbody>
                  {previewData.map((c) => (
                    <tr
                      key={c.key}
                      className={cx(
                        "transition-colors",
                        c.is_overridden ? "bg-(--warn-s)" : "hover:bg-(--panel)"
                      )}
                    >
                      <td className={cx(TD, "text-xs text-(--t-2)")}>{c.key}</td>
                      <td className={cx(TD, "text-center")}>{formatCapValue(c.base_value)}</td>
                      <td className={cx(TD, "text-center")}>{formatCapValue(c.effective_value)}</td>
                      <td className={cx(TD, "text-center")}>
                        {c.is_overridden ? (
                          <span className={CHIP_WARN}>
                            <Crown size={10} /> Override
                          </span>
                        ) : (
                          <span className="text-xs text-(--t-3)">-</span>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </div>
    </section>
  );
}

/* -------------------------------------------------------------------------- */
/*  Section: Feature Flags                                                    */
/* -------------------------------------------------------------------------- */

function FeatureFlagsSection({
  flags,
  onRefresh,
  token,
}: {
  flags: FeatureFlag[];
  onRefresh: () => void;
  token: string;
}) {
  const [showCreate, setShowCreate] = useState(false);
  const [creating, setCreating] = useState(false);
  const [form, setForm] = useState({
    key: "",
    description: "",
    is_enabled: false,
    rollout_percentage: "",
  });

  const handleCreate = async () => {
    if (!form.key.trim()) {
      toast.error("Key is required");
      return;
    }
    setCreating(true);
    try {
      const res = await fetch("/api/admin/feature-flags", {
        method: "POST",
        headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
        body: JSON.stringify({
          key: form.key.trim(),
          description: form.description || null,
          is_enabled: form.is_enabled,
          rollout_percentage: form.rollout_percentage ? Number(form.rollout_percentage) : null,
        }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || "Failed to create flag");
      }
      toast.success("Feature flag created");
      setShowCreate(false);
      setForm({ key: "", description: "", is_enabled: false, rollout_percentage: "" });
      onRefresh();
    } catch (e: unknown) {
      toast.error(e instanceof Error ? e.message : "Error creating flag");
    } finally {
      setCreating(false);
    }
  };

  const handleToggle = async (flag: FeatureFlag) => {
    try {
      const res = await fetch(`/api/admin/feature-flags/${flag.id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
        body: JSON.stringify({ is_enabled: !flag.is_enabled }),
      });
      if (!res.ok) throw new Error("Failed to toggle flag");
      toast.success(`${flag.key} ${!flag.is_enabled ? "enabled" : "disabled"}`);
      onRefresh();
    } catch {
      toast.error("Error toggling flag");
    }
  };

  const handleDelete = async (id: number) => {
    try {
      const res = await fetch(`/api/admin/feature-flags/${id}`, {
        method: "DELETE",
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!res.ok) throw new Error("Failed to delete flag");
      toast.success("Feature flag deleted");
      onRefresh();
    } catch {
      toast.error("Error deleting flag");
    }
  };

  const handleRolloutChange = async (flag: FeatureFlag, value: string) => {
    const pct = value === "" ? null : Number(value);
    if (pct !== null && (pct < 0 || pct > 100)) return;
    try {
      const res = await fetch(`/api/admin/feature-flags/${flag.id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
        body: JSON.stringify({ rollout_percentage: pct }),
      });
      if (!res.ok) throw new Error("Failed to update rollout");
      onRefresh();
    } catch {
      toast.error("Error updating rollout");
    }
  };

  return (
    <section className={cx(CARD, "space-y-5")}>
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <h2 className={CARD_TITLE}>
            <Flag size={18} className="text-(--purple)" />
            Feature flags
          </h2>
          <span className="text-xs text-(--t-3)">{flags.length} total</span>
        </div>
        <Button variant="ghost" size="sm" onClick={() => setShowCreate(!showCreate)}>
          {showCreate ? <X size={14} /> : <Plus size={14} />}
          <span className="ml-1">{showCreate ? "Cancel" : "New Flag"}</span>
        </Button>
      </div>

      {/* Create form */}
      {showCreate && (
        <div className={cx(INSET, "grid grid-cols-1 gap-3 md:grid-cols-2")}>
          <div>
            <label className={FIELD_LABEL}>Key</label>
            <input
              type="text"
              value={form.key}
              onChange={(e) => setForm({ ...form, key: e.target.value })}
              className={WINPUT}
              placeholder="e.g. enable_new_dashboard"
            />
          </div>
          <div>
            <label className={FIELD_LABEL}>Description</label>
            <input
              type="text"
              value={form.description}
              onChange={(e) => setForm({ ...form, description: e.target.value })}
              className={WINPUT}
              placeholder="Optional description"
            />
          </div>
          <div className="flex items-center gap-3">
            <label className={FIELD_LABEL}>Enabled</label>
            <button
              type="button"
              role="switch"
              aria-checked={form.is_enabled}
              onClick={() => setForm({ ...form, is_enabled: !form.is_enabled })}
              className={cx(
                "relative inline-flex h-6 w-11 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors",
                form.is_enabled ? "bg-(--good)" : "bg-(--line-2)"
              )}
            >
              <span
                className={cx(
                  "pointer-events-none inline-block h-5 w-5 transform rounded-full bg-white shadow transition-transform",
                  form.is_enabled ? "translate-x-5" : "translate-x-0"
                )}
              />
            </button>
          </div>
          <div>
            <label className={FIELD_LABEL}>Rollout %</label>
            <input
              type="number"
              min={0}
              max={100}
              value={form.rollout_percentage}
              onChange={(e) => setForm({ ...form, rollout_percentage: e.target.value })}
              className={WINPUT}
              placeholder="0-100 (optional)"
            />
          </div>
          <div className="md:col-span-2 flex justify-end">
            <Button variant="primary" size="sm" loading={creating} onClick={handleCreate}>
              Create Flag
            </Button>
          </div>
        </div>
      )}

      {/* Flags list */}
      {flags.length === 0 ? (
        <p className="px-4 py-[26px] text-center text-[13px] text-(--t-3)">
          No feature flags configured
        </p>
      ) : (
        <div className="space-y-2">
          {flags.map((flag) => (
            <div
              key={flag.id}
              className="flex items-center justify-between rounded-(--r-md) border-0 bg-[#EEF1F6] px-4 py-3 transition-colors hover:bg-(--line-2)"
            >
              <div className="flex min-w-0 items-center gap-4">
                <button
                  type="button"
                  role="switch"
                  aria-checked={flag.is_enabled}
                  aria-label={`Toggle ${flag.key}`}
                  onClick={() => handleToggle(flag)}
                  className={cx(
                    "relative inline-flex h-6 w-11 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors",
                    flag.is_enabled ? "bg-(--good)" : "bg-(--line-2)"
                  )}
                >
                  <span
                    className={cx(
                      "pointer-events-none inline-block h-5 w-5 transform rounded-full bg-white shadow transition-transform",
                      flag.is_enabled ? "translate-x-5" : "translate-x-0"
                    )}
                  />
                </button>
                <div className="min-w-0">
                  <p className="truncate text-sm font-semibold text-(--t-1)">{flag.key}</p>
                  {flag.description && (
                    <p className="truncate text-xs text-(--t-3)">{flag.description}</p>
                  )}
                </div>
              </div>
              <div className="flex shrink-0 items-center gap-4">
                {flag.rollout_percentage !== null && (
                  <div className="flex items-center gap-2">
                    <span className="font-(family-name:--mono) text-[10.5px] uppercase tracking-[0.08em] text-(--t-3)">
                      Rollout
                    </span>
                    <input
                      type="number"
                      min={0}
                      max={100}
                      value={flag.rollout_percentage}
                      onChange={(e) => handleRolloutChange(flag, e.target.value)}
                      className="field-focus-ring h-8 w-16 rounded-(--r-sm) border-0 bg-white px-2 text-center text-xs text-(--t-1) outline-none focus:border-[#c7cdd6]"
                    />
                    <span className="text-xs text-(--t-3)">%</span>
                  </div>
                )}
                <button
                  onClick={() => handleDelete(flag.id)}
                  className="rounded-(--r-sm) p-1.5 text-(--t-3) transition-colors hover:bg-(--bad-s) hover:text-(--bad)"
                  title="Delete flag"
                >
                  <Trash2 size={14} />
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}

/* -------------------------------------------------------------------------- */
/*  Main Page                                                                 */
/* -------------------------------------------------------------------------- */

export default function AdminPlansPage() {
  const { getToken } = useAuth();
  const [loading, setLoading] = useState(true);
  const [plansData, setPlansData] = useState<PlansResponse | null>(null);
  const [overrides, setOverrides] = useState<Override[]>([]);
  const [flags, setFlags] = useState<FeatureFlag[]>([]);
  const [token, setToken] = useState("");

  const fetchAll = useCallback(async () => {
    const t = await getToken();
    if (!t) return;
    setToken(t);
    setLoading(true);

    try {
      const [plansRes, overridesRes, flagsRes] = await Promise.all([
        fetch("/api/admin/plans", { headers: { Authorization: `Bearer ${t}` } }),
        fetch("/api/admin/plans/overrides", { headers: { Authorization: `Bearer ${t}` } }),
        fetch("/api/admin/feature-flags", { headers: { Authorization: `Bearer ${t}` } }),
      ]);

      if (plansRes.ok) setPlansData(await plansRes.json());
      if (overridesRes.ok) {
        const d = await overridesRes.json();
        setOverrides(d.overrides || []);
      }
      if (flagsRes.ok) {
        const d = await flagsRes.json();
        setFlags(d.flags || []);
      }
    } catch {
      toast.error("Failed to load plan data");
    } finally {
      setLoading(false);
    }
  }, [getToken]);

  useEffect(() => {
    fetchAll();
  }, [fetchAll]);

  if (loading) {
    return (
      <div className="flex items-center justify-center py-20">
        <div className="h-8 w-8 animate-spin rounded-full border-2 border-(--purple) border-t-transparent" />
      </div>
    );
  }

  return (
    <>
      <DashboardPageIntro icon={Layers} title="Pricing tiers & features">
        View plan capabilities, manage per-workspace overrides, and control feature flags.
      </DashboardPageIntro>

      {/* Plan comparison */}
      {plansData && <PlanComparisonTable data={plansData} />}

      {/* Overrides */}
      <OverridesSection
        overrides={overrides}
        // SIGV2-1147: offer only the capabilities an override actually changes,
        // not every key in the plan matrix.
        capKeys={plansData?.overridable_capability_keys || []}
        refusalReasons={plansData?.override_refusal_reasons || {}}
        onRefresh={fetchAll}
        token={token}
      />

      {/* Feature flags */}
      <FeatureFlagsSection flags={flags} onRefresh={fetchAll} token={token} />
    </>
  );
}
