"use client";

import React, { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { Building2, FolderOpen, Users, Calendar } from "lucide-react";
import { toast } from "sonner";
import { useAuth } from "@/contexts/AuthContext";
import { requestJson } from "@/services/http";
import {
  workspaceHeaders,
  getActiveWorkspaceId,
  setActiveWorkspaceId,
} from "@/components/app/WorkspaceSwitcher";
import Button from "@/components/ui/Button";
import Card from "@/components/ui/Card";
import Badge from "@/components/ui/Badge";
import EmptyState from "@/components/ui/EmptyState";
import { Spinner } from "@/components/ui/Loading";
import { cx } from "@/components/ui/utils";
import { TYPO } from "@/components/ui/typographyTokens";
import { CARD_TITLE_CLASS } from "@/components/ui/cardStyleTokens";

/* ── Inline types ────────────────────────────────────────────────── */

type WorkspaceSummary = {
  id: number;
  name: string;
  custom_logo_url: string | null;
  role: string;
  project_count: number;
  member_count: number;
  created_at: string | null;
};

/* ── Helpers ─────────────────────────────────────────────────────── */

const ROLE_BADGE_COLOR: Record<string, "success" | "info" | "default" | "warning"> = {
  owner: "success",
  admin: "info",
  manager: "info",
  editor: "default",
  viewer: "default",
  client_readonly: "warning",
};

function roleBadgeColor(role: string) {
  return ROLE_BADGE_COLOR[role.toLowerCase()] ?? "default";
}

function formatDate(value: string | null): string {
  if (!value) return "-";
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return "-";
  return d.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
}

/* ── Page component ──────────────────────────────────────────────── */

export default function WorkspacesPage() {
  const { user, getToken } = useAuth();
  const router = useRouter();

  const [workspaces, setWorkspaces] = useState<WorkspaceSummary[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [activeId, setActiveId] = useState<number | null>(null);

  const getAuthHeaders = useCallback(async (): Promise<Record<string, string>> => {
    const token = await getToken();
    if (!token) throw new Error("Authentication required");
    return { Authorization: `Bearer ${token}`, ...workspaceHeaders() };
  }, [getToken]);

  useEffect(() => {
    setActiveId(getActiveWorkspaceId());
  }, []);

  useEffect(() => {
    if (!user) return;

    let cancelled = false;

    const load = async () => {
      try {
        const headers = await getAuthHeaders();
        const data = await requestJson<WorkspaceSummary[]>({
          endpoint: "/api/v1/workspaces",
          method: "GET",
          headers,
          errorMessage: "Unable to load workspaces.",
        });
        if (!cancelled) setWorkspaces(data);
      } catch (err) {
        if (!cancelled)
          toast.error(err instanceof Error ? err.message : "Failed to load workspaces.");
      } finally {
        if (!cancelled) setIsLoading(false);
      }
    };

    void load();
    return () => {
      cancelled = true;
    };
  }, [user, getAuthHeaders]);

  const handleSwitch = (ws: WorkspaceSummary) => {
    setActiveWorkspaceId(ws.id);
    setActiveId(ws.id);
    router.push("/dashboard");
  };

  /* ── Loading ───────────────────────────────────────────────────── */

  if (isLoading) {
    return (
      <div className="flex min-h-[40vh] items-center justify-center">
        <Spinner label="Loading workspaces…" />
      </div>
    );
  }

  /* ── Empty ─────────────────────────────────────────────────────── */

  if (workspaces.length === 0) {
    return (
      <section className="space-y-6">
        <h1 className={TYPO.pageTitle}>Workspaces</h1>
        <EmptyState
          icon={Building2}
          title="No workspaces found"
          description="You don't belong to any workspaces yet. Create one from the sidebar or ask an admin to invite you."
        />
      </section>
    );
  }

  /* ── Grid ──────────────────────────────────────────────────────── */

  return (
    <section className="space-y-6">
      <h1 className={TYPO.pageTitle}>Workspaces</h1>

      <div className="grid gap-5 sm:grid-cols-2 lg:grid-cols-3">
        {workspaces.map((ws) => {
          const isActive = ws.id === activeId;

          return (
            <Card
              key={ws.id}
              variant="surface"
              className={cx(
                "flex flex-col gap-4 p-5 transition-colors",
                isActive && "border-(--primary)"
              )}
            >
              {/* Header: logo / icon + name + role */}
              <div className="flex items-start gap-3">
                {ws.custom_logo_url ? (
                  <img
                    src={ws.custom_logo_url}
                    alt={`${ws.name} logo`}
                    className="h-10 w-10 shrink-0 rounded-lg object-contain"
                  />
                ) : (
                  <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-[14px] border-0 bg-[#EEF1F6]">
                    <Building2 className="h-5 w-5 text-(--text-soft)" />
                  </div>
                )}

                <div className="min-w-0 flex-1">
                  <h2 className={cx(CARD_TITLE_CLASS, "truncate")}>{ws.name}</h2>
                  <Badge color={roleBadgeColor(ws.role)} className="mt-1">
                    {ws.role.replace("_", " ")}
                  </Badge>
                </div>
              </div>

              {/* Stats row */}
              <div className="flex items-center gap-4 text-xs text-(--text-soft)">
                <span className="inline-flex items-center gap-1">
                  <FolderOpen className="h-3.5 w-3.5" />
                  {ws.project_count} {ws.project_count === 1 ? "project" : "projects"}
                </span>
                <span className="inline-flex items-center gap-1">
                  <Users className="h-3.5 w-3.5" />
                  {ws.member_count} {ws.member_count === 1 ? "member" : "members"}
                </span>
              </div>

              {/* Created date */}
              <p className="inline-flex items-center gap-1 text-xs text-(--muted-foreground)">
                <Calendar className="h-3 w-3" />
                Created {formatDate(ws.created_at)}
              </p>

              {/* Switch button */}
              <Button
                variant="primary"
                size="sm"
                className="mt-auto w-full"
                disabled={isActive}
                onClick={() => handleSwitch(ws)}
              >
                {isActive ? "Current workspace" : "Switch"}
              </Button>
            </Card>
          );
        })}
      </div>
    </section>
  );
}
