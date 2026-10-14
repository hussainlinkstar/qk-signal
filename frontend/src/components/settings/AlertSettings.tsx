"use client";

import SignalAlert from "@/components/signal/SignalAlert";
import React, { useState, useEffect, useCallback } from "react";
import { Plus, Trash2, Bell, CheckCircle2, Loader2, ArrowRight } from "lucide-react";
import { toast } from "sonner";
import { useAuth } from "@/components/auth/custom-auth";
import Modal from "@/components/ui/Modal";
import {
  AlertRuleResponse,
  AlertRuleCreate,
  fetchAlertRules,
  createAlertRule,
  updateAlertRule,
  deleteAlertRule,
} from "@/services/alertRulesService";
import { formatDateTime } from "@/lib/dateFormat";

interface AlertSettingsProps {
  projectId: number | string;
}

const METRIC_OPTIONS = [
  { value: "geo_score", label: "AI Visibility Score (%)" },
  { value: "seo_score", label: "SEO Score (%)" },
  { value: "aeo_score", label: "Answer Engine Index (%)" },
  { value: "ai_visibility_score", label: "AI Visibility Score (%)" },
  { value: "aeo_mention_drop", label: "Off-Page Answer Engine Index (%)" },
  { value: "featured_snippets_lost", label: "Featured Snippets Lost" },
];

const CONDITION_OPTIONS = [
  { value: "below", label: "Drops Below" },
  { value: "above", label: "Goes Above" },
];

