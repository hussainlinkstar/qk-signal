"use client";

import React, { useCallback, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Loader2, Plus, Trash2 } from "lucide-react";
import { toast } from "sonner";

import PlanLockNotice from "@/components/dashboard/PlanLockNotice";
import { getPlanLockContent } from "@/lib/planLocks";
import { cx } from "@/components/ui/utils";
import { uploadLogoAsset } from "@/services/uploadService";
import {
  createWorkspaceCustomDomain,
  deleteWorkspaceCustomDomain,
  fetchWorkspaceWhiteLabelSettings,
  updateWorkspaceWhiteLabelSettings,
  verifyWorkspaceCustomDomain,
  type WorkspaceWhiteLabelSettings,
} from "@/services/workspaceService";

/* ------------------------------------------------------------------ */
/*  Shared class strings, matching the approved .wsec card vocabulary   */
/* ------------------------------------------------------------------ */

const CARD = "rounded-[22px] border-0 bg-white px-[22px] py-[18px]";
const CARD_TITLE =
  "m-0 mb-[3px] font-(family-name:--disp) text-[15px] font-bold tracking-[-0.01em]";
const CARD_DESC = "m-0 mb-[18px] text-[12.5px] leading-[1.5] text-(--t-3)";
const FIELD_LABEL =
  "mb-2 block font-(family-name:--mono) text-[10.5px] uppercase tracking-[0.08em] text-(--t-3)";
const INPUT =
  "field-focus-ring h-11 w-full rounded-[14px] border border-(--line) bg-white px-[13px] py-0 font-(family-name:--body-font) text-[13.5px] text-(--t-1) outline-none placeholder:text-(--t-3) disabled:border-transparent disabled:bg-(--line-2) disabled:text-(--t-3)";
const TEXTAREA =
  "field-focus-ring min-h-[76px] w-full resize-y rounded-[14px] border border-(--line) bg-white px-[13px] py-2.5 font-(family-name:--body-font) text-[13.5px] leading-[1.5] text-(--t-1) outline-none placeholder:text-(--t-3) disabled:border-transparent disabled:bg-(--line-2) disabled:text-(--t-3)";
const BTN =
  "inline-flex h-[38px] cursor-pointer items-center gap-2 rounded-full border-0 bg-[#EEF1F6] px-[15px] py-0 font-(family-name:--body-font) text-[13.5px] font-semibold text-(--t-1) hover:bg-[#E8ECF3] disabled:cursor-not-allowed disabled:opacity-55";
const BTN_PRIMARY =
  "inline-flex h-[38px] cursor-pointer items-center gap-2 rounded-full border-0 bg-[#111827] px-[15px] py-0 font-(family-name:--body-font) text-[13.5px] font-semibold text-white hover:bg-black disabled:cursor-not-allowed disabled:opacity-55";
const GRID2 = "grid grid-cols-1 gap-4 md:grid-cols-2";
const GRID3 = "grid grid-cols-1 gap-4 md:grid-cols-3";
const NOTE = "text-[12px] leading-[1.5] text-(--t-3)";
const STEP_ROW = "flex gap-[13px] border-t border-t-(--line-2) py-3.5 first:border-t-0";
const STEP_NUMBER =
  "flex h-6 w-6 flex-none items-center justify-center rounded-full bg-(--ink) font-(family-name:--disp) text-[12px] font-bold text-white";
const TOGGLE_ROW =
  "flex items-center justify-between gap-4 border-t border-t-(--line-2) py-3.5 first:border-t-0 max-md:flex-wrap max-md:items-start";

/* ------------------------------------------------------------------ */
/*  Editable form shape                                                */
/* ------------------------------------------------------------------ */

type BrandingForm = {
  company_name: string;
  custom_page_title: string;
  custom_logo_url: string;
  custom_favicon_url: string;
  custom_meta_description: string;
  primary_color: string;
  secondary_color: string;
  hide_powered_by: boolean;
  email_reply_to: string;
  email_sender_name: string;
  social_x_url: string;
  social_linkedin_url: string;
  company_legal_name: string;
  company_trademark_text: string;
  company_address: string;
  footer_about_url: string;
  footer_blog_url: string;
  footer_support_url: string;
  footer_legal_url: string;
  footer_preferences_url: string;
  footer_privacy_url: string;
};

