import { BASE_PATH } from "@/lib/basePath";
import type { Metadata, Viewport } from "next";
import { cookies, headers } from "next/headers";
import localFont from "next/font/local";
import "./globals.css";
import I18nProvider from "@/components/I18nProvider";
import QueryProvider from "@/components/QueryProvider";
import { Toaster } from "sonner";
import { AlertTriangle, CheckCircle2, Info, Loader2, XCircle } from "lucide-react";
import { AuthProvider } from "@/contexts/AuthContext";
import { CookieConsentProvider } from "@/contexts/CookieConsentContext";
import CookieConsentManager from "@/components/compliance/CookieConsentManager";
import GoogleTagManager from "@/components/analytics/GoogleTagManager";
import BasePathShim from "@/components/BasePathShim";
import ToastFocusRelease from "@/components/ToastFocusRelease";
import QikoBackdrop from "@/components/QikoBackdrop";
import { localeDir } from "@/lib/i18nFlags";

const inter = localFont({
  src: [
    { path: "./fonts/inter-400.woff2", weight: "400", style: "normal" },
    { path: "./fonts/inter-500.woff2", weight: "500", style: "normal" },
    { path: "./fonts/inter-600.woff2", weight: "600", style: "normal" },
    { path: "./fonts/inter-700.woff2", weight: "700", style: "normal" },
  ],
  variable: "--font-sans",
  display: "swap",
  declarations: [
    {
      prop: "unicode-range",
      value:
        "U+0000,U+0020-007E,U+00A0-00AC,U+00AE-0148,U+014A-01C3,U+01C5-0254,U+0256-027B,U+027E-0284,U+0286-0290,U+0292-02A4,U+02A6-02CC,U+02CE-02D7,U+02DA,U+02DC-0301,U+0303-0304,U+0308-0309,U+0323,U+0374-0376,U+037A-037F,U+0384-038A,U+038C,U+038E-03A1,U+03A3-03D7,U+03DC-03DD,U+03F0-03F6,U+03F9-03FA,U+03FC-0479,U+0480-049D,U+04A0-04FF,U+052F,U+1D00,U+1D0D,U+1D1B,U+1D43,U+1D47-1D49,U+1D4D,U+1D4F-1D50,U+1D52,U+1D56-1D58,U+1D5B,U+1D62-1D65,U+1D9C,U+1DA0,U+1DBB,U+1DBF,U+1E00-1E9B,U+1E9D-1F15,U+1F18-1F1D,U+1F20-1F45,U+1F48-1F4D,U+1F50-1F57,U+1F59,U+1F5B,U+1F5D,U+1F5F-1F7D,U+1F80-1FB4,U+1FB6-1FC4,U+1FC6-1FD3,U+1FD6-1FDB,U+1FDD-1FEF,U+1FF2-1FF4,U+1FF6-1FFE,U+2002,U+2009,U+200B,U+2013-2014,U+2018-201A,U+201C-201E,U+2020,U+2022,U+2026,U+2032-2033,U+2039-203A,U+2044,U+20A0-20AF,U+20B1-20B5,U+20B8-20BA,U+20BC-20BF,U+2113,U+2116,U+2122,U+2191,U+2193,U+2212,U+2C7C,U+2C7F,U+2DFF,U+A69F,U+A7FF,U+FEFF",
    },
  ],
});

// Used by the signal-light design system (authenticated dashboard/admin app) for
// mono labels/eyebrows/metrics. See globals.css `[data-signal-theme]` tokens.
const robotoMono = localFont({
  src: [
    { path: "./fonts/roboto-mono-400.woff2", weight: "400", style: "normal" },
    { path: "./fonts/roboto-mono-500.woff2", weight: "500", style: "normal" },
  ],
  variable: "--font-roboto-mono",
  display: "swap",
  declarations: [
    {
      prop: "unicode-range",
      value:
        "U+000D,U+0020-007E,U+00A0-017F,U+0192,U+01A0-01A1,U+01AF-01B0,U+01F0,U+01FA-01FF,U+0218-021B,U+0237,U+0259,U+02BC,U+02C6-02C7,U+02C9,U+02DA,U+02DC-02DD,U+02F3,U+0300-0301,U+0303,U+0309,U+0323,U+0384-038A,U+038C,U+038E-03A1,U+03A3-03CE,U+03D1-03D2,U+03D6,U+0400-0486,U+0488-0513,U+1E00-1E01,U+1E3E-1E3F,U+1E80-1E85,U+1EA0-1EF9,U+2002,U+2009,U+200B,U+2013-2014,U+2018-201A,U+201C-201E,U+2020,U+2022,U+2026,U+2032-2033,U+2039-203A,U+2044,U+20A3-20A4,U+20A7,U+20AB-20AC,U+2113,U+2116,U+2122,U+2212,U+2215,U+FEFF,U+FFFD",
    },
  ],
});

// Qiko brand display font. Self-hosted via next/font so it is preloaded
// with the app instead of depending on a runtime external stylesheet.
const satoshi = localFont({
  src: [
    { path: "./fonts/satoshi-400.woff2", weight: "400" },
    { path: "./fonts/satoshi-500.woff2", weight: "500" },
    { path: "./fonts/satoshi-700.woff2", weight: "700" },
    { path: "./fonts/satoshi-900.woff2", weight: "900" },
  ],
  variable: "--font-satoshi",
  display: "swap",
});

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  maximumScale: 5,
  themeColor: "#0D1B2A",
};

