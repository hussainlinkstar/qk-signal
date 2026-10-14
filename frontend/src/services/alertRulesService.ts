import { requestJson, requestVoid } from "@/services/http";

export interface AlertLogResponse {
  id: number;
  rule_id: number;
  triggered_at: string;
  metric_value: number;
  message: string;
}

export interface AlertRuleResponse {
  id: number;
  project_id: number;
  metric: string;
  condition: string;
  threshold: number;
  email_to: string;
  is_active: boolean;
  last_triggered_at: string | null;
  created_at: string;
  recent_logs: AlertLogResponse[];
}

export interface AlertRuleCreate {
  metric: string;
  condition: string;
  threshold: number;
  email_to: string;
  is_active: boolean;
}

export interface AlertRuleUpdate {
  metric?: string;
  condition?: string;
  threshold?: number;
  email_to?: string;
  is_active?: boolean;
}

export async function fetchAlertRules(projectId: number | string): Promise<AlertRuleResponse[]> {
  return requestJson<AlertRuleResponse[]>({
    endpoint: `/api/v1/projects/${projectId}/alerts`,
    method: "GET",
    errorMessage: "Failed to load alert rules.",
  });
}

export async function createAlertRule(
  projectId: number | string,
  payload: AlertRuleCreate
): Promise<AlertRuleResponse> {
  return requestJson<AlertRuleResponse>({
    endpoint: `/api/v1/projects/${projectId}/alerts`,
    method: "POST",
    body: payload,
    errorMessage: "Failed to create alert rule.",
  });
}

export async function updateAlertRule(
  projectId: number | string,
  ruleId: number,
  payload: AlertRuleUpdate
): Promise<AlertRuleResponse> {
  return requestJson<AlertRuleResponse>({
    endpoint: `/api/v1/projects/${projectId}/alerts/${ruleId}`,
    method: "PUT",
    body: payload,
    errorMessage: "Failed to update alert rule.",
  });
}

export async function deleteAlertRule(projectId: number | string, ruleId: number): Promise<void> {
  return requestVoid({
    endpoint: `/api/v1/projects/${projectId}/alerts/${ruleId}`,
    method: "DELETE",
    errorMessage: "Failed to delete alert rule.",
  });
}
