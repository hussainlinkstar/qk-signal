"use client";

import React, { useState } from "react";
import { Loader2 } from "lucide-react";
import { toast } from "sonner";

import SignalAlert, { SIGNAL_ALERT_ACTION } from "@/components/signal/SignalAlert";
import authService from "@/services/auth.service";

type EmailVerificationBannerProps = {
  email: string;
  onDismiss: () => void;
};

export default function EmailVerificationBanner({
  email,
  onDismiss,
}: EmailVerificationBannerProps) {
  const [isResending, setIsResending] = useState(false);

  const handleResend = async () => {
    try {
      setIsResending(true);
      await authService.resendVerificationEmail(email);
      toast.success("If this email exists, a new verification link has been sent.");
    } catch (error) {
      const message =
        error instanceof Error ? error.message : "Unable to resend verification email.";
      toast.error(message);
    } finally {
      setIsResending(false);
    }
  };

  return (
    <SignalAlert
      tone="warning"
      title="Verify your email to unlock all features."
      onDismiss={onDismiss}
      dismissLabel="Dismiss"
      actions={
        <button
          type="button"
          className={SIGNAL_ALERT_ACTION}
          disabled={isResending}
          aria-busy={isResending || undefined}
          onClick={() => {
            void handleResend();
          }}
        >
          {isResending ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" /> : null}
          {isResending ? "Sending..." : "Resend verification email"}
        </button>
      }
    >
      <p>Complete verification to secure your account and receive report delivery updates.</p>
    </SignalAlert>
  );
}
