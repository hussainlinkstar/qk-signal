"use client";

import React, { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useAuth } from "@/components/auth/custom-auth";
import { workspaceHeaders } from "@/components/app/WorkspaceSwitcher";
import SelectField from "@/components/ui/SelectField";
import { fetchWorkspaceProjects, type WorkspaceProjectSummary } from "@/services/workspaceService";
import { GlassCard } from "@/components/ui/GlassComponents";
import Button from "@/components/ui/Button";
import { Loader2, Target, ChevronRight } from "lucide-react";

type ProjectRouteBridgeProps = {
  moduleLabel: string;
  description: string;
  targetPath?: string;
  ctaLabel?: string;
};

const formatProjectOption = (project: WorkspaceProjectSummary) => {
  if (!project.domain_url) {
    return project.name;
  }
  try {
    const parsed = new URL(project.domain_url);
    return `${project.name} (${parsed.hostname})`;
  } catch {
    return `${project.name} (${project.domain_url.replace(/^https?:\/\//i, "")})`;
  }
};

export default function ProjectRouteBridge({
  moduleLabel,
  description,
  targetPath = "",
  ctaLabel = "Open Project Module",
}: ProjectRouteBridgeProps) {
  const { getToken, isSignedIn, isLoading: authLoading } = useAuth();
  const [projects, setProjects] = useState<WorkspaceProjectSummary[]>([]);
  const [selectedProjectId, setSelectedProjectId] = useState<string>("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const requiresSignIn = !authLoading && !isSignedIn;

  const getAuthHeaders = useCallback(async (): Promise<HeadersInit> => {
    const token = await getToken();
    if (!token) {
      throw new Error("Sign in to select a project.");
    }
    return { Authorization: `Bearer ${token}`, ...workspaceHeaders() };
  }, [getToken]);

  useEffect(() => {
    const loadProjects = async () => {
      if (authLoading) {
        return;
      }
      if (!isSignedIn) {
        setProjects([]);
        setSelectedProjectId("");
        setLoading(false);
        setError(null);
        return;
      }

      setLoading(true);
      setError(null);
      try {
        const headers = await getAuthHeaders();
        const payload = await fetchWorkspaceProjects(headers);
        setProjects(payload);
        setSelectedProjectId((previous) => {
          if (previous && payload.some((project) => String(project.id) === previous)) {
            return previous;
          }
          return payload.length ? String(payload[0].id) : "";
        });
      } catch (loadError) {
        setProjects([]);
        setSelectedProjectId("");
        setError(
          loadError instanceof Error ? loadError.message : "Unable to load workspace projects."
        );
      } finally {
        setLoading(false);
      }
    };

    void loadProjects();
  }, [authLoading, getAuthHeaders, isSignedIn]);

  const destinationHref = useMemo(() => {
    if (!selectedProjectId) {
      return "/dashboard";
    }
    const normalizedPath = targetPath.startsWith("/") ? targetPath : `/${targetPath}`;
    return `/dashboard/projects/${selectedProjectId}${normalizedPath === "/" ? "" : normalizedPath}`;
  }, [selectedProjectId, targetPath]);

  return (
    <div className="dashboard-page-shell group/bridge space-y-8">
      <GlassCard className="mx-auto max-w-2xl border-primary/20 bg-primary/[0.01] p-12 text-center shadow-[0_0_50px_-12px_rgba(6,182,212,0.15)]">
        <div className="flex flex-col items-center gap-8">
          <div className="flex flex-col items-center gap-4">
            <div className="flex items-center gap-3 mb-2">
              <div className="flex h-10 w-10 items-center justify-center rounded-xl border border-primary/30 bg-primary/10 text-primary shadow-[0_0_20px_rgba(6,182,212,0.2)]">
                <Target size={20} className="animate-pulse" />
              </div>
              <h1 className="text-3xl font-black tracking-tighter text-(--t-1) uppercase ">
                {moduleLabel.split(" ")[0]}{" "}
                <span className="text-primary">{moduleLabel.split(" ").slice(1).join(" ")}</span>
              </h1>
            </div>
            <p className="text-sm font-medium text-(--t-2) max-w-md leading-relaxed  opacity-80">
              {description}
            </p>
          </div>

          <div className="w-full h-px bg-linear-to-r from-transparent via-white/5 to-transparent" />

          {requiresSignIn ? (
            <div className="rounded border border-rose-500/20  p-6 text-xs text-rose-400 font-black uppercase tracking-widest ">
              Sign in required for project access.
            </div>
          ) : loading ? (
            <div className="flex flex-col items-center gap-4 p-8">
              <Loader2 className="h-8 w-8 text-primary animate-spin" />
              <p className="text-[10px] font-black text-(--t-3) uppercase tracking-widest ">
                Loading project list...
              </p>
            </div>
          ) : error ? (
            <div className="rounded border border-rose-500/20  p-6 text-xs text-rose-400 font-black uppercase tracking-widest ">
              Unable to load projects: {error}
            </div>
          ) : (
            <div className="w-full space-y-8 animate-in fade-in slide-in-from-bottom-4 duration-700">
              {projects.length === 0 ? (
                <div className="space-y-6">
                  <p className="text-xs text-(--t-3)  font-medium">
                    No projects found in this workspace.
                  </p>
                  <Link href="/dashboard">
                    <Button variant="ghost" className="h-12 px-8">
                      Return to Dashboard
                    </Button>
                  </Link>
                </div>
              ) : (
                <div className="space-y-8">
                  <div className="space-y-4 text-left border-l-2 border-primary/20 pl-6">
                    <label className="text-[10px] font-black uppercase tracking-[0.2em] text-(--t-3) ">
                      Select Project
                    </label>
                    <SelectField
                      value={selectedProjectId}
                      onChange={(event) => setSelectedProjectId(event.target.value)}
                      className="bg-(--line-2) border-(--line) h-12 rounded-xl text-sm font-bold text-(--t-1) "
                    >
                      {projects.map((project) => (
                        <option key={project.id} value={String(project.id)}>
                          {formatProjectOption(project)}
                        </option>
                      ))}
                    </SelectField>
                  </div>

                  <Link href={destinationHref} className="block group/cta">
                    <Button variant="outline" size="lg" className="w-full h-14">
                      {ctaLabel}{" "}
                      <ChevronRight className="h-4 w-4 ml-2 transition-transform group-hover/cta:translate-x-1" />
                    </Button>
                  </Link>
                </div>
              )}
            </div>
          )}
        </div>
      </GlassCard>

      <div className="flex items-center justify-center gap-4 font-mono text-[9px] font-black uppercase tracking-[0.3em] text-(--t-3)">
        <div className="h-1 w-1 rounded-full bg-(--line-2)" />
        Project Routing
        <div className="h-1 w-1 rounded-full bg-(--line-2)" />
        Active
      </div>
    </div>
  );
}
