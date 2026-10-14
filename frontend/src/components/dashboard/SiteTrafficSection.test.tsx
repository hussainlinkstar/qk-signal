import React from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import SiteTrafficSection from "@/components/dashboard/SiteTrafficSection";
import type { UseSiteTrafficResult } from "@/hooks/useSiteTraffic";
import type {
  SiteTrafficChannelBucket,
  SiteTrafficKeyEvents,
  SiteTrafficPayload,
} from "@/types/siteTraffic";
import { tEn } from "@/test/i18nEn";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: tEn }),
}));

const makeState = (overrides: Partial<UseSiteTrafficResult>): UseSiteTrafficResult => ({
  traffic: {
    status: "disconnected",
    availability: "disconnected",
  } as UseSiteTrafficResult["traffic"],
  ga4WorkspaceConnected: null,
  ga4BoundInactive: null,
  loading: false,
  error: null,
  window: "7D",
  setWindow: vi.fn(),
  refetch: vi.fn(),
  ...overrides,
});

// SIGV2-1202: a 403 is not a revoked authorization. The card for it must not
// be the reconnect card, because reconnecting the same account changes
// nothing and the customer comes straight back to the same screen.
describe("SiteTrafficSection permission denied call to action", () => {
  const denied = (reason: string) =>
    ({
      status: "permission_denied",
      availability: "unavailable",
      reason,
    }) as UseSiteTrafficResult["traffic"];

  it("offers the property choice and the account change for a confirmed property denial", () => {
    render(
      <SiteTrafficSection
        projectId="42"
        state={makeState({ traffic: denied("property_denied"), ga4WorkspaceConnected: true })}
      />
    );
    expect(screen.getByText(tEn("siteTraffic.propertyDeniedTitle"))).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: tEn("siteTraffic.choosePropertyCta") })
    ).toHaveAttribute("href", "/dashboard/projects/42/settings#data-sources");
    expect(screen.getByRole("link", { name: tEn("siteTraffic.changeAccountCta") })).toHaveAttribute(
      "href",
      "/dashboard/connections"
    );
    // The reconnect instruction is what the customer had already followed.
    expect(screen.queryByText(tEn("siteTraffic.revokedTitle"))).not.toBeInTheDocument();
    expect(
      screen.queryByRole("link", { name: tEn("siteTraffic.reconnectCta") })
    ).not.toBeInTheDocument();
  });

  it("sends a missing scope down the permission recovery path instead", () => {
    render(
      <SiteTrafficSection
        projectId="42"
        state={makeState({ traffic: denied("insufficient_scope"), ga4WorkspaceConnected: true })}
      />
    );
    expect(screen.getByText(tEn("siteTraffic.scopeDeniedTitle"))).toBeInTheDocument();
    expect(screen.getByRole("link", { name: tEn("siteTraffic.reconnectCta") })).toHaveAttribute(
      "href",
      "/dashboard/connections"
    );
    expect(
      screen.queryByRole("link", { name: tEn("siteTraffic.choosePropertyCta") })
    ).not.toBeInTheDocument();
  });

  it("does not claim a confirmed property denial for an unclassified 403", () => {
    render(
      <SiteTrafficSection
        projectId="42"
        state={makeState({ traffic: denied("permission_denied"), ga4WorkspaceConnected: true })}
      />
    );
    expect(screen.getByText(tEn("siteTraffic.permissionDeniedTitle"))).toBeInTheDocument();
    expect(screen.queryByText(tEn("siteTraffic.propertyDeniedTitle"))).not.toBeInTheDocument();
  });

  it("hides the account change when the workspace holds no Google grant", () => {
    // The binding is authorized by a client magic link, so the workspace
    // connections page cannot change anything for it.
    render(
      <SiteTrafficSection
        projectId="42"
        state={makeState({ traffic: denied("property_denied"), ga4WorkspaceConnected: false })}
      />
    );
    expect(
      screen.getByRole("link", { name: tEn("siteTraffic.choosePropertyCta") })
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("link", { name: tEn("siteTraffic.changeAccountCta") })
    ).not.toBeInTheDocument();
  });
});

