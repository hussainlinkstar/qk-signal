"use client";

import React, { useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { toast } from "sonner";

import AuthService from "@/services/auth.service";
import TextField from "@/components/ui/TextField";
import PasswordStrengthIndicator from "@/components/auth/PasswordStrengthIndicator";
import { passwordSchema } from "@/lib/auth-validation";

import AuthCheckbox from "./AuthCheckbox";
import { AuthFormDivider, AuthFormSocialSection, AuthSubmitButton } from "./AuthFormSections";
import { resolveQikoSiteUrl } from "@/lib/qiko-site-url";

const qikoSiteUrl = resolveQikoSiteUrl();
const SSO_ENABLED = process.env.NEXT_PUBLIC_ENABLE_SSO === "true";

const registerSchema = z
  .object({
    name: z.string().min(2, "Name must be at least 2 characters"),
    email: z.string().email("Invalid email address"),
    password: passwordSchema,
    confirmPassword: z.string(),
    legalConsent: z.boolean().refine((value) => value, {
      message: "You must agree to the Terms of Service and Privacy Policy.",
    }),
  })
  .refine((data) => data.password === data.confirmPassword, {
    message: "Passwords don't match",
    path: ["confirmPassword"],
  });

type RegisterFormData = z.infer<typeof registerSchema>;

export const RegisterForm = () => {
  const [isLoading, setIsLoading] = useState(false);
  const router = useRouter();

  const {
    register,
    watch,
    handleSubmit,
    formState: { errors },
  } = useForm<RegisterFormData>({
    resolver: zodResolver(registerSchema),
    defaultValues: {
      legalConsent: false,
    },
  });
  const passwordValue = watch("password", "");

  const onSubmit = async (data: RegisterFormData) => {
    try {
      setIsLoading(true);
      await AuthService.register({
        name: data.name,
        email: data.email,
        password: data.password,
      });
      // SIGV2-1307: the confirmation survives the navigation.
      //
      // This fired a toast and then immediately pushed to /login, so the one
      // sentence telling a new user what happens next was racing a route
      // change. QA logged "Create account sends the user to /login with no
      // 'check your email' step", and separately logged the missing mail as a
      // blocker, when the mail had in fact been sent.
      //
      // Carrying the address in the URL means /login can say it in place,
      // naming the inbox, rather than relying on something transient.
      toast.success("Account created. Check your inbox to verify your email.");
      router.push(`/login?registered=${encodeURIComponent(data.email)}`);
    } catch (error: unknown) {
      const message = error instanceof Error ? error.message : "Registration failed.";
      toast.error(message);
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="w-full space-y-4">
      {SSO_ENABLED ? (
        <>
          <AuthFormSocialSection mode="register" variant="icon-row" />
          <AuthFormDivider label="or use email" />
        </>
      ) : null}

      <form onSubmit={handleSubmit(onSubmit)} className="space-y-4">
        {/* SIGV2-1307: the label says which name this is.
            QA: "Label is Name; placeholder is 'Agency or company name'".
            The placeholder was the honest one. This field writes
            `User.company_name`: its value goes through
            `normalize_company_name` in `schemas/auth.py`, whose docstring
            calls itself "the single rule for User.company_name". A person's
            own name is not stored here at all.
            So the label was the wrong half, and it is the half a reader
            trusts. Same confusion between a label and a real name that
            SIGV2-1288 fixed in the prompt generator. */}
        <TextField
          {...register("name")}
          error={errors.name?.message}
          label="Company or agency name"
          placeholder="For example, Northwind Studio"
          type="text"
          variant="auth"
        />

        <TextField
          {...register("email")}
          error={errors.email?.message}
          label="Email"
          placeholder="you@company.com"
          type="email"
          autoCapitalize="none"
          autoCorrect="off"
          spellCheck={false}
          variant="auth"
        />

        <div className="grid grid-cols-1 gap-3.5 sm:grid-cols-2">
          <TextField
            {...register("password")}
            error={errors.password?.message}
            label="Password"
            placeholder="Create password"
            type="password"
            variant="auth"
          />

          <TextField
            {...register("confirmPassword")}
            error={errors.confirmPassword?.message}
            label="Confirm Password"
            placeholder="Repeat password"
            type="password"
            variant="auth"
          />
        </div>

        <PasswordStrengthIndicator password={passwordValue} />

        <AuthCheckbox
          aria-label="I agree to the Terms of Service and Privacy Policy"
          error={errors.legalConsent?.message}
          label={
            <>
              I agree to the{" "}
              <Link
                href={`${qikoSiteUrl}/signal/terms`}
                className="font-medium text-(--foreground) underline underline-offset-4 transition-colors hover:text-primary"
              >
                Terms of Service
              </Link>{" "}
              and{" "}
              <Link
                href={`${qikoSiteUrl}/signal/privacy`}
                className="font-medium text-(--foreground) underline underline-offset-4 transition-colors hover:text-primary"
              >
                Privacy Policy
              </Link>
              .
            </>
          }
          {...register("legalConsent")}
          id="register-legal-consent"
        />

        <AuthSubmitButton loading={isLoading} loadingText="Creating account...">
          Create account
        </AuthSubmitButton>
      </form>
    </div>
  );
};
