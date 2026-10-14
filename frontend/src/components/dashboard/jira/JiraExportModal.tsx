"use client";

import React, { useState, useEffect } from "react";
import { ExternalLink, Check, Loader2, AlertCircle, Briefcase, Zap } from "lucide-react";
import Modal from "@/components/ui/Modal";
import Button from "@/components/ui/Button";
import SelectField from "@/components/ui/SelectField";
import { useJira, JiraExportResponse } from "@/hooks/useJira";

type JiraExportModalProps = {
  open: boolean;
  onClose: () => void;
  projectId: string | number | null | undefined;
  defaultSummary: string;
  defaultDescription: string;
  issueType?: string;
  onExportSuccess?: (result: JiraExportResponse) => void;
};

export default function JiraExportModal({
  open,
  onClose,
  projectId,
  defaultSummary,
  defaultDescription,
  issueType = "Task",
  onExportSuccess,
}: JiraExportModalProps) {
  const {
    status,
    loading: statusLoading,
    exportIssue,
    canExportToJira,
    initializeProject,
  } = useJira();
  const [selectedProject, setSelectedProject] = useState("");
  const [isExporting, setIsExporting] = useState(false);
  const [isInitializing, setIsInitializing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<JiraExportResponse | null>(null);

  // Set default project when status loads
  useEffect(() => {
    if (status?.projects?.length && !selectedProject) {
      const defaultKey = status.default_project || status.projects[0].key;
      setSelectedProject(defaultKey);
    }
  }, [status, selectedProject]);

  const handleExport = async () => {
    if (!selectedProject) {
      setError("Please select a target project.");
      return;
    }

    setIsExporting(true);
    setError(null);
    try {
      const res = await exportIssue(selectedProject, defaultSummary, defaultDescription, issueType);
      setResult(res);
      onExportSuccess?.(res);
    } catch (e: any) {
      setError(e.message || "Failed to create Jira issue.");
    } finally {
      setIsExporting(false);
    }
  };

  const handleInitialize = async () => {
    if (projectId === null || projectId === undefined || projectId === "") {
      setError("Project ID is missing. Please ensure this assessment is linked to a project.");
      return;
    }

    setIsInitializing(true);
    setError(null);
    try {
      const numId = typeof projectId === "number" ? projectId : parseInt(projectId as string);
      if (isNaN(numId)) {
        throw new Error(`Invalid project ID format: ${projectId}`);
      }
      const newProj = await initializeProject(numId);
      setSelectedProject(newProj.key);
    } catch (e: any) {
      setError(e.message || "Failed to initialize Jira project.");
    } finally {
      setIsInitializing(false);
    }
  };

  const handleClose = () => {
    setResult(null);
    setError(null);
    onClose();
  };

  if (!canExportToJira) return null;

  return (
    <Modal
      open={open}
      onClose={handleClose}
      panelClassName="w-full max-w-lg border border-(--border) bg-(--card) p-0"
    >
      <div className="relative overflow-hidden p-8">
        <div className="relative z-10">
          <div className="flex items-center gap-3 mb-6">
            <div className="flex h-10 w-10 items-center justify-center rounded border border-thoth-logic/30 bg-thoth-logic/10 text-thoth-logic">
              <Zap size={20} />
            </div>
            <div>
              <h2 className="text-xl font-semibold text-(--t-1) uppercase tracking-tight">
                prompt<span className="text-thoth-logic">.AI</span>
              </h2>
              <p className="mt-1 text-[10px] font-medium uppercase tracking-wider leading-none text-(--t-3)">
                Direct Prompt-to-Jira Sync
              </p>
            </div>
          </div>

          {!result ? (
            <div className="space-y-6">
              <div className="space-y-2 rounded border border-(--border) bg-(--background) p-4">
                <p className="text-[10px] font-medium uppercase tracking-wider text-(--t-3)">
                  Task Definition
                </p>
                <p className="line-clamp-2 text-sm font-medium text-(--t-1)">{defaultSummary}</p>
              </div>

              {statusLoading ? (
                <div className="flex flex-col items-center justify-center py-8 gap-3">
                  <Loader2 className="h-6 w-6 text-(--purple) animate-spin" />
                  <p className="text-[10px] font-black text-(--t-3) uppercase tracking-widest">
                    Loading Jira projects...
                  </p>
                </div>
              ) : status?.projects?.length ? (
                <div className="space-y-4">
                  <SelectField
                    label="Target Jira Project"
                    value={selectedProject}
                    onChange={(e) => setSelectedProject(e.target.value)}
                  >
                    {status.projects.map((p) => (
                      <option key={p.key} value={p.key}>
                        {p.name} ({p.key})
                      </option>
                    ))}
                  </SelectField>

                  {error && (
                    <div className="flex items-start gap-2 p-3 rounded-lg border border-rose-500/20 bg-rose-500/10 text-rose-400 text-xs font-bold">
                      <AlertCircle className="h-4 w-4 shrink-0" />
                      {error}
                    </div>
                  )}

                  <div className="pt-2 flex gap-3">
                    <Button
                      variant="outline"
                      className="h-12 flex-1"
                      onClick={handleExport}
                      disabled={isExporting}
                    >
                      {isExporting ? (
                        <>
                          <Loader2 className="h-4 w-4 mr-2 animate-spin" /> Creating Ticket...
                        </>
                      ) : (
                        "Confirm & Deploy"
                      )}
                    </Button>
                    <Button variant="ghost" className="h-12 px-6" onClick={handleClose}>
                      Cancel
                    </Button>
                  </div>
                </div>
              ) : (
                <div className="py-8 text-center space-y-6">
                  <div className="flex flex-col items-center gap-3">
                    <div className="flex h-12 w-12 items-center justify-center rounded border border-thoth-logic/20 bg-thoth-logic/10 text-thoth-logic">
                      <Briefcase size={24} />
                    </div>
                    <p className="text-sm font-medium text-(--t-2)">
                      No Jira projects found in your workspace.
                    </p>
                  </div>

                  <div className="flex flex-col gap-3">
                    <Button
                      variant="outline"
                      className="h-12"
                      onClick={handleInitialize}
                      disabled={isInitializing}
                    >
                      {isInitializing ? (
                        <>
                          <Loader2 className="h-4 w-4 mr-2 animate-spin" /> Initializing...
                        </>
                      ) : (
                        "Initialize Qiko Signal Project"
                      )}
                    </Button>

                    <div className="flex items-center gap-2">
                      <div className="h-px flex-1 bg-(--line-2)" />
                      <span className="text-[9px] font-black text-(--t-3) uppercase tracking-widest">
                        or
                      </span>
                      <div className="h-px flex-1 bg-(--line-2)" />
                    </div>

                    <Button
                      variant="inverse"
                      className="h-12 px-6"
                      onClick={() => window.open("/dashboard/connections", "_blank")}
                    >
                      Check Connection
                    </Button>
                  </div>

                  {error && (
                    <div className="flex items-start gap-2 p-3 rounded-lg border border-rose-500/20 bg-rose-500/10 text-rose-400 text-xs font-bold text-left">
                      <AlertCircle className="h-4 w-4 shrink-0" />
                      {error}
                    </div>
                  )}
                </div>
              )}
            </div>
          ) : (
            <div className="py-8 space-y-8 animate-in zoom-in-95 duration-300">
              <div className="flex flex-col items-center text-center gap-4">
                <div className="flex h-16 w-16 items-center justify-center rounded border border-emerald-500/20 bg-emerald-500/10 text-emerald-400">
                  <Check size={32} />
                </div>
                <div>
                  <p className="text-lg font-semibold text-(--t-1) uppercase tracking-tight">
                    Sync Successful
                  </p>
                  <p className="mt-1 text-xs font-medium text-(--t-2)">
                    Ticket created in project{" "}
                    <span className="text-(--t-1)">{selectedProject}</span>
                  </p>
                </div>
              </div>

              <div className="group flex items-center justify-between rounded border border-(--border) bg-(--background) p-5">
                <div>
                  <p className="mb-1 text-[10px] font-medium uppercase tracking-wider leading-none text-(--t-3)">
                    Jira Resource Identifier
                  </p>
                  <p className="text-xl font-semibold uppercase tracking-tight text-thoth-logic">
                    {result.issue_key}
                  </p>
                </div>
                <a
                  href={result.issue_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="flex h-12 w-12 items-center justify-center rounded border border-thoth-logic/20 bg-thoth-logic/10 text-thoth-logic transition-colors hover:bg-thoth-logic/20"
                >
                  <ExternalLink size={20} />
                </a>
              </div>

              <Button variant="ghost" className="h-12 w-full" onClick={handleClose}>
                Done
              </Button>
            </div>
          )}
        </div>
      </div>
    </Modal>
  );
}
