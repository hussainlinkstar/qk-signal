import React from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import SnippetBattlePanel from "@/components/dashboard/aeo/SnippetBattlePanel";

describe("SnippetBattlePanel", () => {
  it("shows empty state when no queries are available", () => {
    render(<SnippetBattlePanel snippets={[]} />);

    expect(screen.getByText("No query benchmark data available yet.")).toBeInTheDocument();
  });

  it("renders competitor fallback when selected query has no competitor data", () => {
    render(
      <SnippetBattlePanel
        snippets={[
          {
            query: "what is aeo",
            winner: "site",
            result_state: "won",
            site: {
              domain: "example.com",
              answer_relevance: 88,
              answer_excerpt: "AEO means answer engine optimization.",
            },
            competitor: {
              domain: null,
              answer_relevance: null,
              answer_excerpt: null,
            },
            competitors: [],
          },
        ]}
      />
    );

    expect(screen.getByText("Main Site")).toBeInTheDocument();
    expect(
      screen.getByText("No competitor data available for the selected query.")
    ).toBeInTheDocument();
    expect(screen.getByText("No competitors for this query")).toBeInTheDocument();
  });

  it("allows selecting a competitor for the same query and shows table values", () => {
    render(
      <SnippetBattlePanel
        snippets={[
          {
            query: "best crm",
            winner: "competitor",
            winner_reason: "score_delta",
            result_state: "lost",
            site: {
              domain: "example.com",
              answer_relevance: 75,
              answer_excerpt: "Site snippet",
              answer_relevance_source: "aeo.answer_relevance",
            },
            competitor: {
              domain: "rival-b.com",
              answer_relevance: 90,
              answer_excerpt: "Rival B snippet",
            },
            competitors: [
              {
                domain: "rival-a.com",
                display_name: "Rival A",
                answer_relevance: 80,
                answer_excerpt: "Rival A snippet",
                answer_relevance_source: "analysis.answer_relevance",
              },
              {
                domain: "rival-b.com",
                display_name: "Rival B",
                answer_relevance: 90,
                answer_excerpt: "Rival B snippet",
                answer_relevance_source: "aeo.answer_relevance",
              },
            ],
          },
        ]}
      />
    );

    fireEvent.change(screen.getByLabelText("Select competitor"), {
      target: { value: "rival-a.com" },
    });

    expect(screen.getByText("Result")).toBeInTheDocument();
    expect(screen.getByText("lost")).toBeInTheDocument();
    expect(screen.getByText("score_delta")).toBeInTheDocument();
    expect(screen.getByText("analysis.answer_relevance")).toBeInTheDocument();
    expect(screen.getByText("Rival A snippet")).toBeInTheDocument();
  });
});
