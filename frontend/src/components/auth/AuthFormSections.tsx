import React, { type ReactNode } from "react";
import Link from "next/link";

import Button from "@/components/ui/Button";
import { cx } from "@/components/ui/utils";

import { SocialLogins, type SocialLoginMode } from "./SocialLogins";

type AuthFormSocialSectionProps = {
  className?: string;
  mode?: SocialLoginMode;
  variant?: "default" | "icon-row";
  label?: string;
  includePasskey?: boolean;
  onPasskeyClick?: () => void;
  passkeyLoading?: boolean;
};

export const AuthFormSocialSection = ({
  className,
  mode = "login",
  variant = "default",
  label,
  includePasskey = false,
  onPasskeyClick,
  passkeyLoading = false,
}: AuthFormSocialSectionProps) => (
  <div className={className}>
    <SocialLogins
      includePasskey={includePasskey}
      label={label}
      mode={mode}
      passkeyLoading={passkeyLoading}
      variant={variant}
      onPasskeyClick={onPasskeyClick}
    />
  </div>
);

type AuthFormDividerProps = {
  label: string;
  className?: string;
};

export const AuthFormDivider = ({ label, className }: AuthFormDividerProps) => (
  <div className={cx("relative flex items-center gap-3", className)}>
    <div className="h-px flex-1 bg-(--border)" />
    <span className="shrink-0 text-[12px] font-normal tracking-normal text-(--t-3)">{label}</span>
    <div className="h-px flex-1 bg-(--border)" />
  </div>
);

type AuthSubmitButtonProps = {
  loading: boolean;
  children: string;
  loadingText: string;
};

export const AuthSubmitButton = ({ loading, children, loadingText }: AuthSubmitButtonProps) => (
  <Button
    aria-busy={loading || undefined}
    className="w-full justify-center"
    loading={loading}
    loadingText={loadingText}
    size="md"
    type="submit"
    variant="auth"
  >
    {children}
  </Button>
);

type AuthFooterHelperProps = {
  children: ReactNode;
};

export const AuthFooterHelper = ({ children }: AuthFooterHelperProps) => (
  <div className="text-center">
    <p className="text-sm text-(--text-muted)">{children}</p>
  </div>
);

type AuthForgotPasswordLinkProps = {
  href: string;
  label: string;
};

export const AuthForgotPasswordLink = ({ href, label }: AuthForgotPasswordLinkProps) => (
  <div className="flex items-center justify-end">
    <Link
      href={href}
      className="inline-flex min-h-6 items-center rounded-sm text-[13px] font-semibold text-(--auth-link) underline-offset-4 hover:underline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-(--brand)"
    >
      {label}
    </Link>
  </div>
);
