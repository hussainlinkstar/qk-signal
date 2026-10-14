"use client";

import React from "react";

import SelectField from "@/components/ui/SelectField";
import TextField from "@/components/ui/TextField";
import { GlassCard } from "@/components/ui/GlassComponents";
import type { WorkflowTriggerConfig } from "@/services/workflowService";

type Props = {
  value: WorkflowTriggerConfig;
  disabled?: boolean;
  onChange: (nextValue: WorkflowTriggerConfig) => void;
};

const defaultTrigger = (): WorkflowTriggerConfig => ({
  type: "platform_event",
  event_key: "audit.completed",
  event_keys: [],
});

export default function WorkflowTriggerCard({ value, disabled = false, onChange }: Props) {
  const trigger = { ...defaultTrigger(), ...value };

  return (
    <GlassCard className="border-(--line) bg-(--panel) p-5">
      <div className="flex items-center justify-between gap-3">
        <div>
          <p className="text-[10px] font-black uppercase tracking-[0.24em] text-(--purple)">
            Trigger
          </p>
          <h4 className="mt-2 text-lg font-black text-(--t-1)">When should this automation run?</h4>
        </div>
      </div>

      <div className="mt-5 grid gap-4 md:grid-cols-2">
        <SelectField
          id="workflow-trigger-type"
          label="Trigger Type"
          value={trigger.type}
          disabled={disabled}
          onChange={(event) =>
            onChange({
              type: event.target.value as WorkflowTriggerConfig["type"],
              event_key: "audit.completed",
              event_keys: [],
            })
          }
          className="bg-(--line-2) border-(--line)"
        >
          <option value="platform_event">Platform Event</option>
          <option value="audit_completed">Assessment Completed</option>
          <option value="metric_threshold">Metric Threshold</option>
          <option value="alert_triggered">Alert Triggered</option>
        </SelectField>

        {(trigger.type === "platform_event" || trigger.type === "alert_triggered") && (
          <TextField
            id="workflow-trigger-event-key"
            label="Event Key"
            value={trigger.event_key || ""}
            disabled={disabled}
            onChange={(event) =>
              onChange({
                ...trigger,
                event_key: event.target.value,
              })
            }
            className="bg-(--line-2) border-(--line)"
          />
        )}

        {trigger.type === "audit_completed" && (
          <SelectField
            id="workflow-trigger-audit-tier"
            label="Assessment Tier"
            value={trigger.audit_tier || "any"}
            disabled={disabled}
            onChange={(event) =>
              onChange({
                ...trigger,
                audit_tier: event.target.value,
              })
            }
            className="bg-(--line-2) border-(--line)"
          >
            <option value="any">Any</option>
            <option value="fast">Fast</option>
            <option value="smart">Smart</option>
            <option value="standard">Standard</option>
            <option value="deep">Deep</option>
          </SelectField>
        )}

        {(trigger.type === "metric_threshold" || trigger.type === "alert_triggered") && (
          <>
            <SelectField
              id="workflow-trigger-metric"
              label="Metric"
              value={trigger.metric || "geo_score"}
              disabled={disabled}
              onChange={(event) =>
                onChange({
                  ...trigger,
                  metric: event.target.value,
                })
              }
              className="bg-(--line-2) border-(--line)"
            >
              <option value="geo_score">AI Visibility Score</option>
              <option value="seo_score">SEO Score</option>
              <option value="aeo_score">Answer Engine Index</option>
              <option value="ai_visibility_score">AI Visibility Score</option>
              <option value="aeo_mention_drop">Off-Page Answer Engine Index</option>
              <option value="featured_snippets_lost">Featured Snippets Lost</option>
            </SelectField>
            <SelectField
              id="workflow-trigger-condition"
              label="Condition"
              value={trigger.condition || "below"}
              disabled={disabled}
              onChange={(event) =>
                onChange({
                  ...trigger,
                  condition: event.target.value as WorkflowTriggerConfig["condition"],
                })
              }
              className="bg-(--line-2) border-(--line)"
            >
              <option value="below">Below</option>
              <option value="above">Above</option>
              <option value="drops_by">Drops By</option>
            </SelectField>
            <TextField
              id="workflow-trigger-threshold"
              label="Threshold"
              type="number"
              value={String(trigger.value ?? 70)}
              disabled={disabled}
              onChange={(event) =>
                onChange({
                  ...trigger,
                  value: Number(event.target.value || 0),
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
