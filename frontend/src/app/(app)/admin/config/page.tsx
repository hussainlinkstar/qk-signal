"use client";

import React, { useCallback, useEffect, useState } from "react";
import { Settings, Search, RotateCcw, Save, Shield, CheckCircle, Eye, EyeOff } from "lucide-react";
import { useAuth } from "@/components/auth/custom-auth";
import { useAdminAccess } from "@/components/admin/AdminGuardProvider";
import DashboardPageIntro from "@/components/dashboard/DashboardPageIntro";
import { AdminInlineError } from "@/components/admin/AdminInlineError";
import { AdminTableSkeleton, AdminCardSkeleton } from "@/components/admin/AdminTableSkeleton";
import { NativeSelect } from "@/components/ui/native-select";
import { toast } from "sonner";

/* ── Types ──────────────────────────────────────────────────────── */

type ConfigSetting = {
  key: string;
  current_value: any;
  source: "default" | "env" | "runtime";
  editable: boolean;
  category: string;
  is_secret: boolean;
  type?: string;
  description?: string;
  min?: number;
  max?: number;
  options?: string[];
  default_value?: any;
  env_value?: any;
  runtime_value?: any;
};

const CARD = "rounded-[22px] border-0 bg-white px-[22px] py-[18px]";
const STAT = "rounded-[22px] border-0 bg-white px-[22px] py-[18px]";
const MICRO_LABEL =
  "font-(family-name:--mono) text-[10.5px] uppercase tracking-[0.08em] text-(--t-3)";
const WINPUT_SM =
  "field-focus-ring h-8 rounded-(--r-md) border-0 bg-[#EEF1F6] px-[10px] text-[12.5px] text-(--t-1) outline-none placeholder:text-(--t-3) focus:border-[#c7cdd6]";
const TH =
  "border-b border-(--line) px-4 py-[11px] text-left font-(family-name:--mono) text-[10px] font-normal uppercase tracking-[0.06em] text-(--t-3)";
const TD = "border-b border-(--line-2) px-4 py-[11px] align-middle text-[13px] text-(--t-1)";
const TROW = "transition-colors hover:bg-(--paper)";
const CHIP =
  "inline-flex items-center rounded-md px-2 py-[3px] font-(family-name:--mono) text-[10.5px] uppercase tracking-[0.04em]";
const FILTER_PILL =
  "rounded-md border px-2.5 py-1.5 font-(family-name:--mono) text-[10.5px] uppercase tracking-[0.04em] transition-colors";

/* ── Source badge ────────────────────────────────────────────────── */

const SOURCE_STYLES: Record<string, string> = {
  default: `${CHIP} text-(--t-2) bg-(--line-2)`,
  env: `${CHIP} text-(--purple) bg-(--purple-s)`,
  runtime: `${CHIP} text-(--warn) bg-(--warn-s)`,
};

function SourceBadge({ source }: { source: string }) {
  return <span className={SOURCE_STYLES[source] ?? SOURCE_STYLES.default}>{source}</span>;
}

/* ── Inline editor ──────────────────────────────────────────────── */

function InlineEditor({
  setting,
  onSave,
  onReset: _onReset,
}: {
  setting: ConfigSetting;
  onSave: (key: string, value: any) => void;
  onReset: (key: string) => void;
}) {
  const [value, setValue] = useState<string>(String(setting.current_value ?? ""));
  const [editing, setEditing] = useState(false);
  const isDirty = String(value) !== String(setting.current_value);

  useEffect(() => {
    setValue(String(setting.current_value ?? ""));
  }, [setting.current_value]);

  if (!editing) {
    return (
      <button
        onClick={() => setEditing(true)}
        className="max-w-[200px] truncate text-left text-[13px] font-medium text-(--t-1) transition-colors hover:text-(--purple)"
        title="Click to edit"
      >
        {String(setting.current_value ?? "-")}
      </button>
    );
  }

  const handleSave = () => {
    onSave(setting.key, value);
    setEditing(false);
  };

  if (setting.options?.length) {
    return (
      <div className="flex items-center gap-2">
        <NativeSelect
          variant="auth"
          value={value}
          onChange={(e) => setValue(e.target.value)}
          className="h-8 w-auto text-[12.5px]"
        >
          {setting.options.map((opt) => (
            <option key={opt} value={opt}>
              {opt}
            </option>
          ))}
        </NativeSelect>
        <button
          onClick={handleSave}
          className="text-(--good) transition-colors hover:opacity-80"
          title="Save"
        >
          <Save size={14} />
        </button>
      </div>
    );
  }

  return (
    <div className="flex items-center gap-2">
      <input
        type={setting.type === "int" ? "number" : "text"}
        value={value}
        onChange={(e) => setValue(e.target.value)}
        min={setting.min}
        max={setting.max}
        className={`${WINPUT_SM} w-24`}
      />
      {isDirty && (
        <button
          onClick={handleSave}
          className="text-(--good) transition-colors hover:opacity-80"
          title="Save"
        >
          <Save size={14} />
        </button>
      )}
      <button
        onClick={() => {
          setEditing(false);
          setValue(String(setting.current_value ?? ""));
        }}
        className="text-(--t-3) transition-colors hover:text-(--t-2)"
      >
        ✕
      </button>
    </div>
  );
}

