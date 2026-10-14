"use client";

import { useEffect, useState } from "react";

import Modal from "@/components/ui/Modal";
import {
  createProjectWorkflow,
  updateProjectWorkflow,
  type WorkflowActionType,
  type WorkflowItem,
  type WorkflowTriggerType,
} from "@/services/workflowService";

export type SignalAutomationModalProps = {
  open: boolean;
  onClose: () => void;
  projectId: string;
  editing: WorkflowItem | null;
  getAuthHeaders: () => Promise<HeadersInit>;
  onSaved?: () => void;
};

const inputClass =
  "h-11 w-full rounded-[10px] border border-(--line) bg-(--paper) px-3 text-[13.5px] text-(--t-1) outline-hidden focus:border-[#C7CDD6]";
const selectClass = `${inputClass} appearance-none`;
const labelClass =
  "mb-2 block font-(family-name:--mono) text-[10.5px] uppercase tracking-[0.08em] text-(--t-3)";

function defaultActionConfig(type: WorkflowActionType): Record<string, unknown> {
  switch (type) {
    case "send_email":
      return { to: "", template_key: "alert.triggered" };
    case "send_slack":
      return { channel_id: "" };
    case "run_audit":
      return { tier: "fast", category: "" };
    case "create_jira_ticket":
      return {
        project_key: "",
        issue_type: "Task",
        summary: "[{project_name}] {event_key}",
        description: "Workflow event {event_key} triggered.",
      };
    case "webhook":
      return { url: "", method: "POST" };
    default:
      return {};
  }
}

/**
 * Real create/edit form for the Workflow Automations engine (`workflowService.ts`
 * -> `backend/services/workflow_engine.py` + `routers/workflow_router.py`).
 * Mirrors the field-per-trigger/action-type logic already established in
 * WorkflowTriggerCard.tsx / WorkflowActionCard.tsx, restyled to the
 * signal-MVP `.modal` pattern (see SignalAddCompetitorModal.tsx). Supports one
 * trigger and one action per automation - the backend model allows multiple
 * actions, but a single-action rule covers the common case and keeps this
 * first cut honest about what the form actually builds.
 */
