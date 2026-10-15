"use client";

import React, { useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { toast } from "sonner";
import { Fingerprint, MailCheck, ShieldCheck } from "lucide-react";

import { useAuth } from "@/contexts/AuthContext";
import { AUTH_REDIRECT_PARAM } from "@/constants/auth";
import authService, { type AuthServiceError } from "@/services/auth.service";
import { checkHasPasskeys, loginWithPasskey } from "@/services/passkey.service";
import TextField from "@/components/ui/TextField";
import Button from "@/components/ui/Button";

import {
  AuthFormDivider,
  AuthForgotPasswordLink,
  AuthFormSocialSection,
  AuthSubmitButton,
} from "./AuthFormSections";
import AuthCheckbox from "./AuthCheckbox";
import { AUTH_STATES, AuthInlineNotice, AuthStateHeader } from "./AuthPrimitives";
const SSO_ENABLED = process.env.NEXT_PUBLIC_ENABLE_SSO === "true";

const loginSchema = z.object({
  email: z.string().email("Invalid email address"),
  password: z.string().min(6, "Password must be at least 6 characters"),
});

type LoginFormData = z.infer<typeof loginSchema>;

export const LoginForm = () => {
  const [isLoading, setIsLoading] = useState(false);
  const [mfaRequired, setMfaRequired] = useState(false);
  const [mfaCode, setMfaCode] = useState("");
  const [rememberMe, setRememberMe] = useState(true);
  const [isPasskeyLoading, setIsPasskeyLoading] = useState(false);
  const [hasPasskeys, setHasPasskeys] = useState(false);
  const [checkedEmail, setCheckedEmail] = useState("");
  const [emailNotVerified, setEmailNotVerified] = useState(false);
  const [resendLoading, setResendLoading] = useState(false);
  // SIGV2-1307: what the last resend did, kept on the page rather than in a
  // toast that is gone before the user has read it.
  const [resendResult, setResendResult] = useState<{ ok: boolean; email: string } | null>(null);
  const [showSessionExpiredNotice, setShowSessionExpiredNotice] = useState(false);

  const { login, setSession } = useAuth();
  const router = useRouter();
  const searchParams = useSearchParams();
  const redirect =
    searchParams.get(AUTH_REDIRECT_PARAM) ?? searchParams.get("redirect") ?? "/dashboard";

  useEffect(() => {
    const oauthError = searchParams.get("error");
    if (oauthError) {
      const provider = searchParams.get("provider") ?? "provider";
      const messages: Record<string, string> = {
        oauth_state_mismatch: `Sign-in session expired. Please try ${provider} again.`,
        oauth_failed: `Something went wrong during ${provider} sign-in. Please try again.`,
      };
      toast.error(messages[oauthError] ?? `Sign-in failed (${oauthError}).`, {
        id: "oauth-error-toast",
      });
      return;
    }

    if (searchParams.get("session_expired") === "true") {
      setShowSessionExpiredNotice(true);
      const hasToasted = sessionStorage.getItem("session_expired_toast");
      if (!hasToasted) {
        toast.error("Your session expired. Sign in to continue.", {
          id: "session-expired-toast",
        });
        sessionStorage.setItem("session_expired_toast", "true");
      }
      return;
    }

    setShowSessionExpiredNotice(false);
    sessionStorage.removeItem("session_expired_toast");
  }, [searchParams]);

  const {
    register,
    handleSubmit,
    getValues,
    formState: { errors },
  } = useForm<LoginFormData>({
    resolver: zodResolver(loginSchema),
  });

  const onSubmit = async (data: LoginFormData) => {
    try {
      setIsLoading(true);
      if (mfaRequired && !/^\d{6}$/.test(mfaCode.replace(/\s+/g, ""))) {
        toast.error("Enter the 6-digit authentication code.");
        return;
      }

      await login({
        ...data,
        mfa_code: mfaRequired ? mfaCode : undefined,
        remember_me: rememberMe,
      });
      setMfaRequired(false);
      setMfaCode("");
      toast.success("Signed in successfully.");
      router.push(redirect);
    } catch (error) {
      const authError = error as AuthServiceError;
      if (authError.emailNotVerified) {
        setEmailNotVerified(true);
        return;
      }
      if (authError.mfaRequired) {
        setMfaRequired(true);
        toast.error(authError.message || "Multi-factor authentication required.");
        return;
      }
      toast.error(authError.message || "Failed to sign in.");
    } finally {
      setIsLoading(false);
    }
  };

  const handlePasskeyLogin = async () => {
    setIsPasskeyLoading(true);
    try {
      const email = getValues("email") || undefined;
      await loginWithPasskey(email);
      await setSession();
      toast.success("Signed in with passkey.");
      router.push(redirect);
    } catch (err) {
      const message = err instanceof Error ? err.message : "Passkey sign-in failed.";
      if (
        message.includes("cancelled") ||
        message.includes("AbortError") ||
        message.includes("NotAllowedError")
      ) {
        return;
      }
      toast.error(message);
    } finally {
      setIsPasskeyLoading(false);
    }
  };

  const handleResendVerification = async () => {
    const email = getValues("email");
    if (!email) return;
    setResendLoading(true);
    // SIGV2-1307: the outcome stays on the page.
    //
    // This reported its result as a toast only. QA pressed it, saw nothing
    // they could point at, and logged "Resend shows no confirmation" as part
    // of a blocker. The mail had in fact been sent: the outbox shows five
    // messages to that address, each accepted by SMTP on the first attempt.
    //
    // A toast is the wrong shape for the one thing a blocked user is waiting
    // on. It is brief, it is easy to miss, and on this screen it competes
    // with whatever else is happening. The answer is now written where the
    // question was asked, and it names the address, because "check your
    // inbox" is useless if the inbox is not the one you think.
    setResendResult(null);
    try {
      await authService.resendVerificationEmail(email);
      setResendResult({ ok: true, email });
    } catch {
      setResendResult({ ok: false, email });
    } finally {
      setResendLoading(false);
    }
  };

  const handleEmailBlur = async () => {
    const email = getValues("email");
    if (!email || email === checkedEmail) return;
    const valid = z.string().email().safeParse(email).success;
    if (!valid) return;
    setCheckedEmail(email);
    const result = await checkHasPasskeys(email);
    setHasPasskeys(result);
  };

  // SIGV2-1307: a new account lands here knowing what happened and what next.
  //
  // Registration used to push straight to /login with the explanation in a
  // toast that the navigation outran, so a user whose mail had not arrived
  // yet had no way to tell whether the product had even tried. It had: the
  // outbox shows the verification message accepted by SMTP on the first
  // attempt. What was missing was any trace of it on screen.
  const justRegistered = searchParams.get("registered");
  if (justRegistered && !emailNotVerified) {
    return (
      <div className="w-full space-y-5">
        <div
          role="status"
          data-registered-notice=""
          className="rounded-(--r-md) border border-[color-mix(in_srgb,var(--blue)_30%,transparent)] bg-(--blue-s) p-[18px]"
        >
          <div className="flex items-start gap-3">
            <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded border border-primary/25 bg-primary/10 text-primary">
              <MailCheck className="h-5 w-5" />
            </div>
            <div className="space-y-2">
              <h2 className="text-lg font-semibold text-(--foreground)">Check your inbox</h2>
              <p className="text-sm leading-6 text-(--text-soft)">
                Your account is created. We have sent a verification link to{" "}
                <span className="font-medium text-(--foreground)">{justRegistered}</span>. Open it
                to finish signing in, and check spam if it is not there within a minute.
              </p>
            </div>
          </div>
        </div>

        <button
          className="text-sm font-medium text-(--text-soft) transition-colors hover:text-(--foreground)"
          type="button"
          onClick={() => router.replace("/login")}
        >
          Back to sign in
        </button>
      </div>
    );
  }

  if (emailNotVerified) {
    return (
      <div className="w-full space-y-5">
        <div className="rounded-(--r-md) border border-[color-mix(in_srgb,var(--blue)_30%,transparent)] bg-(--blue-s) p-[18px]">
          <div className="flex items-start gap-3">
            <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded border border-primary/25 bg-primary/10 text-primary">
              <MailCheck className="h-5 w-5" />
            </div>
            <div className="space-y-2">
              <h2 className="text-lg font-semibold text-(--foreground)">Verify your email</h2>
              <p className="text-sm leading-6 text-(--text-soft)">
                Your email address has not been verified yet. Please check your inbox for the
                verification link, or request a new one below.
              </p>
            </div>
          </div>
        </div>

        <Button
          className="w-full justify-center"
          loading={resendLoading}
          loadingText="Sending..."
          size="md"
          variant="auth"
          onClick={handleResendVerification}
        >
          Resend verification email
        </Button>

        {resendResult ? (
          <p
            role="status"
            data-resend-result={resendResult.ok ? "sent" : "failed"}
            className="text-sm leading-6 text-(--text-soft)"
          >
            {resendResult.ok
              ? `Sent. Check the inbox for ${resendResult.email}, including spam.`
              : `Could not send to ${resendResult.email}. Try again in a moment.`}
          </p>
        ) : null}

        <button
          className="text-sm font-medium text-(--text-soft) transition-colors hover:text-(--foreground)"
          type="button"
          onClick={() => setEmailNotVerified(false)}
        >
          Back to sign in
        </button>
      </div>
    );
  }

  const showMockDemoHint =
    process.env.NEXT_PUBLIC_MOCK_PREVIEW === "1" ||
    process.env.NEXT_PUBLIC_MOCK_PREVIEW === "true";

  return (
    <div className="w-full space-y-4">
      {showSessionExpiredNotice ? (
        <AuthInlineNotice
          className="mb-1"
          description="For security reasons, your previous session has ended. Continue with password, passkey, or provider sign-in."
          title="Your session expired. Sign in to continue."
          variant="warning"
        />
      ) : null}

      {showMockDemoHint ? (
        <AuthInlineNotice
          className="mb-1"
          description="Use demo@demo.com / demo123 to open the mock preview dashboard."
          title="Demo preview sign-in"
          variant="progress"
        />
      ) : null}

      {SSO_ENABLED ? (
        <>
          <AuthFormSocialSection mode="login" variant="icon-row" />
          <AuthFormDivider className="my-4" label="or use password" />
        </>
      ) : null}

      <form onSubmit={handleSubmit(onSubmit)} className="space-y-4">
        {!mfaRequired ? (
          <>
            <TextField
              {...register("email")}
              error={errors.email?.message}
              label="Email"
              onBlur={handleEmailBlur}
              placeholder="your@email.com"
              type="email"
              autoCapitalize="none"
              autoCorrect="off"
              spellCheck={false}
              variant="auth"
            />

            {hasPasskeys ? (
              <Button
                className="w-full justify-center gap-2"
                disabled={isPasskeyLoading}
                loading={isPasskeyLoading}
                loadingText="Verifying passkey..."
                size="lg"
                type="button"
                variant="outline"
                onClick={handlePasskeyLogin}
              >
                <Fingerprint className="h-5 w-5" strokeWidth={2.4} />
                Sign in with passkey
              </Button>
            ) : null}

            <TextField
              {...register("password")}
              error={errors.password?.message}
              label="Password"
              placeholder="********"
              type="password"
              variant="auth"
            />

            <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-2">
              <AuthCheckbox
                aria-label="Remember me"
                checked={rememberMe}
                id="remember-me"
                label="Remember me"
                onChange={(event) => setRememberMe(event.target.checked)}
              />
              <AuthForgotPasswordLink href="/forgot-password" label="Forgot password?" />
            </div>
          </>
        ) : (
          <div className="space-y-5 rounded-(--r-md) border-0 bg-[#EEF1F6] p-[18px]">
            <div className="flex items-start gap-3">
              <div className="flex h-10 w-10 items-center justify-center rounded border border-primary/25 bg-primary/10 text-primary">
                <ShieldCheck className="h-5 w-5" />
              </div>
              <AuthStateHeader
                chip={{ variant: "progress", label: AUTH_STATES.verifying }}
                className="space-y-2"
                subtitle="Use your 6-digit verification code to complete sign-in."
                title="Enter the code from your authenticator app"
              />
            </div>

            <TextField
              autoComplete="one-time-code"
              inputMode="numeric"
              label="Authentication Code"
              maxLength={6}
              placeholder="123456"
              type="text"
              value={mfaCode}
              variant="auth"
              onChange={(event) => {
                const digitsOnly = event.target.value.replace(/\D/g, "").slice(0, 6);
                setMfaCode(digitsOnly);
              }}
            />

            <Button
              className="w-full justify-center gap-2"
              disabled={isPasskeyLoading}
              size="lg"
              type="button"
              variant="ghost"
              onClick={handlePasskeyLogin}
            >
              <Fingerprint className="h-6 w-6" strokeWidth={2.4} />
              Use a passkey instead
            </Button>

            <button
              className="text-sm font-medium text-(--text-soft) transition-colors hover:text-(--foreground)"
              type="button"
              onClick={() => {
                setMfaRequired(false);
                setMfaCode("");
              }}
            >
              Back to sign in
            </button>
          </div>
        )}

        <AuthSubmitButton
          loading={isLoading}
          loadingText={mfaRequired ? "Verifying identity..." : "Completing sign-in..."}
        >
          {mfaRequired ? "Verify and sign in" : "Sign in"}
        </AuthSubmitButton>
      </form>
    </div>
  );
};
