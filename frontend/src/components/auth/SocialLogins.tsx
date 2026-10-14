"use client";

import { resolveBackendAuthUrl } from "@/lib/backendAuthUrl";
import React, { useState } from "react";
import { Fingerprint, Loader2 } from "lucide-react";

import Button from "@/components/ui/Button";
import BrandMark, { BRAND_MARK_LABELS, type BrandMarkId } from "@/components/ui/BrandMark";
import { cx } from "@/components/ui/utils";

export type SocialLoginMode = "login" | "register";
export type SocialLoginVariant = "default" | "icon-row";

type OAuthProvider = "google" | "github" | "linkedin" | "microsoft";

type ProviderDefinition = {
  id: OAuthProvider;
  brand: Extract<BrandMarkId, OAuthProvider>;
};

type SocialLoginsProps = {
  mode?: SocialLoginMode;
  variant?: SocialLoginVariant;
  label?: string;
  includePasskey?: boolean;
  onPasskeyClick?: () => void;
  passkeyLoading?: boolean;
};

export function resolveOAuthUrl(
  provider: OAuthProvider,
  _options: { mode?: SocialLoginMode } = {}
) {
  // OAuth login MUST go through the same origin: Caddy routes /api/v1/*
  // to the backend, and session cookies + Google redirect URIs must share
  // the browser origin.  Do NOT use a separate API subdomain here.
  return resolveBackendAuthUrl(`/auth/login/${provider}`);
}

const providers: ProviderDefinition[] = [
  { id: "microsoft", brand: "microsoft" },
  { id: "google", brand: "google" },
  { id: "github", brand: "github" },
  { id: "linkedin", brand: "linkedin" },
];

function ProviderButtonLabel({
  provider,
  compact = false,
}: {
  provider: ProviderDefinition;
  compact?: boolean;
}) {
  if (compact) {
    return (
      <span className="text-xs font-medium text-(--foreground)">
        {BRAND_MARK_LABELS[provider.brand]}
      </span>
    );
  }

  return (
    <span className="flex items-center gap-1.5 text-sm font-medium text-(--foreground)">
      <span>Login with</span>
      <span>{BRAND_MARK_LABELS[provider.brand]}</span>
    </span>
  );
}

/* Passkey Fingerprint is a stroke icon, bump it slightly larger than the
   filled brand-mark SVGs so it has comparable visual weight. */
const PASSKEY_ICON_CLASS_COMPACT = "h-5 w-5";
const PASSKEY_ICON_CLASS_DEFAULT = "h-6 w-6";
const PASSKEY_STROKE_WIDTH = 2.4;

function PasskeyIconButton({
  compact,
  loading,
  disabled,
  onClick,
}: {
  compact: boolean;
  loading: boolean;
  disabled?: boolean;
  onClick?: () => void;
}) {
  if (compact) {
    return (
      <Button
        aria-label="Sign in with passkey"
        className={cx("h-11 w-11 shrink-0 p-0!", loading && "border-primary/50")}
        disabled={disabled || loading}
        loading={false}
        size="md"
        title="Passkey"
        type="button"
        variant="ghost"
        onClick={onClick}
      >
        {loading ? (
          <Loader2 className="h-4 w-4 animate-spin" />
        ) : (
          <Fingerprint className={PASSKEY_ICON_CLASS_COMPACT} strokeWidth={PASSKEY_STROKE_WIDTH} />
        )}
      </Button>
    );
  }

  return (
    <Button
      className="w-full justify-center gap-3"
      loading={loading}
      loadingText="Verifying passkey..."
      size="md"
      type="button"
      variant="ghost"
      onClick={onClick}
    >
      <Fingerprint className={PASSKEY_ICON_CLASS_DEFAULT} strokeWidth={PASSKEY_STROKE_WIDTH} />
      <span>Sign in with passkey</span>
    </Button>
  );
}

export function SocialLogins({
  mode = "login",
  variant = "default",
  label: _label,
  includePasskey = false,
  onPasskeyClick,
  passkeyLoading = false,
}: SocialLoginsProps) {
  const [loadingProvider, setLoadingProvider] = useState<OAuthProvider | null>(null);
  const loadingText = mode === "register" ? "Continuing..." : "Completing sign-in...";

  const handleOAuthClick = (provider: OAuthProvider) => {
    setLoadingProvider(provider);
    window.location.assign(resolveOAuthUrl(provider, { mode }));
  };

  if (variant === "icon-row") {
    return (
      <div className="flex flex-wrap items-center justify-center gap-2.5">
        {providers.map((provider) => {
          const isLoading = loadingProvider === provider.id;
          return (
            <Button
              key={provider.id}
              aria-label={`Continue with ${BRAND_MARK_LABELS[provider.brand]}`}
              className={cx("h-11 w-11 shrink-0 p-0!", isLoading && "border-primary/50")}
              disabled={isLoading}
              loading={false}
              size="md"
              title={BRAND_MARK_LABELS[provider.brand]}
              type="button"
              variant="ghost"
              onClick={() => handleOAuthClick(provider.id)}
            >
              {isLoading ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <BrandMark brand={provider.brand} markClassName="h-4.5 w-4.5" />
              )}
            </Button>
          );
        })}
        {includePasskey ? (
          <PasskeyIconButton
            compact
            loading={passkeyLoading}
            disabled={!onPasskeyClick}
            onClick={onPasskeyClick}
          />
        ) : null}
      </div>
    );
  }

  return (
    <div className="space-y-3">
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        {providers.map((provider) => {
          const isLoading = loadingProvider === provider.id;
          return (
            <Button
              key={provider.id}
              aria-label={`Continue with ${BRAND_MARK_LABELS[provider.brand]}`}
              className={cx(
                "w-full justify-start gap-3 px-4 text-left",
                isLoading && "border-primary/50"
              )}
              loading={isLoading}
              loadingText={loadingText}
              size="md"
              type="button"
              variant="ghost"
              onClick={() => handleOAuthClick(provider.id)}
            >
              <BrandMark brand={provider.brand} markClassName="h-5 w-5" />
              <ProviderButtonLabel compact provider={provider} />
            </Button>
          );
        })}
      </div>

      {includePasskey ? (
        <PasskeyIconButton compact={false} loading={passkeyLoading} onClick={onPasskeyClick} />
      ) : null}
    </div>
  );
}