/* ── Main page ──────────────────────────────────────────────────── */

export default function AdminConfigPage() {
  const { getToken, isSignedIn } = useAuth();
  const { isLoading: isGuardLoading } = useAdminAccess();

  const [allSettings, setAllSettings] = useState<ConfigSetting[]>([]);
  const [categories, setCategories] = useState<string[]>([]);
  const [totalSettings, setTotalSettings] = useState(0);
  const [runtimeOverrides, setRuntimeOverrides] = useState(0);
  const [selectedCategory, setSelectedCategory] = useState("All");
  const [searchQuery, setSearchQuery] = useState("");
  const [showSecrets, setShowSecrets] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const getAuthHeaders = useCallback(async () => {
    const token = await getToken();
    if (!token) throw new Error("Not authenticated.");
    return { Authorization: `Bearer ${token}`, "Content-Type": "application/json" };
  }, [getToken]);

  const loadConfig = useCallback(async () => {
    if (!isSignedIn) return;
    setLoading(true);
    setError("");
    try {
      const headers = await getAuthHeaders();
      const res = await fetch("/api/admin/config", { headers });
      if (!res.ok) throw new Error("Failed to load configuration.");
      const data = await res.json();
      setAllSettings(data.settings || []);
      setCategories(data.categories || []);
      setTotalSettings(data.total_settings || 0);
      setRuntimeOverrides(data.runtime_overrides || 0);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to load config.");
    } finally {
      setLoading(false);
    }
  }, [getAuthHeaders, isSignedIn]);

  useEffect(() => {
    loadConfig();
  }, [loadConfig]);

  const handleSave = useCallback(
    async (key: string, value: any) => {
      try {
        const headers = await getAuthHeaders();
        const res = await fetch("/api/admin/config", {
          method: "PATCH",
          headers,
          body: JSON.stringify({ updates: { [key]: value } }),
        });
        if (!res.ok) {
          const data = await res.json().catch(() => null);
          throw new Error(data?.detail || "Failed to update.");
        }
        toast.success(`Updated ${key}`);
        loadConfig();
      } catch (err) {
        toast.error(err instanceof Error ? err.message : "Update failed.");
      }
    },
    [getAuthHeaders, loadConfig]
  );

  const handleReset = useCallback(
    async (key: string) => {
      try {
        const headers = await getAuthHeaders();
        const res = await fetch(`/api/admin/config/${key}`, {
          method: "DELETE",
          headers,
        });
        if (!res.ok) throw new Error("Failed to reset.");
        toast.success(`Reset ${key} to default`);
        loadConfig();
      } catch (err) {
        toast.error(err instanceof Error ? err.message : "Reset failed.");
      }
    },
    [getAuthHeaders, loadConfig]
  );

  // Filter
  const filtered = allSettings.filter((s) => {
    if (selectedCategory !== "All" && s.category !== selectedCategory) return false;
    if (searchQuery) {
      const q = searchQuery.toLowerCase();
      return (
        s.key.toLowerCase().includes(q) ||
        (s.description || "").toLowerCase().includes(q) ||
        s.category.toLowerCase().includes(q)
      );
    }
    return true;
  });

  if (loading || isGuardLoading) {
    return (
      <>
        <DashboardPageIntro icon={Settings} title="Runtime configuration" />
        <AdminCardSkeleton cards={3} />
        <AdminTableSkeleton rows={10} columns={5} />
      </>
    );
  }

  if (error) {
    return <AdminInlineError message={error} onRetry={loadConfig} />;
  }

  return (
    <>
      <DashboardPageIntro icon={Settings} title="Runtime configuration">
        View and override application parameters at runtime. Changes take effect within 30 seconds.
      </DashboardPageIntro>

      {/* KPI bar */}
      <div className="grid grid-cols-3 gap-4">
        <div className={STAT}>
          <div className="flex items-center justify-between">
            <p className="font-(family-name:--disp) text-[24px] font-bold tracking-[-0.02em] text-(--t-1)">
              {totalSettings}
            </p>
            <Settings size={16} className="text-(--purple)" />
          </div>
          <p className={`${MICRO_LABEL} mt-1`}>Total settings</p>
        </div>
        <div className={STAT}>
          <div className="flex items-center justify-between">
            <p className="font-(family-name:--disp) text-[24px] font-bold tracking-[-0.02em] text-(--t-1)">
              {runtimeOverrides}
            </p>
            <Shield size={16} className="text-(--warn)" />
          </div>
          <p className={`${MICRO_LABEL} mt-1`}>Runtime overrides</p>
        </div>
        <div className={STAT}>
          <div className="flex items-center justify-between">
            <p className="font-(family-name:--disp) text-[24px] font-bold tracking-[-0.02em] text-(--t-1)">
              {categories.length}
            </p>
            <CheckCircle size={16} className="text-(--good)" />
          </div>
          <p className={`${MICRO_LABEL} mt-1`}>Categories</p>
        </div>
      </div>

      {/* Filters */}
      <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
        <div className="flex flex-wrap gap-1.5">
          <button
            onClick={() => setSelectedCategory("All")}
            className={`${FILTER_PILL} ${
              selectedCategory === "All"
                ? "border-(--purple) bg-(--purple-s) text-(--purple)"
                : "border-(--line) bg-(--panel) text-(--t-3) hover:text-(--t-2)"
            }`}
          >
            All
          </button>
          {categories.map((cat) => (
            <button
              key={cat}
              onClick={() => setSelectedCategory(cat)}
              className={`${FILTER_PILL} ${
                selectedCategory === cat
                  ? "border-(--purple) bg-(--purple-s) text-(--purple)"
                  : "border-(--line) bg-(--panel) text-(--t-3) hover:text-(--t-2)"
              }`}
            >
              {cat}
            </button>
          ))}
        </div>
        <div className="flex items-center gap-2">
          <div className="relative">
            <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-(--t-3)" />
            <input
              type="text"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder="Search settings..."
              className={`${WINPUT_SM} w-56 pl-9`}
            />
          </div>
          <button
            onClick={() => setShowSecrets(!showSecrets)}
            className="flex h-8 w-8 items-center justify-center rounded-(--r-md) border-0 bg-white text-(--t-2) transition-colors hover:text-(--t-1)"
            title={showSecrets ? "Hide secrets" : "Show secrets"}
          >
            {showSecrets ? <EyeOff size={14} /> : <Eye size={14} />}
          </button>
        </div>
      </div>

      {/* Settings table */}
      <section className={`${CARD} overflow-hidden px-0 py-0`}>
        <table className="w-full text-left">
          <thead>
            <tr>
              <th className={TH}>Key</th>
              <th className={TH}>Value</th>
              <th className={TH}>Source</th>
              <th className={TH}>Category</th>
              <th className={`${TH} w-12`}></th>
            </tr>
          </thead>
          <tbody>
            {filtered.map((s) => (
              <tr key={s.key} className={`${TROW} group`}>
                <td className={TD}>
                  <p className="font-(family-name:--mono) text-xs font-semibold text-(--t-1)">
                    {s.key}
                  </p>
                  {s.description && (
                    <p className="mt-0.5 text-[11px] text-(--t-3)">{s.description}</p>
                  )}
                </td>
                <td className={TD}>
                  {s.editable ? (
                    <InlineEditor setting={s} onSave={handleSave} onReset={handleReset} />
                  ) : (
                    <span className="block max-w-[200px] truncate text-[13px] text-(--t-2)">
                      {s.is_secret && !showSecrets ? "••••••••" : String(s.current_value ?? "-")}
                    </span>
                  )}
                </td>
                <td className={TD}>
                  <SourceBadge source={s.source} />
                </td>
                <td className={TD}>
                  <span className="text-[11px] font-semibold text-(--t-2)">{s.category}</span>
                </td>
                <td className={TD}>
                  {s.editable && s.source === "runtime" && (
                    <button
                      onClick={() => handleReset(s.key)}
                      className="text-(--t-3) opacity-0 transition-all hover:text-(--bad) group-hover:opacity-100"
                      title="Reset to default"
                    >
                      <RotateCcw size={14} />
                    </button>
                  )}
                </td>
              </tr>
            ))}
            {filtered.length === 0 && (
              <tr>
                <td colSpan={5} className="px-4 py-10 text-center">
                  <p className="font-(family-name:--mono) text-[10.5px] uppercase tracking-[0.08em] text-(--t-3)">
                    No settings found
                  </p>
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </section>
    </>
  );
}
