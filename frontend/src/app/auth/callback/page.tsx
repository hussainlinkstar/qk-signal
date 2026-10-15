"use client";

import { asset } from "@/lib/basePath";
import React, { Suspense, useEffect, useMemo, useRef, useState } from "react";
import { Loader2 } from "lucide-react";

import SignalBrandLockup from "@/components/signal/SignalBrandLockup";
import { AuthRecoveryCard } from "@/components/auth/AuthPrimitives";
import { CARD_LABEL_CLASS } from "@/components/ui/cardStyleTokens";
import { RADIUS_PANEL_CLASS } from "@/components/ui/radiusTokens";
import { TYPO } from "@/components/ui/typographyTokens";
import { cx } from "@/components/ui/utils";
import { useAuth } from "@/contexts/AuthContext";

type TokenPayload = {
  authenticated?: boolean;
};

type AuthStage = "verifying" | "exchanging" | "dashboard";
type CallbackErrorCode = "provider_error" | "expired_code" | "invalid_state" | "unknown";

type CallbackErrorState = {
  code: CallbackErrorCode;
  title: string;
  description: string;
};

type StageDefinition = {
  id: AuthStage;
  title: string;
  description: string;
};

const STAGES: StageDefinition[] = [
  {
    id: "verifying",
    title: "Verifying",
    description: "Checking your provider response and validating the secure handoff.",
  },
  {
    id: "exchanging",
    title: "Exchanging Token",
    description: "Issuing session tokens and binding them to your browser session.",
  },
  {
    id: "dashboard",
    title: "Loading Dashboard",
    description: "Opening your workspace with the new authenticated session.",
  },
];

async function exchangeOneTimeCode(code: string): Promise<TokenPayload> {
  const response = await fetch("/api/auth/exchange-code", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ code }),
    credentials: "include",
  });

  if (!response.ok) {
    if (response.status === 401) {
      throw new Error("expired_code");
    }
    throw new Error("invalid_state");
  }

  return response.json();
}

const providerDisplayNames: Record<string, string> = {
  google: "Google",
  github: "GitHub",
  linkedin: "LinkedIn",
  microsoft: "Microsoft",
};

const inferProviderName = (provider: string | null, errorDescription: string | null) => {
  if (provider && providerDisplayNames[provider.toLowerCase()]) {
    return providerDisplayNames[provider.toLowerCase()];
  }

  const normalized = (errorDescription || "").toLowerCase();
  if (normalized.includes("google")) {
    return "Google";
  }
  if (normalized.includes("github")) {
    return "GitHub";
  }
  if (normalized.includes("linkedin")) {
    return "LinkedIn";
  }
  if (normalized.includes("microsoft")) {
    return "Microsoft";
  }
  return "provider";
};

const buildCallbackError = (
  code: CallbackErrorCode,
  context?: { provider?: string | null; errorDescription?: string | null }
): CallbackErrorState => {
  if (code === "provider_error") {
    const providerName = inferProviderName(
      context?.provider ?? null,
      context?.errorDescription ?? null
    );
    return {
      code,
      title: "Provider session could not connect",
      description: `Your ${providerName} session couldn't connect. Try again or use email sign-in.`,
    };
  }

  if (code === "expired_code") {
    return {
      code,
      title: "Sign-in link expired",
      description: "This sign-in link expired. Return to Sign In and try again.",
    };
  }

  if (code === "invalid_state") {
    return {
      code,
      title: "Unexpected sign-in interruption",
      description: "Unexpected error during sign-in. Please try again.",
    };
  }

  return {
    code,
    title: "Could not complete sign-in",
    description: "We could not complete your secure sign-in flow. Please try again.",
  };
};

const toCallbackErrorCode = (value: string | null): CallbackErrorCode => {
  if (!value) {
    return "unknown";
  }
  if (value === "provider_error" || value === "expired_code" || value === "invalid_state") {
    return value;
  }
  if (value.includes("expired")) {
    return "expired_code";
  }
  if (value.includes("state") || value.includes("missing")) {
    return "invalid_state";
  }
  return "unknown";
};

function CallbackFrame({
  children,
  tone = "default",
}: {
  children: React.ReactNode;
  tone?: "default" | "error";
}) {
  const isErrorTone = tone === "error";

  return (
    <main className="relative flex min-h-screen items-center justify-center overflow-hidden bg-(--background) px-4 py-8 text-(--foreground) sm:px-6 sm:py-10">
      <div
        className={cx(
          "pointer-events-none absolute inset-0 opacity-90",
          isErrorTone
            ? "bg-[radial-gradient(circle_at_top,rgba(244,63,94,0.18),transparent_34%)]"
            : "bg-[radial-gradient(circle_at_top,rgba(6,182,212,0.16),transparent_36%)]"
        )}
      />
      <div
        className={cx(
          "pointer-events-none absolute -left-32 top-1/2 h-128 w-lg -translate-y-1/2 rounded-full blur-[160px]",
          isErrorTone ? "" : ""
        )}
      />
      <div
        className={cx(
          "pointer-events-none absolute right-[12%] -top-28 h-96 w-[24rem] rounded-full blur-[160px]",
          isErrorTone ? "" : ""
        )}
      />

      <section
        className={cx(
          "relative z-10 w-full max-w-184 overflow-hidden border-0  px-6 py-7 shadow-[0_32px_120px_rgba(0,0,0,0.58)] sm:px-8 sm:py-9",
          RADIUS_PANEL_CLASS
        )}
      >
        <div
          className={cx(
            "pointer-events-none absolute inset-x-0 top-0 h-px bg-linear-to-r from-transparent via-white/30 to-transparent",
            isErrorTone ? "via-rose-300/50" : "via-brand-aeo/50"
          )}
        />
        {children}
      </section>
    </main>
  );
}

