"use client";

import { useEffect } from "react";
import { useCookieConsent } from "@/contexts/CookieConsentContext";

/**
 * Google Tag Manager, gated by Consent Mode v2.
 *
 * Before the visitor answers the cookie banner, only a `consent default` of
 * denied signals is pushed to the dataLayer; no script is injected and no
 * request reaches Google. Once consent is known, a `consent update` is pushed
 * on every change, and the GTM container script (plus the noscript iframe) is
 * added only while `analytics` consent is granted.
 *
 * Env vars consumed:
 *   NEXT_PUBLIC_GTM_ID, e.g. "GTM-XXXXXXX" (unset means no tag and no error)
 */

export const GTM_SCRIPT_ELEMENT_ID = "gtm-script";
export const GTM_HOST = "https://www.googletagmanager.com";

// Consent Mode v2: nothing optional is stored until the visitor grants it.
export const GTM_CONSENT_DEFAULTS = {
  ad_storage: "denied",
  ad_user_data: "denied",
  ad_personalization: "denied",
  analytics_storage: "denied",
  functionality_storage: "denied",
  personalization_storage: "denied",
  security_storage: "granted",
} as const;

export type GtmWindow = {
  dataLayer?: unknown[];
  gtag?: (...args: unknown[]) => void;
};

export type GtmDocument = {
  getElementById: (id: string) => unknown;
  createElement: (tag: "script") => {
    id: string;
    async: boolean;
    src: string;
    nonce?: string;
  };
  head: { appendChild: (node: unknown) => unknown };
};

export type GtmConsentState = {
  consentKnown: boolean;
  analyticsAllowed: boolean;
  marketingAllowed: boolean;
  preferencesAllowed: boolean;
};

export function gtmScriptSrc(gtmId: string): string {
  return `${GTM_HOST}/gtm.js?id=${encodeURIComponent(gtmId)}`;
}

export function gtmNoscriptSrc(gtmId: string): string {
  return `${GTM_HOST}/ns.html?id=${encodeURIComponent(gtmId)}`;
}

export function consentUpdatePayload(state: GtmConsentState): Record<string, "granted" | "denied"> {
  const marketing = state.marketingAllowed ? "granted" : "denied";
  const preferences = state.preferencesAllowed ? "granted" : "denied";
  return {
    ad_storage: marketing,
    ad_user_data: marketing,
    ad_personalization: marketing,
    analytics_storage: state.analyticsAllowed ? "granted" : "denied",
    functionality_storage: preferences,
    personalization_storage: preferences,
    security_storage: "granted",
  };
}

/** Returns true only when the stub was created, so the consent default is pushed once per window. */
function ensureGtagStub(w: GtmWindow): boolean {
  w.dataLayer = w.dataLayer || [];
  if (w.gtag) return false;
  // Must stay the canonical `function` + `arguments` form, even though a rest-spread arrow
  // looks equivalent: gtm.js distinguishes gtag *commands* from ordinary data pushes by
  // checking `Object.prototype.toString` for `[object Arguments]`. An arrow's rest-spread
  // pushes a real Array instead, which gtm.js ignores, so consent commands never reach
  // Google's tags. Do not "clean this up".
  w.gtag = function () {
    // eslint-disable-next-line prefer-rest-params
    w.dataLayer!.push(arguments);
  };
  return true;
}

/** Returns true only when the script element was actually inserted. */
export function injectGtmScript(
  w: GtmWindow,
  doc: GtmDocument,
  gtmId: string,
  nonce?: string
): boolean {
  if (doc.getElementById(GTM_SCRIPT_ELEMENT_ID)) return false;

  // The gtm.start bootstrap is ordinary dataLayer data read by key, so unlike the
  // gtag commands above it must be pushed as a plain object, not as `arguments`.
  w.dataLayer = w.dataLayer || [];
  w.dataLayer.push({ "gtm.start": Date.now(), event: "gtm.js" });

  const script = doc.createElement("script");
  script.id = GTM_SCRIPT_ELEMENT_ID;
  script.async = true;
  script.src = gtmScriptSrc(gtmId);
  if (nonce) script.nonce = nonce;
  doc.head.appendChild(script);
  return true;
}

/**
 * Synchronise gtm/gtag state with the current consent. The Consent Mode defaults
 * are pushed before anything else, so the first network-capable object only ever
 * sees a denied-by-default state. The gtm.js script itself is injected only after
 * analytics consent is granted; before that there are zero requests to Google.
 */
export function syncGtm(
  w: GtmWindow,
  doc: GtmDocument,
  gtmId: string,
  state: GtmConsentState,
  nonce?: string
): void {
  if (!gtmId) return;

  const created = ensureGtagStub(w);
  if (created) w.gtag!("consent", "default", { ...GTM_CONSENT_DEFAULTS });

  if (!state.consentKnown) return;

  w.gtag!("consent", "update", consentUpdatePayload(state));
  if (state.analyticsAllowed) injectGtmScript(w, doc, gtmId, nonce);
}

export default function GoogleTagManager({ nonce }: { nonce?: string }) {
  const { hasAnswered, canUseCategory } = useCookieConsent();
  const gtmId = (process.env.NEXT_PUBLIC_GTM_ID ?? "").trim();
  const analyticsAllowed = canUseCategory("analytics");
  const marketingAllowed = canUseCategory("marketing");
  const preferencesAllowed = canUseCategory("preferences");

  useEffect(() => {
    syncGtm(
      window as unknown as GtmWindow,
      document,
      gtmId,
      {
        consentKnown: hasAnswered,
        analyticsAllowed,
        marketingAllowed,
        preferencesAllowed,
      },
      nonce
    );
  }, [gtmId, hasAnswered, analyticsAllowed, marketingAllowed, preferencesAllowed, nonce]);

  if (!gtmId || !analyticsAllowed) return null;

  return (
    <noscript>
      <iframe
        src={gtmNoscriptSrc(gtmId)}
        height="0"
        width="0"
        className="invisible hidden"
        title="Google Tag Manager"
      />
    </noscript>
  );
}
