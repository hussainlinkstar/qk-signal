import React from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import GoogleTagManager, {
  GTM_CONSENT_DEFAULTS,
  GTM_SCRIPT_ELEMENT_ID,
  consentUpdatePayload,
  gtmScriptSrc,
  syncGtm,
  type GtmConsentState,
  type GtmDocument,
  type GtmWindow,
} from "@/components/analytics/GoogleTagManager";
import { CookieConsentProvider, useCookieConsent } from "@/contexts/CookieConsentContext";
import { renderToStaticMarkup } from "react-dom/server";

// React renders no DOM children inside <noscript> on the client, so the gated iframe
// can only be observed in the component's markup, not via jsdom queries. When set,
// this override drives useCookieConsent for a static render; null falls through to
// the real hook so the provider-backed tests below still exercise the real context.
const consentOverride: {
  current: ReturnType<typeof useCookieConsent> | null;
} = { current: null };

vi.mock("@/contexts/CookieConsentContext", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/contexts/CookieConsentContext")>();
  return {
    ...actual,
    useCookieConsent: () => consentOverride.current ?? actual.useCookieConsent(),
  };
});

const GTM_ID = "GTM-TEST123";

type FakeScript = {
  id: string;
  async: boolean;
  src: string;
  nonce?: string;
  dataLayerLengthAtCreate: number;
};

// Fake window + document, sufficient for syncGtm's dataLayer/gtag/script interactions.
// createElement records the dataLayer length at creation time so ordering is assertable.
function fakeBrowser() {
  const scripts: FakeScript[] = [];
  const w: GtmWindow = {};
  const doc: GtmDocument = {
    getElementById: (id) => scripts.find((s) => s.id === id) ?? null,
    createElement: () => {
      const script: FakeScript = {
        id: "",
        async: false,
        src: "",
        dataLayerLengthAtCreate: (w.dataLayer ?? []).length,
      };
      return script;
    },
    head: {
      appendChild: (node) => scripts.push(node as FakeScript),
    },
  };
  return { w, doc, scripts };
}

const consentState = (overrides: Partial<GtmConsentState> = {}): GtmConsentState => ({
  consentKnown: true,
  analyticsAllowed: false,
  marketingAllowed: false,
  preferencesAllowed: false,
  ...overrides,
});

const isArguments = (entry: unknown): entry is IArguments =>
  Object.prototype.toString.call(entry) === "[object Arguments]";

const consentCalls = (w: GtmWindow, kind: "default" | "update") =>
  (w.dataLayer ?? []).filter(
    (entry) => isArguments(entry) && entry[0] === "consent" && entry[1] === kind
  ) as IArguments[];

