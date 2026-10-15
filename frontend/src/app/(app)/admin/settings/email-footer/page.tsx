"use client";

import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Save,
  RefreshCcw,
  CheckCircle2,
  AlertTriangle,
  Globe,
  Link as LinkIcon,
  Building2,
  Palette,
  Image as ImageIcon,
} from "lucide-react";
import { useAuth } from "@/components/auth/custom-auth";
import { useAdminAccess } from "@/components/admin/AdminGuardProvider";
import DashboardPageIntro from "@/components/dashboard/DashboardPageIntro";
import { useWorkspacePageHeader } from "@/components/dashboard/workspacePageHeader";
import Button from "@/components/ui/Button";
import { Alert, AlertDescription } from "@/components/ui/alert";

const CARD = "rounded-[22px] border-0 bg-white px-[22px] py-[18px]";
const CARD_TITLE =
  "m-0 mb-[3px] flex items-center gap-2 font-(family-name:--disp) text-[15px] font-bold tracking-[-0.01em]";
const CARD_DESC = "mb-[18px] text-[12.5px] leading-[1.5] text-(--t-3)";
const FIELD_LABEL =
  "mb-2 flex items-center gap-1.5 font-(family-name:--mono) text-[10.5px] uppercase tracking-[0.08em] text-(--t-3)";
const WINPUT =
  "field-focus-ring h-11 w-full rounded-(--r-md) border-0 bg-[#EEF1F6] px-[13px] text-[13.5px] text-(--t-1) outline-none placeholder:text-(--t-3) focus:border-[#c7cdd6] disabled:bg-(--line-2) disabled:text-(--t-3)";

// ── Types ─────────────────────────────────────────────────────────────────────

type FooterDefaults = {
  social_x_url: string | null;
  social_linkedin_url: string | null;
  company_address: string | null;
  company_legal_name: string | null;
  company_trademark_text: string | null;
  footer_about_url: string | null;
  footer_blog_url: string | null;
  footer_support_url: string | null;
  footer_legal_url: string | null;
  footer_preferences_url: string | null;
  footer_privacy_url: string | null;
  brand_primary_color: string | null;
  brand_secondary_color: string | null;
  logo_light_url: string | null;
  logo_dark_url: string | null;
};

type Draft = Record<keyof FooterDefaults, string>;

const EMPTY_DRAFT: Draft = {
  social_x_url: "",
  social_linkedin_url: "",
  company_address: "",
  company_legal_name: "",
  company_trademark_text: "",
  footer_about_url: "",
  footer_blog_url: "",
  footer_support_url: "",
  footer_legal_url: "",
  footer_preferences_url: "",
  footer_privacy_url: "",
  brand_primary_color: "",
  brand_secondary_color: "",
  logo_light_url: "",
  logo_dark_url: "",
};

function footerToDraft(footer: FooterDefaults): Draft {
  const draft = { ...EMPTY_DRAFT };
  for (const key of Object.keys(EMPTY_DRAFT) as (keyof FooterDefaults)[]) {
    draft[key] = footer[key] ?? "";
  }
  return draft;
}

function draftToPayload(draft: Draft): Record<string, string | null> {
  const payload: Record<string, string | null> = {};
  for (const [key, value] of Object.entries(draft)) {
    payload[key] = value.trim() || null;
  }
  return payload;
}

// ── Field configs ─────────────────────────────────────────────────────────────

type FieldConfig = {
  key: keyof FooterDefaults;
  label: string;
  placeholder: string;
  type?: "url" | "text" | "color";
};

const SOCIAL_FIELDS: FieldConfig[] = [
  { key: "social_x_url", label: "X (Twitter)", placeholder: "https://x.com/yourhandle" },
  {
    key: "social_linkedin_url",
    label: "LinkedIn",
    placeholder: "https://linkedin.com/company/yourcompany",
  },
];

const FOOTER_LINK_FIELDS: FieldConfig[] = [
  { key: "footer_about_url", label: "About", placeholder: "https://yoursite.com/about" },
  { key: "footer_blog_url", label: "Blog", placeholder: "https://yoursite.com/blog" },
  { key: "footer_support_url", label: "Support", placeholder: "https://yoursite.com/contact" },
  { key: "footer_legal_url", label: "Legal / Terms", placeholder: "https://yoursite.com/terms" },
  {
    key: "footer_preferences_url",
    label: "Preferences",
    placeholder: "https://yoursite.com/preferences",
  },
  {
    key: "footer_privacy_url",
    label: "Privacy Policy",
    placeholder: "https://yoursite.com/privacy",
  },
];

