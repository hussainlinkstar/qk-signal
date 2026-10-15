"use client";

import React, { useCallback, useEffect, useState } from "react";
import { Check, Loader2, Users, X } from "lucide-react";
import Modal from "@/components/ui/Modal";
import Button from "@/components/ui/Button";
import CyberField from "@/components/ui/CyberField";
import SelectField from "@/components/ui/SelectField";
import { cx } from "@/components/ui/utils";
import { addWorkspaceMember, type WorkspaceSummary } from "@/services/workspaceService";

type Role = "ADMIN" | "MANAGER" | "EDITOR" | "VIEWER";
const ROLE_OPTIONS: Role[] = ["ADMIN", "MANAGER", "EDITOR", "VIEWER"];

type InviteResult = { workspaceId: number; workspaceName: string; ok: boolean; error?: string };

type Props = {
  open: boolean;
  onClose: () => void;
  /** All workspaces owned by the current user */
  ownedWorkspaces: WorkspaceSummary[];
  /** Current active workspace id, pre-checked by default */
  activeWorkspaceId: number | null;
  /** Returns a bare auth token (no workspace header) */
  getToken: () => Promise<string | null>;
};

export default function InviteToMultipleWorkspacesModal({
  open,
  onClose,
  ownedWorkspaces,
  activeWorkspaceId,
  getToken,
}: Props) {
  const [email, setEmail] = useState("");
  const [role, setRole] = useState<Role>("EDITOR");
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [isSending, setIsSending] = useState(false);
  const [results, setResults] = useState<InviteResult[] | null>(null);
  const [emailError, setEmailError] = useState<string | null>(null);

  // Reset on open
  useEffect(() => {
    if (open) {
      setEmail("");
      setRole("EDITOR");
      setSelected(new Set(activeWorkspaceId !== null ? [activeWorkspaceId] : []));
      setIsSending(false);
      setResults(null);
      setEmailError(null);
    }
  }, [open, activeWorkspaceId]);

  const toggle = (id: number) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const handleSend = useCallback(async () => {
    const trimmed = email.trim();
    if (!trimmed) {
      setEmailError("Email is required.");
      return;
    }
    if (selected.size === 0) {
      setEmailError("Select at least one workspace.");
      return;
    }
    setEmailError(null);
    setIsSending(true);

    const token = await getToken();
    const authHeader = token ? `Bearer ${token}` : "";

    const settled = await Promise.allSettled(
      [...selected].map(async (wsId) => {
        const ws = ownedWorkspaces.find((w) => w.id === wsId)!;
        await addWorkspaceMember(trimmed, role, {
          Authorization: authHeader,
          "X-Workspace-Id": String(wsId),
        });
        return ws;
      })
    );

    const inviteResults: InviteResult[] = settled.map((result, idx) => {
      const wsId = [...selected][idx];
      const ws = ownedWorkspaces.find((w) => w.id === wsId)!;
      if (result.status === "fulfilled") {
        return { workspaceId: wsId, workspaceName: ws.name, ok: true };
      }
      const err = result.reason instanceof Error ? result.reason.message : "Failed";
      return { workspaceId: wsId, workspaceName: ws.name, ok: false, error: err };
    });

    setResults(inviteResults);
    setIsSending(false);
  }, [email, role, selected, ownedWorkspaces, getToken]);

  const allSucceeded = results?.every((r) => r.ok);

  return (
    <Modal open={open} onClose={onClose} panelClassName="w-full max-w-lg">
      {/* Header */}
      <div className="flex items-start justify-between gap-4">
        <div className="flex items-center gap-3">
          <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-[14px] border-0 bg-[#EEF1F6]">
            <Users className="h-5 w-5 text-(--muted-foreground)" />
          </div>
          <div>
            <h2 className="text-base font-semibold text-(--t-1)">Invite to Multiple Workspaces</h2>
            <p className="text-xs text-(--text-secondary)">
              Owner-only, sends one invite per workspace
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

      {results ? (
        /* Results view */
        <div className="mt-6 space-y-3">
          <p className="text-sm font-medium text-(--t-1)">
            {allSucceeded ? "All invitations sent successfully." : "Some invitations failed."}
          </p>
          <div className="space-y-2">
            {results.map((r) => (
              <div
                key={r.workspaceId}
                className={cx(
                  "flex items-center justify-between rounded-[14px] border-0 px-4 py-3 text-sm",
                  r.ok
                    ? "bg-emerald-500/10 text-emerald-700"
                    : "bg-rose-500/10 text-rose-700"
                )}
              >
                <span className="font-medium">{r.workspaceName}</span>
                <span className="text-xs">{r.ok ? "Invited" : r.error}</span>
              </div>
            ))}
          </div>
          <div className="flex justify-end pt-2">
            <Button variant="ghost" size="md" onClick={onClose}>
              Done
            </Button>
          </div>
        </div>
      ) : (
        /* Form view */
        <div className="mt-6 space-y-5">
          <div className="grid gap-4 sm:grid-cols-[minmax(0,1fr)_160px]">
            <CyberField
              id="multi-invite-email"
              label="Email"
              placeholder="colleague@company.com"
              value={email}
              onChange={(e) => {
                setEmail(e.target.value);
                setEmailError(null);
              }}
              onKeyDown={(e) => {
                if (e.key === "Enter") void handleSend();
              }}
            />
            <SelectField
              label="Role"
              value={role}
              onChange={(e) => setRole(e.target.value as Role)}
            >
              {ROLE_OPTIONS.map((r) => (
                <option key={r} value={r}>
                  {r.charAt(0) + r.slice(1).toLowerCase()}
                </option>
              ))}
            </SelectField>
          </div>

          {emailError ? <p className="text-xs text-rose-400">{emailError}</p> : null}

          {/* Workspace checkboxes */}
          <div className="space-y-2">
            <p className="text-[10px] font-semibold uppercase tracking-[0.18em] text-(--text-secondary)">
              Workspaces
            </p>
            <div className="max-h-52 space-y-2 overflow-y-auto">
              {ownedWorkspaces.map((ws) => {
                const checked = selected.has(ws.id);
                const isActive = ws.id === activeWorkspaceId;
                return (
                  <label
                    key={ws.id}
                    className={cx(
                      "flex cursor-pointer items-center justify-between rounded-[14px] border-0 px-4 py-3 transition-colors",
                      checked
                        ? "bg-[#E8F1FF]"
                        : "bg-[#EEF1F6] hover:bg-[#E8EBF2]"
                    )}
                  >
                    <div className="flex items-center gap-3">
                      <div
                        className={cx(
                          "flex h-4 w-4 shrink-0 items-center justify-center rounded-[4px] border-0 transition-colors",
                          checked ? "bg-[#1D4ED8]" : "bg-white"
                        )}
                      >
                        {checked ? (
                          <Check className="h-2.5 w-2.5 text-white" strokeWidth={3} />
                        ) : null}
                      </div>
                      <input
                        type="checkbox"
                        className="sr-only"
                        checked={checked}
                        onChange={() => toggle(ws.id)}
                      />
                      <span className="text-sm font-medium text-(--t-1)">{ws.name}</span>
                      {isActive ? (
                        <span className="rounded-full border-0 bg-[#E8F1FF] px-1.5 py-0.5 text-[9px] font-bold uppercase tracking-wider text-[#1D4ED8]">
                          Current
                        </span>
                      ) : null}
                    </div>
                    <span className="text-xs text-(--text-secondary)">
                      {ws.project_count} {ws.project_count === 1 ? "project" : "projects"}
                    </span>
                  </label>
                );
              })}
            </div>
          </div>

          <div className="flex items-center justify-between gap-4 pt-1">
            <p className="text-xs text-(--text-secondary)">
              {selected.size} workspace{selected.size !== 1 ? "s" : ""} selected
            </p>
            <div className="flex gap-3">
              <Button variant="ghost" size="md" onClick={onClose} disabled={isSending}>
                Cancel
              </Button>
              <Button
                variant="primary"
                size="md"
                onClick={() => void handleSend()}
                disabled={selected.size === 0 || !email.trim()}
                loading={isSending}
              >
                {isSending ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <Users className="h-4 w-4" />
                )}
                Send Invitation{selected.size > 1 ? `s (${selected.size})` : ""}
              </Button>
            </div>
          </div>
        </div>
      )}
    </Modal>
  );
}