describe("syncGtm", () => {
  it("no GTM id: no gtag stub, no dataLayer, no script, no error", () => {
    const { w, doc, scripts } = fakeBrowser();
    expect(() => syncGtm(w, doc, "", consentState({ analyticsAllowed: true }))).not.toThrow();
    expect(w.dataLayer).toBeUndefined();
    expect(w.gtag).toBeUndefined();
    expect(scripts).toHaveLength(0);
  });

  it("id set, consent not answered: denied defaults pushed once, no script", () => {
    const { w, doc, scripts } = fakeBrowser();
    syncGtm(w, doc, GTM_ID, consentState({ consentKnown: false }));
    expect(scripts).toHaveLength(0);

    const defaults = consentCalls(w, "default");
    expect(defaults).toHaveLength(1);
    const payload = defaults[0][2] as Record<string, string>;
    for (const key of Object.keys(GTM_CONSENT_DEFAULTS)) {
      expect(payload[key], key).toBe(
        GTM_CONSENT_DEFAULTS[key as keyof typeof GTM_CONSENT_DEFAULTS]
      );
    }
    expect(payload.analytics_storage).toBe("denied");
    expect(payload.ad_storage).toBe("denied");
    expect(payload.ad_user_data).toBe("denied");
    expect(payload.ad_personalization).toBe("denied");

    // A second sync must not re-push the default over the existing state.
    syncGtm(w, doc, GTM_ID, consentState({ consentKnown: false }));
    expect(consentCalls(w, "default")).toHaveLength(1);
  });

  it("analytics granted: script injected exactly once with nonce, granted update pushed", () => {
    const { w, doc, scripts } = fakeBrowser();
    const state = consentState({ analyticsAllowed: true });
    syncGtm(w, doc, GTM_ID, state, "nonce-abc");
    syncGtm(w, doc, GTM_ID, state, "nonce-abc");

    expect(scripts).toHaveLength(1);
    expect(scripts[0].id).toBe(GTM_SCRIPT_ELEMENT_ID);
    expect(scripts[0].src).toBe(gtmScriptSrc(GTM_ID));
    expect(scripts[0].src).toMatch(
      /^https:\/\/www\.googletagmanager\.com\/gtm\.js\?id=GTM-TEST123$/
    );
    expect(scripts[0].async).toBe(true);
    expect(scripts[0].nonce).toBe("nonce-abc");

    const updates = consentCalls(w, "update");
    expect(updates.length).toBeGreaterThan(0);
    expect((updates[0][2] as Record<string, string>).analytics_storage).toBe("granted");
  });

  it("analytics denied: no script, denied update still pushed", () => {
    const { w, doc, scripts } = fakeBrowser();
    syncGtm(w, doc, GTM_ID, consentState({ analyticsAllowed: false }));
    expect(scripts).toHaveLength(0);
    const updates = consentCalls(w, "update");
    expect(updates).toHaveLength(1);
    expect((updates[0][2] as Record<string, string>).analytics_storage).toBe("denied");
  });

  it("consent granted then revoked: second denied update, still one script", () => {
    const { w, doc, scripts } = fakeBrowser();
    syncGtm(w, doc, GTM_ID, consentState({ analyticsAllowed: true }));
    syncGtm(w, doc, GTM_ID, consentState({ analyticsAllowed: false }));

    const updates = consentCalls(w, "update");
    expect(updates).toHaveLength(2);
    expect((updates[1][2] as Record<string, string>).analytics_storage).toBe("denied");
    expect(scripts).toHaveLength(1);
  });

  it("marketing consent drives all three ad_* signals", () => {
    expect(consentUpdatePayload(consentState({ marketingAllowed: true }))).toMatchObject({
      ad_storage: "granted",
      ad_user_data: "granted",
      ad_personalization: "granted",
    });
    expect(consentUpdatePayload(consentState({ marketingAllowed: false }))).toMatchObject({
      ad_storage: "denied",
      ad_user_data: "denied",
      ad_personalization: "denied",
    });
  });

  it("preferences consent drives functionality and personalization storage; security stays granted", () => {
    const granted = consentUpdatePayload(consentState({ preferencesAllowed: true }));
    expect(granted.functionality_storage).toBe("granted");
    expect(granted.personalization_storage).toBe("granted");
    expect(granted.security_storage).toBe("granted");

    const denied = consentUpdatePayload(consentState());
    expect(denied.functionality_storage).toBe("denied");
    expect(denied.personalization_storage).toBe("denied");
    expect(denied.security_storage).toBe("granted");
  });

  it("pushes the denied default before any script element exists", () => {
    const { w, doc, scripts } = fakeBrowser();
    syncGtm(w, doc, GTM_ID, consentState({ analyticsAllowed: true }));

    const first = w.dataLayer![0];
    expect(isArguments(first)).toBe(true);
    expect((first as IArguments)[0]).toBe("consent");
    expect((first as IArguments)[1]).toBe("default");

    const defaultIndex = w.dataLayer!.indexOf(first);
    expect(scripts).toHaveLength(1);
    expect(scripts[0].dataLayerLengthAtCreate).toBeGreaterThan(defaultIndex);
  });

  it("every gtag command is pushed as Arguments, never a real Array", () => {
    const { w, doc } = fakeBrowser();
    syncGtm(w, doc, GTM_ID, consentState({ analyticsAllowed: true }));
    expect(w.dataLayer!.length).toBeGreaterThan(0);

    const plainObjects: Record<string, unknown>[] = [];
    for (const entry of w.dataLayer!) {
      // gtm.js tells gtag *commands* from ordinary data pushes by checking
      // Object.prototype.toString for [object Arguments]. A real Array command is
      // silently ignored, so the consent update never reaches Google's tags even
      // though the pushed values look right. Checking contents alone would pass
      // while broken.
      expect(
        Array.isArray(entry),
        `gtag command must be pushed as arguments, not an Array, or gtm.js ignores it: ${JSON.stringify(entry)}`
      ).toBe(false);
      if (isArguments(entry)) {
        expect(["consent", "js", "config"]).toContain(entry[0]);
      } else {
        plainObjects.push(entry as Record<string, unknown>);
      }
    }
    // The only plain-object push allowed is the gtm.start bootstrap, which is
    // ordinary dataLayer data read by key, not a gtag command.
    expect(plainObjects).toHaveLength(1);
    expect(plainObjects[0].event).toBe("gtm.js");
    expect(typeof plainObjects[0]["gtm.start"]).toBe("number");
  });
});

const AcceptAllButton = () => {
  const { acceptAll } = useCookieConsent();
  return (
    <button type="button" onClick={acceptAll}>
      accept-all
    </button>
  );
};

const RejectButton = () => {
  const { rejectOptional } = useCookieConsent();
  return (
    <button type="button" onClick={rejectOptional}>
      reject-optional
    </button>
  );
};

