"use client";

import { useEffect, useMemo, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { toast } from "sonner";
import { Fingerprint, ShieldCheck } from "lucide-react";

import AuthShell from "@/components/auth/AuthShell";
import {
  AUTH_STATES,
  AuthInlineNotice,
  AuthRecoveryCard,
  AuthStateHeader,
} from "@/components/auth/AuthPrimitives";
import Button from "@/components/ui/Button";
import TextField from "@/components/ui/TextField";
import authService from "@/services/auth.service";
import type { AuthTenantBranding } from "@/lib/auth-branding";

type VerificationState = "checking_inbox" | "verifying" | "success" | "error";

type VerifyEmailPageClientProps = {
  branding: AuthTenantBranding | null;
};

const isEmailFormatValid = (value: string) => /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value.trim());

export default function VerifyEmailPageClient({ branding }: VerifyEmailPageClientProps) {
  const [state, setState] = useState<VerificationState>("verifying");
  const [message, setMessage] = useState("Completing email verification...");
  const [resendEmail, setResendEmail] = useState("");
  const [isResending, setIsResending] = useState(false);
  const router = useRouter();
  const searchParams = useSearchParams();
  const token = useMemo(() => searchParams.get("token"), [searchParams]);
  const email = useMemo(() => searchParams.get("email"), [searchParams]);

  useEffect(() => {
    if (email) {
      setResendEmail(email);
    }
  }, [email]);

  useEffect(() => {
    const verify = async () => {
      if (!token) {
        setState("checking_inbox");
        setMessage("Check your inbox for the verification link.");
        return;
      }

      try {
        await authService.verifyEmail(token);
        setState("success");
        setMessage("Email verified. You can now sign in.");
      } catch (error: unknown) {
        const detail = error instanceof Error ? error.message : "Email verification failed.";
        setState("error");
        setMessage(
          "We could not verify this link. Request a new verification email and try again."
        );
        toast.error(detail);
      }
    };

    void verify();
  }, [token]);

  const handleResend = async () => {
    const normalizedEmail = resendEmail.trim().toLowerCase();
    if (!isEmailFormatValid(normalizedEmail)) {
      toast.error("Enter a valid email address to resend verification.");
      return;
    }

    try {
      setIsResending(true);
      await authService.resendVerificationEmail(normalizedEmail);
      toast.success("If this email exists, a new verification link has been sent.");
    } catch (error: unknown) {
      const detail =
        error instanceof Error ? error.message : "Unable to resend verification email.";
      toast.error(detail);
    } finally {
      setIsResending(false);
    }
  };

  return (
    <AuthShell
      branding={branding}
      chipLabel="Email Verification"
      footerCtaHref="/login"
      footerCtaLabel="Sign in"
      footerText="Already verified?"
      title="Verify your email"
    >
      <div className="space-y-4">
        {state === "verifying" ? (
          <AuthStateHeader
            chip={{ variant: "progress", label: AUTH_STATES.completing }}
            subtitle="Verifying your email link…"
            title="Completing email verification..."
          />
        ) : null}

        {state === "checking_inbox" ? (
          <>
            <AuthInlineNotice
              description={`Open the verification link sent to ${email || "your email address"}. If you cannot find it, check your spam folder or request a new link below.`}
              title="Check your inbox"
              variant="progress"
            />
            <div className="space-y-3">
              <TextField
                label="Email"
                placeholder="name@company.com"
                type="email"
                value={resendEmail}
                variant="auth"
                onChange={(event) => setResendEmail(event.target.value)}
              />
              <Button
                className="w-full"
                loading={isResending}
                loadingText="Resending verification..."
                type="button"
                variant="ghost"
                onClick={handleResend}
              >
                Resend verification email
              </Button>
            </div>
          </>
        ) : null}

        {state === "success" ? (
          <>
            <AuthStateHeader
              chip={{ variant: "success", label: AUTH_STATES.success }}
              subtitle={message}
              title="Email verified"
            />

            <div className="space-y-3 rounded-(--r-md) border border-(--line) bg-(--paper) p-[18px]">
              <div className="flex items-start gap-3">
                <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded border border-primary/25 bg-primary/10 text-primary">
                  <ShieldCheck className="h-4.5 w-4.5" />
                </div>
                <div className="space-y-1">
                  <p className="text-sm font-medium text-(--foreground)">Strengthen your account</p>
                  <p className="text-xs leading-5 text-(--text-soft)">
                    After signing in, visit Account Settings to enable two-factor authentication or
                    register a passkey for stronger protection.
                  </p>
                </div>
              </div>
              <div className="flex flex-wrap items-center gap-2 ps-12 text-[12px] font-normal tracking-normal text-(--t-3)">
                <ShieldCheck className="h-3.5 w-3.5" />
                <span>Authenticator app</span>
                <span className="text-(--border)">|</span>
                <Fingerprint className="h-3.5 w-3.5" />
                <span>Passkey</span>
              </div>
            </div>

            <Button
              className="w-full"
              size="md"
              variant="auth"
              onClick={() => router.push("/login")}
            >
              Continue to sign in
            </Button>
          </>
        ) : null}

        {state === "error" ? (
          // The route back to sign-in belongs to AuthShell's shared footer,
          // which this screen already renders. Repeating it here stacked two
          // links to /login with the same accessible name (SIGV2-1088).
          <AuthRecoveryCard
            description={message}
            primaryAction={{
              label: "Resend verification email",
              onClick: () => {
                void handleResend();
              },
              variant: "primary",
            }}
            title="Verification failed"
          />
        ) : null}
      </div>
    </AuthShell>
  );
}
