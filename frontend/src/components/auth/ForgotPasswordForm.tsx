"use client";

import React, { useState } from "react";
import Link from "next/link";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { toast } from "sonner";

import AuthService from "@/services/auth.service";
import TextField from "@/components/ui/TextField";
import { buttonClasses } from "@/components/ui/Button";
import { cx } from "@/components/ui/utils";

import { AuthSubmitButton } from "./AuthFormSections";
import { AUTH_STATES, AuthInlineNotice, AuthStateHeader } from "./AuthPrimitives";

const forgotPasswordSchema = z.object({
  email: z.string().email("Invalid email address"),
});

type ForgotPasswordFormData = z.infer<typeof forgotPasswordSchema>;

export const ForgotPasswordForm = () => {
  const [isLoading, setIsLoading] = useState(false);
  const [isSubmitted, setIsSubmitted] = useState(false);
  const [submittedEmail, setSubmittedEmail] = useState("");

  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm<ForgotPasswordFormData>({
    resolver: zodResolver(forgotPasswordSchema),
  });

  const onSubmit = async (data: ForgotPasswordFormData) => {
    try {
      setIsLoading(true);
      await AuthService.forgotPassword(data.email);
      setSubmittedEmail(data.email);
      setIsSubmitted(true);
      toast.success("If an account exists, reset instructions are on the way.");
    } catch (error: unknown) {
      const message = error instanceof Error ? error.message : "Failed to send reset instructions.";
      toast.error(message);
    } finally {
      setIsLoading(false);
    }
  };

  if (isSubmitted) {
    return (
      <div className="space-y-6">
        <AuthStateHeader
          chip={{ variant: "success", label: AUTH_STATES.success }}
          subtitle={`If ${submittedEmail || "this email"} matches an account, you will receive password reset instructions shortly.`}
          title="Check your inbox"
        />
        <AuthInlineNotice
          description="Wait a minute, check your spam folder, then request a new link if needed."
          title="Did not receive the email?"
          variant="progress"
        />
        {/* The route back to sign-in belongs to AuthShell's shared footer, which
            every auth screen renders. Repeating it here stacked two links to
            /login on the same card (SIGV2-1088). */}
        <div className="flex flex-wrap gap-3">
          <Link
            className={cx(buttonClasses({ variant: "ghost", size: "md" }))}
            href="/forgot-password"
          >
            Request new link
          </Link>
        </div>
      </div>
    );
  }

  return (
    <div className="mx-auto w-full max-w-md space-y-5">
      <form onSubmit={handleSubmit(onSubmit)} className="space-y-5">
        <TextField
          {...register("email")}
          error={errors.email?.message}
          label="Email"
          placeholder="your@email.com"
          type="email"
          autoCapitalize="none"
          autoCorrect="off"
          spellCheck={false}
          variant="auth"
        />

        <AuthSubmitButton loading={isLoading} loadingText="Sending reset instructions...">
          Send reset instructions
        </AuthSubmitButton>
      </form>
    </div>
  );
};