const renderGtm = () =>
  render(
    <CookieConsentProvider>
      <GoogleTagManager nonce="test-nonce" />
      <AcceptAllButton />
      <RejectButton />
    </CookieConsentProvider>
  );

const consentValue = (
  overrides: Partial<ReturnType<typeof useCookieConsent>> = {}
): ReturnType<typeof useCookieConsent> => ({
  consentRecord: null,
  hasAnswered: true,
  isBannerVisible: false,
  isSettingsOpen: false,
  canUseCategory: () => false,
  openSettings: () => {},
  closeSettings: () => {},
  acceptAll: () => {},
  rejectOptional: () => {},
  savePreferences: () => {},
  ...overrides,
});

const gtmNoscriptElement = () => document.querySelector("noscript");

const renderGtmStaticMarkup = (value: ReturnType<typeof useCookieConsent>) => {
  consentOverride.current = value;
  try {
    return renderToStaticMarkup(<GoogleTagManager nonce="test-nonce" />);
  } finally {
    consentOverride.current = null;
  }
};

describe("GoogleTagManager component", () => {
  beforeEach(() => {
    vi.stubEnv("NEXT_PUBLIC_GTM_ID", GTM_ID);
    window.localStorage.clear();
    delete (window as unknown as GtmWindow).dataLayer;
    delete (window as unknown as GtmWindow).gtag;
    document.getElementById(GTM_SCRIPT_ELEMENT_ID)?.remove();
  });

  afterEach(() => {
    vi.unstubAllEnvs();
  });

  it("first-time visitor: no gtm script, no googletagmanager src, no noscript iframe", async () => {
    renderGtm();

    // render() wraps in act(), so the effect has already run: assert the absence
    // synchronously. A negative inside waitFor resolves on the first tick and
    // would pass against a component that injects a moment later.
    expect(document.getElementById(GTM_SCRIPT_ELEMENT_ID)).toBeNull();
    const gtmSources = Array.from(document.head.querySelectorAll("script[src]")).filter((el) =>
      (el as HTMLScriptElement).src.includes("googletagmanager.com")
    );
    expect(gtmSources).toHaveLength(0);
    expect(gtmNoscriptElement()).toBeNull();

    // Liveness: the gated code path ran - the denied Consent Mode default was
    // pushed to the real window.dataLayer even though no script exists.
    const defaults = consentCalls(window as unknown as GtmWindow, "default");
    expect(defaults).toHaveLength(1);
    expect((defaults[0][2] as Record<string, string>).analytics_storage).toBe("denied");

    // Positive control: this harness can observe an injection, so the absence
    // above is a real negative rather than a broken render.
    fireEvent.click(screen.getByRole("button", { name: "accept-all" }));
    await waitFor(() => {
      expect(document.getElementById(GTM_SCRIPT_ELEMENT_ID)).not.toBeNull();
    });
  });

  it("granting analytics consent injects the script and renders the noscript iframe", async () => {
    renderGtm();
    fireEvent.click(screen.getByRole("button", { name: "accept-all" }));

    await waitFor(() => {
      expect(document.getElementById(GTM_SCRIPT_ELEMENT_ID)).not.toBeNull();
    });
    expect(document.getElementById(GTM_SCRIPT_ELEMENT_ID)).toHaveAttribute(
      "src",
      `https://www.googletagmanager.com/gtm.js?id=${GTM_ID}`
    );
    // IDL property, not the attribute: the nonce content attribute is blanked
    // once set via the property, so toHaveAttribute("nonce") is unreliable.
    expect((document.getElementById(GTM_SCRIPT_ELEMENT_ID) as HTMLScriptElement).nonce).toBe(
      "test-nonce"
    );
    expect(gtmNoscriptElement()).not.toBeNull();

    // The iframe itself never reaches jsdom (React renders nothing inside client
    // <noscript>), so assert its markup on a static render of the same component.
    const markup = renderGtmStaticMarkup(consentValue({ canUseCategory: () => true }));
    expect(markup).toContain(`ns.html?id=${GTM_ID}`);
    expect(markup).toContain("<noscript>");
  });

  it("rejecting optional cookies leaves script and iframe absent", async () => {
    renderGtm();
    fireEvent.click(screen.getByRole("button", { name: "reject-optional" }));

    await waitFor(() => {
      expect(window.localStorage.length).toBeGreaterThan(0);
    });
    expect(document.getElementById(GTM_SCRIPT_ELEMENT_ID)).toBeNull();
    expect(gtmNoscriptElement()).toBeNull();

    const markup = renderGtmStaticMarkup(consentValue());
    expect(markup).not.toContain("ns.html");
    expect(markup).not.toContain("<noscript>");
  });
});
