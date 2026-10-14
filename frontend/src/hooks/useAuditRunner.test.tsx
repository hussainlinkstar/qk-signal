import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useAuditRunner } from "@/hooks/useAuditRunner";
import { PROJECT_SETUP_FAILURE_I18N_KEYS } from "@/lib/projectSetupFailure";
import { HttpRequestError } from "@/services/http";
import { tEn } from "@/test/i18nEn";

const createAuditJobMock = vi.fn();
const estimateAuditCreditsMock = vi.fn();
const normalizeReportMock = vi.fn();
const toastSuccessMock = vi.fn();
const toastErrorMock = vi.fn();
const fetchWorkspaceProjectsMock = vi.fn();
const createWorkspaceProjectMock = vi.fn();

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: tEn }),
}));

vi.mock("@/services/workspaceService", () => ({
  fetchWorkspaceProjects: (...args: unknown[]) => fetchWorkspaceProjectsMock(...args),
  createWorkspaceProject: (...args: unknown[]) => createWorkspaceProjectMock(...args),
}));

vi.mock("@/services/auditService", () => ({
  createAuditJob: (...args: unknown[]) => createAuditJobMock(...args),
  estimateAuditCredits: (...args: unknown[]) => estimateAuditCreditsMock(...args),
  AuditConflictError: class AuditConflictError extends Error {
    existingJobId: string | null;
    constructor(message: string, existingJobId: string | null = null) {
      super(message);
      this.name = "AuditConflictError";
      this.existingJobId = existingJobId;
    }
  },
}));

vi.mock("@/lib/auditWorkspaceUtils", () => ({
  normalizeReport: (...args: unknown[]) => normalizeReportMock(...args),
}));

vi.mock("sonner", () => ({
  toast: {
    success: (...args: unknown[]) => toastSuccessMock(...args),
    error: (...args: unknown[]) => toastErrorMock(...args),
  },
}));

class FakeEventSource {
  static instances: FakeEventSource[] = [];

  readonly url: string;
  readonly close = vi.fn();
  onopen: ((event: Event) => void) | null = null;
  onerror: ((event: Event) => void) | null = null;
  private listeners = new Map<string, Set<(event: MessageEvent) => void>>();

  constructor(url: string) {
    this.url = url;
    FakeEventSource.instances.push(this);
  }

  addEventListener(type: string, listener: (event: MessageEvent) => void) {
    const listeners = this.listeners.get(type) ?? new Set();
    listeners.add(listener);
    this.listeners.set(type, listeners);
  }

  removeEventListener(type: string, listener: (event: MessageEvent) => void) {
    this.listeners.get(type)?.delete(listener);
  }

  emit(type: string, payload: unknown) {
    const event = { data: JSON.stringify(payload) } as MessageEvent;
    for (const listener of this.listeners.get(type) ?? []) {
      listener(event);
    }
  }

  open() {
    this.onopen?.(new Event("open"));
  }

  error() {
    this.onerror?.(new Event("error"));
  }
}

const originalEventSource = globalThis.EventSource;
const originalFetch = globalThis.fetch;

const createWrapper = () => {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
      },
      mutations: {
        retry: false,
      },
    },
  });

  const TestWrapper = ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
  return TestWrapper;
};

