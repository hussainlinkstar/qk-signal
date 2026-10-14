"use client";

import { useState, useEffect, useCallback, useMemo } from "react";
import { useAuth } from "@/components/auth/custom-auth";
import { resolvePlanCapabilities } from "@/lib/planCapabilities";

export type JiraProject = {
  key: string;
  name: string;
  id: string;
};

export type JiraConnectionStatus = {
  is_connected: boolean;
  cloud_id?: string;
  site_name?: string;
  site_url?: string;
  default_project?: string;
  projects: JiraProject[];
};

export type JiraExportResponse = {
  issue_id: string;
  issue_key: string;
  issue_url: string;
};

export function useJira() {
  const { user, getToken } = useAuth();
  const [status, setStatus] = useState<JiraConnectionStatus | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const canExportToJira = useMemo(() => {
    return resolvePlanCapabilities(user?.subscription_plan).can_export_to_jira;
  }, [user]);

  const fetchStatus = useCallback(async () => {
    if (!canExportToJira) return;

    setLoading(true);
    try {
      const token = await getToken();
      const res = await fetch("/api/v1/integrations/jira/status", {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (res.ok) {
        const data = await res.json();
        setStatus(data);
      } else {
        const errData = await res.json().catch(() => ({}));
        setError(errData.detail || "Failed to fetch Jira status");
      }
    } catch (e) {
      console.error("Jira status check failed", e);
      setError("Connection error while fetching Jira status");
    } finally {
      setLoading(false);
    }
  }, [canExportToJira, getToken]);

  useEffect(() => {
    fetchStatus();
  }, [fetchStatus]);

  const exportIssue = useCallback(
    async (
      projectKey: string,
      summary: string,
      description: string,
      issueType: string = "Task"
    ): Promise<JiraExportResponse> => {
      const token = await getToken();
      const res = await fetch("/api/v1/integrations/jira/export", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({
          project_key: projectKey,
          summary,
          description,
          issue_type: issueType,
        }),
      });

      if (!res.ok) {
        const errData = await res.json().catch(() => ({}));
        throw new Error(errData.detail || "Failed to export to Jira");
      }

      return await res.json();
    },
    [getToken]
  );

  const exportProjectIssue = useCallback(
    async (
      projectId: string | number,
      summary: string,
      description: string,
      issueType: string = "Task",
      projectKey?: string
    ): Promise<JiraExportResponse> => {
      const token = await getToken();
      const res = await fetch(`/api/v1/projects/${projectId}/export/jira`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({
          recommendation_title: summary,
          generated_guide_markdown: description,
          issue_type: issueType,
          project_key: projectKey,
        }),
      });

      if (!res.ok) {
        const errData = await res.json().catch(() => ({}));
        throw new Error(errData.detail || "Failed to export to Jira");
      }

      return await res.json();
    },
    [getToken]
  );

  const initializeProject = useCallback(
    async (projectId: number): Promise<JiraProject> => {
      const token = await getToken();
      const res = await fetch("/api/v1/integrations/jira/initialize", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({ project_id: projectId }),
      });

      if (!res.ok) {
        const errData = await res.json().catch(() => ({}));
        throw new Error(errData.detail || "Failed to initialize Jira project");
      }

      const newProject = await res.json();
      await fetchStatus();
      return newProject;
    },
    [getToken, fetchStatus]
  );

  return {
    status,
    loading,
    error,
    canExportToJira,
    refreshStatus: fetchStatus,
    exportIssue,
    exportProjectIssue,
    initializeProject,
  };
}
