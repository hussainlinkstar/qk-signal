"use client";

import { useEffect, useMemo, useState } from "react";

export type JiraTrackedExport = {
  issueKey: string;
  issueUrl: string;
  exportedAt: string;
};

type JiraTrackedExportMap = Record<string, JiraTrackedExport>;

const buildStorageKey = (projectId: string | number | null | undefined) =>
  `jira-export-tracker:${String(projectId ?? "unknown")}`;

export function useJiraExportTracker(projectId: string | number | null | undefined) {
  const storageKey = useMemo(() => buildStorageKey(projectId), [projectId]);
  const [trackedExports, setTrackedExports] = useState<JiraTrackedExportMap>({});

  useEffect(() => {
    if (typeof window === "undefined") {
      return;
    }
    try {
      const raw = window.localStorage.getItem(storageKey);
      setTrackedExports(raw ? (JSON.parse(raw) as JiraTrackedExportMap) : {});
    } catch {
      setTrackedExports({});
    }
  }, [storageKey]);

  const markExported = (trackingKey: string, exportInfo: JiraTrackedExport) => {
    setTrackedExports((current) => {
      const next = { ...current, [trackingKey]: exportInfo };
      if (typeof window !== "undefined") {
        window.localStorage.setItem(storageKey, JSON.stringify(next));
      }
      return next;
    });
  };

  const getTrackedExport = (trackingKey: string) => trackedExports[trackingKey] ?? null;

  return {
    trackedExports,
    markExported,
    getTrackedExport,
  };
}
