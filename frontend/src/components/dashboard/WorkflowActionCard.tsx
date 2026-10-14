"use client";

import React from "react";
import { Trash2 } from "lucide-react";

import Button from "@/components/ui/Button";
import SelectField from "@/components/ui/SelectField";
import TextField from "@/components/ui/TextField";
import { GlassCard } from "@/components/ui/GlassComponents";
import type { WorkflowActionConfig, WorkflowActionType } from "@/services/workflowService";

type Props = {
  index: number;
  value: WorkflowActionConfig;
  disabled?: boolean;
  onChange: (nextValue: WorkflowActionConfig) => void;
  onRemove: () => void;
};

function defaultConfig(type: WorkflowActionType): Record<string, unknown> {
  if (type === "send_email") {
    return { to: "", template_key: "alert.triggered" };
  }
  if (type === "send_slack") {
    return { channel_id: "" };
  }
  if (type === "send_teams") {
    return {};
  }
  if (type === "run_audit") {
    return { tier: "fast", category: "" };
  }
  if (type === "create_jira_ticket") {
    return {
      project_key: "",
      issue_type: "Task",
      summary: "[{project_name}] {event_key}",
      description: "Workflow event {event_key} triggered.\n\nMessage: {message}",
    };
  }
  return { url: "", method: "POST" };
}

export default function WorkflowActionCard({
  index,
  value,
  disabled = false,
  onChange,
  onRemove,
}: Props) {
  const action = {
    ...value,
    config: value.config || {},
  };

  return (
    <GlassCard className="border-(--line) bg-(--panel) p-5">
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="text-[10px] font-black uppercase tracking-[0.24em] text-indigo-300">
            Action {index + 1}
          </p>
          <h4 className="mt-2 text-lg font-black text-(--t-1)">Then do this next</h4>
        </div>
        <Button
          variant="ghost"
          size="sm"
          disabled={disabled}
          onClick={onRemove}
          className="rounded-xl border border-rose-500/20 bg-rose-500/10 text-rose-200 hover:bg-rose-500/20"
        >
          <Trash2 className="h-4 w-4" />
        </Button>
      </div>

      <div className="mt-5 grid gap-4 md:grid-cols-2">
        <SelectField
          id={`workflow-action-type-${index}`}
          label="Action Type"
          value={action.type}
          disabled={disabled}
          onChange={(event) => {
            const nextType = event.target.value as WorkflowActionType;
            onChange({
              type: nextType,
              config: defaultConfig(nextType),
            });
          }}
          className="bg-(--line-2) border-(--line)"
        >
          <option value="send_email">Send Email</option>
          <option value="send_slack">Send Slack Message</option>
          <option value="send_teams">Send Teams Message</option>
          <option value="webhook">Webhook</option>
          <option value="run_audit">Run Assessment</option>
          <option value="create_jira_ticket">Create Jira Ticket</option>
        </SelectField>

        {action.type === "send_email" && (
          <>
            <TextField
              id={`workflow-action-email-${index}`}
              label="Recipient Email"
              value={String(action.config.to || "")}
              disabled={disabled}
              onChange={(event) =>
                onChange({
                  ...action,
                  config: { ...action.config, to: event.target.value },
                })
              }
              className="bg-(--line-2) border-(--line)"
            />
            <TextField
              id={`workflow-action-template-${index}`}
              label="Template Key"
              value={String(action.config.template_key || "")}
              disabled={disabled}
              onChange={(event) =>
                onChange({
                  ...action,
                  config: { ...action.config, template_key: event.target.value },
                })
              }
              className="bg-(--line-2) border-(--line)"
            />
          </>
        )}

        {action.type === "send_slack" && (
          <TextField
            id={`workflow-action-slack-channel-${index}`}
            label="Slack Channel ID"
            value={String(action.config.channel_id || "")}
            disabled={disabled}
            onChange={(event) =>
              onChange({
                ...action,
                config: { ...action.config, channel_id: event.target.value },
              })
            }
            className="bg-(--line-2) border-(--line)"
          />
        )}

        {action.type === "webhook" && (
          <>
            <TextField
              id={`workflow-action-webhook-url-${index}`}
              label="Webhook URL"
              value={String(action.config.url || "")}
              disabled={disabled}
              onChange={(event) =>
                onChange({
                  ...action,
                  config: { ...action.config, url: event.target.value },
                })
              }
              className="bg-(--line-2) border-(--line)"
            />
            <SelectField
              id={`workflow-action-webhook-method-${index}`}
              label="Method"
              value={String(action.config.method || "POST")}
              disabled={disabled}
              onChange={(event) =>
                onChange({
                  ...action,
                  config: { ...action.config, method: event.target.value },
                })
              }
              className="bg-(--line-2) border-(--line)"
            >
              <option value="POST">POST</option>
              <option value="PUT">PUT</option>
              <option value="PATCH">PATCH</option>
            </SelectField>
          </>
        )}

        {action.type === "run_audit" && (
          <>
            <SelectField
              id={`workflow-action-run-audit-tier-${index}`}
              label="Assessment Tier"
              value={String(action.config.tier || "fast")}
              disabled={disabled}
              onChange={(event) =>
                onChange({
                  ...action,
                  config: { ...action.config, tier: event.target.value },
                })
              }
              className="bg-(--line-2) border-(--line)"
            >
              <option value="fast">Fast</option>
              <option value="deep">Deep</option>
            </SelectField>
            <TextField
              id={`workflow-action-run-audit-category-${index}`}
              label="Category (optional)"
              value={String(action.config.category || "")}
              disabled={disabled}
              onChange={(event) =>
                onChange({
                  ...action,
                  config: { ...action.config, category: event.target.value },
                })
              }
              className="bg-(--line-2) border-(--line)"
            />
          </>
        )}

        {action.type === "create_jira_ticket" && (
          <>
            <TextField
              id={`workflow-action-jira-project-${index}`}
              label="Jira Project Key"
              value={String(action.config.project_key || "")}
              disabled={disabled}
              onChange={(event) =>
                onChange({
                  ...action,
                  config: { ...action.config, project_key: event.target.value },
                })
              }
              className="bg-(--line-2) border-(--line)"
            />
            <TextField
              id={`workflow-action-jira-type-${index}`}
              label="Issue Type"
              value={String(action.config.issue_type || "Task")}
              disabled={disabled}
              onChange={(event) =>
                onChange({
                  ...action,
                  config: { ...action.config, issue_type: event.target.value },
                })
              }
              className="bg-(--line-2) border-(--line)"
            />
            <TextField
              id={`workflow-action-jira-summary-${index}`}
              label="Summary Template"
              value={String(action.config.summary || "")}
              disabled={disabled}
              onChange={(event) =>
                onChange({
                  ...action,
                  config: { ...action.config, summary: event.target.value },
                })
              }
              className="bg-(--line-2) border-(--line)"
            />
            <TextField
              id={`workflow-action-jira-description-${index}`}
              label="Description Template"
              value={String(action.config.description || "")}
              disabled={disabled}
              onChange={(event) =>
                onChange({
                  ...action,
                  config: { ...action.config, description: event.target.value },
                })
              }
              className="bg-(--line-2) border-(--line)"
            />
          </>
        )}
      </div>
    </GlassCard>
  );
}
