"use client";

import React, { useEffect, useState } from "react";
import { FileText } from "lucide-react";
import "@scalar/api-reference-react/style.css";

import { useAuth } from "@/components/auth/custom-auth";
import { GlassCard } from "@/components/ui/GlassComponents";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";

export default function ApiReferencePage() {
  const { getToken } = useAuth();
  const [spec, setSpec] = useState<Record<string, unknown> | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [ScalarComponent, setScalarComponent] = useState<React.ComponentType<{
    configuration: Record<string, unknown>;
  }> | null>(null);

  useEffect(() => {
    let cancelled = false;

    async function loadSpec() {
      try {
        const token = await getToken();
        const res = await fetch("/api/v1/developer/openapi-spec", {
          headers: token ? { Authorization: `Bearer ${token}` } : {},
        });
        if (!res.ok) throw new Error(`Failed to load API spec (${res.status})`);
        const data = await res.json();
        if (!cancelled) setSpec(data);
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : "Failed to load API spec");
      }
    }

    async function loadScalar() {
      try {
        const mod = await import("@scalar/api-reference-react");
        if (!cancelled) setScalarComponent(() => mod.ApiReferenceReact);
      } catch {
        if (!cancelled) setError("Failed to load API reference viewer");
      }
    }

    void loadSpec();
    void loadScalar();

    return () => {
      cancelled = true;
    };
  }, [getToken]);

  if (error) {
    return (
      <div className="flex h-full items-center justify-center p-12">
        <GlassCard className="max-w-md p-6">
          <Alert variant="destructive">
            <FileText />
            <AlertTitle>{error}</AlertTitle>
            <AlertDescription>Check your connection and try refreshing the page.</AlertDescription>
          </Alert>
        </GlassCard>
      </div>
    );
  }

  if (!spec || !ScalarComponent) {
    return (
      <div className="flex h-full items-center justify-center">
        <div className="flex flex-col items-center gap-3 text-(--muted-foreground)">
          <div className="h-8 w-8 animate-spin rounded-full border-2 border-current border-t-transparent" />
          <p className="text-sm">Loading API reference...</p>
        </div>
      </div>
    );
  }

  return (
    <ScalarComponent
      configuration={{
        content: spec,
        forceDarkModeState: "dark",
        hideDarkModeToggle: true,
        hideModels: false,
        hideDownloadButton: false,
        hiddenClients: [],
        defaultHttpClient: { targetKey: "node", clientKey: "fetch" },
        theme: "deepSpace",
        layout: "classic",
        showSidebar: true,
        customCss: `
          .dark-mode,
          .scalar-app {
            --scalar-background-1: var(--background);
            --scalar-background-2: var(--surface);
            --scalar-background-3: #0D1726;
            --scalar-border-color: var(--border);
            --scalar-color-accent: var(--primary);
            background: var(--background) !important;
          }
          .section-flare { display: none !important; }
        `,
      }}
    />
  );
}
