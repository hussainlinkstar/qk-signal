"use client";

import React, { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import {
  AlertTriangle,
  ArrowLeft,
  Bot,
  Clock3,
  Coins,
  GitBranch,
  Search,
  Shield,
  Workflow,
} from "lucide-react";

import { useAuth } from "@/components/auth/custom-auth";
import { useAdminAccess } from "@/components/admin/AdminGuardProvider";
import Button from "@/components/ui/Button";
import DashboardPageIntro from "@/components/dashboard/DashboardPageIntro";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { AdminTableSkeleton } from "@/components/admin/AdminTableSkeleton";
import { ClientSafeDate } from "@/lib/dateFormat";
import { cx } from "@/components/ui/utils";

type DebateTraceTimelineEntry = {
  agent_role: string;
  provider: string;
  model: string;
  status: string;
  latency_ms: number;
  cost_usd?: number | null;
  input_chars: number;
  output_preview: string;
  claim_count: number;
  prompt_tokens?: number | null;
  completion_tokens?: number | null;
  error_message?: string | null;
};

type DebateTraceLayer = {
  layer: number;
  name: string;
  parallel: boolean;
  traces: DebateTraceTimelineEntry[];
};

type DebateTraceTimelineResponse = {
  audit_id: number;
  pipeline_type: string;
  total_agents: number;
  total_latency_ms: number;
  total_cost_usd: number;
  layers: DebateTraceLayer[];
};

type DebateTraceOutputResponse = {
  audit_id: number;
  agent_role: string;
  agent_layer: number;
  pipeline_type: string;
  provider: string;
  model: string;
  status: string;
  latency_ms: number;
  cost_usd?: number | null;
  prompt_tokens?: number | null;
  completion_tokens?: number | null;
  input_payload_hash: string;
  input_payload_chars: number;
  input_summary?: string | null;
  input_payload?: unknown;
  output_raw?: unknown;
  output_claim_ledger?: Record<string, unknown> | null;
  error_message?: string | null;
  created_at?: string | null;
};

type DebateTraceJourneyStep = {
  layer: number;
  agent: string;
  provider: string;
  model: string;
  status: string;
  action: string;
  confidence?: number | null;
  new_confidence?: number | null;
  critique?: string | null;
  severity?: string | null;
  suggested_disposition?: string | null;
  disposition?: string | null;
  critique_reference?: string | null;
  recommended_action?: string | null;
};

type DebateTraceJourneyResponse = {
  audit_id: number;
  claim_id: string;
  claim_text?: string | null;
  claim_domain?: string | null;
  journey: DebateTraceJourneyStep[];
};

/* -------------------------------------------------------------------------- */
/*  Design tokens                                                              */
/* -------------------------------------------------------------------------- */

const MICRO_LABEL =
  "font-(family-name:--mono) text-[10.5px] uppercase tracking-[0.08em] text-(--t-3)";
const MONO_META = MICRO_LABEL.replace("uppercase ", "");
const WSEC = "rounded-[22px] border-0 bg-white px-[22px] py-[18px]";
const SEC_TITLE =
  "m-0 mb-4 flex items-center gap-2 font-(family-name:--disp) text-[15px] font-bold tracking-[-0.01em] text-(--t-1)";
const INSET = "rounded-(--r-md) border-0 bg-[#EEF1F6] p-4";
const CHIP =
  "inline-flex items-center gap-1.5 rounded-md px-2 py-[3px] font-(family-name:--mono) text-[10.5px] uppercase tracking-[0.04em]";
const BACKLINK =
  "flex w-fit items-center gap-2 font-(family-name:--mono) text-[11.5px] tracking-[0.06em] text-(--t-3) transition-colors hover:text-(--t-1)";
const WINPUT =
  "field-focus-ring h-9 w-full rounded-(--r-md) border-0 bg-[#EEF1F6] px-[10px] text-[12.5px] text-(--t-1) outline-none placeholder:text-(--t-3) focus:border-[#c7cdd6]";
const PRE_BLOCK =
  "max-h-[280px] overflow-auto rounded-(--r-md) border-0 bg-[#EEF1F6] p-3 font-(family-name:--mono) text-[11px] leading-relaxed text-(--t-2)";

const formatRole = (value: string) => value.replace(/_/g, " ");
const formatStatus = (value: string) => value.replace(/_/g, " ");
const formatMoney = (value?: number | null) =>
  typeof value === "number" ? `EUR ${value.toFixed(2)}` : "-";
const formatMs = (value: number) => `${Math.round(value)} ms`;

function getClaimIdsFromOutput(output: DebateTraceOutputResponse | null): string[] {
  if (!output || !output.output_claim_ledger || typeof output.output_claim_ledger !== "object") {
    return [];
  }
  const packet = output.output_claim_ledger;
  const keys = ["claim_ledger", "consolidated_claim_disposition"] as const;
  const ids = new Set<string>();

  for (const key of keys) {
    const rows = packet[key];
    if (!Array.isArray(rows)) continue;
    for (const row of rows) {
      if (!row || typeof row !== "object") continue;
      const claimId = (row as Record<string, unknown>).claim_id;
      if (typeof claimId === "string" && claimId.trim()) {
        ids.add(claimId.trim());
      }
    }
  }

  return Array.from(ids);
}

export default function AdminDebateTracePage() {
  const params = useParams();
  const auditId = Array.isArray(params?.auditId) ? params.auditId[0] : params?.auditId;

  const { getToken, isSignedIn } = useAuth();
  const { isAdmin, isLoading: isGuardLoading } = useAdminAccess();

  const [timeline, setTimeline] = useState<DebateTraceTimelineResponse | null>(null);
  const [selectedOutput, setSelectedOutput] = useState<DebateTraceOutputResponse | null>(null);
  const [journey, setJourney] = useState<DebateTraceJourneyResponse | null>(null);
  const [claimId, setClaimId] = useState("");
  const [pageError, setPageError] = useState("");
  const [journeyError, setJourneyError] = useState("");
  const [isLoadingTimeline, setIsLoadingTimeline] = useState(false);
  const [isLoadingOutput, setIsLoadingOutput] = useState(false);
  const [isLoadingJourney, setIsLoadingJourney] = useState(false);

  const getAuthHeaders = useCallback(async () => {
    const token = await getToken();
    if (!token) {
      throw new Error("You must be signed in to access debate traces.");
    }
    return { Authorization: `Bearer ${token}` };
  }, [getToken]);

  const loadTimeline = useCallback(async () => {
    if (!auditId || !isSignedIn) return;
    setIsLoadingTimeline(true);
    setPageError("");
    try {
      const headers = await getAuthHeaders();
      const response = await fetch(`/api/admin/audits/${auditId}/debate-trace`, { headers });
      if (!response.ok) {
        const payload = await response.json().catch(() => null);
        throw new Error(payload?.detail ?? "Unable to load the debate trace.");
      }
      const payload = (await response.json()) as DebateTraceTimelineResponse;
      setTimeline(payload);
    } catch (error) {
      setPageError(error instanceof Error ? error.message : "Unable to load the debate trace.");
    } finally {
      setIsLoadingTimeline(false);
    }
  }, [auditId, getAuthHeaders, isSignedIn]);

  const loadAgentOutput = useCallback(
    async (role: string) => {
      if (!auditId || !role) return;
      setIsLoadingOutput(true);
      setJourneyError("");
      try {
        const headers = await getAuthHeaders();
        const response = await fetch(`/api/admin/audits/${auditId}/debate-trace/${role}/output`, {
          headers,
        });
        if (!response.ok) {
          const payload = await response.json().catch(() => null);
          throw new Error(payload?.detail ?? "Unable to load the agent output.");
        }
        const payload = (await response.json()) as DebateTraceOutputResponse;
        setSelectedOutput(payload);
      } catch (error) {
        setPageError(error instanceof Error ? error.message : "Unable to load the agent output.");
      } finally {
        setIsLoadingOutput(false);
      }
    },
    [auditId, getAuthHeaders]
  );

  const loadJourney = useCallback(
    async (requestedClaimId: string) => {
      const normalizedClaimId = requestedClaimId.trim();
      if (!auditId || !normalizedClaimId) return;
      setIsLoadingJourney(true);
      setJourneyError("");
      try {
        const headers = await getAuthHeaders();
        const response = await fetch(
          `/api/admin/audits/${auditId}/debate-trace/claim/${encodeURIComponent(normalizedClaimId)}/journey`,
          { headers }
        );
        if (!response.ok) {
          const payload = await response.json().catch(() => null);
          throw new Error(payload?.detail ?? "Unable to load the claim journey.");
        }
        const payload = (await response.json()) as DebateTraceJourneyResponse;
        setJourney(payload);
        setClaimId(normalizedClaimId);
      } catch (error) {
        setJourneyError(
          error instanceof Error ? error.message : "Unable to load the claim journey."
        );
      } finally {
        setIsLoadingJourney(false);
      }
    },
    [auditId, getAuthHeaders]
  );

  useEffect(() => {
    loadTimeline();
  }, [loadTimeline]);

  useEffect(() => {
    const firstRole = timeline?.layers[0]?.traces[0]?.agent_role;
    if (firstRole && !selectedOutput) {
      void loadAgentOutput(firstRole);
    }
  }, [loadAgentOutput, selectedOutput, timeline]);

  const suggestedClaimIds = useMemo(() => getClaimIdsFromOutput(selectedOutput), [selectedOutput]);

  if (!isAdmin && !isGuardLoading) {
    return (
      <Alert variant="warning">
        <AlertDescription>Admin privileges are required to view debate traces.</AlertDescription>
      </Alert>
    );
  }

  return (
    <>
      <Link href={`/admin/audit-application/${auditId}`} className={BACKLINK}>
        <ArrowLeft size={14} />
        Back to audit detail
      </Link>

      <div className="flex flex-col gap-4 md:flex-row md:items-end md:justify-between">
        <DashboardPageIntro icon={Workflow} title={`Audit #${auditId} debate trace`}>
          Admin-only timeline for Orchestra execution, raw agent payload inspection, and claim
          journey debugging.
        </DashboardPageIntro>

        <div className="flex flex-wrap gap-2">
          <span className={`${CHIP} text-(--t-2) bg-(--panel)`}>
            Pipeline: {timeline?.pipeline_type ?? "loading"}
          </span>
          <span className={`${CHIP} text-(--t-2) bg-(--panel)`}>
            Agents: {timeline?.total_agents ?? 0}
          </span>
        </div>
      </div>

      {pageError && (
        <Alert variant="destructive">
          <AlertTriangle size={16} />
          <AlertDescription>{pageError}</AlertDescription>
        </Alert>
      )}

      {isLoadingTimeline ? (
        <AdminTableSkeleton rows={6} columns={3} />
      ) : (
        <div className="grid gap-6 xl:grid-cols-[minmax(0,1.5fr)_minmax(360px,0.9fr)]">
          <div className="space-y-5">
            <div className="grid gap-3 sm:grid-cols-3">
              <div className={INSET}>
                <p className={MICRO_LABEL}>Total latency</p>
                <p className="mt-2 font-(family-name:--disp) text-lg font-bold text-(--t-1)">
                  {formatMs(timeline?.total_latency_ms ?? 0)}
                </p>
              </div>
              <div className={INSET}>
                <p className={MICRO_LABEL}>Total cost</p>
                <p className="mt-2 font-(family-name:--disp) text-lg font-bold text-(--t-1)">
                  {formatMoney(timeline?.total_cost_usd)}
                </p>
              </div>
              <div className={INSET}>
                <p className={MICRO_LABEL}>Trace layers</p>
                <p className="mt-2 font-(family-name:--disp) text-lg font-bold text-(--t-1)">
                  {timeline?.layers.length ?? 0}
                </p>
              </div>
            </div>

            {timeline?.layers.length ? (
              timeline.layers.map((layer) => (
                <section key={layer.layer} className={WSEC}>
                  <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
                    <div>
                      <p className={MONO_META}>Layer {layer.layer}</p>
                      <h2 className="mt-1 font-(family-name:--disp) text-[17px] font-bold text-(--t-1)">
                        {layer.name}
                      </h2>
                    </div>
                    <span
                      className={cx(
                        CHIP,
                        layer.parallel
                          ? "text-(--purple) bg-(--purple-s)"
                          : "text-(--t-2) bg-(--paper)"
                      )}
                    >
                      {layer.parallel ? "Parallel" : "Sequential"}
                    </span>
                  </div>

                  <div className="grid gap-3 md:grid-cols-2">
                    {layer.traces.map((trace) => (
                      <button
                        key={`${layer.layer}-${trace.agent_role}`}
                        type="button"
                        onClick={() => void loadAgentOutput(trace.agent_role)}
                        className="rounded-(--r-md) border-0 bg-[#EEF1F6] p-4 text-left transition-colors hover:border-[#c7cdd6] focus:outline-hidden focus-visible:ring-2 focus-visible:ring-(--purple)"
                        aria-label={`Open ${trace.agent_role} trace`}
                      >
                        <div className="flex items-start justify-between gap-3">
                          <div>
                            <p className="text-[13px] font-semibold text-(--t-1)">
                              {formatRole(trace.agent_role)}
                            </p>
                            <p className="mt-1 text-[11px] text-(--t-2)">
                              {trace.provider} / {trace.model}
                            </p>
                          </div>
                          <span
                            className={cx(
                              CHIP,
                              trace.status === "completed"
                                ? "text-(--good) bg-(--good-s)"
                                : "text-(--warn) bg-(--warn-s)"
                            )}
                          >
                            {formatStatus(trace.status)}
                          </span>
                        </div>

                        <p className="mt-3 line-clamp-3 text-sm text-(--t-2)">
                          {trace.output_preview || "No preview available for this step."}
                        </p>

                        <div className="mt-4 grid grid-cols-3 gap-2">
                          <div className="rounded-(--r-sm) border-0 bg-white px-2 py-2 font-(family-name:--mono) text-[10.5px] text-(--t-3)">
                            <Clock3 className="mb-1 h-3 w-3 text-(--t-2)" />
                            {formatMs(trace.latency_ms)}
                          </div>
                          <div className="rounded-(--r-sm) border-0 bg-white px-2 py-2 font-(family-name:--mono) text-[10.5px] text-(--t-3)">
                            <Coins className="mb-1 h-3 w-3 text-(--t-2)" />
                            {formatMoney(trace.cost_usd)}
                          </div>
                          <div className="rounded-(--r-sm) border-0 bg-white px-2 py-2 font-(family-name:--mono) text-[10.5px] text-(--t-3)">
                            <GitBranch className="mb-1 h-3 w-3 text-(--t-2)" />
                            {trace.claim_count} claims
                          </div>
                        </div>
                      </button>
                    ))}
                  </div>
                </section>
              ))
            ) : (
              <section className={WSEC}>
                <p className="text-sm text-(--t-2)">
                  No persisted debate traces were found for this audit.
                </p>
              </section>
            )}
          </div>

          <div className="space-y-5">
            <section className={WSEC}>
              <h2 className={SEC_TITLE}>
                <Bot size={14} className="text-(--purple)" />
                Agent output
              </h2>

              {isLoadingOutput ? (
                <p className={MONO_META}>Loading agent output...</p>
              ) : selectedOutput ? (
                <div className="space-y-4">
                  <div className={INSET}>
                    <p className="text-[13px] font-semibold text-(--t-1)">
                      {formatRole(selectedOutput.agent_role)}
                    </p>
                    <p className="mt-1 text-[11px] text-(--t-2)">
                      {selectedOutput.provider} / {selectedOutput.model}
                    </p>
                    <div className="mt-3 flex flex-wrap gap-2">
                      <span className={`${CHIP} text-(--t-2) bg-(--panel)`}>
                        {formatStatus(selectedOutput.status)}
                      </span>
                      <span className={`${CHIP} text-(--t-2) bg-(--panel)`}>
                        {formatMs(selectedOutput.latency_ms)}
                      </span>
                      <span className={`${CHIP} text-(--t-2) bg-(--panel)`}>
                        {formatMoney(selectedOutput.cost_usd)}
                      </span>
                    </div>
                    {selectedOutput.created_at && (
                      <p className="mt-3 text-[11px] text-(--t-3)">
                        Captured{" "}
                        <ClientSafeDate date={selectedOutput.created_at} format="datetime" />
                      </p>
                    )}
                  </div>

                  {suggestedClaimIds.length > 0 && (
                    <div>
                      <p className={`${MICRO_LABEL} mb-2`}>Claim IDs from this step</p>
                      <div className="flex flex-wrap gap-2">
                        {suggestedClaimIds.map((item) => (
                          <Button
                            key={item}
                            type="button"
                            variant="ghost"
                            onClick={() => void loadJourney(item)}
                            className="h-8 px-3 font-(family-name:--mono) text-[11px]"
                          >
                            {item}
                          </Button>
                        ))}
                      </div>
                    </div>
                  )}

                  <div className="space-y-3">
                    <div>
                      <p className={`${MICRO_LABEL} mb-2`}>Input</p>
                      <pre className={PRE_BLOCK}>
                        {JSON.stringify(selectedOutput.input_payload ?? {}, null, 2)}
                      </pre>
                    </div>
                    <div>
                      <p className={`${MICRO_LABEL} mb-2`}>Output</p>
                      <pre className={`${PRE_BLOCK} max-h-[320px]`}>
                        {JSON.stringify(selectedOutput.output_raw ?? {}, null, 2)}
                      </pre>
                    </div>
                  </div>
                </div>
              ) : (
                <p className="text-sm text-(--t-2)">
                  Select a timeline step to inspect its stored payload.
                </p>
              )}
            </section>

            <section className={WSEC}>
              <h2 className={SEC_TITLE}>
                <Shield size={14} className="text-(--purple)" />
                Claim journey
              </h2>

              <form
                className="space-y-3"
                onSubmit={(event) => {
                  event.preventDefault();
                  void loadJourney(claimId);
                }}
              >
                <div className="space-y-1.5">
                  <label className={MICRO_LABEL} htmlFor="claim-id-input">
                    Claim ID
                  </label>
                  <input
                    id="claim-id-input"
                    aria-label="Claim ID"
                    type="text"
                    placeholder="seo-01"
                    value={claimId}
                    onChange={(event) => setClaimId(event.target.value)}
                    className={WINPUT}
                  />
                </div>
                <Button type="submit" variant="ghost" loading={isLoadingJourney}>
                  <Search size={14} />
                  Load journey
                </Button>
              </form>

              {journeyError && (
                <Alert variant="destructive" className="mt-3">
                  <AlertDescription>{journeyError}</AlertDescription>
                </Alert>
              )}

              {journey && (
                <div className="mt-5 space-y-3">
                  <div className={INSET}>
                    <p className="font-(family-name:--mono) text-[12px] font-semibold text-(--t-1)">
                      {journey.claim_id}
                    </p>
                    {journey.claim_text && (
                      <p className="mt-2 text-sm text-(--t-2)">{journey.claim_text}</p>
                    )}
                  </div>

                  {journey.journey.length ? (
                    journey.journey.map((step, index) => (
                      <div key={`${step.agent}-${index}`} className={INSET}>
                        <div className="flex items-start justify-between gap-3">
                          <div>
                            <p className="text-[13px] font-semibold text-(--t-1)">
                              Layer {step.layer}: {formatRole(step.agent)}
                            </p>
                            <p className="mt-1 text-[11px] text-(--t-2)">
                              {step.provider} / {step.model}
                            </p>
                          </div>
                          <span className={`${CHIP} text-(--purple) bg-(--purple-s)`}>
                            {formatRole(step.action)}
                          </span>
                        </div>

                        <div className="mt-3 space-y-2 text-sm text-(--t-2)">
                          {typeof step.confidence === "number" && (
                            <p>Confidence: {step.confidence.toFixed(2)}</p>
                          )}
                          {typeof step.new_confidence === "number" && (
                            <p>New confidence: {step.new_confidence.toFixed(2)}</p>
                          )}
                          {step.disposition && <p>Disposition: {formatRole(step.disposition)}</p>}
                          {step.suggested_disposition && (
                            <p>Suggested disposition: {formatRole(step.suggested_disposition)}</p>
                          )}
                          {step.critique && <p>Critique: {step.critique}</p>}
                          {step.critique_reference && (
                            <p>Critique ref: {step.critique_reference}</p>
                          )}
                          {step.recommended_action && (
                            <p>Recommended action: {step.recommended_action}</p>
                          )}
                        </div>
                      </div>
                    ))
                  ) : (
                    <p className="text-sm text-(--t-2)">
                      No persisted journey steps were found for that claim ID.
                    </p>
                  )}
                </div>
              )}
            </section>
          </div>
        </div>
      )}
    </>
  );
}
