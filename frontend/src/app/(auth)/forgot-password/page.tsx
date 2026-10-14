import type { Metadata } from "next";
import AuthShell from "@/components/auth/AuthShell";
import { ForgotPasswordForm } from "@/components/auth/ForgotPasswordForm";
import { fetchAuthBranding } from "@/lib/auth-branding";

export const metadata: Metadata = {
  title: "Reset Your Password",
  description: "Recover access to your Qiko Signal account.",
};

export default async function ForgotPasswordPage() {
  const branding = await fetchAuthBranding();

  return (
    <AuthShell
      chipLabel="Account Recovery"
      title="Forgot your password?"
      subtitle="We will send a secure recovery link if the address matches an existing account."
      footerText="Already recovered access?"
      footerCtaLabel="Sign in"
      footerCtaHref="/login"
      branding={branding}
    >
      <ForgotPasswordForm />
    </AuthShell>
  );
}