export default function AlertSettings({ projectId }: AlertSettingsProps) {
  const { user } = useAuth();

  const [rules, setRules] = useState<AlertRuleResponse[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Create mode state
  const [isCreating, setIsCreating] = useState(false);
  const [newRule, setNewRule] = useState<AlertRuleCreate>({
    metric: "geo_score",
    condition: "below",
    threshold: 80,
    email_to: user?.email || "",
    is_active: true,
  });

  const [saving, setSaving] = useState(false);
  const [pendingDeleteRuleId, setPendingDeleteRuleId] = useState<number | null>(null);

  const loadRules = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await fetchAlertRules(projectId);
      setRules(data);
    } catch (err: any) {
      setError(err.message || "Failed to load alert rules.");
    } finally {
      setLoading(false);
    }
  }, [projectId]);

  useEffect(() => {
    loadRules();
  }, [loadRules]);

  const handleCreate = async () => {
    if (!newRule.email_to || newRule.email_to.indexOf("@") === -1) {
      toast.error("Please enter a valid email address.");
      return;
    }
    setSaving(true);
    try {
      await createAlertRule(projectId, newRule);
      await loadRules();
      setIsCreating(false);
      // Reset form
      setNewRule({
        metric: "geo_score",
        condition: "below",
        threshold: 80,
        email_to: user?.email || "",
        is_active: true,
      });
    } catch (err: any) {
      toast.error(err.message || "Failed to create alert rule");
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = (ruleId: number) => {
    setPendingDeleteRuleId(ruleId);
  };

  const confirmDelete = async () => {
    if (pendingDeleteRuleId === null) return;
    const ruleId = pendingDeleteRuleId;
    setPendingDeleteRuleId(null);
    try {
      await deleteAlertRule(projectId, ruleId);
      setRules(rules.filter((r) => r.id !== ruleId));
    } catch (err: any) {
      toast.error(err.message || "Failed to delete alert rule");
    }
  };

  const handleToggleActive = async (rule: AlertRuleResponse) => {
    try {
      const updated = await updateAlertRule(projectId, rule.id, { is_active: !rule.is_active });
      setRules(rules.map((r) => (r.id === updated.id ? updated : r)));
    } catch (err: any) {
      toast.error(err.message || "Failed to update alert rule state");
    }
  };

  if (loading) {
    return (
      <div className="flex justify-center p-12">
        <Loader2 className="h-6 w-6 animate-spin text-(--t-2)" />
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <p className="font-mono text-[10px] font-bold uppercase tracking-[0.14em] text-(--t-3)">
            Alert Rules
          </p>
          <p className="mt-1 text-[12.5px] text-(--t-2)">
            Configure automated email notifications when metrics cross specific thresholds.
          </p>
        </div>
        {!isCreating && (
          <button
            onClick={() => setIsCreating(true)}
            className="flex h-[38px] items-center gap-1.5 rounded-[10px] border border-(--ink) bg-(--ink) px-[15px] text-[13.5px] font-semibold text-white transition-colors hover:bg-black max-md:min-h-11"
          >
            <Plus size={15} />
            Add Rule
          </button>
        )}
      </div>

      {error && (
        <SignalAlert tone="danger" title="Alert settings unavailable">
          {error}
        </SignalAlert>
      )}

      {isCreating && (
        <div className="rounded-xl border border-(--line) bg-(--line-2) p-6 animate-in fade-in slide-in-from-top-4 duration-300">
          <p className="mb-4 font-mono text-[10px] font-bold uppercase tracking-[0.14em] text-(--t-3)">
            Create New Alert Rule
          </p>
          <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
            <div className="space-y-1">
              <label className="text-xs text-(--t-2)">Metric</label>
              <select
                value={newRule.metric}
                onChange={(e) => setNewRule({ ...newRule, metric: e.target.value })}
                className="w-full rounded-lg border border-(--line) bg-(--paper) p-2.5 text-sm text-(--t-1) focus:border-(--blue) focus:outline-hidden"
              >
                {METRIC_OPTIONS.map((o) => (
                  <option key={o.value} value={o.value}>
                    {o.label}
                  </option>
                ))}
              </select>
            </div>

            <div className="space-y-1">
              <label className="text-xs text-(--t-2)">Condition</label>
              <select
                value={newRule.condition}
                onChange={(e) => setNewRule({ ...newRule, condition: e.target.value })}
                className="w-full rounded-lg border border-(--line) bg-(--paper) p-2.5 text-sm text-(--t-1) focus:border-(--blue) focus:outline-hidden"
              >
                {CONDITION_OPTIONS.map((o) => (
                  <option key={o.value} value={o.value}>
                    {o.label}
                  </option>
                ))}
              </select>
            </div>

            <div className="space-y-1">
              <label className="text-xs text-(--t-2)">Threshold</label>
              <input
                type="number"
                value={newRule.threshold}
                onChange={(e) =>
                  setNewRule({ ...newRule, threshold: parseFloat(e.target.value) || 0 })
                }
                className="w-full rounded-lg border border-(--line) bg-(--paper) p-2.5 text-sm text-(--t-1) focus:border-(--blue) focus:outline-hidden"
                placeholder="e.g. 50"
              />
            </div>

            <div className="space-y-1">
              <label className="text-xs text-(--t-2)">Send To (Email)</label>
              <input
                type="email"
                value={newRule.email_to}
                onChange={(e) => setNewRule({ ...newRule, email_to: e.target.value })}
                className="w-full rounded-lg border border-(--line) bg-(--paper) p-2.5 text-sm text-(--t-1) focus:border-(--blue) focus:outline-hidden"
                placeholder="alert@example.com"
              />
            </div>
          </div>

          <div className="mt-6 flex justify-end gap-3">
            <button
              onClick={() => setIsCreating(false)}
              className="rounded-lg px-4 py-2 text-sm font-medium text-(--t-2) hover:text-(--t-1)"
            >
              Cancel
            </button>
            <button
              onClick={handleCreate}
              disabled={saving}
              className="flex items-center gap-1.5 rounded-[10px] border border-(--ink) bg-(--ink) px-[15px] py-2 text-[13.5px] font-semibold text-white hover:bg-black disabled:opacity-50"
            >
              {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : <CheckCircle2 size={16} />}
              Save Rule
            </button>
          </div>
        </div>
      )}

      {rules.length === 0 && !isCreating ? (
        <div className="flex flex-col items-center justify-center rounded-xl border border-dashed border-(--line) py-12 text-center">
          <Bell className="mb-3 h-8 w-8 text-(--t-3)" />
          <p className="text-[13.5px] font-semibold text-(--t-1)">No active alerts</p>
          <p className="mt-1 text-sm text-(--t-2)">
            Create an alert to be notified when your visibility metrics take a hit.
          </p>
        </div>
      ) : (
        <div className="space-y-3">
          {rules.map((rule) => {
            const metricLabel =
              METRIC_OPTIONS.find((m) => m.value === rule.metric)?.label || rule.metric;
            const conditionLabel =
              CONDITION_OPTIONS.find((c) => c.value === rule.condition)?.label || rule.condition;

            return (
              <div
                key={rule.id}
                className={`flex flex-col sm:flex-row sm:items-center justify-between gap-4 rounded-xl border p-4 transition-colors ${
                  rule.is_active
                    ? "border-(--line) bg-(--line-2)"
                    : "border-(--line) bg-(--line-2) opacity-70"
                }`}
              >
                <div className="space-y-1 flex-1">
                  <div className="flex items-center gap-2">
                    <span className="font-medium text-(--t-1)">{metricLabel}</span>
                    <ArrowRight size={14} className="text-(--t-3)" />
                    <span className="text-(--warn) text-sm font-medium">
                      {conditionLabel} {rule.threshold}
                    </span>
                  </div>
                  <div className="flex flex-wrap items-center gap-y-1 gap-x-4 text-xs text-(--t-2)">
                    <span>Target: {rule.email_to}</span>
                    <span className="hidden sm:inline">&bull;</span>
                    <span>
                      {rule.last_triggered_at
                        ? `Last triggered: ${formatDateTime(rule.last_triggered_at)}`
                        : "Never triggered"}
                    </span>
                  </div>
                </div>

                <div className="flex items-center gap-3 self-end sm:self-auto">
                  <button
                    onClick={() => handleToggleActive(rule)}
                    className={`rounded-full px-3 py-1 text-xs font-medium transition-colors ${
                      rule.is_active
                        ? "bg-(--line-2) text-(--good) hover:bg-(--line)"
                        : "bg-(--line-2) text-(--t-2) hover:bg-(--line) hover:text-(--t-1)"
                    }`}
                  >
                    {rule.is_active ? "Active" : "Paused"}
                  </button>
                  <button
                    onClick={() => handleDelete(rule.id)}
                    className="rounded-lg p-2 text-(--t-3) hover:bg-(--bad-s) hover:text-(--bad) transition-colors"
                    title="Delete rule"
                  >
                    <Trash2 size={16} />
                  </button>
                </div>
              </div>
            );
          })}
        </div>
      )}

      <Modal open={pendingDeleteRuleId !== null} onClose={() => setPendingDeleteRuleId(null)}>
        <div className="flex items-start gap-3">
          <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-(--bad-s) text-(--bad)">
            <Trash2 size={18} />
          </div>
          <div>
            <p className="text-[13.5px] font-semibold text-(--t-1)">Confirm Deletion</p>
            <p className="mt-1 text-sm text-(--t-2)">
              Are you sure you want to delete this alert rule? This cannot be undone.
            </p>
          </div>
        </div>
        <div className="mt-6 flex justify-end gap-3">
          <button
            onClick={() => setPendingDeleteRuleId(null)}
            className="rounded-lg px-4 py-2 text-sm font-medium text-(--t-2) hover:text-(--t-1)"
          >
            Cancel
          </button>
          <button
            onClick={() => void confirmDelete()}
            className="rounded-[10px] bg-(--bad) px-[15px] py-2 text-[13.5px] font-semibold text-white hover:opacity-90"
          >
            Confirm Delete
          </button>
        </div>
      </Modal>
    </div>
  );
}