describe("SiteTrafficSection disconnected call to action", () => {
  it("routes to the workspace connection when no Google account exists", () => {
    render(
      <SiteTrafficSection
        projectId="42"
        state={makeState({ ga4WorkspaceConnected: false, ga4BoundInactive: false })}
      />
    );
    const cta = screen.getByRole("link", { name: tEn("siteTraffic.connectAccountCta") });
    expect(cta).toHaveAttribute("href", "/dashboard/connections");
  });

  it("routes to the Connected data step when the account is connected", () => {
    render(
      <SiteTrafficSection
        projectId="42"
        state={makeState({ ga4WorkspaceConnected: true, ga4BoundInactive: false })}
      />
    );
    const cta = screen.getByRole("link", { name: tEn("siteTraffic.connectCta") });
    expect(cta).toHaveAttribute("href", "/dashboard/projects/42/settings#data-sources");
  });

  it("says the source is switched off rather than claiming nothing is connected", () => {
    render(
      <SiteTrafficSection
        projectId="42"
        state={makeState({ ga4WorkspaceConnected: true, ga4BoundInactive: true })}
      />
    );
    expect(screen.getByText(tEn("siteTraffic.inactiveTitle"))).toBeInTheDocument();
    const cta = screen.getByRole("link", { name: tEn("siteTraffic.reactivateCta") });
    expect(cta).toHaveAttribute("href", "/dashboard/projects/42/settings#data-sources");
    expect(screen.queryByText(tEn("siteTraffic.disconnectedTitle"))).not.toBeInTheDocument();
  });
});

// SIGV2-1204: the approved design marks all five Traffic & Conversions KPI
// cards with `data-xsell` (mockup/Signal Overview.html:88-112), so each one
// owns a help panel. The build mounted it only when channel_mix happened to
// supply a comparison, so any period without one, plus Audience and the two
// unavailable key-event states, rendered with no explanation at all. These
// assert the binding per card and per state, and that the panel is reachable
// without a mouse, rather than photographing the overlay.
const channel = (
  bucket: string,
  label: string,
  share: number,
  shareChange: number | null
): SiteTrafficChannelBucket => ({
  bucket,
  label,
  sessions: 100,
  share,
  share_change: { value: shareChange, kind: "percentage_points" },
});

const okPayload = (overrides: Partial<SiteTrafficPayload> = {}): SiteTrafficPayload => ({
  status: "ok",
  window: "7D",
  start_date: "2026-09-23",
  end_date: "2026-09-29",
  comparison_start_date: "2026-09-16",
  comparison_end_date: "2026-09-22",
  property_timezone: "America/New_York",
  bucket_granularity: "daily",
  bucket_boundary: "day",
  data_freshness: "2026-09-29T12:00:00+00:00",
  availability: "available",
  data_quality: {},
  overview: {
    sessions: 4800,
    pageviews: 12300,
    key_events: 214,
    engaged_sessions: 2784,
    total_users: 3100,
    engagement_rate: 0.58,
    bounce_rate: 0.42,
    avg_session_duration: 147,
    audience: { value: null, available: false, reason: "not_defined" },
    changes: {
      sessions: { value: 0.0045, kind: "relative" },
      pageviews: { value: -0.012, kind: "relative" },
      key_events: { value: -0.0061, kind: "relative" },
      total_users: { value: 0.0045, kind: "relative" },
    },
  },
  series: [
    { bucket: "2026-09-23", sessions: 640, pageviews: 1600, key_events: 28 },
    { bucket: "2026-09-24", sessions: 700, pageviews: 1800, key_events: 31 },
  ],
  channel_mix: [channel("organic", "Organic", 34, 2), channel("direct", "Direct", 22, -1)],
  breakdowns: {
    sessions: [
      { bucket: "organic", label: "Organic", change: { value: 0.062, kind: "relative" } },
      { bucket: "ai", label: "AI assistants", change: { value: 0.087, kind: "relative" } },
    ],
    users: [
      { bucket: "organic", label: "Organic", change: { value: 0.041, kind: "relative" } },
      { bucket: "paid", label: "Paid", change: { value: -0.028, kind: "relative" } },
    ],
    engagement: [
      { metric: "engaged_sessions", change: { value: 0.013, kind: "relative" } },
      { metric: "bounce_rate", change: { value: -1.4, kind: "percentage_points" } },
      { metric: "avg_session_duration", change: { value: 0.022, kind: "relative" } },
    ],
    conversions: [
      { bucket: "organic", label: "Organic", change: { value: -0.011, kind: "relative" } },
      { bucket: "referral", label: "Referral", change: { value: 0.055, kind: "relative" } },
    ],
  },
  key_events: {
    state: "active",
    total: 214,
    change: { value: -0.0061, kind: "relative" },
    by_event: [],
    by_channel: [],
  },
  ...overrides,
});

