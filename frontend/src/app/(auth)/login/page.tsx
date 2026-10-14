import type { Metadata } from "next";
import { Suspense } from "react";
import { redirect } from "next/navigation";
import AuthShell from "@/components/auth/AuthShell";
import { LoginForm } from "@/components/auth/LoginForm";
import { fetchAuthBranding } from "@/lib/auth-branding";
import { serverFetch } from "@/utils/server-fetch";

export const metadata: Metadata = {
  title: "Sign In",
  description: "Sign in to your Qiko Signal account to access SEO and AIO audits.",
};

export default async function LoginPage() {
  // Authenticated users should not see the login form.
  const session = await serverFetch("/auth/me", {
    cache: "no-store",
    redirectOnUnauthorized: false,
  });
  if (session.ok) redirect("/dashboard");

  const branding = await fetchAuthBranding();

  return (
    <AuthShell
      chipLabel="Secure Access"
      title="Welcome back"
      subtitle="Sign in to your Signal workspace."
      footerText="New to Signal?"
      footerCtaLabel="Create an account"
      footerCtaHref="/register"
      branding={branding}
    >
      <Suspense
        fallback={
          <div className="text-center text-sm text-(--text-soft)">Loading Sign In form...</div>
        }
      >
        <LoginForm />
      </Suspense>
    </AuthShell>
  );
}