const EMPTY_FORM: BrandingForm = {
  company_name: "",
  custom_page_title: "",
  custom_logo_url: "",
  custom_favicon_url: "",
  custom_meta_description: "",
  primary_color: "",
  secondary_color: "",
  hide_powered_by: false,
  email_reply_to: "",
  email_sender_name: "",
  social_x_url: "",
  social_linkedin_url: "",
  company_legal_name: "",
  company_trademark_text: "",
  company_address: "",
  footer_about_url: "",
  footer_blog_url: "",
  footer_support_url: "",
  footer_legal_url: "",
  footer_preferences_url: "",
  footer_privacy_url: "",
};

const text = (value: string | null | undefined) => value ?? "";

const formFromSettings = (settings: WorkspaceWhiteLabelSettings): BrandingForm => ({
  company_name: text(settings.company_name),
  custom_page_title: text(settings.custom_page_title),
  custom_logo_url: text(settings.custom_logo_url),
  custom_favicon_url: text(settings.custom_favicon_url),
  custom_meta_description: text(settings.custom_meta_description),
  primary_color: text(settings.primary_color),
  secondary_color: text(settings.secondary_color),
  hide_powered_by: settings.hide_powered_by === true,
  email_reply_to: text(settings.email_reply_to),
  email_sender_name: text(settings.email_sender_name),
  social_x_url: text(settings.social_x_url),
  social_linkedin_url: text(settings.social_linkedin_url),
  company_legal_name: text(settings.company_legal_name),
  company_trademark_text: text(settings.company_trademark_text),
  company_address: text(settings.company_address),
  footer_about_url: text(settings.footer_about_url),
  footer_blog_url: text(settings.footer_blog_url),
  footer_support_url: text(settings.footer_support_url),
  footer_legal_url: text(settings.footer_legal_url),
  footer_preferences_url: text(settings.footer_preferences_url),
  footer_privacy_url: text(settings.footer_privacy_url),
});

/** Empty string means "cleared", which the API models as null, not "". */
const nullable = (value: string) => {
  const trimmed = value.trim();
  return trimmed ? trimmed : null;
};

export type WorkspaceWhiteLabelSectionProps = {
  /**
   * Resolved from the entitlement the API serves (`/api/billing/plans`), never
   * from a frontend plan table. When false the configuration form is not
   * rendered at all: every endpoint behind it answers 402, so an editable
   * field would be a control that cannot do anything.
   */
  entitled: boolean;
  canManage: boolean;
  getAuthHeaders: () => Promise<HeadersInit>;
};

/**
 * Approved "White-Label" tab of Workspace Settings (SIGV2-1039).
 *
 * Every control here is bound to a field the backend already persists through
 * `GET/PUT /api/v1/workspaces/current/white-label` and the custom-domain
 * endpoints beside it (`routers/workspace_router.py`), so nothing on this tab
 * is decorative. The approved page carries one section the product has no
 * source for, and it is therefore absent rather than faked: the design's
 * "Tenant status: Ready to configure" is a static string, so the build reports
 * the real configuration state instead.
 */
