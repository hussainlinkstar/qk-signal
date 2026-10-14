/* eslint-disable */
"use client";

// ---------------------------------------------------------------------------
// Base-path request shim.
// When the app is served under a sub-path (e.g. /signal on qiko.ai), Next.js
// basePath prefixes Links, route handlers and assets, but it does NOT rewrite
// raw client-side fetch('/api/...'), EventSource or XHR. This patches those so
// the existing absolute '/api' calls keep working under the base path, without
// touching hundreds of call sites. Typed loosely on purpose (lint disabled).
// ---------------------------------------------------------------------------

const BASE_PATH: string = (process.env.NEXT_PUBLIC_BASE_PATH || "").replace(/\/+$/, "");

function withBasePath(url: string): string {
  if (!BASE_PATH) return url;
  if (url.startsWith("/api") && !url.startsWith(BASE_PATH + "/")) {
    return BASE_PATH + url;
  }
  return url;
}

const w: any = typeof window !== "undefined" ? window : undefined;

if (w && BASE_PATH && !w.__basePathShimInstalled) {
  w.__basePathShimInstalled = true;
  const origin: string = w.location.origin;

  // fetch
  const origFetch = w.fetch.bind(w);
  w.fetch = (input: any, init?: any) => {
    try {
      if (typeof input === "string") {
        input = withBasePath(input);
      } else if (input instanceof URL) {
        if (input.origin === origin) {
          input = new URL(withBasePath(input.pathname + input.search + input.hash), origin);
        }
      } else if (input && typeof input.url === "string") {
        const u = new URL(input.url, origin);
        if (u.origin === origin) {
          const cur = u.pathname + u.search + u.hash;
          const next = withBasePath(cur);
          if (next !== cur) input = new Request(origin + next, input);
        }
      }
    } catch (e) {
      /* fall through */
    }
    return origFetch(input, init);
  };

  // EventSource (SSE, e.g. live audit streaming)
  if (typeof w.EventSource !== "undefined") {
    const ES: any = w.EventSource;
    const Patched: any = function (url: any, init?: any) {
      let u = typeof url === "string" ? url : String(url);
      if (u.startsWith("/")) u = withBasePath(u);
      return new ES(u, init);
    };
    Patched.prototype = ES.prototype;
    Patched.CONNECTING = ES.CONNECTING;
    Patched.OPEN = ES.OPEN;
    Patched.CLOSED = ES.CLOSED;
    w.EventSource = Patched;
  }

  // Anchor navigations: rewrite raw root-absolute <a href="/..."> that are not
  // already under the base path (Next <Link> already includes it, so it is skipped).
  document.addEventListener(
    "click",
    (ev: any) => {
      try {
        if (
          ev.defaultPrevented ||
          ev.button !== 0 ||
          ev.metaKey ||
          ev.ctrlKey ||
          ev.shiftKey ||
          ev.altKey
        )
          return;
        let el = ev.target;
        while (el && el.tagName !== "A") el = el.parentElement;
        if (!el) return;
        const raw = el.getAttribute("href");
        if (!raw || !raw.startsWith("/") || raw.startsWith("//")) return;
        const u = new URL(raw, origin);
        if (u.origin !== origin) return;
        const path = u.pathname;
        if (path === BASE_PATH || path.startsWith(BASE_PATH + "/") || path.startsWith("/_next"))
          return;
        el.setAttribute("href", BASE_PATH + u.pathname + u.search + u.hash);
      } catch (e) {
        /* ignore */
      }
    },
    true
  );

  // XMLHttpRequest
  const xhrProto: any = w.XMLHttpRequest && w.XMLHttpRequest.prototype;
  if (xhrProto) {
    const xhrOpen = xhrProto.open;
    xhrProto.open = function (method: string, url: any, ...rest: any[]) {
      let u = typeof url === "string" ? url : String(url);
      if (u.startsWith("/")) u = withBasePath(u);
      return xhrOpen.call(this, method, u, ...rest);
    };
  }
}

export default function BasePathShim() {
  return null;
}
