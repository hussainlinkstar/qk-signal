import React from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import { describe, expect, it, vi } from "vitest";

import VisibilitySearchTypeCoverage from "./VisibilitySearchTypeCoverage";
import type { SearchTypeCoverageEntry } from "@/types/monitoring";

const entry = (
  id: SearchTypeCoverageEntry["id"],
  overrides: Partial<SearchTypeCoverageEntry> = {}
): SearchTypeCoverageEntry => ({
  id,
  label: id.charAt(0).toUpperCase() + id.slice(1),
  premium: id === "comparison",
  prompt_count: 0,
  covered: false,
  suggested_prompt: `What is Acme and what does it offer? (${id})`,
  ...overrides,
});

const fullGap: SearchTypeCoverageEntry[] = [
  entry("brand"),
  entry("category"),
  entry("problem"),
  entry("feature"),
  entry("comparison"),
];

describe("VisibilitySearchTypeCoverage (SIGV2-1186)", () => {
  it("names every one of the five types and how many are covered", () => {
    render(
      <VisibilitySearchTypeCoverage
        coverage={[
          entry("brand", { covered: true, prompt_count: 2, suggested_prompt: null }),
          entry("category"),
          entry("problem"),
          entry("feature"),
          entry("comparison"),
        ]}
      />
    );

    expect(screen.getByTestId("coverage-summary")).toHaveTextContent("1 of 5 search types covered");
    for (const id of ["brand", "category", "problem", "feature", "comparison"]) {
      expect(screen.getByTestId(`coverage-${id}`)).toBeInTheDocument();
    }
    expect(screen.getByTestId("coverage-brand")).toHaveTextContent("2 prompts");
    expect(screen.getByTestId("coverage-problem")).toHaveTextContent("No prompt yet");
  });

  // The honest claim the ticket is about: an uncovered type is not a bad score,
  // it is nothing measured, and the copy has to say so before a scan runs.
  it("says an uncovered type is unmeasured rather than low-scoring", () => {
    render(<VisibilitySearchTypeCoverage coverage={fullGap} />);
    expect(
      screen.getByText(/a type with no prompt is not a low score, it is nothing measured/i)
    ).toBeInTheDocument();
  });

  it("offers the prompt that would fill each gap, and nothing for a covered type", () => {
    render(
      <VisibilitySearchTypeCoverage
        coverage={[
          entry("brand", { covered: true, prompt_count: 1, suggested_prompt: null }),
          entry("category"),
          entry("problem"),
          entry("feature"),
          entry("comparison"),
        ]}
      />
    );

    expect(screen.getByTestId("coverage-problem")).toHaveTextContent(
      "What is Acme and what does it offer? (problem)"
    );
    expect(screen.getByTestId("coverage-brand")).not.toHaveTextContent("Suggested prompt");
  });

  it("fills one named gap with the entry the customer was shown", async () => {
    const onFillGap = vi.fn().mockResolvedValue(undefined);
    render(<VisibilitySearchTypeCoverage coverage={fullGap} onFillGap={onFillGap} />);

    const problem = screen.getByTestId("coverage-problem");
    fireEvent.click(problem.querySelector("button")!);

    await waitFor(() => expect(onFillGap).toHaveBeenCalledTimes(1));
    expect(onFillGap.mock.calls[0][0].id).toBe("problem");
  });

  it("offers one action for every gap at once", async () => {
    const onGenerateAll = vi.fn().mockResolvedValue(undefined);
    render(<VisibilitySearchTypeCoverage coverage={fullGap} onGenerateAll={onGenerateAll} />);

    fireEvent.click(screen.getByRole("button", { name: /add a prompt for each gap/i }));
    await waitFor(() => expect(onGenerateAll).toHaveBeenCalledTimes(1));
  });

  it("hides the bulk action once every type is covered", () => {
    render(
      <VisibilitySearchTypeCoverage
        coverage={fullGap.map((item) => ({
          ...item,
          covered: true,
          prompt_count: 1,
          suggested_prompt: null,
        }))}
        onGenerateAll={vi.fn()}
      />
    );
    expect(screen.queryByRole("button", { name: /add a prompt for each gap/i })).toBeNull();
    expect(screen.getByTestId("coverage-summary")).toHaveTextContent("5 of 5 search types covered");
  });

  // A refusal must be stated, with the reason, and the button must not look
  // available. Both states are served by the API, never guessed here.
  it("states why a gap cannot be filled when the plan does not track prompts", () => {
    render(<VisibilitySearchTypeCoverage coverage={fullGap} onGenerateAll={vi.fn()} locked />);
    expect(screen.getByText(/not included on this plan/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /add a prompt for each gap/i })).toBeDisabled();
  });

  it("states why a gap cannot be filled when the prompt allowance is used up", () => {
    render(<VisibilitySearchTypeCoverage coverage={fullGap} onGenerateAll={vi.fn()} capReached />);
    expect(screen.getByText(/prompt allowance is fully used/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /add a prompt for each gap/i })).toBeDisabled();
  });

  it("renders an explicit empty state rather than claiming nothing is covered", () => {
    render(<VisibilitySearchTypeCoverage coverage={[]} />);
    expect(screen.getByText(/coverage is not available for this project/i)).toBeInTheDocument();
    expect(screen.queryByTestId("coverage-summary")).toBeNull();
  });

  it("shows a loading state while coverage is being fetched", () => {
    render(<VisibilitySearchTypeCoverage coverage={[]} loading />);
    expect(screen.getByRole("status")).toHaveTextContent(/loading search-type coverage/i);
  });
});