const renderTraffic = (payload: SiteTrafficPayload) =>
  render(
    <SiteTrafficSection
      projectId="42"
      state={makeState({ traffic: payload as UseSiteTrafficResult["traffic"] })}
    />
  );

/** The KPI card for `metric`, its hover/focus trigger and its help panel. */
function kpiPanel(container: HTMLElement, metric: string) {
  const card = container.querySelector(`[data-metric="${metric}"]`);
  expect(card, `no KPI card rendered for ${metric}`).not.toBeNull();
  const trigger = (card as HTMLElement).parentElement as HTMLElement;
  const panel = trigger.querySelector('[role="tooltip"]') as HTMLElement | null;
  expect(panel, `no help panel on the ${metric} KPI card`).not.toBeNull();
  // Assistive technology reads the panel as this card's description, so the
  // explanation is announced rather than merely painted on hover.
  expect(trigger).toHaveAttribute("aria-describedby", (panel as HTMLElement).id);
  return { trigger, panel: panel as HTMLElement };
}

/** A panel a keyboard user can open and dismiss, with no pointer involved. */
function expectReachableWithoutAMouse(trigger: HTMLElement, panel: HTMLElement) {
  expect(trigger).toHaveAttribute("tabindex", "0");
  expect(panel).toHaveClass("invisible");
  fireEvent.focus(trigger);
  expect(panel).toHaveClass("visible", "opacity-100");
  fireEvent.keyDown(trigger, { key: "Escape" });
  expect(panel).toHaveClass("invisible");
}

