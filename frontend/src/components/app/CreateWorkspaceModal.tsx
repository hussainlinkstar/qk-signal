"use client";

import { asset } from "@/lib/basePath";
import React, { useCallback, useEffect, useState } from "react";
import { Building2, ExternalLink, Plus, X, Zap } from "lucide-react";
import Modal from "@/components/ui/Modal";
import Button from "@/components/ui/Button";
import CyberField from "@/components/ui/CyberField";
import { createWorkspace } from "@/services/workspaceService";
import { setActiveWorkspaceId } from "@/components/app/WorkspaceSwitcher";

// ---------------------------------------------------------------------------
// Create workspace modal
// ---------------------------------------------------------------------------

type CreateWorkspaceModalProps = {
  open: boolean;
  onClose: () => void;
  /** Auth headers (Authorization + X-Workspace-Id) */
  getAuthHeaders: () => Promise<HeadersInit>;
};

export function CreateWorkspaceModal({ open, onClose, getAuthHeaders }: CreateWorkspaceModalProps) {
  const [name, setName] = useState("");
  const [isCreating, setIsCreating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Reset state when modal opens
  useEffect(() => {
    if (open) {
      setName("");
      setError(null);
      setIsCreating(false);
    }
  }, [open]);

  const handleCreate = useCallback(async () => {
    const trimmed = name.trim();
    if (!trimmed) {
      setError("Workspace name is required.");
      return;
    }
    setIsCreating(true);
    setError(null);
    try {
      const headers = await getAuthHeaders();
      const workspace = await createWorkspace(trimmed, headers);
      setActiveWorkspaceId(workspace.id);
      window.location.reload();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to create workspace.");
      setIsCreating(false);
    }
  }, [name, getAuthHeaders]);

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter") void handleCreate();
  };

  return (
    <Modal open={open} onClose={onClose} panelClassName="w-full max-w-md">
      <div className="flex items-start justify-between gap-4">
        <div className="flex items-center gap-3">
          <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl border border-(--line) bg-(--line-2)">
            <Building2 className="h-5 w-5 text-(--muted-foreground)" />
          </div>
          <div>
            <h2 className="text-base font-semibold text-(--t-1)">Create Workspace</h2>
            <p className="text-xs text-(--text-secondary)">
              New isolated workspace under your account
            </p>
          </div>
        </div>
        <button
          type="button"
          onClick={onClose}
          className="rounded-md p-1 text-(--text-secondary) transition-colors hover:text-(--t-1) focus:outline-hidden"
          aria-label="Close"
        >
          <X className="h-4 w-4" />
        </button>
      </div>

      <div className="mt-6 space-y-4">
        <CyberField
          autoFocus
          id="new-workspace-name"
          label="Workspace Name"
          placeholder="e.g. ACME Corp, EU"
          value={name}
          onChange={(e) => {
            setName(e.target.value);
            setError(null);
          }}
          onKeyDown={handleKeyDown}
        />

        {error ? <p className="text-xs text-rose-400">{error}</p> : null}
      </div>

      <div className="mt-6 flex justify-end gap-3">
        <Button variant="ghost" size="md" onClick={onClose} disabled={isCreating}>
          Cancel
        </Button>
        <Button
          variant="primary"
          size="md"
          onClick={() => void handleCreate()}
          loading={isCreating}
          disabled={!name.trim()}
        >
          <Plus className="h-4 w-4" />
          Create Workspace
        </Button>
      </div>
    </Modal>
  );
}

// ---------------------------------------------------------------------------
// Upgrade prompt modal (plans without multi-workspace federation)
// ---------------------------------------------------------------------------

type UpgradeWorkspaceModalProps = {
  open: boolean;
  onClose: () => void;
};

export function UpgradeToMultiWorkspaceModal({ open, onClose }: UpgradeWorkspaceModalProps) {
  return (
    <Modal open={open} onClose={onClose} panelClassName="w-full max-w-md">
      <div className="flex items-start justify-between gap-4">
        <div className="flex items-center gap-3">
          <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl border border-amber-500/30 bg-amber-500/10">
            <Zap className="h-5 w-5 text-amber-400" />
          </div>
          <div>
            <h2 className="text-base font-semibold text-(--t-1)">Multiple workspaces</h2>
            <p className="text-xs text-(--text-secondary)">Not included in your plan</p>
          </div>
        </div>
        <button
          type="button"
          onClick={onClose}
          className="rounded-md p-1 text-(--text-secondary) transition-colors hover:text-(--t-1) focus:outline-hidden"
          aria-label="Close"
        >
          <X className="h-4 w-4" />
        </button>
      </div>

      <div className="mt-5 space-y-3">
        <p className="text-sm leading-7 text-(--t-2)">
          Multiple workspaces is available on the Executive plan. Each workspace is fully isolated,
          separate projects, team members, and billing.
        </p>

        <div className="rounded-xl border border-(--line) bg-(--line-2) p-4 space-y-2">
          {[
            "Unlimited workspaces under one account",
            "Isolated projects, audits & members per workspace",
            "Centralised billing across every workspace",
          ].map((item) => (
            <div key={item} className="flex items-center gap-2.5 text-sm text-(--t-2)">
              <div className="h-1.5 w-1.5 shrink-0 rounded-full bg-amber-400" />
              {item}
            </div>
          ))}
        </div>
      </div>

      <div className="mt-6 flex justify-end gap-3">
        <Button variant="ghost" size="md" onClick={onClose}>
          Maybe Later
        </Button>
        <Button
          variant="primary"
          size="md"
          onClick={() => {
            window.location.href = asset("/dashboard/billing");
          }}
        >
          <ExternalLink className="h-4 w-4" />
          View Plans
        </Button>
      </div>
    </Modal>
  );
}
