"use client";

// Rebranded from the "Agents" mockup to "Automations", bound to REAL data end to end.
// The signal-MVP "Signal Agents.html" mockup depicted a fictional "Qiko Agent
// Orchestrator" (autonomous agents, a fake API key connect flow, fabricated AIO-lift
// charts) that has no backend behind it anywhere in this codebase. What IS real and
// fully implemented is the Workflow Automations engine (trigger -> action rules,
// `workflowService.ts` / `backend/routers/workflow_router.py`), gated by the exact
// same `feature_access.automations` flag. This page surfaces that real engine under
// the same visual language (`.sg .agents` classes) instead of the fictional one.
import React, { useCallback, useEffect, useMemo, useState } from "react";
import { useParams } from "next/navigation";
import { toast } from "sonner";

import { useAuth } from "@/components/auth/custom-auth";
import SignalAutomationModal from "@/components/signal/SignalAutomationModal";
import SignalUpgradeGate from "@/components/signal/SignalUpgradeGate";
import { useProjectLatestAudit } from "@/hooks/useProjectLatestAudit";
import { useWorkspacePageHeader } from "@/components/dashboard/workspacePageHeader";
import { cx } from "@/components/ui/utils";
import { formatRelativeTime } from "@/lib/dateFormat";
import {
  deleteProjectWorkflow,
  fetchProjectWorkflows,
  testProjectWorkflow,
  updateProjectWorkflow,
  type WorkflowActionConfig,
  type WorkflowItem,
  type WorkflowTriggerConfig,
} from "@/services/workflowService";

const UPGRADE_HREF = "/dashboard/billing?section=plans&plan=plan_specialist";

const ACTION_LABELS: Record<string, string> = {
  send_email: "Send email",
  send_slack: "Send Slack message",
  send_teams: "Send Teams message",
  webhook: "Call a webhook",
  run_audit: "Run an assessment",
  create_jira_ticket: "Create a Jira ticket",
};

const METRIC_LABELS: Record<string, string> = {
  seo_score: "SEO score",
  geo_score: "AI visibility score",
  aeo_score: "AI answers score",
  ai_visibility_score: "AI visibility score",
  featured_snippets_lost: "Featured snippets lost",
};

function describeTrigger(trigger: WorkflowTriggerConfig): string {
  if (trigger.type === "audit_completed") {
    const tier =
      trigger.audit_tier && trigger.audit_tier !== "any" ? ` (${trigger.audit_tier})` : "";
    return `When: an assessment completes${tier}`;
  }
  if (trigger.type === "metric_threshold" || trigger.type === "alert_triggered") {
    const metric = METRIC_LABELS[trigger.metric || ""] || trigger.metric || "a metric";
    const cond =
      trigger.condition === "above"
        ? "goes above"
        : trigger.condition === "drops_by"
          ? "drops by"
          : "drops below";
    return `When: ${metric} ${cond} ${trigger.value ?? "-"}`;
  }
  return `When: "${trigger.event_key || "a platform event"}" fires`;
}

function describeActions(actions: WorkflowActionConfig[]): string {
  if (!actions.length) return "Then: no action configured";
  return `Then: ${actions.map((a) => ACTION_LABELS[a.type] ?? a.type).join(", ")}`;
}