describe("SiteTrafficSection KPI help panels", () => {
  // head / question / body expected per card, with a measured comparison on
  // screen. The two question lines are the approved mockup copy verbatim;
  // which one a card uses follows its own measured direction, so Conversions
  // on a negative change asks about the drop and the rest ask about change.
  const measured: [string, string, string, string, [string, string][]][] = [
    [
      "sessions",
      "metricSessions",
      "xsellMoved",
      "xsellBody_sessions",
      [
        ["Organic", "+6.20%"],
        ["AI assistants", "+8.70%"],
      ],
    ],
    [
      "users",
      "metricUsers",
      "xsellMoved",
      "xsellBody_users",
      [
        ["Organic", "+4.10%"],
        ["Paid", "-2.80%"],
      ],
    ],
    [
      "engagement",
      "metricEngagement",
      "xsellMoved",
      "xsellBody_engagement",
      [
        ["Engaged sessions", "+1.30%"],
        ["Bounce rate", "-1.4 pp"],
        ["Avg. session duration", "+2.20%"],
      ],
    ],
    [
      "conversions",
      "metricConversions",
      "xsellDropped",
      "xsellBody_conversions",
      [
        ["Organic", "-1.10%"],
        ["Referral", "+5.50%"],
      ],
    ],
  ];

  it.each(measured)(
    "gives the %s card its own measured breakdown, not another card's",
    (metric, labelKey, questionKey, bodyKey, rows) => {
      const { container } = renderTraffic(okPayload());
      const { trigger, panel } = kpiPanel(container, metric);
      expect(panel).toHaveTextContent(tEn(`siteTraffic.${labelKey}`));
      expect(panel).toHaveTextContent(tEn(`siteTraffic.${questionKey}`));
      expect(panel).toHaveTextContent(tEn(`siteTraffic.${bodyKey}`));
      for (const [label, value] of rows) {
        expect(panel).toHaveTextContent(label);
        expect(panel).toHaveTextContent(value);
      }
      expectReachableWithoutAMouse(trigger, panel);
    }
  );

  it("no two measured cards render the same breakdown rows", () => {
    const { container } = renderTraffic(okPayload());
    const texts = measured.map(([metric]) => {
      const { panel } = kpiPanel(container, metric);
      return panel.textContent ?? "";
    });
    expect(new Set(texts).size).toBe(measured.length);
  });

  it.each(measured)(
    "keeps the %s card's panel when no breakdown is available",
    (metric, labelKey, questionKey) => {
      // The regression: every factor's change is null, so the old build
      // dropped the panel off all four measured cards.
      const { container } = renderTraffic(
        okPayload({
          breakdowns: {
            sessions: [],
            users: [],
            engagement: [],
            conversions: [],
          },
        })
      );
      const { trigger, panel } = kpiPanel(container, metric);
      expect(panel).toHaveTextContent(tEn(`siteTraffic.${labelKey}`));
      expect(panel).toHaveTextContent(tEn(`siteTraffic.${questionKey}`));
      expect(panel).toHaveTextContent(tEn("siteTraffic.xsellNoBreakdown"));
      // No breakdown means no rows, never a placeholder figure.
      expect(panel).not.toHaveTextContent("pp");
      expectReachableWithoutAMouse(trigger, panel);
    }
  );

  it("explains the Audience card instead of leaving it bare", () => {
    const { container } = renderTraffic(okPayload());
    const { trigger, panel } = kpiPanel(container, "audience");
    expect(panel).toHaveTextContent(tEn("siteTraffic.metricAudience"));
    expect(panel).toHaveTextContent(tEn("siteTraffic.xsellWhyNotMeasured"));
    // SIGV2-1281: the panel carries the server's reason. It used to carry a
    // hardcoded "not available yet" over a backend saying `not_defined`.
    expect(panel).toHaveTextContent(tEn("siteTraffic.audienceReasons.not_defined"));
    // Contract 2.4: no number, and no invented attribution either.
    expect(panel).not.toHaveTextContent("pp");
    expect(panel).not.toHaveTextContent("Organic");
    expectReachableWithoutAMouse(trigger, panel);
  });

  it.each([
    ["not_configured", "keyEventsNotConfigured"],
    ["unknown", "keyEventsUnknown"],
  ])("explains the Conversions card in the %s key-event state", (state, reasonKey) => {
    const { container } = renderTraffic(
      okPayload({
        key_events: {
          state,
          total: 0,
          change: { value: null, kind: "relative" },
          by_event: [],
          by_channel: [],
        } as SiteTrafficKeyEvents,
      })
    );
    const { trigger, panel } = kpiPanel(container, "conversions");
    expect(panel).toHaveTextContent(tEn("siteTraffic.metricConversions"));
    expect(panel).toHaveTextContent(tEn("siteTraffic.xsellWhyNotMeasured"));
    expect(panel).toHaveTextContent(tEn(`siteTraffic.${reasonKey}`));
    expect(panel).not.toHaveTextContent("pp");
    expectReachableWithoutAMouse(trigger, panel);
  });

  it("marks every rendered KPI card as carrying a panel, as the design does", () => {
    const { container } = renderTraffic(okPayload());
    expect(container.querySelectorAll("[data-metric]")).toHaveLength(5);
    expect(container.querySelectorAll("[data-metric][data-xsell]")).toHaveLength(5);
    expect(screen.getAllByRole("tooltip")).toHaveLength(5);
  });

  // The approved panel (mockup/app.js XSELL_CARDS) is head + question +
  // provenance line + measured breakdown rows. No definition copy: the
  // mockup's xsell overlay has no element for it.
  it.each(["sessions", "users", "engagement", "conversions", "audience"] as const)(
    "gives the %s card the approved panel: metric name, question, breakdown",
    (metric) => {
      const { container } = renderTraffic(okPayload());
      const { panel } = kpiPanel(container, metric);
      expect(panel).not.toHaveTextContent("Definition");
    }
  );

  it("renders no KPI cards, and so no panels, when there is no data", () => {
    const { container } = renderTraffic(okPayload({ availability: "no_data" }));
    expect(container.querySelectorAll("[data-metric]")).toHaveLength(0);
    expect(screen.getByText(tEn("siteTraffic.noDataTitle"))).toBeInTheDocument();
  });
  // A payload written before `breakdowns` existed - a cached report, an
  // older backend, the visual-suite stub - must not take the section down.
  // Indexing the field unconditionally threw a TypeError that unmounted the
  // whole of Traffic and Conversions, so every KPI card disappeared because
  // one hover panel had no rows to show.
  it("still renders every card when the payload has no breakdowns at all", () => {
    const payload = okPayload();
    delete (payload as { breakdowns?: unknown }).breakdowns;

    const { container } = renderTraffic(payload);

    expect(container.querySelectorAll("[data-metric]").length).toBeGreaterThan(0);
    expect(container.querySelector('[data-metric="sessions"]')).not.toBeNull();
  });

  it("says there is no breakdown rather than showing another card's rows", () => {
    const payload = okPayload();
    delete (payload as { breakdowns?: unknown }).breakdowns;

    const { container } = renderTraffic(payload);
    const { panel } = kpiPanel(container, "sessions");

    expect(panel.textContent).toContain(tEn("siteTraffic.xsellNoBreakdown"));
  });
  // The reported symptom, reproduced: project 19 on preprod is a new GA4
  // property with no previous period, so every `change.value` comes back
  // null. The rows were per-metric all along, but a change-only row had
  // nothing to render and was dropped, so all five panels collapsed onto the
  // same "no breakdown" sentence and read identically.
  describe("a property with no previous period to compare against", () => {
    const noDeltas = () =>
      okPayload({
        breakdowns: {
          sessions: [
            {
              bucket: "organic",
              label: "Organic",
              value: 7,
              change: { value: null, kind: "relative" },
            },
            {
              bucket: "direct",
              label: "Direct",
              value: 4,
              change: { value: null, kind: "relative" },
            },
          ],
          users: [
            {
              bucket: "organic",
              label: "Organic",
              value: 3,
              change: { value: null, kind: "relative" },
            },
          ],
          engagement: [
            {
              metric: "engaged_sessions",
              value: 7,
              value_kind: "count",
              change: { value: null, kind: "relative" },
            },
            {
              metric: "bounce_rate",
              value: 36.4,
              value_kind: "percent",
              change: { value: null, kind: "percentage_points" },
            },
            {
              metric: "avg_session_duration",
              value: 234.37,
              value_kind: "seconds",
              change: { value: null, kind: "relative" },
            },
          ],
          conversions: [
            {
              bucket: "organic",
              label: "Organic",
              value: 0,
              change: { value: null, kind: "relative" },
            },
          ],
        },
      });

    it("shows the measured value instead of dropping the row", () => {
      const { container } = renderTraffic(noDeltas());
      const { panel } = kpiPanel(container, "sessions");

      expect(panel.textContent).toContain("Organic");
      expect(panel.textContent).toContain("7");
      expect(panel.textContent).not.toContain(tEn("siteTraffic.xsellNoBreakdown"));
    });

    it("gives each card a different panel, which is the whole point", () => {
      const { container } = renderTraffic(noDeltas());

      const texts = ["sessions", "users", "engagement", "conversions"].map(
        (metric) => kpiPanel(container, metric).panel.textContent ?? ""
      );

      expect(new Set(texts).size).toBe(texts.length);
    });

    it("formats engagement components by their own unit", () => {
      const { container } = renderTraffic(noDeltas());
      const { panel } = kpiPanel(container, "engagement");

      // A percentage stays a percentage and a duration stays seconds; neither
      // is rendered as a bare count.
      expect(panel.textContent).toContain("36.4%");
      expect(panel.textContent).toContain("234s");
    });
  });
  // SIGV2-1281: the Audience card.
  describe("the audience card", () => {
    it("puts the reason under the words it explains, not in the spark column", () => {
      const { container } = renderTraffic(okPayload());
      const card = container.querySelector('[data-metric="audience"]') as HTMLElement;

      expect(card).not.toBeNull();
      // "Not measured" and the reason share the same text block, so they read
      // as one statement. They used to sit at opposite edges of the card.
      const block = card.querySelector("div.min-w-0");
      expect(block?.textContent).toContain(tEn("siteTraffic.notMeasured"));
      expect(block?.textContent).toContain(tEn("siteTraffic.audienceReasons.not_defined"));
    });

    it("no longer shows a question nothing answers", () => {
      const { container } = renderTraffic(okPayload());
      const card = container.querySelector('[data-metric="audience"]') as HTMLElement;

      // "Why no data?" was a span with no handler, no link and no tooltip.
      // The question invited a click that did nothing.
      expect(card.textContent).not.toContain("Why no data?");
      // No dead tooltip either: SIGV2-1204 removed it because a native
      // tooltip is mouse-only and fired a second overlay on the same hover.
      expect(card.querySelector("[title]")).toBeNull();
    });

    it("says what the server said, not a sentence of our own", () => {
      // The payload has always carried the reason. The card printed
      // "not available yet" over a backend saying `not_defined`, which is a
      // different claim.
      const { container } = renderTraffic(okPayload());
      const card = container.querySelector('[data-metric="audience"]') as HTMLElement;

      expect(card.textContent).toContain(tEn("siteTraffic.audienceReasons.not_defined"));
      expect(card.textContent).not.toContain(tEn("siteTraffic.audienceReason"));
    });

    it("falls back rather than leaking a raw key for an unknown reason", () => {
      const payload = okPayload();
      payload.overview.audience = {
        value: null,
        available: false,
        reason: "something_new_from_the_server",
      };

      const { container } = renderTraffic(payload);
      const card = container.querySelector('[data-metric="audience"]') as HTMLElement;

      expect(card.textContent).toContain(tEn("siteTraffic.audienceReasons.fallback"));
      expect(card.textContent).not.toContain("something_new_from_the_server");
      expect(card.textContent).not.toContain("audienceReasons");
    });
  });
});