export default function WorkspaceWhiteLabelSection({
  entitled,
  canManage,
  getAuthHeaders,
}: WorkspaceWhiteLabelSectionProps) {
  const { t } = useTranslation();

  const [settings, setSettings] = useState<WorkspaceWhiteLabelSettings | null>(null);
  const [form, setForm] = useState<BrandingForm>(EMPTY_FORM);
  const [isLoading, setIsLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [isSaving, setIsSaving] = useState(false);
  const [isUploadingLogo, setIsUploadingLogo] = useState(false);
  const [domainInput, setDomainInput] = useState("");
  const [isAddingDomain, setIsAddingDomain] = useState(false);
  const [busyDomainId, setBusyDomainId] = useState<number | null>(null);

  const fileInputRef = useRef<HTMLInputElement | null>(null);

  const applySettings = useCallback((payload: WorkspaceWhiteLabelSettings) => {
    setSettings(payload);
    setForm(formFromSettings(payload));
  }, []);

  const load = useCallback(async () => {
    if (!entitled) {
      setIsLoading(false);
      return;
    }

    setIsLoading(true);
    setLoadError(null);
    try {
      const headers = await getAuthHeaders();
      applySettings(await fetchWorkspaceWhiteLabelSettings(headers));
    } catch (error) {
      setLoadError(error instanceof Error ? error.message : t("wsSettings.whiteLabel.loadFailed"));
    } finally {
      setIsLoading(false);
    }
  }, [applySettings, entitled, getAuthHeaders, t]);

  useEffect(() => {
    void load();
  }, [load]);

  const patch = (next: Partial<BrandingForm>) => setForm((current) => ({ ...current, ...next }));

  const handleSave = async () => {
    setIsSaving(true);
    try {
      const headers = await getAuthHeaders();
      applySettings(
        await updateWorkspaceWhiteLabelSettings(
          {
            company_name: nullable(form.company_name),
            custom_page_title: nullable(form.custom_page_title),
            custom_logo_url: nullable(form.custom_logo_url),
            custom_favicon_url: nullable(form.custom_favicon_url),
            custom_meta_description: nullable(form.custom_meta_description),
            primary_color: nullable(form.primary_color),
            secondary_color: nullable(form.secondary_color),
            hide_powered_by: form.hide_powered_by,
            email_reply_to: nullable(form.email_reply_to),
            email_sender_name: nullable(form.email_sender_name),
            social_x_url: nullable(form.social_x_url),
            social_linkedin_url: nullable(form.social_linkedin_url),
            company_legal_name: nullable(form.company_legal_name),
            company_trademark_text: nullable(form.company_trademark_text),
            company_address: nullable(form.company_address),
            footer_about_url: nullable(form.footer_about_url),
            footer_blog_url: nullable(form.footer_blog_url),
            footer_support_url: nullable(form.footer_support_url),
            footer_legal_url: nullable(form.footer_legal_url),
            footer_preferences_url: nullable(form.footer_preferences_url),
            footer_privacy_url: nullable(form.footer_privacy_url),
          },
          headers
        )
      );
      toast.success(t("wsSettings.whiteLabel.saved"));
    } catch (error) {
      toast.error(error instanceof Error ? error.message : t("wsSettings.whiteLabel.saveFailed"));
    } finally {
      setIsSaving(false);
    }
  };

  const handleLogoSelected = async (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) {
      return;
    }

    setIsUploadingLogo(true);
    try {
      const headers = await getAuthHeaders();
      const uploaded = await uploadLogoAsset(file, "workspace", headers);
      patch({ custom_logo_url: uploaded.url });
      toast.success(t("wsSettings.whiteLabel.logoUploaded"));
    } catch (error) {
      toast.error(
        error instanceof Error ? error.message : t("wsSettings.whiteLabel.logoUploadFailed")
      );
    } finally {
      setIsUploadingLogo(false);
    }
  };

  const handleAddDomain = async () => {
    const domain = domainInput.trim();
    if (!domain) {
      toast.error(t("wsSettings.whiteLabel.customDomain.subdomainPlaceholder"));
      return;
    }

    setIsAddingDomain(true);
    try {
      const headers = await getAuthHeaders();
      applySettings(await createWorkspaceCustomDomain(domain, headers));
      setDomainInput("");
      toast.success(t("wsSettings.whiteLabel.customDomain.domainAdded"));
    } catch (error) {
      toast.error(
        error instanceof Error
          ? error.message
          : t("wsSettings.whiteLabel.customDomain.domainAddFailed")
      );
    } finally {
      setIsAddingDomain(false);
    }
  };

  const handleVerifyDomain = async (domainId: number) => {
    setBusyDomainId(domainId);
    try {
      const headers = await getAuthHeaders();
      applySettings(await verifyWorkspaceCustomDomain(domainId, headers));
    } catch (error) {
      toast.error(
        error instanceof Error
          ? error.message
          : t("wsSettings.whiteLabel.customDomain.domainVerifyFailed")
      );
    } finally {
      setBusyDomainId(null);
    }
  };

  const handleRemoveDomain = async (domainId: number) => {
    setBusyDomainId(domainId);
    try {
      const headers = await getAuthHeaders();
      await deleteWorkspaceCustomDomain(domainId, headers);
      await load();
    } catch (error) {
      toast.error(
        error instanceof Error
          ? error.message
          : t("wsSettings.whiteLabel.customDomain.domainRemoveFailed")
      );
    } finally {
      setBusyDomainId(null);
    }
  };

  /* ---------------------------------------------------------------- */
  /*  Not entitled: state the plan position, do not render controls     */
  /* ---------------------------------------------------------------- */

  if (!entitled) {
    return (
      <div className="flex flex-col gap-4">
        <div className={CARD}>
          <h3 className={CARD_TITLE}>{t("wsSettings.whiteLabel.heading")}</h3>
          <p className="m-0 text-[12.5px] leading-[1.5] text-(--t-3)">
            {t("wsSettings.whiteLabel.lockedIntro")}
          </p>
        </div>
        <PlanLockNotice {...getPlanLockContent("whiteLabel")} />
      </div>
    );
  }

  if (isLoading) {
    return (
      <div role="status" className="flex items-center gap-2.5 py-6 text-[13px] text-(--t-3)">
        <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
        {t("wsSettings.whiteLabel.loading")}
      </div>
    );
  }

  if (loadError) {
    return (
      <div className={CARD}>
        <h3 className={CARD_TITLE}>{t("wsSettings.whiteLabel.heading")}</h3>
        <p className="m-0 mb-[18px] text-[12.5px] leading-[1.5] text-(--bad)">{loadError}</p>
        <button type="button" className={BTN} onClick={() => void load()}>
          {t("wsSettings.whiteLabel.retry")}
        </button>
      </div>
    );
  }

  const domains = settings?.domains ?? [];
  const activeDomain = domains.find((domain) => domain.verified) ?? null;
  const dnsTarget = settings?.dns_target ?? null;
  const disabled = !canManage;

  return (
    <div className="flex flex-col gap-4">
      {/* ── Tenant Status ── */}
      <div className={CARD}>
        <h3 className={CARD_TITLE}>{t("wsSettings.whiteLabel.tenantStatus.heading")}</h3>
        <p className={CARD_DESC}>{t("wsSettings.whiteLabel.tenantStatus.description")}</p>
        <div className={GRID3}>
          <div>
            <span className={FIELD_LABEL}>
              {t("wsSettings.whiteLabel.tenantStatus.statusLabel")}
            </span>
            <div className="text-[13.5px] font-semibold">
              {activeDomain
                ? t("wsSettings.whiteLabel.tenantStatus.statusLive")
                : t("wsSettings.whiteLabel.tenantStatus.statusReady")}
            </div>
          </div>
          <div>
            <span className={FIELD_LABEL}>
              {t("wsSettings.whiteLabel.tenantStatus.hostnameLabel")}
            </span>
            <div
              className={cx(
                "text-[13.5px] font-semibold",
                activeDomain ? "text-(--good)" : "text-(--warn)"
              )}
            >
              {activeDomain
                ? activeDomain.domain
                : t("wsSettings.whiteLabel.tenantStatus.hostnameNotConnected")}
            </div>
          </div>
          <div>
            <span className={FIELD_LABEL}>{t("wsSettings.whiteLabel.tenantStatus.dnsLabel")}</span>
            <div className="font-(family-name:--mono) text-[12.5px]">
              {dnsTarget ?? t("wsSettings.whiteLabel.tenantStatus.dnsUnavailable")}
            </div>
          </div>
        </div>
        <p className={cx(NOTE, "mt-3 mb-0")}>{t("wsSettings.whiteLabel.tenantStatus.cnameNote")}</p>
      </div>

      {/* ── Brand Identity ── */}
      <div className={CARD}>
        <h3 className={CARD_TITLE}>{t("wsSettings.whiteLabel.brandIdentity.heading")}</h3>
        <p className={CARD_DESC}>{t("wsSettings.whiteLabel.brandIdentity.description")}</p>
        <div className={cx(GRID2, "mb-4")}>
          <div>
            <span className={FIELD_LABEL}>
              {t("wsSettings.whiteLabel.brandIdentity.brandNameLabel")}
            </span>
            <input
              className={INPUT}
              type="text"
              value={form.company_name}
              disabled={disabled}
              onChange={(event) => patch({ company_name: event.target.value })}
            />
          </div>
          <div>
            <span className={FIELD_LABEL}>
              {t("wsSettings.whiteLabel.brandIdentity.pageTitleLabel")}
            </span>
            <input
              className={INPUT}
              type="text"
              value={form.custom_page_title}
              disabled={disabled}
              onChange={(event) => patch({ custom_page_title: event.target.value })}
            />
          </div>
        </div>
        <div className="mb-4">
          <span className={FIELD_LABEL}>{t("wsSettings.whiteLabel.brandIdentity.logoLabel")}</span>
          <input
            ref={fileInputRef}
            type="file"
            accept="image/png,image/jpeg,image/webp,image/svg+xml"
            className="hidden"
            disabled={disabled || isUploadingLogo}
            onChange={(event) => void handleLogoSelected(event)}
          />
          <div
            className={cx(
              "flex flex-col items-center justify-center gap-2 rounded-[12px] border-[1.5px] border-dashed border-(--line) p-[26px] text-center text-(--t-3)",
              disabled
                ? "cursor-not-allowed opacity-55"
                : "cursor-pointer hover:border-(--purple) hover:text-(--purple)"
            )}
            onClick={() => {
              if (disabled || isUploadingLogo) return;
              fileInputRef.current?.click();
            }}
          >
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" width="24" height="24">
              <path d="M12 16V4M8 8l4-4 4 4" />
              <path d="M4 16v2a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-2" />
            </svg>
            <b>
              {isUploadingLogo
                ? t("wsSettings.whiteLabel.brandIdentity.logoUploading")
                : form.custom_logo_url
                  ? t("wsSettings.whiteLabel.brandIdentity.logoUploaded")
                  : t("wsSettings.whiteLabel.brandIdentity.logoDropzone")}
            </b>
            <span>{t("wsSettings.whiteLabel.brandIdentity.logoHint")}</span>
          </div>
          {form.custom_logo_url ? (
            <button
              type="button"
              className={cx(BTN, "mt-2.5")}
              disabled={disabled || isUploadingLogo}
              onClick={() => patch({ custom_logo_url: "" })}
            >
              {t("wsSettings.whiteLabel.brandIdentity.logoRemove")}
            </button>
          ) : null}
        </div>
        <div className={GRID2}>
          <div>
            <span className={FIELD_LABEL}>
              {t("wsSettings.whiteLabel.brandIdentity.faviconLabel")}
            </span>
            <input
              className={INPUT}
              type="text"
              placeholder={t("wsSettings.whiteLabel.brandIdentity.faviconPlaceholder")}
              value={form.custom_favicon_url}
              disabled={disabled}
              onChange={(event) => patch({ custom_favicon_url: event.target.value })}
            />
          </div>
          <div>
            <span className={FIELD_LABEL}>
              {t("wsSettings.whiteLabel.brandIdentity.metaLabel")}
            </span>
            <input
              className={INPUT}
              type="text"
              placeholder={t("wsSettings.whiteLabel.brandIdentity.metaPlaceholder")}
              value={form.custom_meta_description}
              disabled={disabled}
              onChange={(event) => patch({ custom_meta_description: event.target.value })}
            />
          </div>
        </div>
      </div>

      {/* ── Brand Colors ── */}
      <div className={CARD}>
        <h3 className={CARD_TITLE}>{t("wsSettings.whiteLabel.brandColors.heading")}</h3>
        <p className={CARD_DESC}>{t("wsSettings.whiteLabel.brandColors.description")}</p>
        <div className={cx(GRID2, "mb-4")}>
          <div>
            <span className={FIELD_LABEL}>
              {t("wsSettings.whiteLabel.brandColors.primaryLabel")}
            </span>
            <div className="flex items-center gap-2.5">
              <span
                className="h-[34px] w-[34px] flex-none rounded-[9px] border-0 bg-(--sw)"
                style={{ "--sw": form.primary_color || "transparent" } as React.CSSProperties}
              />
              <input
                className={INPUT}
                type="text"
                value={form.primary_color}
                disabled={disabled}
                onChange={(event) => patch({ primary_color: event.target.value })}
              />
            </div>
          </div>
          <div>
            <span className={FIELD_LABEL}>
              {t("wsSettings.whiteLabel.brandColors.secondaryLabel")}
            </span>
            <div className="flex items-center gap-2.5">
              <span
                className="h-[34px] w-[34px] flex-none rounded-[9px] border-0 bg-(--sw)"
                style={{ "--sw": form.secondary_color || "transparent" } as React.CSSProperties}
              />
              <input
                className={INPUT}
                type="text"
                value={form.secondary_color}
                disabled={disabled}
                onChange={(event) => patch({ secondary_color: event.target.value })}
              />
            </div>
          </div>
        </div>
        <div className={TOGGLE_ROW}>
          <div>
            <div className="text-[13.5px] font-semibold">
              {t("wsSettings.whiteLabel.brandColors.hidePoweredByLabel")}
            </div>
            <div className="mt-0.5 max-w-[560px] text-[12px] leading-[1.45] text-(--t-3)">
              {t("wsSettings.whiteLabel.brandColors.hidePoweredByDescription")}
            </div>
          </div>
          <button
            type="button"
            role="switch"
            aria-checked={form.hide_powered_by}
            aria-label={t("wsSettings.whiteLabel.brandColors.hidePoweredByLabel")}
            disabled={disabled}
            onClick={() => patch({ hide_powered_by: !form.hide_powered_by })}
            className={cx(
              "relative h-6 w-[42px] flex-none cursor-pointer rounded-full border-none disabled:cursor-not-allowed disabled:opacity-55",
              form.hide_powered_by ? "bg-(--good)" : "bg-(--line)"
            )}
          >
            <i
              className={cx(
                "absolute top-[3px] h-[18px] w-[18px] rounded-full bg-white",
                form.hide_powered_by ? "left-[21px]" : "left-[3px]"
              )}
            />
          </button>
        </div>
      </div>

      {/* ── Email Sender ── */}
      <div className={CARD}>
        <h3 className={CARD_TITLE}>{t("wsSettings.whiteLabel.emailSender.heading")}</h3>
        <p className={CARD_DESC}>{t("wsSettings.whiteLabel.emailSender.description")}</p>
        <div className={GRID2}>
          <div>
            <span className={FIELD_LABEL}>
              {t("wsSettings.whiteLabel.emailSender.replyToLabel")}
            </span>
            <input
              className={INPUT}
              type="text"
              placeholder={t("wsSettings.whiteLabel.emailSender.replyToPlaceholder")}
              value={form.email_reply_to}
              disabled={disabled}
              onChange={(event) => patch({ email_reply_to: event.target.value })}
            />
          </div>
          <div>
            <span className={FIELD_LABEL}>
              {t("wsSettings.whiteLabel.emailSender.senderNameLabel")}
            </span>
            <input
              className={INPUT}
              type="text"
              value={form.email_sender_name}
              disabled={disabled}
              onChange={(event) => patch({ email_sender_name: event.target.value })}
            />
          </div>
        </div>
      </div>

      {/* ── Social Links ── */}
      <div className={CARD}>
        <h3 className={CARD_TITLE}>{t("wsSettings.whiteLabel.social.heading")}</h3>
        <p className={CARD_DESC}>{t("wsSettings.whiteLabel.social.description")}</p>
        <div className={GRID2}>
          <div>
            <span className={FIELD_LABEL}>{t("wsSettings.whiteLabel.social.xLabel")}</span>
            <input
              className={INPUT}
              type="text"
              placeholder={t("wsSettings.whiteLabel.social.xPlaceholder")}
              value={form.social_x_url}
              disabled={disabled}
              onChange={(event) => patch({ social_x_url: event.target.value })}
            />
          </div>
          <div>
            <span className={FIELD_LABEL}>{t("wsSettings.whiteLabel.social.linkedinLabel")}</span>
            <input
              className={INPUT}
              type="text"
              placeholder={t("wsSettings.whiteLabel.social.linkedinPlaceholder")}
              value={form.social_linkedin_url}
              disabled={disabled}
              onChange={(event) => patch({ social_linkedin_url: event.target.value })}
            />
          </div>
        </div>
      </div>

      {/* ── Footer & Legal ── */}
      <div className={CARD}>
        <h3 className={CARD_TITLE}>{t("wsSettings.whiteLabel.footer.heading")}</h3>
        <p className={CARD_DESC}>{t("wsSettings.whiteLabel.footer.description")}</p>
        <div className={cx(GRID2, "mb-4")}>
          <div>
            <span className={FIELD_LABEL}>{t("wsSettings.whiteLabel.footer.legalNameLabel")}</span>
            <input
              className={INPUT}
              type="text"
              placeholder={t("wsSettings.whiteLabel.footer.legalNamePlaceholder")}
              value={form.company_legal_name}
              disabled={disabled}
              onChange={(event) => patch({ company_legal_name: event.target.value })}
            />
          </div>
          <div>
            <span className={FIELD_LABEL}>{t("wsSettings.whiteLabel.footer.trademarkLabel")}</span>
            <input
              className={INPUT}
              type="text"
              value={form.company_trademark_text}
              disabled={disabled}
              onChange={(event) => patch({ company_trademark_text: event.target.value })}
            />
          </div>
        </div>
        <div className="mb-4">
          <span className={FIELD_LABEL}>{t("wsSettings.whiteLabel.footer.addressLabel")}</span>
          <textarea
            className={TEXTAREA}
            placeholder={t("wsSettings.whiteLabel.footer.addressPlaceholder")}
            value={form.company_address}
            disabled={disabled}
            onChange={(event) => patch({ company_address: event.target.value })}
          />
        </div>
        <span className={FIELD_LABEL}>{t("wsSettings.whiteLabel.footer.navLabel")}</span>
        <div className={cx(GRID3, "mb-3")}>
          <input
            className={INPUT}
            type="text"
            aria-label={t("wsSettings.whiteLabel.footer.aboutUrl")}
            placeholder={t("wsSettings.whiteLabel.footer.aboutUrl")}
            value={form.footer_about_url}
            disabled={disabled}
            onChange={(event) => patch({ footer_about_url: event.target.value })}
          />
          <input
            className={INPUT}
            type="text"
            aria-label={t("wsSettings.whiteLabel.footer.blogUrl")}
            placeholder={t("wsSettings.whiteLabel.footer.blogUrl")}
            value={form.footer_blog_url}
            disabled={disabled}
            onChange={(event) => patch({ footer_blog_url: event.target.value })}
          />
          <input
            className={INPUT}
            type="text"
            aria-label={t("wsSettings.whiteLabel.footer.supportUrl")}
            placeholder={t("wsSettings.whiteLabel.footer.supportUrl")}
            value={form.footer_support_url}
            disabled={disabled}
            onChange={(event) => patch({ footer_support_url: event.target.value })}
          />
        </div>
        <div className={GRID3}>
          <input
            className={INPUT}
            type="text"
            aria-label={t("wsSettings.whiteLabel.footer.legalUrl")}
            placeholder={t("wsSettings.whiteLabel.footer.legalUrl")}
            value={form.footer_legal_url}
            disabled={disabled}
            onChange={(event) => patch({ footer_legal_url: event.target.value })}
          />
          <input
            className={INPUT}
            type="text"
            aria-label={t("wsSettings.whiteLabel.footer.preferencesUrl")}
            placeholder={t("wsSettings.whiteLabel.footer.preferencesUrl")}
            value={form.footer_preferences_url}
            disabled={disabled}
            onChange={(event) => patch({ footer_preferences_url: event.target.value })}
          />
          <input
            className={INPUT}
            type="text"
            aria-label={t("wsSettings.whiteLabel.footer.privacyUrl")}
            placeholder={t("wsSettings.whiteLabel.footer.privacyUrl")}
            value={form.footer_privacy_url}
            disabled={disabled}
            onChange={(event) => patch({ footer_privacy_url: event.target.value })}
          />
        </div>
      </div>

      <div className="flex justify-end">
        <button
          type="button"
          className={BTN_PRIMARY}
          disabled={disabled || isSaving || isUploadingLogo}
          onClick={() => void handleSave()}
        >
          {isSaving ? t("wsSettings.whiteLabel.saving") : t("wsSettings.whiteLabel.saveAction")}
        </button>
      </div>

      {/* ── Custom Domain ── */}
      <div className={CARD}>
        <h3 className={CARD_TITLE}>{t("wsSettings.whiteLabel.customDomain.heading")}</h3>
        <p className={CARD_DESC}>
          {dnsTarget
            ? t("wsSettings.whiteLabel.customDomain.description", { target: dnsTarget })
            : t("wsSettings.whiteLabel.customDomain.descriptionNoTarget")}
        </p>
        <div className="mb-3.5 flex items-end gap-3 max-md:flex-col max-md:items-stretch">
          <div className="flex-1">
            <span className={FIELD_LABEL}>
              {t("wsSettings.whiteLabel.customDomain.subdomainLabel")}
            </span>
            <input
              className={INPUT}
              type="text"
              placeholder={t("wsSettings.whiteLabel.customDomain.subdomainPlaceholder")}
              value={domainInput}
              disabled={disabled}
              onChange={(event) => setDomainInput(event.target.value)}
            />
          </div>
          <button
            type="button"
            className={BTN_PRIMARY}
            disabled={disabled || isAddingDomain}
            onClick={() => void handleAddDomain()}
          >
            {!isAddingDomain ? (
              <Plus className="h-4 w-4" strokeWidth={2.25} aria-hidden="true" />
            ) : null}
            {isAddingDomain
              ? t("wsSettings.whiteLabel.customDomain.adding")
              : t("wsSettings.whiteLabel.customDomain.addAction")}
          </button>
        </div>
        {domains.length === 0 ? (
          <div className="rounded-[14px] border border-dashed border-[#D1D5DB] bg-[#F8FAFC] px-4 py-[22px] text-center text-[13px] text-(--t-3)">
            {t("wsSettings.whiteLabel.customDomain.empty")}
          </div>
        ) : (
          <div className="flex flex-col">
            {domains.map((domain) => (
              <div className={TOGGLE_ROW} key={domain.id}>
                <div className="min-w-0">
                  <div className="font-(family-name:--mono) text-[13px] font-semibold">
                    {domain.domain}
                  </div>
                  <div className="mt-0.5 text-[12px] leading-[1.45] text-(--t-3)">
                    {domain.verification_error
                      ? domain.verification_error
                      : t(`wsSettings.whiteLabel.customDomain.sslStatus.${domain.ssl_status}`)}
                  </div>
                </div>
                <div className="flex flex-none gap-2.5">
                  <button
                    type="button"
                    className={BTN}
                    disabled={disabled || busyDomainId === domain.id}
                    onClick={() => void handleVerifyDomain(domain.id)}
                  >
                    {busyDomainId === domain.id ? (
                      <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
                    ) : (
                      t("wsSettings.whiteLabel.customDomain.verifyAction")
                    )}
                  </button>
                  <button
                    type="button"
                    className={BTN}
                    disabled={disabled || busyDomainId === domain.id}
                    aria-label={t("wsSettings.whiteLabel.customDomain.removeAction")}
                    title={t("wsSettings.whiteLabel.customDomain.removeAction")}
                    onClick={() => void handleRemoveDomain(domain.id)}
                  >
                    <Trash2 className="h-4 w-4" aria-hidden="true" />
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* ── Deployment Checklist ── */}
      <div className={CARD}>
        <h3 className={CARD_TITLE}>{t("wsSettings.whiteLabel.checklist.heading")}</h3>
        <p className={CARD_DESC}>{t("wsSettings.whiteLabel.checklist.description")}</p>
        {["one", "two", "three"].map((step, index) => (
          <div className={STEP_ROW} key={step}>
            <span className={STEP_NUMBER}>{index + 1}</span>
            <div>
              <p className="m-0 text-[13px] leading-[1.5] text-(--t-2)">
                {t(`wsSettings.whiteLabel.checklist.${step}`)}
              </p>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
