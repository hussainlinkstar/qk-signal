import React, { useMemo, useState } from "react";
import Card from "@/components/ui/Card";
import type { CompetitorSnippetComparison } from "@/types/auditResult";

type SnippetBattle = CompetitorSnippetComparison;

const formatScore = (value: number | null): string =>
  value === null ? "N/A" : `${Math.round(value)}`;

export default function SnippetBattlePanel({ snippets }: { snippets: SnippetBattle[] }) {
  const [selectedQuery, setSelectedQuery] = useState(snippets[0]?.query ?? "");
  const [selectedCompetitorDomain, setSelectedCompetitorDomain] = useState("");

  const activeSnippet = useMemo(
    () => snippets.find((snippet) => snippet.query === selectedQuery) ?? snippets[0] ?? null,
    [selectedQuery, snippets]
  );

  const competitors = useMemo(
    () => activeSnippet?.competitors?.filter((item) => item.domain) ?? [],
    [activeSnippet]
  );

  const selectedCompetitor = useMemo(() => {
    if (!activeSnippet) {
      return null;
    }

    if (selectedCompetitorDomain) {
      const exact = competitors.find((item) => item.domain === selectedCompetitorDomain);
      if (exact) {
        return exact;
      }
    }

    if (activeSnippet.competitor?.domain) {
      const winnerCompetitor = competitors.find(
        (item) => item.domain === activeSnippet.competitor?.domain
      );
      if (winnerCompetitor) {
        return winnerCompetitor;
      }
    }

    return competitors[0] ?? null;
  }, [activeSnippet, competitors, selectedCompetitorDomain]);

  return (
    <Card className="space-y-4 p-6">
      <div>
        <h3 className="text-lg font-semibold text-(--t-1)">Battle for the Snippet</h3>
        <p className="text-sm text-(--t-2)">Compare direct-answer extracts for the same query.</p>
      </div>

      {snippets.length === 0 ? (
        <p className="text-sm text-(--t-2)">No query benchmark data available yet.</p>
      ) : (
        <>
          <label
            className="block text-[10px] font-bold tracking-widest uppercase text-(--t-3) mb-2"
            htmlFor="snippet-query"
          >
            Select query
          </label>
          <select
            id="snippet-query"
            value={activeSnippet?.query ?? ""}
            onChange={(event) => {
              setSelectedQuery(event.target.value);
              setSelectedCompetitorDomain("");
            }}
            className="w-full rounded-xl border border-(--line) bg-(--line-2) px-4 py-3 text-sm font-medium text-(--t-1) shadow-inner transition-colors focus:border-cyan-500/50 focus:outline-hidden focus:ring-1 focus:ring-cyan-500/50"
          >
            {snippets.map((snippet) => (
              <option key={snippet.query} value={snippet.query}>
                {snippet.query}
              </option>
            ))}
          </select>

          {activeSnippet ? (
            <>
              <label
                className="block mt-4 text-[10px] font-bold tracking-widest uppercase text-(--t-3) mb-2"
                htmlFor="snippet-competitor"
              >
                Select competitor
              </label>
              <select
                id="snippet-competitor"
                value={selectedCompetitor?.domain ?? ""}
                onChange={(event) => setSelectedCompetitorDomain(event.target.value)}
                className="w-full rounded-xl border border-(--line) bg-(--line-2) px-4 py-3 text-sm font-medium text-(--t-1) shadow-inner transition-colors focus:border-cyan-500/50 focus:outline-hidden focus:ring-1 focus:ring-cyan-500/50 disabled:opacity-50"
                disabled={competitors.length === 0}
              >
                {competitors.length === 0 ? (
                  <option value="">No competitors for this query</option>
                ) : (
                  competitors.map((item) => (
                    <option key={item.domain} value={item.domain ?? ""}>
                      {item.display_name ?? item.domain}
                    </option>
                  ))
                )}
              </select>

              <div className="mt-6 overflow-x-auto rounded-xl border border-(--line) shadow-inner">
                <table className="min-w-full text-left text-sm text-(--t-1)">
                  <thead className="bg-(--line-2) text-xs uppercase tracking-wider text-(--t-2)">
                    <tr>
                      <th className="px-3 py-2">Metric</th>
                      <th className="px-3 py-2">Site</th>
                      <th className="px-3 py-2">Competitor</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr className="border-t border-(--line) transition-colors hover:bg-(--line-2)">
                      <td className="px-4 py-3 text-(--t-2) font-medium">Domain</td>
                      <td className="px-4 py-3 font-semibold text-(--t-1)">
                        {activeSnippet.site.domain}
                      </td>
                      <td className="px-4 py-3 font-semibold text-(--t-1)">
                        {selectedCompetitor?.domain ?? "N/A"}
                      </td>
                    </tr>
                    <tr className="border-t border-(--line) transition-colors hover:bg-(--line-2)">
                      <td className="px-4 py-3 text-(--t-2) font-medium">Answer relevance</td>
                      <td className="px-4 py-3 text-thoth-brass font-semibold">
                        {formatScore(activeSnippet.site.answer_relevance)}
                      </td>
                      <td className="px-4 py-3 text-amber-500 font-semibold">
                        {formatScore(selectedCompetitor?.answer_relevance ?? null)}
                      </td>
                    </tr>
                    <tr className="border-t border-(--line) transition-colors hover:bg-(--line-2)">
                      <td className="px-4 py-3 text-(--t-2) font-medium">Result</td>
                      <td className="px-4 py-3 text-(--t-2)">
                        {activeSnippet.result_state ?? "no_data"}
                      </td>
                      <td className="px-4 py-3 text-(--t-2)">
                        {activeSnippet.winner_reason ?? "-"}
                      </td>
                    </tr>
                    <tr className="border-t border-(--line) transition-colors hover:bg-(--line-2)">
                      <td className="px-4 py-3 text-(--t-2) font-medium">Score source</td>
                      <td className="px-4 py-3 text-(--t-2) capitalize">
                        {activeSnippet.site.answer_relevance_source ?? "unknown"}
                      </td>
                      <td className="px-4 py-3 text-(--t-2) capitalize">
                        {selectedCompetitor?.answer_relevance_source ?? "unknown"}
                      </td>
                    </tr>
                  </tbody>
                </table>
              </div>

              <div className="mt-6 grid gap-4 lg:grid-cols-2">
                <div className="rounded-xl border border-cyan-500/30 bg-cyan-500/5 p-5 shadow-inner">
                  <p className="text-[10px] uppercase font-bold tracking-widest text-cyan-500">
                    Main Site
                  </p>
                  <p className="mt-2 text-base font-bold text-(--t-1)">
                    {activeSnippet.site.domain}
                  </p>
                  <p className="mt-1 text-xs font-semibold text-(--t-2)">
                    Answer relevance:{" "}
                    <span className="text-(--purple)">
                      {formatScore(activeSnippet.site.answer_relevance)}
                    </span>
                  </p>
                  <p className="mt-3 text-sm font-medium text-(--t-2) leading-relaxed">
                    {activeSnippet.site.answer_excerpt ?? "No direct answer snippet available."}
                  </p>
                </div>

                <div className="rounded-xl border border-amber-500/30 bg-amber-500/5 p-5 shadow-inner">
                  <p className="text-[10px] uppercase font-bold tracking-widest text-amber-500">
                    Competitor
                  </p>
                  {selectedCompetitor?.domain ? (
                    <>
                      <p className="mt-2 text-base font-bold text-(--t-1)">
                        {selectedCompetitor.domain}
                      </p>
                      <p className="mt-1 text-xs font-semibold text-(--t-2)">
                        Answer relevance:{" "}
                        <span className="text-amber-500">
                          {formatScore(selectedCompetitor.answer_relevance)}
                        </span>
                      </p>
                      <p className="mt-3 text-sm font-medium text-(--t-2) leading-relaxed">
                        {selectedCompetitor.answer_excerpt ??
                          "No competitor snippet available for this query."}
                      </p>
                    </>
                  ) : (
                    <p className="mt-3 text-sm text-(--t-2)">
                      No competitor data available for the selected query.
                    </p>
                  )}
                </div>
              </div>
            </>
          ) : null}
        </>
      )}
    </Card>
  );
}
