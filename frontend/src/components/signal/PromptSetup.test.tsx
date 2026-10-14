import React from "react";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import PromptSetup from "@/components/signal/PromptSetup";
import type { ScanPromptsState } from "@/hooks/useScanPrompts";
import { tEn } from "@/test/i18nEn";
import type {
  SearchTypeCoverageEntry,
  SearchTypeId,
  VisibilityEntitlements,
  VisibilityQuery,
} from "@/types/monitoring";

const { createMock, updateMock, deleteMock, generateBaseMock } = vi.hoisted(() => ({
  createMock: vi.fn(),
  updateMock: vi.fn(),
  deleteMock: vi.fn(),
  generateBaseMock: vi.fn(),
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: tEn }),
}));

vi.mock("@/services/monitoringService", () => ({
  createVisibilityQuery: (...args: unknown[]) => createMock(...args),
  updateVisibilityQuery: (...args: unknown[]) => updateMock(...args),
  deleteVisibilityQuery: (...args: unknown[]) => deleteMock(...args),
  generateBaseVisibilityPrompts: (...args: unknown[]) => generateBaseMock(...args),
}));

// The existing dialog is covered by its own surface; here it only matters
// that "Add your own" opens it.
vi.mock("@/components/signal/SignalAddPromptModal", () => ({
  default: ({ open }: { open: boolean }) => (open ? <div data-testid="add-prompt-modal" /> : null),
}));

vi.mock("next/link", () => ({
  default: ({ href, children, ...rest }: { href: string; children: React.ReactNode }) => (
    <a href={href} {...rest}>
      {children}
    </a>
  ),
}));

const entitlements: VisibilityEntitlements = {
  plan: "plan_standard",
  plan_label: "Standard",
  upgrade_plan: "plan_specialist",
  upgrade_plan_label: "Specialist",
  upgrade_max_queries: 50,
  max_queries: 10,
  used_queries: 4,
  remaining_queries: 6,
  allowed_providers: ["openai"],
  is_locked: false,
  estimated_cost_per_check: {},
};

const prompt = (
  id: number,
  text: string,
  overrides: Partial<VisibilityQuery> = {}
): VisibilityQuery => ({
  id,
  project_id: 42,
  query_text: text,
  query_type: "aeo",
  providers: ["openai"],
  is_active: true,
  is_generated: true,
  origin: "generated",
  created_at: null,
  updated_at: null,
  ...overrides,
});

const STARTER_PROMPTS: VisibilityQuery[] = [
  prompt(1, "What is Northwind Hotels known for?", { search_type: "brand" }),
  prompt(2, "Which boutique hotels are worth considering?", { search_type: "category" }),
  prompt(3, "Where can I stay for a quiet night?", { search_type: "problem" }),
];

const coverageEntry = (
  id: SearchTypeId,
  covered: boolean,
  suggested: string | null = null
): SearchTypeCoverageEntry => ({
  id,
  label: id,
  premium: false,
  prompt_count: covered ? 1 : 0,
  covered,
  suggested_prompt: suggested,
});

const COVERAGE_GAP: SearchTypeCoverageEntry[] = [
  coverageEntry("brand", true),
  coverageEntry("category", true),
  coverageEntry("problem", true),
  coverageEntry("feature", false, "Which waterfront hotels have soundproof rooms?"),
  coverageEntry("comparison", false, "How does Northwind Hotels compare with Coastline Resorts?"),
];

const COVERAGE_FULL: SearchTypeCoverageEntry[] = [
  coverageEntry("brand", true),
  coverageEntry("category", true),
  coverageEntry("problem", true),
  coverageEntry("feature", true),
  coverageEntry("comparison", true),
];

const state = (overrides: Partial<ScanPromptsState> = {}): ScanPromptsState => ({
  projectId: 42,
  prompts: STARTER_PROMPTS,
  coverage: COVERAGE_GAP,
  entitlements,
  project: null,
  isLoading: false,
  error: null,
  canAddPrompt: true,
  isPlanLocked: false,
  hasPrompt: true,
  blocksLaunch: false,
  reload: vi.fn().mockResolvedValue(undefined),
  ...overrides,
});

const getAuthHeaders = vi.fn().mockResolvedValue({ Authorization: "Bearer token" });

const renderSetup = (s = state(), mode: "scan" | "manage" = "scan") =>
  render(<PromptSetup mode={mode} state={s} getAuthHeaders={getAuthHeaders} />);

