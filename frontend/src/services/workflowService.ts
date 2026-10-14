import { requestJson, requestVoid } from "@/services/http";

export type WorkflowTriggerType =
  | "platform_event"
  | "audit_completed"
  | "metric_threshold"
  | "alert_triggered";

export type WorkflowActionType =
  | "send_email"
  | "send_slack"
  | "send_teams"
  | "webhook"
  | "run_audit"
  | "create_jira_ticket";

export type WorkflowTriggerConfig = {
  type: WorkflowTriggerType;
  event_key?: string | null;
  event_keys?: string[];
  metric?: string | null;
  condition?: "below" | "above" | "drops_by" | null;
  value?: number | null;
  audit_tier?: string | null;
};

export type WorkflowActionConfig = {
  type: WorkflowActionType;
  config: Record<string, unknown>;
};

export type WorkflowItem = {
  id: number;
  workspace_id: number;
  project_id: number | null;
  name: string;
  description: string | null;
  trigger_config: WorkflowTriggerConfig;
  actions_config: WorkflowActionConfig[];
  cooldown_minutes: number;
  is_active: boolean;
  last_triggered_at: string | null;
  created_at: string | null;
  updated_at: string | null;
};

export type WorkflowRun = {
  id: number;
  workflow_id: number;
  triggered_at: string | null;
  trigger_event: string;
  trigger_context: Record<string, unknown>;
  status: string;
  action_results: Array<Record<string, unknown>>;
  completed_at: string | null;
};

export type WorkflowUpsertPayload = {
  name: string;
  description?: string | null;
  trigger_config: WorkflowTriggerConfig;
  actions_config: WorkflowActionConfig[];
  cooldown_minutes: number;
  is_active: boolean;
};

export async function fetchProjectWorkflows(
  projectId: string | number,
  headers: HeadersInit = {}
): Promise<WorkflowItem[]> {
  return requestJson<WorkflowItem[]>({
    endpoint: `/api/projects/${projectId}/workflows`,
    method: "GET",
    headers,
    errorMessage: "Unable to load project automations.",
  });
}

export async function createProjectWorkflow(
  projectId: string | number,
  payload: WorkflowUpsertPayload,
  headers: HeadersInit = {}
): Promise<WorkflowItem> {
  return requestJson<WorkflowItem>({
    endpoint: `/api/projects/${projectId}/workflows`,
    method: "POST",
    headers,
    body: payload,
    errorMessage: "Unable to create the workflow.",
  });
}

export async function updateProjectWorkflow(
  projectId: string | number,
  workflowId: number,
  payload: Partial<WorkflowUpsertPayload>,
  headers: HeadersInit = {}
): Promise<WorkflowItem> {
  return requestJson<WorkflowItem>({
    endpoint: `/api/projects/${projectId}/workflows/${workflowId}`,
    method: "PUT",
    headers,
    body: payload,
    errorMessage: "Unable to update the workflow.",
  });
}

export async function deleteProjectWorkflow(
  projectId: string | number,
  workflowId: number,
  headers: HeadersInit = {}
): Promise<void> {
  return requestVoid({
    endpoint: `/api/projects/${projectId}/workflows/${workflowId}`,
    method: "DELETE",
    headers,
    errorMessage: "Unable to delete the workflow.",
  });
}

export async function testProjectWorkflow(
  projectId: string | number,
  workflowId: number,
  payload: { context?: Record<string, unknown> } = {},
  headers: HeadersInit = {}
): Promise<{ run: WorkflowRun }> {
  return requestJson<{ run: WorkflowRun }>({
    endpoint: `/api/projects/${projectId}/workflows/${workflowId}/test`,
    method: "POST",
    headers,
    body: payload,
    errorMessage: "Unable to run the workflow test.",
  });
}

export async function fetchProjectWorkflowRuns(
  projectId: string | number,
  workflowId: number,
  headers: HeadersInit = {}
): Promise<WorkflowRun[]> {
  return requestJson<WorkflowRun[]>({
    endpoint: `/api/projects/${projectId}/workflows/${workflowId}/runs`,
    method: "GET",
    headers,
    errorMessage: "Unable to load workflow runs.",
  });
}
