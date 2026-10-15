"use client";

import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  AlertTriangle,
  Bot,
  Check,
  Database,
  Radar,
  RefreshCcw,
  Save,
  ShieldAlert,
  UploadCloud,
} from "lucide-react";
import { toast } from "sonner";

import PlanLockNotice from "@/components/dashboard/PlanLockNotice";
import ProjectMonitoringSection, {
  ProjectMonitoringAlert,
  ProjectMonitoringEmptyState,
  ProjectMonitoringLoadingState,
  ProjectMonitoringMetricCard,
  ProjectMonitoringStateCard,
} from "@/components/dashboard/ProjectMonitoringSection";
import { useAuth } from "@/components/auth/custom-auth";
import Button, { BUTTON_ICON_CLASS } from "@/components/ui/Button";
import CyberField from "@/components/ui/CyberField";
import { GlassCard } from "@/components/ui/GlassComponents";
import { getPlanLockContent } from "@/lib/planLocks";
import {
  BotLogApiError,
  fetchProjectBotLogSources,
  fetchProjectBotLogSummary,
  uploadProjectBotLogFile,
  upsertProjectBotLogSource,
} from "@/services/projectBotLogService";
import type {
  BotLogIngestionSource,
  BotLogSummaryResponse,
  UpsertBotLogSourcePayload,
} from "@/types/projectBotLog";

type SourceType = UpsertBotLogSourcePayload["source_type"];

type SourceDraft = {
  display_name: string;
  config_json: string;
  is_active: boolean;
};

const SOURCE_PRESETS: Array<{
  source_type: SourceType;
  title: string;
  description: string;
  placeholder: string;
}> = [
  {
    source_type: "manual_upload",
    title: "Manual Upload",
    description: "Upload Nginx/Apache access logs directly from agency workstations.",
    placeholder: "{}",
  },
  {
    source_type: "cloudflare_logpush",
    title: "Cloudflare Logpush",
    description: "Store Logpush dataset metadata for scheduled enterprise pulls.",
    placeholder: '{"dataset":"http_requests","bucket":"cf-logpush-bucket"}',
  },
  {
    source_type: "aws_s3",
    title: "AWS S3",
    description: "Track the S3 bucket and prefix where nightly server logs are delivered.",
    placeholder: '{"bucket":"agency-logs","prefix":"client-a/"}',
  },
  {
    source_type: "gcp_cloud_storage",
    title: "GCP Cloud Storage",
    description: "Track the GCS bucket path for recurring export ingestion.",
    placeholder: '{"bucket":"qiko-signal-log-exports","prefix":"raw/"}',
  },
];

const formatInteger = (value: number) => new Intl.NumberFormat("en-US").format(value);

function normalizeDrafts(items: BotLogIngestionSource[]): Record<SourceType, SourceDraft> {
  const next: Record<SourceType, SourceDraft> = {
    manual_upload: { display_name: "", config_json: "{}", is_active: true },
    cloudflare_logpush: { display_name: "", config_json: "{}", is_active: false },
    aws_s3: { display_name: "", config_json: "{}", is_active: false },
    gcp_cloud_storage: { display_name: "", config_json: "{}", is_active: false },
  };

  for (const item of items) {
    if (!(item.source_type in next)) {
      continue;
    }
    const sourceType = item.source_type as SourceType;
    next[sourceType] = {
      display_name: item.display_name ?? "",
      config_json: JSON.stringify(item.config ?? {}, null, 2),
      is_active: item.is_active,
    };
  }

  return next;
}

type ProjectBotLogAnalyzerPanelProps = {
  projectId: number | string;
};