describe("PromptSetup (SIGV2-1194)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders one collapsible group per canonical search type, in order", () => {
    renderSetup();

    // <details> has no implicit role; the canonical order is asserted on the
    // group elements themselves.
    const groups = Array.from(document.querySelectorAll("details[data-prompt-group]"));
    expect(groups.map((g) => g.getAttribute("data-prompt-group"))).toEqual([
      "brand",
      "category",
      "problem",
      "feature",
      "comparison",
    ]);
    const labels = ["Brand", "Category", "Problem", "Feature", "Comparison"];
    labels.forEach((label, i) =>
      expect(within(groups[i] as HTMLElement).getByText(label)).toBeInTheDocument()
    );
  });

  it("marks an uncovered type 'No prompts', opens it and offers its starter", () => {
    renderSetup();

    const comparisonGroup = document.querySelector(
      "details[data-prompt-group='comparison']"
    ) as HTMLDetailsElement;
    expect(comparisonGroup.open).toBe(true);
    expect(within(comparisonGroup).getByText("No prompts")).toBeInTheDocument();
    expect(
      within(comparisonGroup).getByRole("button", { name: /add comparison starter/i })
    ).toBeInTheDocument();
  });

  it("adds a single type's starter from the served suggestion, not generate-base", async () => {
    createMock.mockResolvedValue(prompt(9, "x"));
    renderSetup();

    const comparisonGroup = document.querySelector(
      "details[data-prompt-group='comparison']"
    ) as HTMLElement;
    fireEvent.click(
      within(comparisonGroup).getByRole("button", { name: /add comparison starter/i })
    );

    await waitFor(() =>
      expect(createMock).toHaveBeenCalledWith(
        42,
        {
          query_text: "How does Northwind Hotels compare with Coastline Resorts?",
          query_type: "aeo",
          providers: ["openai"],
          search_type: "comparison",
        },
        { Authorization: "Bearer token" }
      )
    );
    expect(generateBaseMock).not.toHaveBeenCalled();
  });

  it("fills every gap at once through generate-base", async () => {
    generateBaseMock.mockResolvedValue({ created: [] });
    renderSetup();

    fireEvent.click(screen.getByRole("button", { name: "Fill the gaps" }));

    await waitFor(() =>
      expect(generateBaseMock).toHaveBeenCalledWith(42, {
        Authorization: "Bearer token",
      })
    );
  });

  it("rewords a prompt through update with query_text", async () => {
    updateMock.mockResolvedValue(prompt(1, "x"));
    renderSetup();

    fireEvent.click(
      screen.getByRole("button", { name: "Edit: What is Northwind Hotels known for?" })
    );
    const editor = screen.getByLabelText("Question");
    fireEvent.change(editor, {
      target: { value: "What do guests say about Northwind Hotels?" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));

    await waitFor(() =>
      expect(updateMock).toHaveBeenCalledWith(
        42,
        1,
        { query_text: "What do guests say about Northwind Hotels?" },
        { Authorization: "Bearer token" }
      )
    );
  });

  it("never offers a search-type choice anywhere", () => {
    renderSetup(state(), "manage");
    expect(screen.queryByRole("combobox")).toBeNull();

    // The editor states the assignment instead of asking for one.
    fireEvent.click(
      screen.getByRole("button", { name: "Edit: What is Northwind Hotels known for?" })
    );
    expect(screen.getByText(/Signal assigns the search type/)).toBeInTheDocument();
    expect(screen.queryByRole("combobox")).toBeNull();
  });

  it("shows the starter badge while every prompt is generated, then 'Project prompts'", () => {
    const { unmount } = renderSetup();
    expect(screen.getByText("Signal starter set")).toBeInTheDocument();
    unmount();

    renderSetup(
      state({
        prompts: [...STARTER_PROMPTS, prompt(9, "my own question", { is_generated: false })],
      })
    );
    expect(screen.getByText("Project prompts")).toBeInTheDocument();
  });

  it("shows the coverage-gap notice as information when a type is uncovered", () => {
    renderSetup();

    const note = screen.getByText(/an untested type has no score/);
    expect(note.closest("[data-signal-inline-note]")).toHaveAttribute(
      "data-signal-inline-note",
      "info"
    );
    expect(screen.getByText("3 of 5 search types covered")).toBeInTheDocument();
  });

  it("distinguishes 'no prompts at all' from a partial gap, per mode", () => {
    const { unmount } = renderSetup(state({ prompts: [], hasPrompt: false, blocksLaunch: true }));
    // Scan mode: the one refusal, in danger.
    const refusal = screen.getByText(/Add at least one prompt before you start the scan/);
    expect(refusal.closest("[data-signal-inline-note]")).toHaveAttribute(
      "data-signal-inline-note",
      "danger"
    );
    unmount();

    renderSetup(state({ prompts: [], hasPrompt: false, blocksLaunch: true }), "manage");
    const note = screen.getByText(/No prompts yet/);
    expect(note.closest("[data-signal-inline-note]")).toHaveAttribute(
      "data-signal-inline-note",
      "warning"
    );
    expect(screen.queryByText(/Add at least one prompt before you start the scan/)).toBeNull();
  });

  it("renders no gap notice when every type is covered", () => {
    renderSetup(state({ coverage: COVERAGE_FULL }));

    expect(screen.queryByText(/an untested type has no score/)).toBeNull();
    expect(screen.getByText("5 of 5 search types covered")).toBeInTheDocument();
  });

  it("files an untyped prompt under Pending classification, stated as unscored", () => {
    renderSetup(
      state({
        prompts: [...STARTER_PROMPTS, prompt(8, "an unclear ask", { search_type: null })],
      })
    );

    const pending = document.querySelector("details[data-prompt-group='pending']") as HTMLElement;
    expect(pending).not.toBeNull();
    expect(within(pending).getByText("Pending classification")).toBeInTheDocument();
    expect(within(pending).getByText(/not scored under any search type/)).toBeInTheDocument();
  });

  it("renders no pending group when every prompt resolves to a type", () => {
    renderSetup();
    expect(document.querySelector("details[data-prompt-group='pending']")).toBeNull();
  });

  it("offers Remove only in manage mode, behind the two-step confirm", async () => {
    deleteMock.mockResolvedValue(undefined);
    const { unmount } = renderSetup(state(), "scan");
    expect(screen.queryByRole("button", { name: /^Remove:/ })).toBeNull();
    unmount();

    renderSetup(state(), "manage");
    const removeButtons = screen.getAllByRole("button", { name: /^Remove:/ });
    fireEvent.click(removeButtons[0]);

    // First press arms the confirm; nothing is deleted yet.
    expect(deleteMock).not.toHaveBeenCalled();
    expect(screen.getByText(/Previous results stay unchanged/)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Remove prompt" }));
    await waitFor(() =>
      expect(deleteMock).toHaveBeenCalledWith(42, 1, {
        Authorization: "Bearer token",
      })
    );
  });

  it("links scan mode to the manage surface and back", () => {
    const { unmount } = renderSetup(state(), "scan");
    expect(screen.getByRole("link", { name: "Manage all prompts" })).toHaveAttribute(
      "href",
      "/dashboard/projects/42/ai-answers?tab=prompts"
    );
    expect(screen.queryByRole("link", { name: "Review next scan" })).toBeNull();
    unmount();

    renderSetup(state(), "manage");
    expect(screen.getByRole("link", { name: "Review next scan" })).toHaveAttribute(
      "href",
      "/dashboard/audit?projectId=42"
    );
    expect(screen.queryByRole("link", { name: "Manage all prompts" })).toBeNull();
  });
  // A prompt left pinned to an engine the plan roster stopped measuring
  // (SIGV2-1216 took Gemini off Specialist) is skipped by the sweep and
  // dropped from every aggregate, so without this it renders as a healthy
  // prompt that silently never produces a result.
  describe("engines the plan stopped measuring", () => {
    const DEAD = prompt(1, "What is Northwind Hotels known for?", {
      search_type: "brand",
      providers: [],
      unmeasured_providers: ["google"],
    });

    it("names the dead engine on the row instead of leaving it blank", () => {
      renderSetup(state({ prompts: [DEAD] }), "manage");

      expect(screen.getByText(/Gemini not measured on your plan/)).toBeInTheDocument();
    });

    it("re-points a fully dead prompt at the engine the plan does measure", async () => {
      updateMock.mockResolvedValue(prompt(1, "x"));
      renderSetup(state({ prompts: [DEAD] }), "manage");

      fireEvent.click(
        screen.getByRole("button", {
          name: "Measure on ChatGPT: What is Northwind Hotels known for?",
        })
      );

      await waitFor(() =>
        expect(updateMock).toHaveBeenCalledWith(
          42,
          1,
          { providers: ["openai"] },
          { Authorization: "Bearer token" }
        )
      );
    });

    it("notes the gap but offers no repair while the prompt still measures somewhere", () => {
      const partly = prompt(1, "What is Northwind Hotels known for?", {
        search_type: "brand",
        providers: ["openai"],
        unmeasured_providers: ["google"],
      });
      renderSetup(state({ prompts: [partly] }), "manage");

      expect(screen.getByText(/Gemini not measured on your plan/)).toBeInTheDocument();
      expect(screen.queryByRole("button", { name: /^Measure on/ })).toBeNull();
    });

    it("says nothing about engines on a healthy prompt", () => {
      renderSetup(state(), "manage");

      expect(screen.queryByText(/not measured on your plan/)).toBeNull();
      expect(screen.queryByRole("button", { name: /^Measure on/ })).toBeNull();
    });
  });
});