export const metadata: Metadata = {
  title: {
    default: "Qiko Signal - SEO & AIO Intelligence Analyzer",
    template: "%s | Qiko Signal",
  },
  description: "Get precision scores and suggestions for your website and entities.",
  manifest: `${BASE_PATH}/manifest.webmanifest`,
  metadataBase: new URL(process.env.NEXT_PUBLIC_APP_URL || "https://qiko.ai/signal"),
  openGraph: {
    type: "website",
    locale: "en_US",
    siteName: "Qiko Signal",
  },
  icons: {
    icon: [
      { url: `${BASE_PATH}/favicon.ico`, sizes: "48x48" },
      { url: `${BASE_PATH}/icon.svg`, type: "image/svg+xml" },
    ],
    shortcut: `${BASE_PATH}/favicon.ico`,
    apple: `${BASE_PATH}/apple-touch-icon.png`,
  },
  verification: {
    google: process.env.NEXT_PUBLIC_GOOGLE_SITE_VERIFICATION || undefined,
    other: {
      ...(process.env.NEXT_PUBLIC_BING_SITE_VERIFICATION
        ? { "msvalidate.01": process.env.NEXT_PUBLIC_BING_SITE_VERIFICATION }
        : {}),
    },
  },
};

export default async function RootLayout({ children }: { children: React.ReactNode }) {
  const nonce = (await headers()).get("x-nonce") ?? "";
  const langCookie = (await cookies()).get("preferred_language")?.value;
  // English is the only always-on interface language; `ar` is accepted from
  // the cookie (only ever set when the RTL flag is on) so dir resolves to
  // "rtl". Any other stored value, including a legacy "ro", falls back to "en".
  const lang = langCookie === "ar" ? "ar" : "en";
  const dir = localeDir(lang);

  return (
    <html lang={lang} dir={dir} className="dark" suppressHydrationWarning>
      <body
        className={`${inter.variable} ${robotoMono.variable} ${satoshi.variable} bg-(--background) font-sans text-(--foreground) antialiased`}
      >
        <QikoBackdrop />
        <a
          href="#main-content"
          className="sr-only focus:not-sr-only focus:fixed focus:inset-s-4 focus:top-4 focus:z-100 focus:rounded-lg focus:bg-(--primary) focus:px-4 focus:py-2 focus:text-sm focus:font-semibold focus:text-white focus:shadow-lg focus:outline-hidden"
        >
          Skip to main content
        </a>
        <BasePathShim />
        <QueryProvider>
          <I18nProvider>
            <AuthProvider>
              <CookieConsentProvider>
                {/* SIGV2-1226: sonner refocuses the element you came from the moment
                    focus leaves the toaster, so Tab cannot get past a live toast. The
                    wrapper intercepts that bookkeeping; every Toaster prop below is
                    unchanged. */}
                <ToastFocusRelease>
                  <Toaster
                    position="bottom-right"
                    offset={{ bottom: 24, right: 24 }}
                    mobileOffset={16}
                    gap={8}
                    className="w-[calc(100vw-32px)]! sm:w-[360px]!"
                    theme="light"
                    expand
                    closeButton
                    richColors={false}
                    icons={{
                      // The four approved `.alert` glyphs (Signal Components
                      // #sec-alerts), reused here so tone is carried by shape,
                      // never by colour alone (SIGV2-1171, WCAG 1.4.1).
                      success: (
                        <CheckCircle2
                          size={15}
                          strokeWidth={2}
                          className="thoth-toast-icon"
                          aria-hidden="true"
                        />
                      ),
                      error: (
                        <XCircle
                          size={15}
                          strokeWidth={2}
                          className="thoth-toast-icon"
                          aria-hidden="true"
                        />
                      ),
                      warning: (
                        <AlertTriangle
                          size={15}
                          strokeWidth={2}
                          className="thoth-toast-icon"
                          aria-hidden="true"
                        />
                      ),
                      info: (
                        <Info
                          size={15}
                          strokeWidth={2}
                          className="thoth-toast-icon"
                          aria-hidden="true"
                        />
                      ),
                      loading: (
                        <Loader2
                          size={15}
                          strokeWidth={2}
                          className="thoth-toast-icon animate-spin"
                          aria-hidden="true"
                        />
                      ),
                    }}
                    toastOptions={{
                      duration: 5000,
                      unstyled: true,
                      classNames: {
                        toast: "thoth-toast thoth-toast-panel",
                        success: "thoth-toast-success",
                        error: "thoth-toast-error",
                        warning: "thoth-toast-warning",
                        info: "thoth-toast-info",
                        loading: "thoth-toast-loading",
                      },
                    }}
                  />
                </ToastFocusRelease>
                {children}
                <GoogleTagManager nonce={nonce} />
                <div data-signal-theme>
                  <CookieConsentManager />
                </div>
              </CookieConsentProvider>
            </AuthProvider>
          </I18nProvider>
        </QueryProvider>
      </body>
    </html>
  );
}