describe("useAuditRunner", () => {
  const invalidateHistoryMock = vi.fn(async () => undefined);
  const upsertHistoryEntryMock = vi.fn();
  const onAuditCompleteMock = vi.fn();
  const fetchAuditRecordMock = vi.fn();

  beforeEach(() => {
    vi.clearAllMocks();
    FakeEventSource.instances = [];
    globalThis.EventSource = FakeEventSource as unknown as typeof EventSource;

    estimateAuditCreditsMock.mockResolvedValue({
      consumes_scan: true,
      scans_used: 2,
      scans_remaining: 8,
      reset_at: null,
      confidence: 0.9,
    });
    createAuditJobMock.mockResolvedValue({
      job_id: "job-1",
      audit_target_type: "website",
      target_name: "Example",
      target_url: "https://example.com",
    });
    fetchWorkspaceProjectsMock.mockResolvedValue([]);
    createWorkspaceProjectMock.mockResolvedValue({ id: 123 });
    normalizeReportMock.mockReturnValue({
      url: "https://example.com",
      analysis: {},
      metadata: {},
    });
    fetchAuditRecordMock.mockResolvedValue({
      id: 42,
      url: "https://example.com",
      audit_target_type: "website",
      target_name: "Example",
      target_url: "https://example.com",
      target_metadata: {},
      geo_score: 81,
      seo_score: 79,
      aeo_score: 77,
      status: "completed",
      audit_type: "SMART",
      created_at: "2026-03-13T10:00:00.000Z",
      project_id: 7,
      full_report: {},
    });

    globalThis.fetch = vi.fn(async () => ({
      ok: true,
      json: async () => ({
        job_id: "job-1",
        status: "queued",
        audit_target_type: "website",
        target_url: "https://example.com",
      }),
    })) as unknown as typeof fetch;
  });

  afterEach(() => {
    globalThis.EventSource = originalEventSource;
    globalThis.fetch = originalFetch;
  });

  it("applies live debate events from EventSource and completes the job without polling", async () => {
    const { result } = renderHook(
      () =>
        useAuditRunner({
          getAuthHeaders: async () => ({ Authorization: "Bearer token" }),
          isSignedIn: true,
          projectId: 99,
          form: {
            auditTargetType: "website",
            url: "https://example.com",
            targetUrl: "https://example.com",
            targetName: "",
            tier: "deep_judgment",
            language: "en",
            market: "us",
            category: "saas",
            entities: [],
            selectedModels: [],
          } as any,
          validateForm: async () => true,
          verifyUrlPreflight: async () => true,
          fetchAuditRecord: fetchAuditRecordMock,
          invalidateHistory: invalidateHistoryMock,
          upsertHistoryEntry: upsertHistoryEntryMock,
          onAuditComplete: onAuditCompleteMock,
        }),
      { wrapper: createWrapper() }
    );

    await waitFor(() => {
      expect(estimateAuditCreditsMock).toHaveBeenCalled();
    });

    await act(async () => {
      await result.current.handleSubmit();
    });

    await waitFor(() => {
      expect(createAuditJobMock).toHaveBeenCalled();
      expect(FakeEventSource.instances).toHaveLength(1);
    });

    const stream = FakeEventSource.instances[0];

    act(() => {
      stream.open();
      stream.emit("step_started", {
        type: "step_started",
        role: "proposer",
        semantic_role: "generator",
        provider: "google",
        model: "gemini-test",
      });
      stream.emit("step_completed", {
        type: "step_completed",
        role: "proposer",
        semantic_role: "generator",
        provider: "google",
        model: "gemini-test",
        summary: "Grounded summary",
        latency_ms: 450,
      });
    });

    await waitFor(() => {
      expect(result.current.isEventStreamConnected).toBe(true);
      expect(result.current.liveDebateProgress?.steps[0]).toMatchObject({
        label: "Generator",
        status: "completed",
        summary: "Grounded summary",
      });
    });

    act(() => {
      stream.emit("debate_finished", {
        type: "debate_finished",
        confidence_score: 0.91,
        profile: "high_confidence",
      });
      stream.emit("job_status", {
        job_id: "job-1",
        status: "succeeded",
        audit_id: 42,
        audit_target_type: "website",
        target_url: "https://example.com",
      });
    });

    await waitFor(() => {
      expect(fetchAuditRecordMock).toHaveBeenCalledWith(42);
      expect(onAuditCompleteMock).toHaveBeenCalledTimes(1);
      // SIGV2-1163: the completion signal names the audit's served project, so
      // the consumer knows which project dashboard the scan belongs to.
      expect(onAuditCompleteMock.mock.calls[0][0]).toEqual(
        expect.objectContaining({ id: 42, projectId: 7 })
      );
      expect(result.current.completionBanner?.title).toBe("Assessment is finished ✨");
    });
  });

  // SIGV2-1163: the completion signal the run view's redirect keys on must
  // never fire for a failed run, which has to keep its failure state.
  it("never signals completion for a failed job", async () => {
    const { result } = renderHook(
      () =>
        useAuditRunner({
          getAuthHeaders: async () => ({ Authorization: "Bearer token" }),
          isSignedIn: true,
          projectId: 99,
          form: {
            auditTargetType: "website",
            url: "https://example.com",
            targetUrl: "https://example.com",
            targetName: "",
            tier: "smart",
            language: "en",
            market: "us",
            category: "saas",
            entities: [],
            selectedModels: [],
          } as any,
          validateForm: async () => true,
          verifyUrlPreflight: async () => true,
          fetchAuditRecord: fetchAuditRecordMock,
          invalidateHistory: invalidateHistoryMock,
          upsertHistoryEntry: upsertHistoryEntryMock,
          onAuditComplete: onAuditCompleteMock,
        }),
      { wrapper: createWrapper() }
    );

    await act(async () => {
      await result.current.handleSubmit();
    });

    await waitFor(() => {
      expect(FakeEventSource.instances).toHaveLength(1);
    });

    act(() => {
      FakeEventSource.instances[0].emit("job_status", {
        job_id: "job-1",
        status: "failed",
        error: "The crawl stage could not reach the site.",
        audit_target_type: "website",
        target_url: "https://example.com",
      });
    });

    await waitFor(() => {
      expect(toastErrorMock).toHaveBeenCalled();
    });
    expect(onAuditCompleteMock).not.toHaveBeenCalled();
    expect(fetchAuditRecordMock).not.toHaveBeenCalled();
    expect(result.current.runSnapshot?.phase).toBe("failed");
  });

  it("falls back to polling when the EventSource stream errors", async () => {
    const { result } = renderHook(
      () =>
        useAuditRunner({
          getAuthHeaders: async () => ({ Authorization: "Bearer token" }),
          isSignedIn: true,
          projectId: 99,
          form: {
            auditTargetType: "website",
            url: "https://example.com",
            targetUrl: "https://example.com",
            targetName: "",
            tier: "smart",
            language: "en",
            market: "us",
            category: "saas",
            entities: [],
            selectedModels: [],
          } as any,
          validateForm: async () => true,
          verifyUrlPreflight: async () => true,
          fetchAuditRecord: fetchAuditRecordMock,
          invalidateHistory: invalidateHistoryMock,
          upsertHistoryEntry: upsertHistoryEntryMock,
          onAuditComplete: onAuditCompleteMock,
        }),
      { wrapper: createWrapper() }
    );

    await act(async () => {
      await result.current.handleSubmit();
    });

    await waitFor(() => {
      expect(FakeEventSource.instances).toHaveLength(1);
    });

    const stream = FakeEventSource.instances[0];
    act(() => {
      stream.open();
      stream.emit("step_started", {
        type: "step_started",
        role: "proposer",
        semantic_role: "generator",
        provider: "google",
        model: "gemini-test",
      });
      stream.error();
    });

    await waitFor(() => {
      expect(result.current.isEventStreamFallback).toBe(true);
      expect(result.current.liveDebateProgress?.mode).toBe("polling_fallback");
    });
  });

  it("seeds a delta-flow layout from pipeline events and updates layered agent progress", async () => {
    const { result } = renderHook(
      () =>
        useAuditRunner({
          getAuthHeaders: async () => ({ Authorization: "Bearer token" }),
          isSignedIn: true,
          projectId: 99,
          form: {
            auditTargetType: "website",
            url: "https://example.com",
            targetUrl: "https://example.com",
            targetName: "",
            tier: "deep_judgment",
            language: "en",
            market: "us",
            category: "saas",
            entities: [],
            selectedModels: [],
          } as any,
          validateForm: async () => true,
          verifyUrlPreflight: async () => true,
          fetchAuditRecord: fetchAuditRecordMock,
          invalidateHistory: invalidateHistoryMock,
          upsertHistoryEntry: upsertHistoryEntryMock,
          onAuditComplete: onAuditCompleteMock,
        }),
      { wrapper: createWrapper() }
    );

    await act(async () => {
      await result.current.handleSubmit();
    });

    await waitFor(() => {
      expect(FakeEventSource.instances).toHaveLength(1);
    });

    const stream = FakeEventSource.instances[0];
    act(() => {
      stream.open();
      stream.emit("pipeline_started", {
        type: "pipeline_started",
        pipeline_type: "delta_flow",
        total_agents: 8,
        parallel_layers: 2,
        estimated_duration_s: 480,
      });
      stream.emit("layer_started", {
        type: "layer_started",
        pipeline_type: "delta_flow",
        layer: 1,
        layer_name: "Specialized Generation",
        agents_in_layer: 3,
        parallel: true,
      });
      stream.emit("step_started", {
        type: "step_started",
        pipeline_type: "delta_flow",
        role: "seo_generator",
        semantic_role: "generator",
        domain: "seo",
        layer: 1,
        provider: "google",
        model: "gemini-test",
      });
      stream.emit("step_completed", {
        type: "step_completed",
        pipeline_type: "delta_flow",
        role: "seo_generator",
        semantic_role: "generator",
        domain: "seo",
        layer: 1,
        provider: "google",
        model: "gemini-test",
        summary: "Grounded SEO proposal",
        latency_ms: 610,
      });
      stream.emit("layer_completed", {
        type: "layer_completed",
        pipeline_type: "delta_flow",
        layer: 1,
        layer_name: "Specialized Generation",
        agents_completed: 1,
        agents_failed: 0,
        total_latency_ms: 610,
      });
      stream.emit("debate_finished", {
        type: "debate_finished",
        pipeline_type: "delta_flow",
        confidence_score: 0.93,
        judge_authority: "primary",
      });
    });

    await waitFor(() => {
      expect(result.current.liveDebateProgress?.pipelineType).toBe("delta_flow");
      expect(result.current.liveDebateProgress?.totalAgents).toBe(8);
      expect(result.current.liveDebateProgress?.layers[0]).toMatchObject({
        label: "Specialized Generation",
        parallel: true,
      });
      expect(result.current.liveDebateProgress?.steps).toHaveLength(8);
      expect(result.current.liveDebateProgress?.steps[0]).toMatchObject({
        label: "SEO Generator",
        status: "completed",
        summary: "Grounded SEO proposal",
      });
      expect(result.current.liveDebateProgress?.steps[1]).toMatchObject({
        label: "AI Visibility Generator",
        status: "pending",
      });
      expect(result.current.liveDebateProgress?.judgeAuthority).toBe("primary");
      expect(result.current.liveDebateProgress?.finished).toBe(true);
    });
  });

  it("skips server credit estimates until a website URL is valid", async () => {
    renderHook(
      () =>
        useAuditRunner({
          getAuthHeaders: async () => ({ Authorization: "Bearer token" }),
          isSignedIn: true,
          projectId: 99,
          form: {
            auditTargetType: "website",
            url: "https://",
            targetUrl: "https://",
            targetName: "",
            tier: "smart",
            language: "en",
            market: "us",
            category: "saas",
            entities: [],
            selectedModels: [],
          } as any,
          validateForm: async () => true,
          verifyUrlPreflight: async () => true,
          fetchAuditRecord: fetchAuditRecordMock,
          invalidateHistory: invalidateHistoryMock,
          upsertHistoryEntry: upsertHistoryEntryMock,
          onAuditComplete: onAuditCompleteMock,
        }),
      { wrapper: createWrapper() }
    );

    await act(async () => {
      await Promise.resolve();
    });

    expect(estimateAuditCreditsMock).not.toHaveBeenCalled();
  });

  // SIGV2-1110. A scan started from /dashboard/audit with no ?projectId has to
  // create the project first. The form's "Main market" is free text and the
  // pre-scan fills it with a country or city name, but the API only accepts an
  // ISO 3166-1 alpha-2 target_country, so sending the raw value made every one
  // of those creations fail and the scan never started.
  const runnerWithoutProject = (market: string) => ({
    getAuthHeaders: async () => ({ Authorization: "Bearer token" }),
    isSignedIn: true,
    form: {
      auditTargetType: "website",
      url: "https://example.com",
      targetUrl: "https://example.com",
      targetName: "",
      tier: "fast",
      language: "en",
      market,
      category: "saas",
      entities: [],
      selectedModels: [],
    } as any,
    validateForm: async () => true,
    verifyUrlPreflight: async () => true,
    fetchAuditRecord: fetchAuditRecordMock,
    invalidateHistory: invalidateHistoryMock,
    upsertHistoryEntry: upsertHistoryEntryMock,
    onAuditComplete: onAuditCompleteMock,
  });

  it("never sends a free-text market as the new project's target country", async () => {
    const { result } = renderHook(() => useAuditRunner(runnerWithoutProject("Romania")), {
      wrapper: createWrapper(),
    });

    await act(async () => {
      await result.current.handleSubmit();
    });

    await waitFor(() => {
      expect(createWorkspaceProjectMock).toHaveBeenCalledTimes(1);
    });

    const [payload] = createWorkspaceProjectMock.mock.calls[0];
    expect(payload.target_country).toBe("RO");
    expect(payload.domain_url).toBe("https://example.com");
    expect(payload.language).toBe("en");

    await waitFor(() => {
      expect(createAuditJobMock).toHaveBeenCalledTimes(1);
    });
    expect(createAuditJobMock.mock.calls[0][0].projectId).toBe(123);
    expect(result.current.error).toBe("");
  });

  it("leaves the target country unset when the market is not a country", async () => {
    // The default market is empty, and an empty string is exactly as invalid
    // for target_country as "Romania" was.
    const { result } = renderHook(() => useAuditRunner(runnerWithoutProject("")), {
      wrapper: createWrapper(),
    });

    await act(async () => {
      await result.current.handleSubmit();
    });

    await waitFor(() => {
      expect(createWorkspaceProjectMock).toHaveBeenCalledTimes(1);
    });
    expect(createWorkspaceProjectMock.mock.calls[0][0].target_country).toBeNull();
  });

  it("explains a project setup failure in terms the customer can act on", async () => {
    createWorkspaceProjectMock.mockRejectedValue(
      new HttpRequestError(403, "Workspace manage access required.")
    );

    const { result } = renderHook(() => useAuditRunner(runnerWithoutProject("Romania")), {
      wrapper: createWrapper(),
    });

    await act(async () => {
      await result.current.handleSubmit();
    });

    await waitFor(() => {
      expect(result.current.error).toBe(tEn(PROJECT_SETUP_FAILURE_I18N_KEYS.noPermission));
    });

    // No internal step name, no server detail text, and nothing that reads as
    // a refusal for being out of scans.
    expect(result.current.error).not.toContain("resolve or create");
    expect(result.current.error).not.toContain("Workspace manage access required.");
    expect(result.current.error.toLowerCase()).not.toContain("credit");
    expect(result.current.error).toContain("No scan was used.");
    expect(createAuditJobMock).not.toHaveBeenCalled();
  });
});
