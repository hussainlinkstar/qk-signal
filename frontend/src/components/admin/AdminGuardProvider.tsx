"use client";

import React, { createContext, useContext } from "react";
import Link from "next/link";
import { Lock, ArrowLeft, Home } from "lucide-react";
import Button from "@/components/ui/Button";
import { SkelCard, SkelPagehead, SkelRow } from "@/components/signal/SignalSkeleton";
import { useAdminGuard } from "@/components/admin/useAdminGuard";

type AdminGuardContextValue = ReturnType<typeof useAdminGuard>;

const AdminGuardContext = createContext<AdminGuardContextValue | null>(null);

export function AdminGuardProvider({ children }: { children: React.ReactNode }) {
  const guard = useAdminGuard();

  // Both fallback states render before SignalAppShell mounts, so they sit
  // outside [data-signal-theme] and must carry the theme scope themselves.
  if (guard.isLoading) {
    return (
      <div data-signal-theme className="min-h-screen bg-(--paper) text-(--t-1)">
        <div className="mx-auto flex max-w-[1100px] flex-col gap-5 p-6">
          <SkelPagehead />
          <SkelCard />
          <SkelRow />
          <SkelRow />
          <SkelRow />
        </div>
      </div>
    );
  }

  if (!guard.isStaff) {
    return (
      <div
        data-signal-theme
        className="flex min-h-screen items-center justify-center bg-(--paper) px-6 py-20 font-(family-name:--body-font) text-(--t-1) antialiased"
      >
        <div className="w-full max-w-md rounded-(--r-lg) border-0 bg-white px-10 py-12 text-center">
          <div className="flex flex-col items-center gap-6">
            <div className="flex h-14 w-14 items-center justify-center rounded-full border-0 bg-[#EEF1F6] text-(--purple)">
              <Lock size={24} />
            </div>
            <div className="space-y-3">
              <h1 className="m-0 font-(family-name:--disp) text-[24px] font-extrabold tracking-[-0.02em]">
                Staff access required
              </h1>
              <p className="mx-auto max-w-sm text-sm leading-relaxed text-(--t-2)">
                You don't have access to this admin workspace. Return to the dashboard to continue.
              </p>
            </div>
            <div className="flex w-full flex-col items-center justify-center gap-3 sm:flex-row">
              <Link href="/dashboard" className="w-full sm:w-auto">
                <Button variant="primary" size="md" className="w-full">
                  <Home className="h-4 w-4" />
                  Back to dashboard
                </Button>
              </Link>
              <Link href="/" className="w-full sm:w-auto">
                <Button variant="ghost" size="md" className="w-full">
                  <ArrowLeft className="h-4 w-4" />
                  Return home
                </Button>
              </Link>
            </div>
          </div>
        </div>
      </div>
    );
  }

  return <AdminGuardContext.Provider value={guard}>{children}</AdminGuardContext.Provider>;
}

export function useAdminAccess() {
  const context = useContext(AdminGuardContext);
  if (!context) {
    throw new Error("useAdminAccess must be used within AdminGuardProvider.");
  }
  return context;
}