export default function SignalAutomationModal({
  open,
  onClose,
  projectId,
  editing,
  getAuthHeaders,
  onSaved,
}: SignalAutomationModalProps) {
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [isActive, setIsActive] = useState(true);
  const [triggerType, setTriggerType] = useState<WorkflowTriggerType>("audit_completed");
  const [auditTier, setAuditTier] = useState("any");
  const [eventKey, setEventKey] = useState("");
  const [metric, setMetric] = useState("seo_score");
  const [condition, setCondition] = useState<"below" | "above" | "drops_by">("below");
  const [threshold, setThreshold] = useState("70");
  const [actionType, setActionType] = useState<WorkflowActionType>("send_email");
  const [actionConfig, setActionConfig] = useState<Record<string, unknown>>(
    defaultActionConfig("send_email")
  );
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    if (editing) {
      setName(editing.name);
      setDescription(editing.description || "");
      setIsActive(editing.is_active);
      setTriggerType(editing.trigger_config.type);
      setAuditTier(editing.trigger_config.audit_tier || "any");
      setEventKey(editing.trigger_config.event_key || "");
      setMetric(editing.trigger_config.metric || "seo_score");
      setCondition(editing.trigger_config.condition || "below");
      setThreshold(String(editing.trigger_config.value ?? 70));
      const firstAction = editing.actions_config[0];
      setActionType(firstAction?.type || "send_email");
      setActionConfig(
        firstAction?.config || defaultActionConfig(firstAction?.type || "send_email")
      );
    } else {
      setName("");
      setDescription("");
      setIsActive(true);
      setTriggerType("audit_completed");
      setAuditTier("any");
      setEventKey("");
      setMetric("seo_score");
      setCondition("below");
      setThreshold("70");
      setActionType("send_email");
      setActionConfig(defaultActionConfig("send_email"));
    }
    setError(null);
  }, [open, editing]);

  const handleClose = () => {
    if (submitting) return;
    onClose();
  };

  const handleSubmit = async () => {
    if (!name.trim()) {
      setError("Give this automation a name.");
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      const headers = await getAuthHeaders();
      const payload = {
        name: name.trim(),
        description: description.trim() || null,
        trigger_config: {
          type: triggerType,
          event_key:
            triggerType === "platform_event" || triggerType === "alert_triggered"
              ? eventKey
              : undefined,
          audit_tier: triggerType === "audit_completed" ? auditTier : undefined,
          metric:
            triggerType === "metric_threshold" || triggerType === "alert_triggered"
              ? metric
              : undefined,
          condition:
            triggerType === "metric_threshold" || triggerType === "alert_triggered"
              ? condition
              : undefined,
          value:
            triggerType === "metric_threshold" || triggerType === "alert_triggered"
              ? Number(threshold || 0)
              : undefined,
        },
        actions_config: [{ type: actionType, config: actionConfig }],
        cooldown_minutes: editing?.cooldown_minutes ?? 60,
        is_active: isActive,
      };
      if (editing) {
        await updateProjectWorkflow(projectId, editing.id, payload, headers);
      } else {
        await createProjectWorkflow(projectId, payload, headers);
      }
      onSaved?.();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to save this automation.");
    } finally {
      setSubmitting(false);
    }
  };

  const updateActionConfig = (key: string, value: string) =>
    setActionConfig((prev) => ({ ...prev, [key]: value }));

  return (
    <Modal
      open={open}
      onClose={handleClose}
      panelClassName="p-0! bg-transparent! border-0! shadow-none!"
    >
      <div
        data-signal-theme
        className="w-[620px] max-w-full rounded-[20px] border border-(--line) bg-(--panel) p-[28px_30px_26px] shadow-[0_40px_90px_-30px_rgba(12,15,22,0.5)]"
      >
        <p className="font-(family-name:--mono) text-[11px] uppercase tracking-[0.14em] text-(--t-3)">
          Automations
        </p>
        <h2 className="mt-2 font-(family-name:--disp) text-[23px] font-extrabold tracking-[-0.02em] text-(--t-1)">
          {editing ? "Edit automation" : "Create automation"}
        </h2>
        <p className="mb-[22px] mt-1.5 text-[13.5px] leading-normal text-(--t-2)">
          Choose the event that triggers this rule, then the action it should take.
        </p>

        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <label className="sm:col-span-2 block">
            <span className={labelClass}>Name</span>
            <input
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="Notify team on SEO drop"
              className={inputClass}
            />
          </label>
          <label className="sm:col-span-2 block">
            <span className={labelClass}>Description (optional)</span>
            <input
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="What this automation does"
              className={inputClass}
            />
          </label>

          <label className="sm:col-span-2 block">
            <span className={labelClass}>Trigger</span>
            <select
              value={triggerType}
              onChange={(e) => setTriggerType(e.target.value as WorkflowTriggerType)}
              className={selectClass}
            >
              <option value="audit_completed">Assessment completed</option>
              <option value="metric_threshold">Metric threshold crossed</option>
              <option value="alert_triggered">Alert triggered</option>
              <option value="platform_event">Platform event</option>
            </select>
          </label>

          {triggerType === "audit_completed" && (
            <label className="sm:col-span-2 block">
              <span className={labelClass}>Assessment tier</span>
              <select
                value={auditTier}
                onChange={(e) => setAuditTier(e.target.value)}
                className={selectClass}
              >
                <option value="any">Any</option>
                <option value="fast">Fast</option>
                <option value="smart">Smart</option>
                <option value="standard">Standard</option>
                <option value="deep">Deep</option>
              </select>
            </label>
          )}

          {(triggerType === "platform_event" || triggerType === "alert_triggered") && (
            <label className="sm:col-span-2 block">
              <span className={labelClass}>Event key</span>
              <input
                value={eventKey}
                onChange={(e) => setEventKey(e.target.value)}
                placeholder="audit.completed"
                className={inputClass}
              />
            </label>
          )}

          {(triggerType === "metric_threshold" || triggerType === "alert_triggered") && (
            <>
              <label className="block">
                <span className={labelClass}>Metric</span>
                <select
                  value={metric}
                  onChange={(e) => setMetric(e.target.value)}
                  className={selectClass}
                >
                  <option value="seo_score">SEO score</option>
                  <option value="geo_score">AI visibility score</option>
                  <option value="aeo_score">AI answers score</option>
                  <option value="ai_visibility_score">AI visibility score</option>
                  <option value="featured_snippets_lost">Featured snippets lost</option>
                </select>
              </label>
              <label className="block">
                <span className={labelClass}>Condition</span>
                <select
                  value={condition}
                  onChange={(e) => setCondition(e.target.value as typeof condition)}
                  className={selectClass}
                >
                  <option value="below">Drops below</option>
                  <option value="above">Goes above</option>
                  <option value="drops_by">Drops by</option>
                </select>
              </label>
              <label className="sm:col-span-2 block">
                <span className={labelClass}>Threshold</span>
                <input
                  type="number"
                  value={threshold}
                  onChange={(e) => setThreshold(e.target.value)}
                  className={inputClass}
                />
              </label>
            </>
          )}

          <label className="sm:col-span-2 block">
            <span className={labelClass}>Then</span>
            <select
              value={actionType}
              onChange={(e) => {
                const next = e.target.value as WorkflowActionType;
                setActionType(next);
                setActionConfig(defaultActionConfig(next));
              }}
              className={selectClass}
            >
              <option value="send_email">Send email</option>
              <option value="send_slack">Send Slack message</option>
              <option value="send_teams">Send Teams message</option>
              <option value="webhook">Call a webhook</option>
              <option value="run_audit">Run an assessment</option>
              <option value="create_jira_ticket">Create a Jira ticket</option>
            </select>
          </label>

          {actionType === "send_email" && (
            <>
              <label className="block">
                <span className={labelClass}>Recipient email</span>
                <input
                  value={String(actionConfig.to || "")}
                  onChange={(e) => updateActionConfig("to", e.target.value)}
                  className={inputClass}
                />
              </label>
              <label className="block">
                <span className={labelClass}>Template key</span>
                <input
                  value={String(actionConfig.template_key || "")}
                  onChange={(e) => updateActionConfig("template_key", e.target.value)}
                  className={inputClass}
                />
              </label>
            </>
          )}

          {actionType === "send_slack" && (
            <label className="sm:col-span-2 block">
              <span className={labelClass}>Slack channel ID</span>
              <input
                value={String(actionConfig.channel_id || "")}
                onChange={(e) => updateActionConfig("channel_id", e.target.value)}
                className={inputClass}
              />
            </label>
          )}

          {actionType === "webhook" && (
            <>
              <label className="block">
                <span className={labelClass}>Webhook URL</span>
                <input
                  value={String(actionConfig.url || "")}
                  onChange={(e) => updateActionConfig("url", e.target.value)}
                  className={inputClass}
                />
              </label>
              <label className="block">
                <span className={labelClass}>Method</span>
                <select
                  value={String(actionConfig.method || "POST")}
                  onChange={(e) => updateActionConfig("method", e.target.value)}
                  className={selectClass}
                >
                  <option value="POST">POST</option>
                  <option value="PUT">PUT</option>
                  <option value="PATCH">PATCH</option>
                </select>
              </label>
            </>
          )}

          {actionType === "run_audit" && (
            <>
              <label className="block">
                <span className={labelClass}>Assessment tier</span>
                <select
                  value={String(actionConfig.tier || "fast")}
                  onChange={(e) => updateActionConfig("tier", e.target.value)}
                  className={selectClass}
                >
                  <option value="fast">Fast</option>
                  <option value="deep">Deep</option>
                </select>
              </label>
              <label className="block">
                <span className={labelClass}>Category (optional)</span>
                <input
                  value={String(actionConfig.category || "")}
                  onChange={(e) => updateActionConfig("category", e.target.value)}
                  className={inputClass}
                />
              </label>
            </>
          )}

          {actionType === "create_jira_ticket" && (
            <>
              <label className="block">
                <span className={labelClass}>Jira project key</span>
                <input
                  value={String(actionConfig.project_key || "")}
                  onChange={(e) => updateActionConfig("project_key", e.target.value)}
                  className={inputClass}
                />
              </label>
              <label className="block">
                <span className={labelClass}>Issue type</span>
                <input
                  value={String(actionConfig.issue_type || "Task")}
                  onChange={(e) => updateActionConfig("issue_type", e.target.value)}
                  className={inputClass}
                />
              </label>
              <label className="sm:col-span-2 block">
                <span className={labelClass}>Summary template</span>
                <input
                  value={String(actionConfig.summary || "")}
                  onChange={(e) => updateActionConfig("summary", e.target.value)}
                  className={inputClass}
                />
              </label>
            </>
          )}

          <label className="sm:col-span-2 flex items-center gap-2 pt-1">
            <input
              type="checkbox"
              checked={isActive}
              onChange={(e) => setIsActive(e.target.checked)}
              className="h-4 w-4"
            />
            <span className="text-[13px] text-(--t-2)">Active as soon as it's saved</span>
          </label>
        </div>

        {error && <p className="mt-3 text-[12.5px] text-(--bad)">{error}</p>}

        <div className="mt-6 flex justify-end gap-2.5">
          <button
            type="button"
            onClick={handleClose}
            disabled={submitting}
            className="h-[38px] rounded-[10px] border border-(--line) bg-(--panel) px-[15px] text-[13.5px] font-semibold text-(--t-1) hover:border-[#D7DAE0] disabled:opacity-50"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={handleSubmit}
            disabled={submitting}
            className="h-[38px] rounded-[10px] bg-(--ink) px-[15px] text-[13.5px] font-semibold text-white hover:bg-black disabled:opacity-50"
          >
            {submitting ? "Saving..." : editing ? "Save changes" : "Create automation"}
          </button>
        </div>
      </div>
    </Modal>
  );
}