const COMPANY_FIELDS: FieldConfig[] = [
  { key: "company_legal_name", label: "Legal Name", placeholder: "Your Company SRL", type: "text" },
  {
    key: "company_address",
    label: "Address",
    placeholder: "123 Street, City, Country",
    type: "text",
  },
  {
    key: "company_trademark_text",
    label: "Trademark Text",
    placeholder: "Your Company is a registered trademark of...",
    type: "text",
  },
];

const BRANDING_FIELDS: FieldConfig[] = [
  { key: "brand_primary_color", label: "Primary Color", placeholder: "#6366F1", type: "color" },
  { key: "brand_secondary_color", label: "Secondary Color", placeholder: "#0A121E", type: "color" },
  {
    key: "logo_light_url",
    label: "Logo (Light)",
    placeholder: "https://yoursite.com/logo-light.svg",
  },
  { key: "logo_dark_url", label: "Logo (Dark)", placeholder: "https://yoursite.com/logo-dark.svg" },
];

const SOCIAL_ICONS: Record<string, React.ReactNode> = {
  social_x_url: <Globe size={14} />,
  social_linkedin_url: <Building2 size={14} />,
};

// ── Field component ───────────────────────────────────────────────────────────

function FooterField({
  field,
  value,
  onChange,
  icon,
}: {
  field: FieldConfig;
  value: string;
  onChange: (val: string) => void;
  icon?: React.ReactNode;
}) {
  const isColor = field.type === "color";
  return (
    <div>
      <label className={FIELD_LABEL}>
        {icon}
        {field.label}
      </label>
      <div className="flex items-center gap-2">
        {isColor && value && (
          <span
            className="h-7 w-7 shrink-0 rounded-[10px] border-0 bg-[#EEF1F6]"
            style={{ backgroundColor: value }}
          />
        )}
        <input
          type="text"
          value={value}
          placeholder={field.placeholder}
          className={WINPUT}
          onChange={(e) => onChange(e.target.value)}
        />
      </div>
    </div>
  );
}

// ── Section component ─────────────────────────────────────────────────────────

function FieldSection({
  title,
  description,
  icon,
  fields,
  draft,
  setDraft,
  fieldIcons,
}: {
  title: string;
  description?: string;
  icon: React.ReactNode;
  fields: FieldConfig[];
  draft: Draft;
  setDraft: React.Dispatch<React.SetStateAction<Draft>>;
  fieldIcons?: Record<string, React.ReactNode>;
}) {
  return (
    <section className={CARD}>
      <h2 className={CARD_TITLE}>
        {icon}
        {title}
      </h2>
      {description && <p className={CARD_DESC}>{description}</p>}
      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        {fields.map((field) => (
          <FooterField
            key={field.key}
            field={field}
            value={draft[field.key]}
            onChange={(val) => setDraft((prev) => ({ ...prev, [field.key]: val }))}
            icon={fieldIcons?.[field.key]}
          />
        ))}
      </div>
    </section>
  );
}

// ── Main Page ─────────────────────────────────────────────────────────────────

