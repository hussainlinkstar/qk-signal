import React from "react";
import { render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import ScanResults from "@/app/(app)/dashboard/audit/[id]/report/ScanResults";
import { tEn } from "@/test/i18nEn";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: tEn }),
}));

const renderResults = (aiVisibility: { score: number; measuredAt: string | null } | null) =>
  render(<ScanResults aioScore={42} seoScore={61} aiVisibility={aiVisibility} comparison={null} />);

// ---------------------------------------------------------------------------
// SIGV2-1295: the AI visibility caption was its own provenance sentence, 80
// characters in a 22ch column. It wrapped to four lines while its two
// neighbours wrapped to two, and the row aligns on its tallest item, so one
// long caption lifted the scores beside it.
// ---------------------------------------------------------------------------

describe("ScanResults, the AI visibility figure", () => {
  it("captions the figure the way its neighbours are captioned", () => {
    renderResults({ score: 17, measuredAt: "2026-10-09T10:00:00Z" });

    const caption = tEn("signalAuditReport.scores.aiVisibilityFine");

    // Says what the score means, like "How you rank in traditional search"
    // does, rather than where the number came from.
    expect(screen.getByText(caption)).toBeInTheDocument();
    expect(screen.queryByText(/not by this scan/i)).not.toBeInTheDocument();
  });

  it("keeps the three captions within a line of each other", () => {
    // The actual defect was relative height, so the guard is relative length.
    // A caption materially longer than its neighbours wraps further and lifts
    // the row again, which is exactly what happened the first time.
    const aio = tEn("signalAuditReport.scores.aioFine");
    const seo = tEn("signalAuditReport.scores.seoFine");
    const ai = tEn("signalAuditReport.scores.aiVisibilityFine");

    const lines = (text: string) => Math.ceil(text.length / 22);

    expect(lines(ai)).toBeLessThanOrEqual(Math.max(lines(aio), lines(seo)));
  });

  it("keeps the provenance, as a tooltip rather than as body text", () => {
    const { container } = renderResults({ score: 17, measuredAt: "2026-10-09T10:00:00Z" });

    // The detail is not lost, it is moved: the trigger is labelled and
    // reachable, and the sentence is its content.
    const trigger = screen.getByLabelText(
      tEn("signalAuditReport.scores.aiVisibilityProvenanceLabel")
    );
    expect(trigger).toBeInTheDocument();
    expect(container).toBeTruthy();
  });

  it("does not render a provenance marker on the figures that have none", () => {
    renderResults(null);

    expect(
      screen.queryByLabelText(tEn("signalAuditReport.scores.aiVisibilityProvenanceLabel"))
    ).not.toBeInTheDocument();
  });

  it("still shows the other two figures", () => {
    renderResults({ score: 17, measuredAt: null });

    const aio = screen.getByText(tEn("signalAuditReport.scores.aioFine"));
    const seo = screen.getByText(tEn("signalAuditReport.scores.seoFine"));
    expect(aio).toBeInTheDocument();
    expect(seo).toBeInTheDocument();
    expect(within(document.body).getByText("42")).toBeInTheDocument();
  });
});