function AuthenticationLoader({
  currentStage,
  showDetailedProgress: _showDetailedProgress,
}: {
  currentStage: AuthStage;
  showDetailedProgress: boolean;
}) {
  const stageIndex = STAGES.findIndex((item) => item.id === currentStage);
  const currentStageDefinition = STAGES[stageIndex] ?? STAGES[0];

  return (
    <CallbackFrame>
      <div className="flex flex-col items-center gap-6 py-4 text-center">
        <SignalBrandLockup className="w-fit" />
        <Loader2 className="h-7 w-7 animate-spin text-brand-aeo" />
        <div className="space-y-2">
          <h1 className="text-xl font-semibold tracking-tight text-white">Completing Sign-In</h1>
          <p className="text-sm leading-6 text-slate-400">{currentStageDefinition.description}</p>
        </div>
      </div>
    </CallbackFrame>
  );
}

function OAuthCallbackContent() {
  const { setSession } = useAuth();

  const [error, setError] = useState<CallbackErrorState | null>(null);
  const [currentStage, setCurrentStage] = useState<AuthStage>("verifying");
  const [showDetailedProgress, setShowDetailedProgress] = useState(false);
  const hasProcessedCodeRef = useRef(false);

  useEffect(() => {
    const timerId = window.setTimeout(() => {
      setShowDetailedProgress(true);
    }, 500);
    return () => {
      window.clearTimeout(timerId);
    };
  }, []);

  const errorView = useMemo(() => {
    if (!error) {
      return null;
    }

    const isProviderError = error.code === "provider_error";
    const isExpired = error.code === "expired_code";

    return (
      <CallbackFrame tone="error">
        <div className="space-y-6">
          <div className="space-y-4">
            <SignalBrandLockup className="w-fit" />
            <div className="space-y-2">
              <p className={cx(CARD_LABEL_CLASS, "text-rose-200")}>Secure Authentication Handoff</p>
              <h1 className={cx(TYPO.pageTitle, "text-white")}>Could not complete sign-in</h1>
              <p className="max-w-2xl text-sm leading-6 text-slate-300">
                The secure authentication handoff did not complete. Choose a recovery path below to
                continue.
              </p>
            </div>
          </div>
          {/* SIGV2-1171: for an expired link and a provider refusal this card
              used to offer "Try Sign In Again" and "Use Email Sign In" side by
              side, both pointing at /login. That is one action with two
              labels, and it asks the customer to choose between two things
              that are the same thing. Email sign-in is a form on /login, which
              the description above already says, so those two codes get the
              single route they actually have. A sign-in that failed for an
              unknown reason keeps two actions, because retrying and creating
              an account are two different destinations. */}
          <AuthRecoveryCard
            title={error.title}
            description={error.description}
            primaryAction={{ label: "Try Sign In Again", href: "/login", variant: "primary" }}
            secondaryAction={
              isExpired || isProviderError
                ? undefined
                : { label: "Create Account", href: "/register", variant: "inverse" }
            }
            className="border-rose-400/20 "
          />
        </div>
      </CallbackFrame>
    );
  }, [error]);

  useEffect(() => {
    if (hasProcessedCodeRef.current) {
      return;
    }
    hasProcessedCodeRef.current = true;

    const processCallback = async () => {
      try {
        const searchParams = new URLSearchParams(window.location.search);
        const code = searchParams.get("code");
        const providerError = searchParams.get("error");
        const provider = searchParams.get("provider");
        const providerErrorDescription = searchParams.get("error_description");

        if (providerError) {
          setError(
            buildCallbackError("provider_error", {
              provider,
              errorDescription: providerErrorDescription,
            })
          );
          return;
        }

        if (!code) {
          setError(buildCallbackError("invalid_state"));
          return;
        }

        setCurrentStage("verifying");
        const data = await exchangeOneTimeCode(code);

        if (!data.authenticated) {
          setError(buildCallbackError("invalid_state"));
          return;
        }

        setCurrentStage("exchanging");
        await setSession();

        setCurrentStage("dashboard");
        // Use a full document navigation after the auth-cookie exchange so the app shell
        // boots with the fresh session instead of racing a client-router refresh.
        window.location.replace(asset("/dashboard"));
      } catch (err) {
        const message = err instanceof Error ? err.message : null;
        const callbackErrorCode = toCallbackErrorCode(message);
        setError(buildCallbackError(callbackErrorCode));
      }
    };

    void processCallback();
  }, [setSession]);

  if (errorView) {
    return errorView;
  }

  return (
    <AuthenticationLoader currentStage={currentStage} showDetailedProgress={showDetailedProgress} />
  );
}

export default function OAuthCallbackPage() {
  return (
    <Suspense
      fallback={<AuthenticationLoader currentStage="verifying" showDetailedProgress={false} />}
    >
      <OAuthCallbackContent />
    </Suspense>
  );
}
