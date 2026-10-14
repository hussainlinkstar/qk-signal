import React, { Suspense } from "react";
import AuthShell from "@/components/auth/AuthShell";
import { ResetPasswordForm } from "@/components/auth/ResetPasswordForm";
import { fetchAuthBranding } from "@/lib/auth-branding";

type ResetPasswordPageProps = {
  searchParams?: {
    flow?: string | string[];
  };
};

const normalizeFlow = (value: string | string[] | undefined) =>
  Array.isArray(value) ? value[0] : value;

export default async function ResetPasswordPage({ searchParams }: ResetPasswordPageProps) {
  const flow = normalizeFlow(searchParams?.flow);
  const isInviteFlow = flow === "invite";
  const branding = await fetchAuthBranding();

  return (
    <AuthShell
      chipLabel={isInviteFlow ? "Portal Onboarding" : "Session Recovery"}
      title={isInviteFlow ? "Set your password" : "Set a new password"}
      subtitle={
        isInviteFlow
          ? "Choose a strong password to activate your client portal access."
          : "Choose a strong password to secure your account."
      }
      footerText={isInviteFlow ? "Already set up?" : "Need another link?"}
      footerCtaLabel={isInviteFlow ? "Sign in" : "Request a new link"}
      footerCtaHref={isInviteFlow ? "/login" : "/forgot-password"}
      branding={branding}
    >
      <Suspense
        fallback={
          <div className="text-center text-sm text-(--text-soft)">Loading reset form...</div>
        }
      >
        <ResetPasswordForm mode={isInviteFlow ? "invite" : "reset"} />
      </Suspense>
    </AuthShell>
  );
}
