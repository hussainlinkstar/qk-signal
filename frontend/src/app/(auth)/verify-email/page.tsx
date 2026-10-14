import { Suspense } from "react";

import VerifyEmailPageClient from "@/components/auth/VerifyEmailPageClient";
import { fetchAuthBranding } from "@/lib/auth-branding";

export default async function VerifyEmailPage() {
  const branding = await fetchAuthBranding();

  return (
    <Suspense
      fallback={
        <div className="text-center text-sm text-(--text-soft)">Loading verification...</div>
      }
    >
      <VerifyEmailPageClient branding={branding} />
    </Suspense>
  );
}