export default function ProjectAutomationsClient() {
  const params = useParams<{ projectId: string }>();
  const projectId = params?.projectId ?? "";
  const { getToken } = useAuth();
  const { project, loading: accessLoading } = useProjectLatestAudit(projectId);

  const allowed = Boolean(
    (project as { feature_access?: { automations?: { allowed?: boolean } } } | null)?.feature_access
      ?.automations?.allowed
  );
  // feature_access arrives asynchronously. Deciding while `project` is still null
  // renders the upgrade gate for a moment and then tears it down again for users
  // who do have access, so hold the verdict until access has actually resolved.
  const locked = !accessLoading && !allowed;

  const [workflows, setWorkflows] = useState<WorkflowItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [busyId, setBusyId] = useState<number | null>(null);
  const [pendingDeleteId, setPendingDeleteId] = useState<number | null>(null);
  const [modalOpen, setModalOpen] = useState(false);
  const [editing, setEditing] = useState<WorkflowItem | null>(null);
  const [upgradeGateOpen, setUpgradeGateOpen] = useState(true);

  const getAuthHeaders = useCallback(async (): Promise<HeadersInit> => {
    const token = await getToken();
    return token ? { Authorization: `Bearer ${token}` } : {};
  }, [getToken]);

  const load = useCallback(async () => {
    if (!projectId || accessLoading || !allowed) {
      setLoading(false);
      return;
    }
    setLoading(true);
    try {
      const headers = await getAuthHeaders();
      const items = await fetchProjectWorkflows(projectId, headers);
      setWorkflows(items);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Unable to load automations.");
    } finally {
      setLoading(false);
    }
  }, [accessLoading, allowed, getAuthHeaders, projectId]);

  useEffect(() => {
    void load();
  }, [load]);

  const handleToggleActive = useCallback(
    async (workflow: WorkflowItem) => {
      setBusyId(workflow.id);
      try {
        const headers = await getAuthHeaders();
        await updateProjectWorkflow(
          projectId,
          workflow.id,
          { is_active: !workflow.is_active },
          headers
        );
        toast.success(workflow.is_active ? "Automation paused." : "Automation activated.");
        await load();
      } catch (err) {
        toast.error(err instanceof Error ? err.message : "Unable to update automation.");
      } finally {
        setBusyId(null);
      }
    },
    [getAuthHeaders, load, projectId]
  );

  const handleTest = useCallback(
    async (workflow: WorkflowItem) => {
      setBusyId(workflow.id);
      try {
        const headers = await getAuthHeaders();
        const { run } = await testProjectWorkflow(projectId, workflow.id, {}, headers);
        toast.success(`Test run ${run.status}.`);
      } catch (err) {
        toast.error(err instanceof Error ? err.message : "Unable to run test.");
      } finally {
        setBusyId(null);
      }
    },
    [getAuthHeaders, projectId]
  );

  const handleDeleteClick = useCallback(
    async (workflow: WorkflowItem) => {
      if (pendingDeleteId !== workflow.id) {
        setPendingDeleteId(workflow.id);
        return;
      }
      setPendingDeleteId(null);
      setBusyId(workflow.id);
      try {
        const headers = await getAuthHeaders();
        await deleteProjectWorkflow(projectId, workflow.id, headers);
        toast.success("Automation deleted.");
        await load();
      } catch (err) {
        toast.error(err instanceof Error ? err.message : "Unable to delete automation.");
      } finally {
        setBusyId(null);
      }
    },
    [getAuthHeaders, load, pendingDeleteId, projectId]
  );

  const activeCount = useMemo(() => workflows.filter((w) => w.is_active).length, [workflows]);

  // `.top` content lives inside the shared SignalTopBar (registered via the
  // page-header context): the `.dom` title + status pills on the left, the
  // New automation action after the spacer - never a second row under it.
  const { setHeader } = useWorkspacePageHeader();
  const topLeft = useMemo(
    () => (
      <>
        <div className="font-(family-name:--disp) text-[16px] font-bold tracking-[-0.01em]">
          Automations
        </div>
        {workflows.length > 0 ? (
          <span
            className={cx(
              "inline-flex items-center gap-[7px] rounded-[999px] px-2.5 py-[5px] text-[11px] tracking-[0.06em]",
              activeCount > 0
                ? "bg-[rgba(147,51,234,0.1)] text-(--purple)"
                : "bg-(--line-2) text-(--t-3)"
            )}
          >
            <span
              className={cx(
                "h-1.5 w-1.5 rounded-[50%]",
                activeCount > 0 ? "bg-(--purple)" : "bg-(--t-3)"
              )}
            />
            {activeCount > 0 ? `${activeCount} ACTIVE` : "ALL PAUSED"}
          </span>
        ) : (
          <span className="inline-flex items-center gap-[7px] rounded-[999px] bg-(--line-2) px-2.5 py-[5px] text-[11px] tracking-[0.06em] text-(--t-3)">
            <span className="h-1.5 w-1.5 rounded-[50%] bg-(--t-3)" />
            NO AUTOMATIONS
          </span>
        )}
      </>
    ),
    [workflows.length, activeCount]
  );
  const topActions = useMemo(
    () => (
      <button
        className="inline-flex h-[38px] cursor-pointer items-center gap-2 rounded-[10px] border border-(--ink) bg-(--ink) px-[15px] font-(family-name:--body-font) text-[13.5px] font-semibold text-white hover:bg-black"
        disabled={locked}
        onClick={() => {
          setEditing(null);
          setModalOpen(true);
        }}
      >
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor">
          <path d="M12 5v14M5 12h14" />
        </svg>
        New automation
      </button>
    ),
    [locked]
  );
  useEffect(() => {
    setHeader({ crumb: topLeft, actions: topActions });
    return () => setHeader(null);
  }, [setHeader, topLeft, topActions]);

  return (
    <div className="min-w-0">
      <div
        className={cx(
          "flex flex-col gap-[22px] pb-[52px]",
          locked && "pointer-events-none select-none blur-[7px]"
        )}
      >
        <div className="flex items-end gap-4 max-md:flex-col max-md:items-start">
          <h1 className="m-0 font-(family-name:--disp) text-[26px] font-black tracking-[-0.02em]">
            Automations
          </h1>
          <div className="mt-[5px] max-w-[520px] text-[13px] leading-[1.5] text-(--t-2)">
            Automatically trigger real actions, email, Slack, Teams, a webhook, a Jira ticket, or a
            follow-up assessment, when specific events happen on this project. No manual follow-up
            required.
          </div>
        </div>

        {!locked && (
          <>
            <div className="flex items-center gap-3 max-md:min-w-0 max-md:flex-wrap max-md:items-start">
              <h2 className="m-0 font-(family-name:--disp) text-[17px] font-extrabold tracking-[-0.01em] max-md:min-w-0 max-md:whitespace-normal">
                Your automations
              </h2>
              <span className="h-4 w-px flex-none bg-(--line-2)" />
              <span className="text-[12.5px] text-(--t-3) max-md:w-full max-md:whitespace-normal">
                {workflows.length} configured
              </span>
            </div>

            {loading ? (
              <div className="rounded-(--r) border border-(--line) bg-(--panel) p-6">
                <span>Loading automations...</span>
              </div>
            ) : (
              <div className="grid grid-cols-1 gap-3.5 md:grid-cols-2">
                {workflows.map((w) => (
                  <div
                    className="flex flex-col gap-3.5 rounded-2xl border border-(--line) bg-(--panel) p-5 transition-[box-shadow,border-color] duration-150 hover:border-[#DDE0E6] hover:shadow-[0_8px_26px_-18px_rgba(12,15,22,0.28)] max-md:min-w-0"
                    key={w.id}
                  >
                    <div className="flex items-start gap-[13px] max-md:flex-wrap">
                      <div className="flex h-10 w-10 flex-none items-center justify-center rounded-[11px] bg-[linear-gradient(135deg,#2563EB,#9333EA)] text-white [&>svg]:h-[21px] [&>svg]:w-[21px] [&>svg]:stroke-[1.9]">
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor">
                          <path d="M13 3L4 14h7l-1 7 10-12h-7z" />
                        </svg>
                      </div>
                      <div className="min-w-0 flex-1">
                        <h3 className="m-0 font-(family-name:--disp) text-[15px] font-bold tracking-[-0.01em]">
                          {w.name}
                        </h3>
                        {w.description ? (
                          <p className="mt-1 text-[12.5px] leading-[1.5] text-(--t-2)">
                            {w.description}
                          </p>
                        ) : null}
                      </div>
                      <span
                        className={cx(
                          "inline-flex flex-none items-center gap-1.5 rounded-[999px] px-[9px] py-1 text-[10.5px] uppercase tracking-[0.04em] max-md:ml-[53px]",
                          w.is_active ? "bg-(--good-s) text-(--good)" : "bg-(--line-2) text-(--t-3)"
                        )}
                      >
                        <span
                          className={cx(
                            "h-1.5 w-1.5 rounded-[50%]",
                            w.is_active ? "bg-(--good)" : "bg-(--t-3)"
                          )}
                        />
                        {w.is_active ? "Active" : "Paused"}
                      </span>
                    </div>
                    <div className="flex items-center gap-[9px] border-t border-b border-t-(--line-2) border-b-(--line-2) py-[13px] text-[12px] text-(--t-2) max-md:flex-wrap [&>svg]:h-3.5 [&>svg]:w-3.5 [&>svg]:flex-none [&>svg]:stroke-2 [&>svg]:text-(--t-3)">
                      <span>{describeTrigger(w.trigger_config)}</span>
                    </div>
                    <div className="flex items-center gap-[9px] text-[12px] text-(--t-2) max-md:flex-wrap [&>svg]:h-3.5 [&>svg]:w-3.5 [&>svg]:flex-none [&>svg]:stroke-2 [&>svg]:text-(--t-3)">
                      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor">
                        <path d="M20 6L9 17l-5-5" />
                      </svg>
                      {describeActions(w.actions_config)}
                      <span className="ml-auto flex-none text-[11px] text-(--t-3) max-md:ml-[23px] max-md:w-full">
                        {w.last_triggered_at
                          ? formatRelativeTime(w.last_triggered_at)
                          : "never run"}
                      </span>
                    </div>
                    <div className="mt-0.5 flex gap-2 max-md:flex-wrap">
                      <button
                        type="button"
                        className="inline-flex h-[34px] flex-1 cursor-pointer items-center justify-center gap-[7px] rounded-[9px] border border-(--line) bg-(--panel) font-(family-name:--body-font) text-[12.5px] font-semibold text-(--t-1) hover:bg-(--line-2) max-md:min-w-[calc(50%-4px)] [&>svg]:h-3.5 [&>svg]:w-3.5 [&>svg]:stroke-2"
                        disabled={busyId === w.id}
                        onClick={() => void handleToggleActive(w)}
                      >
                        {w.is_active ? (
                          <>
                            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor">
                              <rect x="6" y="5" width="4" height="14" />
                              <rect x="14" y="5" width="4" height="14" />
                            </svg>
                            Pause
                          </>
                        ) : (
                          <>
                            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor">
                              <path d="M6 4l12 8-12 8V4z" />
                            </svg>
                            Activate
                          </>
                        )}
                      </button>
                      <button
                        type="button"
                        className="inline-flex h-[34px] flex-1 cursor-pointer items-center justify-center gap-[7px] rounded-[9px] border border-(--line) bg-(--panel) font-(family-name:--body-font) text-[12.5px] font-semibold text-(--t-1) hover:bg-(--line-2) max-md:min-w-[calc(50%-4px)] [&>svg]:h-3.5 [&>svg]:w-3.5 [&>svg]:stroke-2"
                        disabled={busyId === w.id}
                        onClick={() => void handleTest(w)}
                      >
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor">
                          <path d="M13 3L4 14h7l-1 7 10-12h-7z" />
                        </svg>
                        Test
                      </button>
                      <button
                        type="button"
                        className="inline-flex h-[34px] flex-1 cursor-pointer items-center justify-center gap-[7px] rounded-[9px] border border-(--line) bg-(--panel) font-(family-name:--body-font) text-[12.5px] font-semibold text-(--t-1) hover:bg-(--line-2) max-md:min-w-[calc(50%-4px)] [&>svg]:h-3.5 [&>svg]:w-3.5 [&>svg]:stroke-2"
                        disabled={busyId === w.id}
                        onClick={() => {
                          setEditing(w);
                          setModalOpen(true);
                        }}
                      >
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor">
                          <path d="M4 20h4L18.5 9.5a2.1 2.1 0 0 0-3-3L4.5 17z" />
                        </svg>
                        Edit
                      </button>
                      <button
                        type="button"
                        className={cx(
                          "inline-flex h-[34px] flex-1 cursor-pointer items-center justify-center gap-[7px] rounded-[9px] border border-(--line) bg-(--panel) font-(family-name:--body-font) text-[12.5px] font-semibold text-(--t-1) hover:bg-(--line-2) max-md:min-w-[calc(50%-4px)] [&>svg]:h-3.5 [&>svg]:w-3.5 [&>svg]:stroke-2",
                          pendingDeleteId === w.id && "border-(--bad) text-(--bad)"
                        )}
                        disabled={busyId === w.id}
                        onClick={() => void handleDeleteClick(w)}
                        onBlur={() =>
                          setPendingDeleteId((current) => (current === w.id ? null : current))
                        }
                      >
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor">
                          <path d="M3 6h18M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2m3 0-1 14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2L4 6" />
                        </svg>
                        {pendingDeleteId === w.id ? "Confirm delete?" : "Delete"}
                      </button>
                    </div>
                  </div>
                ))}

                <div
                  className="flex min-h-[200px] cursor-pointer flex-col items-center justify-center gap-2 rounded-2xl border-[1.5px] border-dashed border-(--line) bg-transparent p-5 text-center text-(--t-3) transition-[border-color,color] duration-150 hover:border-(--purple) hover:text-(--purple) [&>svg]:h-[26px] [&>svg]:w-[26px] [&>svg]:stroke-[1.8]"
                  role="button"
                  tabIndex={0}
                  onClick={() => {
                    setEditing(null);
                    setModalOpen(true);
                  }}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" || e.key === " ") {
                      setEditing(null);
                      setModalOpen(true);
                    }
                  }}
                >
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor">
                    <path d="M12 5v14M5 12h14" />
                  </svg>
                  <h3 className="m-0 font-(family-name:--disp) text-[14px] font-bold text-(--t-1)">
                    Create automation
                  </h3>
                  <p className="m-0 max-w-[220px] text-[12px] leading-[1.5]">
                    Turn a recurring follow-up into a rule that fires automatically.
                  </p>
                </div>
              </div>
            )}
          </>
        )}
      </div>

      {locked ? (
        <SignalUpgradeGate
          open={upgradeGateOpen}
          onClose={() => setUpgradeGateOpen(false)}
          title="Automate the follow-up work"
          description="Turn recommendations and score changes into real actions, emails, Slack alerts, Jira tickets and follow-up assessments, fired automatically."
          planLabel="Specialist"
          upgradeHref={UPGRADE_HREF}
          upgradeLabel="Upgrade to Specialist"
          fallbackHref={projectId ? `/dashboard/projects/${projectId}` : "/dashboard"}
          // The page behind is blurred and inert while locked, so dismissing the
          // gate would leave the user stuck on an unreadable page.
          dismissible={false}
        >
          <div>
            <b className="text-(--t-1)">Trigger on real events</b>
            <p>Assessment completions, metric thresholds and alerts can all kick off a rule.</p>
          </div>
        </SignalUpgradeGate>
      ) : null}

      <SignalAutomationModal
        open={modalOpen}
        onClose={() => setModalOpen(false)}
        projectId={projectId}
        editing={editing}
        getAuthHeaders={getAuthHeaders}
        onSaved={() => {
          toast.success(editing ? "Automation updated." : "Automation created.");
          setModalOpen(false);
          void load();
        }}
      />
    </div>
  );
}