export default function EmailFooterPage() {
  const { getToken, isSignedIn } = useAuth();
  const { isAdmin, isLoading: isGuardLoading } = useAdminAccess();

  const [draft, setDraft] = useState<Draft>(EMPTY_DRAFT);
  const [serverState, setServerState] = useState<Draft>(EMPTY_DRAFT);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [savedAt, setSavedAt] = useState<string | null>(null);

  const isDirty = useMemo(
    () => JSON.stringify(draft) !== JSON.stringify(serverState),
    [draft, serverState]
  );

  const configuredCount = useMemo(
    () => Object.values(draft).filter((v) => v.trim()).length,
    [draft]
  );

  const fetchData = useCallback(async () => {
    if (!isSignedIn) return;
    setLoading(true);
    setError(null);
    try {
      const token = await getToken();
      const res = await fetch("/api/admin/settings", {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!res.ok) throw new Error(await res.text());
      const json = await res.json();
      const footer: FooterDefaults = json.email_footer_defaults ?? {};
      const d = footerToDraft(footer);
      setDraft(d);
      setServerState(d);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Failed to load");
    } finally {
      setLoading(false);
    }
  }, [isSignedIn, getToken]);

  useEffect(() => {
    if (!isGuardLoading && isAdmin) fetchData();
  }, [isGuardLoading, isAdmin, fetchData]);

  const handleSave = async () => {
    setSaving(true);
    setError(null);
    setSavedAt(null);
    try {
      const token = await getToken();
      const payload = draftToPayload(draft);
      const res = await fetch("/api/admin/settings", {
        method: "PATCH",
        headers: {
          Authorization: `Bearer ${token}`,
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ email_footer_defaults: payload }),
      });
      if (!res.ok) throw new Error(await res.text());
      setSavedAt(new Date().toLocaleTimeString());
      await fetchData();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Save failed");
    } finally {
      setSaving(false);
    }
  };

  const { setHeader } = useWorkspacePageHeader();
  const actionsRef = useRef({ fetchData, handleSave });
  actionsRef.current = { fetchData, handleSave };
  useEffect(() => {
    setHeader({
      actions: isAdmin ? (
        <>
          <Button
            variant="ghost"
            size="sm"
            onClick={() => void actionsRef.current.fetchData()}
            disabled={loading}
            aria-label="Refresh"
            title="Refresh"
            className="h-8 w-8 p-0"
          >
            <RefreshCcw size={14} className={loading ? "animate-spin" : ""} />
          </Button>
          <Button
            variant="primary"
            size="sm"
            onClick={() => void actionsRef.current.handleSave()}
            disabled={saving || !isDirty}
          >
            <Save size={14} />
            <span className="max-sm:hidden">{saving ? "Saving…" : "Save"}</span>
          </Button>
        </>
      ) : null,
    });
    return () => setHeader(null);
  }, [isAdmin, isDirty, loading, saving, setHeader]);

  if (isGuardLoading || loading) {
    return (
      <div className="flex min-h-[40vh] items-center justify-center text-[13px] text-(--t-3)">
        Loading email footer configuration…
      </div>
    );
  }

  if (!isAdmin) {
    return (
      <div className="flex min-h-[40vh] items-center justify-center text-[13px] text-(--bad)">
        Access denied.
      </div>
    );
  }

  return (
    <>
      <DashboardPageIntro icon={Globe} title="Email footer &amp; social links">
        Platform-wide defaults for email templates and the website footer.
        {configuredCount > 0 && (
          <span className="ml-2 text-(--good)">
            {configuredCount} field{configuredCount !== 1 ? "s" : ""} configured
          </span>
        )}
      </DashboardPageIntro>

      {error && (
        <Alert variant="destructive">
          <AlertTriangle />
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}
      {savedAt && (
        <Alert variant="success">
          <CheckCircle2 />
          <AlertDescription>Saved at {savedAt}</AlertDescription>
        </Alert>
      )}

      <FieldSection
        title="Social Links"
        description="URLs shown in the email footer and website footer. Leave blank to hide a platform."
        icon={<Globe size={16} className="text-(--purple)" />}
        fields={SOCIAL_FIELDS}
        draft={draft}
        setDraft={setDraft}
        fieldIcons={SOCIAL_ICONS}
      />

      <FieldSection
        title="Footer Navigation Links"
        description="Links shown in the legal/navigation row of email templates."
        icon={<LinkIcon size={16} className="text-(--purple)" />}
        fields={FOOTER_LINK_FIELDS}
        draft={draft}
        setDraft={setDraft}
      />

      <FieldSection
        title="Company Information"
        description="Legal entity details shown at the bottom of emails."
        icon={<Building2 size={16} className="text-(--purple)" />}
        fields={COMPANY_FIELDS}
        draft={draft}
        setDraft={setDraft}
      />

      <FieldSection
        title="Brand Colors &amp; Logos"
        description="Overrides for email template branding. Leave blank for platform defaults."
        icon={<Palette size={16} className="text-(--purple)" />}
        fields={BRANDING_FIELDS}
        draft={draft}
        setDraft={setDraft}
        fieldIcons={{
          logo_light_url: <ImageIcon size={14} />,
          logo_dark_url: <ImageIcon size={14} />,
        }}
      />

      {isDirty && (
        <p className="text-right text-[12.5px] font-medium text-(--warn)">
          You have unsaved changes.
        </p>
      )}
    </>
  );
}
