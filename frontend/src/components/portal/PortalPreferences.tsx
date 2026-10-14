"use client";

import React, { useEffect, useState, useCallback } from "react";
import { Bell, Save } from "lucide-react";
import { toast } from "sonner";
import { cx } from "@/components/ui/utils";
import Button from "@/components/ui/Button";
import SelectField from "@/components/ui/SelectField";
import ToggleSwitch from "@/components/ui/ToggleSwitch";
import { fetchPortalPreferences, updatePortalPreferences } from "@/services/portalService";

const DIGEST_OPTIONS = [
  { label: "Daily", value: "daily" },
  { label: "Weekly", value: "weekly" },
  { label: "Monthly", value: "monthly" },
  { label: "None", value: "none" },
] as const;

function SkeletonBlock({ className }: { className?: string }) {
  return <div className={cx("animate-pulse rounded", className)} />;
}

function LoadingSkeleton() {
  return (
    <div className="bg-(--surface) border border-(--border) rounded p-6 space-y-6">
      {/* Header skeleton */}
      <div className="flex items-center gap-2">
        <SkeletonBlock className="h-5 w-5" />
        <SkeletonBlock className="h-5 w-40" />
      </div>

      {/* Select field skeleton */}
      <div className="space-y-2">
        <SkeletonBlock className="h-4 w-32" />
        <SkeletonBlock className="h-11 w-full" />
      </div>

      {/* Toggle skeleton */}
      <div className="flex items-center gap-3">
        <SkeletonBlock className="h-6 w-11 rounded-full" />
        <div className="space-y-1">
          <SkeletonBlock className="h-4 w-36" />
          <SkeletonBlock className="h-3 w-64" />
        </div>
      </div>

      {/* Button skeleton */}
      <div className="flex justify-end">
        <SkeletonBlock className="h-11 w-24" />
      </div>
    </div>
  );
}

export default function PortalPreferencesCard() {
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [digestFrequency, setDigestFrequency] = useState<string>("weekly");
  const [notifyOnNewAudit, setNotifyOnNewAudit] = useState(true);

  useEffect(() => {
    let cancelled = false;

    async function load() {
      try {
        const prefs = await fetchPortalPreferences();
        if (cancelled) return;
        setDigestFrequency(prefs.email_digest_frequency ?? "weekly");
        setNotifyOnNewAudit(prefs.notify_on_new_audit ?? true);
      } catch {
        toast.error("Failed to load preferences");
      } finally {
        if (!cancelled) setLoading(false);
      }
    }

    load();
    return () => {
      cancelled = true;
    };
  }, []);

  const handleSave = useCallback(async () => {
    setSaving(true);
    try {
      await updatePortalPreferences({
        email_digest_frequency: digestFrequency,
        notify_on_new_audit: notifyOnNewAudit,
      });
      toast.success("Preferences saved");
    } catch {
      toast.error("Failed to save preferences");
    } finally {
      setSaving(false);
    }
  }, [digestFrequency, notifyOnNewAudit]);

  if (loading) return <LoadingSkeleton />;

  return (
    <div className="bg-(--surface) border border-(--border) rounded p-6 space-y-6">
      {/* Header */}
      <div className="flex items-center gap-2">
        <Bell className="h-5 w-5 text-(--muted-foreground)" />
        <h2 className="text-base font-semibold text-(--foreground)">Notification Preferences</h2>
      </div>

      {/* Digest frequency */}
      <SelectField
        label="Email digest frequency"
        value={digestFrequency}
        onChange={(e) => setDigestFrequency(e.target.value)}
      >
        {DIGEST_OPTIONS.map((opt) => (
          <option key={opt.value} value={opt.value}>
            {opt.label}
          </option>
        ))}
      </SelectField>

      {/* New-audit notifications toggle */}
      <ToggleSwitch
        checked={notifyOnNewAudit}
        onChange={setNotifyOnNewAudit}
        label="Notify on new audit"
        description="Receive an email when a new audit is completed for your projects"
      />

      {/* Save */}
      <div className="flex justify-end">
        <Button
          variant="primary"
          size="md"
          loading={saving}
          loadingText="Saving…"
          onClick={handleSave}
        >
          <Save className="h-4 w-4" />
          Save
        </Button>
      </div>
    </div>
  );
}
