"use client";

import React, { useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { toast } from "sonner";

import AuthService from "@/services/auth.service";
import TextField from "@/components/ui/TextField";
import PasswordStrengthIndicator from "@/components/auth/PasswordStrengthIndicator";
import { passwordSchema } from "@/lib/auth-validation";

import { AuthSubmitButton } from "./AuthFormSections";

const resetPasswordSchema = z
  .object({
    password: passwordSchema,
    confirmPassword: z.string(),
  })
  .refine((data) => data.password === data.confirmPassword, {
    message: "Passwords don't match",
    path: ["confirmPassword"],
  });

type ResetPasswordFormData = z.infer<typeof resetPasswordSchema>;
type ResetPasswordMode = "invite" | "reset";

type ResetPasswordFormProps = {
  mode?: ResetPasswordMode;
};

const copyByMode: Record<
  ResetPasswordMode,
  {
    passwordLabel: string;
    confirmLabel: string;
    submitLabel: string;
    successMessage: string;
    invalidTokenMessage: string;
  }
> = {
  invite: {
    passwordLabel: "Password",
    confirmLabel: "Confirm Password",
    submitLabel: "Set up password",
    successMessage: "Password set successfully.",
    invalidTokenMessage: "Invalid setup link.",
  },
  reset: {
    passwordLabel: "New Password",
    confirmLabel: "Confirm New Password",
    submitLabel: "Reset password",
    successMessage: "Password reset complete.",
    invalidTokenMessage: "Invalid reset token.",
  },
};

export const ResetPasswordForm = ({ mode = "reset" }: ResetPasswordFormProps) => {
  const [isLoading, setIsLoading] = useState(false);
  const router = useRouter();
  const searchParams = useSearchParams();
  const token = searchParams.get("token");
  const copy = copyByMode[mode];

  const {
    register,
    watch,
    handleSubmit,
    formState: { errors },
  } = useForm<ResetPasswordFormData>({
    resolver: zodResolver(resetPasswordSchema),
  });
  const passwordValue = watch("password", "");

  const onSubmit = async (data: ResetPasswordFormData) => {
    if (!token) {
      toast.error(copy.invalidTokenMessage);
      return;
    }

    try {
      setIsLoading(true);
      await AuthService.resetPassword(token, data.password);
      toast.success(copy.successMessage);
      router.push("/login");
    } catch (error: unknown) {
      const message = error instanceof Error ? error.message : "Failed to reset password.";
      toast.error(message);
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <form onSubmit={handleSubmit(onSubmit)} className="space-y-4">
      <p id="password-policy" className="text-[12.5px] leading-[1.5] text-(--t-2)">
        Use at least 8 characters with uppercase, lowercase, a number, and a special character.
      </p>

      <TextField
        {...register("password")}
        id="password"
        aria-describedby="password-policy"
        error={errors.password?.message}
        label={copy.passwordLabel}
        placeholder="Enter a strong password"
        type="password"
        variant="auth"
      />

      <PasswordStrengthIndicator password={passwordValue} />

      <TextField
        {...register("confirmPassword")}
        id="confirm-password"
        error={errors.confirmPassword?.message}
        label={copy.confirmLabel}
        placeholder="Re-enter your password"
        type="password"
        variant="auth"
      />

      <AuthSubmitButton loading={isLoading} loadingText="Updating password...">
        {copy.submitLabel}
      </AuthSubmitButton>
    </form>
  );
};