export default function ProjectBotLogAnalyzerPanel({ projectId }: ProjectBotLogAnalyzerPanelProps) {
  const { getToken } = useAuth();
  const fileInputRef = useRef<HTMLInputElement | null>(null);

  const [summary, setSummary] = useState<BotLogSummaryResponse | null>(null);
  const [sources, setSources] = useState<BotLogIngestionSource[]>([]);
  const [drafts, setDrafts] = useState<Record<SourceType, SourceDraft>>(() => normalizeDrafts([]));

  const [selectedSourceType, setSelectedSourceType] = useState<SourceType>("manual_upload");
  const [selectedFile, setSelectedFile] = useState<File | null>(null);

  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [savingSourceType, setSavingSourceType] = useState<SourceType | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [planLocked, setPlanLocked] = useState(false);

  const buildHeaders = useCallback(async (): Promise<HeadersInit> => {
    const token = await getToken();
    return token ? { Authorization: `Bearer ${token}` } : {};
  }, [getToken]);

  const loadData = useCallback(
    async (mode: "initial" | "refresh" = "initial") => {
      if (!projectId) {
        return;
      }

      if (mode === "initial") {
        setLoading(true);
      } else {
        setRefreshing(true);
      }

      setError(null);
      setPlanLocked(false);

      try {
        const headers = await buildHeaders();
        const [summaryPayload, sourcesPayload] = await Promise.all([
          fetchProjectBotLogSummary(projectId, headers, 30),
          fetchProjectBotLogSources(projectId, headers),
        ]);

        setSummary(summaryPayload);
        setSources(sourcesPayload.items);
        setDrafts(normalizeDrafts(sourcesPayload.items));
      } catch (loadError) {
        setSummary(null);
        setSources([]);
        if (loadError instanceof BotLogApiError && loadError.status === 402) {
          setPlanLocked(true);
        } else {
          setError(
            loadError instanceof Error ? loadError.message : "Unable to load bot log analyzer."
          );
        }
      } finally {
        setLoading(false);
        setRefreshing(false);
      }
    },
    [buildHeaders, projectId]
  );

  useEffect(() => {
    void loadData("initial");
  }, [loadData]);

  const sourceByType = useMemo(() => {
    const index: Partial<Record<SourceType, BotLogIngestionSource>> = {};
    for (const source of sources) {
      if (source.source_type in drafts) {
        index[source.source_type as SourceType] = source;
      }
    }
    return index;
  }, [drafts, sources]);
  const planLockContent = getPlanLockContent("botLogAnalyzer");

  const pickFile = () => {
    fileInputRef.current?.click();
  };

  const handleUpload = useCallback(async () => {
    if (!selectedFile) {
      toast.error("Choose a log file before uploading.");
      return;
    }

    setUploading(true);
    try {
      const headers = await buildHeaders();
      const sourceId = sourceByType[selectedSourceType]?.id;
      const uploadResponse = await uploadProjectBotLogFile(projectId, selectedFile, headers, {
        sourceType: selectedSourceType,
        sourceId,
      });
      toast.success(
        `Processed ${formatInteger(uploadResponse.bot_hits)} AI bot hits from ${selectedFile.name}.`
      );
      setSelectedFile(null);
      if (fileInputRef.current) {
        fileInputRef.current.value = "";
      }
      await loadData("refresh");
    } catch (uploadError) {
      if (uploadError instanceof BotLogApiError && uploadError.status === 402) {
        setPlanLocked(true);
      }
      toast.error(uploadError instanceof Error ? uploadError.message : "Bot log upload failed.");
    } finally {
      setUploading(false);
    }
  }, [buildHeaders, loadData, projectId, selectedFile, selectedSourceType, sourceByType]);

  const handleSaveSource = useCallback(
    async (sourceType: SourceType) => {
      const draft = drafts[sourceType];
      let parsedConfig: Record<string, unknown> = {};

      try {
        const rawConfig = draft.config_json.trim();
        parsedConfig = rawConfig ? (JSON.parse(rawConfig) as Record<string, unknown>) : {};
      } catch {
        toast.error("Connector config must be valid JSON.");
        return;
      }

      setSavingSourceType(sourceType);
      try {
        const headers = await buildHeaders();
        await upsertProjectBotLogSource(
          projectId,
          {
            source_type: sourceType,
            display_name: draft.display_name.trim() || undefined,
            config: parsedConfig,
            is_active: draft.is_active,
          },
          headers
        );
        toast.success("Ingestion source saved.");
        await loadData("refresh");
      } catch (sourceError) {
        toast.error(sourceError instanceof Error ? sourceError.message : "Failed to save source.");
      } finally {
        setSavingSourceType(null);
      }
    },
    [buildHeaders, drafts, loadData, projectId]
  );

  if (loading) {
    return <ProjectMonitoringLoadingState label="Loading AI bot log analyzer..." />;
  }

  if (planLocked) {
    return <PlanLockNotice {...planLockContent} />;
  }

  if (error) {
    return (
      <ProjectMonitoringStateCard
        icon={AlertTriangle}
        title="Bot Log Analyzer Unavailable"
        description={error}
        tone="rose"
        action={
          <div>
            <Button variant="ghost" onClick={() => void loadData("refresh")}>
              Retry
            </Button>
          </div>
        }
      />
    );
  }

  return (
    <ProjectMonitoringSection
      id="bot-log-analyzer"
      icon={Radar}
      title="AI Bot Log"
      accent="Analyzer"
      description="Parse server logs to track AI crawler coverage, identify 4xx/5xx crawl waste, and flag spoofed bot traffic with reverse DNS verification."
      action={
        <Button variant="ghost" onClick={() => void loadData("refresh")} loading={refreshing}>
          <RefreshCcw className="h-4 w-4" /> Refresh
        </Button>
      }
    >
      <GlassCard className="space-y-4 p-6 border-(--border) bg-(--card)">
        <div className="flex flex-wrap items-center gap-3">
          <input
            ref={fileInputRef}
            type="file"
            accept=".log,.txt,.gz"
            className="hidden"
            aria-label="Upload server log file"
            onChange={(event) => {
              const file = event.target.files?.[0] ?? null;
              setSelectedFile(file);
            }}
          />
          <Button variant="ghost" onClick={pickFile}>
            <UploadCloud className="h-4 w-4" /> Choose Log File
          </Button>
          <select
            aria-label="Bot log source type"
            value={selectedSourceType}
            onChange={(event) => setSelectedSourceType(event.target.value as SourceType)}
            className="h-10 rounded border-0 bg-(--background) px-3 text-sm text-(--foreground) transition-colors focus-visible:border-brand-geo focus-visible:outline-hidden focus-visible:ring-1 focus-visible:ring-brand-geo"
          >
            {SOURCE_PRESETS.map((preset) => (
              <option key={preset.source_type} value={preset.source_type}>
                {preset.title}
              </option>
            ))}
          </select>
          <Button variant="primary" onClick={() => void handleUpload()} loading={uploading}>
            <UploadCloud className="h-4 w-4" /> Upload + Parse
          </Button>
        </div>
        <p className="text-xs text-(--muted-foreground)">
          {selectedFile
            ? `Selected file: ${selectedFile.name}`
            : "No file selected. Supported formats: .log, .txt, .gz"}
        </p>
      </GlassCard>

      {summary?.degraded ? (
        <ProjectMonitoringAlert
          icon={ShieldAlert}
          title="Diagnostics are partially degraded."
          description={summary.degraded_reasons.join("; ") || "Data quality warning detected."}
        />
      ) : null}

      {summary?.no_data ? (
        <ProjectMonitoringEmptyState
          icon={Bot}
          title="No AI bot crawl data yet"
          description="Upload your first server log file to generate crawl diagnostics, section heatmaps, and spoofing radar insights."
          action={
            <Button variant="primary" onClick={pickFile}>
              <UploadCloud className="h-4 w-4" /> Upload First Log
            </Button>
          }
        />
      ) : null}

      {!summary?.no_data && summary ? (
        <>
          <div className="grid gap-4 md:grid-cols-5">
            <ProjectMonitoringMetricCard
              label="Total Bot Hits"
              value={
                <p className="text-2xl font-black text-(--t-1)">
                  {formatInteger(summary.totals.total_hits)}
                </p>
              }
            />
            <ProjectMonitoringMetricCard
              label="Verified"
              value={
                <p className="text-2xl font-black text-emerald-300">
                  {formatInteger(summary.totals.verified_hits)}
                </p>
              }
            />
            <ProjectMonitoringMetricCard
              label="Spoofed"
              value={
                <p className="text-2xl font-black text-rose-300">
                  {formatInteger(summary.totals.spoofed_hits)}
                </p>
              }
            />
            <ProjectMonitoringMetricCard
              label="4xx Errors"
              value={
                <p className="text-2xl font-black text-amber-200">
                  {formatInteger(summary.totals.error_4xx_hits)}
                </p>
              }
            />
            <ProjectMonitoringMetricCard
              label="5xx Errors"
              value={
                <p className="text-2xl font-black text-amber-100">
                  {formatInteger(summary.totals.error_5xx_hits)}
                </p>
              }
            />
          </div>

          <div className="grid gap-4 xl:grid-cols-3">
            <GlassCard className="xl:col-span-2 p-6">
              <h3 className="text-sm font-black uppercase tracking-wider text-(--t-1)">
                Bot Breakdown
              </h3>
              <div className="mt-4 overflow-x-auto">
                <table className="min-w-full text-left text-xs text-(--t-2)">
                  <thead>
                    <tr className="border-b border-(--line) text-[10px] uppercase tracking-widest text-(--t-3)">
                      <th className="pb-2 pr-3">Bot</th>
                      <th className="pb-2 pr-3">Hits</th>
                      <th className="pb-2 pr-3">Verified</th>
                      <th className="pb-2 pr-3">Spoofed</th>
                      <th className="pb-2 pr-3">4xx</th>
                      <th className="pb-2">5xx</th>
                    </tr>
                  </thead>
                  <tbody>
                    {summary.bot_breakdown.slice(0, 10).map((row) => (
                      <tr key={row.bot_name} className="border-b border-(--line)">
                        <td className="py-2 pr-3 font-semibold text-(--t-1)">{row.bot_name}</td>
                        <td className="py-2 pr-3">{formatInteger(row.hits)}</td>
                        <td className="py-2 pr-3">{formatInteger(row.verified_hits)}</td>
                        <td className="py-2 pr-3">{formatInteger(row.spoofed_hits)}</td>
                        <td className="py-2 pr-3">{formatInteger(row.error_4xx_hits)}</td>
                        <td className="py-2">{formatInteger(row.error_5xx_hits)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </GlassCard>

            <GlassCard className="space-y-4 p-6">
              <h3 className="text-sm font-black uppercase tracking-wider text-(--t-1)">
                Section Heatmap
              </h3>
              <ul className="space-y-2 text-sm text-(--t-2)">
                {summary.section_heatmap.slice(0, 8).map((row) => (
                  <li key={row.section} className="flex items-center justify-between gap-3">
                    <span>{row.section}</span>
                    <span className="font-semibold text-(--t-1)">{formatInteger(row.hits)}</span>
                  </li>
                ))}
              </ul>

              <h4 className="pt-2 text-xs font-black uppercase tracking-widest text-(--t-2)">
                Spoofing Radar
              </h4>
              {summary.spoofing_radar.length === 0 ? (
                <p className="text-xs text-emerald-300">
                  No spoofed AI bots detected in this window.
                </p>
              ) : (
                <ul className="space-y-2 text-sm text-(--t-2)">
                  {summary.spoofing_radar.slice(0, 6).map((row) => (
                    <li key={row.bot_name} className="flex items-center justify-between gap-3">
                      <span>{row.bot_name}</span>
                      <span className="font-semibold text-rose-200">
                        {formatInteger(row.spoofed_hits)}
                      </span>
                    </li>
                  ))}
                </ul>
              )}
            </GlassCard>
          </div>
        </>
      ) : null}

      <GlassCard className="space-y-5 p-6 border-(--border) bg-(--card)">
        <div className="flex items-center gap-2 text-sm font-black uppercase tracking-wider text-(--foreground)">
          <Database className="h-4 w-4 text-primary" />
          Ingestion Sources
        </div>

        <div className="grid gap-4 xl:grid-cols-2">
          {SOURCE_PRESETS.map((preset) => {
            const draft = drafts[preset.source_type];
            const source = sourceByType[preset.source_type];
            const isSaving = savingSourceType === preset.source_type;

            return (
              <div
                key={preset.source_type}
                className="rounded border-0 p-4 transition-colors hover:border-(--border-hover)"
              >
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <h4 className="text-sm font-black uppercase tracking-wider text-(--foreground)">
                      {preset.title}
                    </h4>
                    <p className="mt-1 text-xs text-(--muted-foreground)">{preset.description}</p>
                  </div>
                  <span
                    className={`rounded-full border px-2.5 py-1 text-[10px] font-black uppercase tracking-wider ${
                      source?.is_active
                        ? "border-emerald-400/20 bg-emerald-500/10 text-emerald-200"
                        : "border-(--border) bg-(--card) text-(--muted-foreground)"
                    }`}
                  >
                    {source?.is_active ? "Active" : "Inactive"}
                  </span>
                </div>

                <div className="mt-4 space-y-3">
                  <CyberField
                    label="Display name"
                    value={draft.display_name}
                    onChange={(event) => {
                      const value = event.target.value;
                      setDrafts((current) => ({
                        ...current,
                        [preset.source_type]: {
                          ...current[preset.source_type],
                          display_name: value,
                        },
                      }));
                    }}
                  />

                  <label className="block text-[11px] uppercase tracking-widest text-(--muted-foreground)">
                    Connector config (JSON)
                    <textarea
                      aria-label={`${preset.title} config JSON`}
                      value={draft.config_json}
                      onChange={(event) => {
                        const value = event.target.value;
                        setDrafts((current) => ({
                          ...current,
                          [preset.source_type]: {
                            ...current[preset.source_type],
                            config_json: value,
                          },
                        }));
                      }}
                      rows={4}
                      placeholder={preset.placeholder}
                      className="mt-2 w-full rounded border-0 bg-(--card) px-3 py-2 text-xs text-(--foreground) outline-hidden transition-colors focus:border-brand-geo"
                    />
                  </label>

                  <div className="flex items-center justify-between gap-3">
                    <label className="group inline-flex w-fit cursor-pointer items-center gap-2 text-xs text-(--foreground)">
                      <input
                        type="checkbox"
                        checked={draft.is_active}
                        onChange={(event) => {
                          const checked = event.target.checked;
                          setDrafts((current) => ({
                            ...current,
                            [preset.source_type]: {
                              ...current[preset.source_type],
                              is_active: checked,
                            },
                          }));
                        }}
                        className="peer sr-only"
                      />
                      <span className="flex h-4 w-4 items-center justify-center rounded-[3px] border-0 bg-(--card) transition-colors group-hover:border-(--border-hover) peer-checked:border-brand-aeo peer-checked:bg-brand-aeo peer-focus-visible:ring-2 peer-focus-visible:ring-brand-geo peer-focus-visible:ring-offset-2 peer-focus-visible:ring-offset-(--background)">
                        <Check className="h-3 w-3 stroke-3 text-(--t-1) opacity-0 transition-opacity peer-checked:opacity-100" />
                      </span>
                      Source active
                    </label>

                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => void handleSaveSource(preset.source_type)}
                      loading={isSaving}
                      loadingText=""
                      className={BUTTON_ICON_CLASS}
                      aria-label={`Save ${preset.title} source`}
                      title={`Save ${preset.title} source`}
                    >
                      <Save />
                    </Button>
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      </GlassCard>
    </ProjectMonitoringSection>
  );
}
