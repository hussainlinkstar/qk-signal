"use client";

import SignalAlert from "@/components/signal/SignalAlert";
import React, { useEffect, useState } from "react";
import DashboardPageIntro from "@/components/dashboard/DashboardPageIntro";
import WorkspacePageFrame from "@/components/dashboard/WorkspacePageFrame";
import DashboardPageSkeleton from "@/components/signal/DashboardPageSkeleton";
import SignalTabs, { SignalTabPanel } from "@/components/signal/SignalTabs";
import { useAccountSettings } from "./useAccountSettings";
import ProfileSection from "./components/ProfileSection";
import SecuritySection from "./components/SecuritySection";
import NotificationsSection from "./components/NotificationsSection";
import BrandingSection from "./components/BrandingSection";
import DataRightsSection from "./components/DataRightsSection";
import type { AccountTab } from "./types";

/* ------------------------------------------------------------------ */
/*  Tab definitions                                                    */
/* ------------------------------------------------------------------ */

const TABS: { id: AccountTab; label: string }[] = [
  { id: "profile", label: "Profile" },
  { id: "security", label: "Security" },
  { id: "notifications", label: "Notifications" },
  { id: "branding", label: "Branding" },
  { id: "data", label: "Data" },
];

/* ------------------------------------------------------------------ */
/*  Page                                                               */
/* ------------------------------------------------------------------ */

export default function AccountSettingsPage() {
  const settings = useAccountSettings();
  const [activeTab, setActiveTab] = useState<AccountTab>("profile");

  // SIGV2-1257: the Microsoft link flow leaves for the provider and comes
  // back here, so open the tab that owns the outcome instead of the default
  // one. Read after mount to keep the server and client markup identical.
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    if (params.has("linked") || params.has("link_error")) {
      setActiveTab("security");
    }
  }, []);

  /* Loading gate — same skeleton language as workspace Settings. */
  if (settings.isBootLoading) {
    return (
      <WorkspacePageFrame backHref="/dashboard" backLabel="Back to Workspace Overview">
        <DashboardPageSkeleton cards={3} showTabs />
      </WorkspacePageFrame>
    );
  }

  /* Active section renderer */
  const renderContent = () => {
    switch (activeTab) {
      case "profile":
        return <ProfileSection settings={settings} />;
      case "security":
        return <SecuritySection settings={settings} />;
      case "notifications":
        return <NotificationsSection settings={settings} />;
      case "branding":
        return <BrandingSection settings={settings} />;
      case "data":
        return <DataRightsSection settings={settings} />;
    }
  };

  return (
    <WorkspacePageFrame backHref="/dashboard" backLabel="Back to Workspace Overview">
      <div className="flex flex-col gap-6">
        <DashboardPageIntro title="My Profile">
          Manage your profile, security, notifications, and data privacy.
        </DashboardPageIntro>

        {/* ── Tab Navigation ── */}
        <SignalTabs<AccountTab>
          tabs={TABS}
          activeId={activeTab}
          onChange={setActiveTab}
          className="gap-2"
        />

        {/* ── Content ── */}
        <SignalTabPanel id={activeTab} activeId={activeTab} className="gap-5">
          {renderContent()}
        </SignalTabPanel>

        {/* ── Boot error banner ── */}
        {settings.bootError && (
          <SignalAlert tone="danger" title="Settings unavailable">
            {settings.bootError}
          </SignalAlert>
        )}
      </div>
    </WorkspacePageFrame>
  );
}
