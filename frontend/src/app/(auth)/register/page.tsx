import type { Metadata } from "next";
import { redirect } from "next/navigation";

import AuthShell from "@/components/auth/AuthShell";
import { RegisterForm } from "@/components/auth/RegisterForm";
import { fetchAuthBranding } from "@/lib/auth-branding";
import { serverFetch } from "@/utils/server-fetch";

export const metadata: Metadata = {
  title: "Create Your Account",
  description: "Create a Qiko Signal account and start auditing your SEO and AIO visibility.",
};

export default async function RegisterPage() {
  // Authenticated users should not see the registration form.
  const session = await serverFetch("/auth/me", {
    cache: "no-store",
    redirectOnUnauthorized: false,
  });
  if (session.ok) redirect("/dashboard");

  const branding = await fetchAuthBranding();

  return (
    <AuthShell
      chipLabel="Get started"
      title="Create your account"
      subtitle="One workspace for SEO, AEO, and GEO — start with a free scan."
      footerText="Already have an account?"
      footerCtaLabel="Sign in"
      footerCtaHref="/login"
      branding={branding}
    >
      <RegisterForm />
    </AuthShell>
  );
}
