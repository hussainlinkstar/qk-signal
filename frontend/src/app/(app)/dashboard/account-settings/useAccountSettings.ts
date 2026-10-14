"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useAuth } from "@/components/auth/custom-auth";
import { normalizeHexColor } from "@/components/ui/ColorPickerField";
import { resolvePlanCapabilities } from "@/lib/planCapabilities";
import {
  NotificationPreferences,
  UserSummaryPayload,
  UserProfilePayload,
  BrandingPayload,
  MfaSetupPayload,
  DataExportPayload,
  DataDeletionPayload,
  BillingInvoicePayload,
} from "./types";
import { DEFAULT_PRIMARY_COLOR, DEFAULT_SECONDARY_COLOR, parseResponseError } from "./utils";
import { uploadLogoAsset } from "@/services/uploadService";

const deriveLogoFileName = (value: string | null): string | null => {
  if (!value) {
    return null;
  }
  const withoutQuery = value.split("?")[0];
  const segments = withoutQuery.split("/");
  return segments[segments.length - 1] || null;
};

export function useAccountSettings() {
  const { getToken, isLoading: authLoading, isSignedIn, logout } = useAuth();

  const [isBootLoading, setIsBootLoading] = useState(false);
  const [bootError, setBootError] = useState("");

  // Profile state
  const [profileName, setProfileName] = useState("");
  const [profileEmail, setProfileEmail] = useState("");
  const [profileRole, setProfileRole] = useState("");
  const [companyLegalName, setCompanyLegalName] = useState("");
  const [companyRegistrationNumber, setCompanyRegistrationNumber] = useState("");
  const [companyVatNumber, setCompanyVatNumber] = useState("");
  const [billingEmail, setBillingEmail] = useState("");
  const [billingPhone, setBillingPhone] = useState("");
  const [billingAddressLine1, setBillingAddressLine1] = useState("");
  const [billingAddressLine2, setBillingAddressLine2] = useState("");
  const [billingCity, setBillingCity] = useState("");
  const [billingState, setBillingState] = useState("");
  const [billingPostalCode, setBillingPostalCode] = useState("");
  const [billingCountry, setBillingCountry] = useState("");
  const [billingWebsiteUrl, setBillingWebsiteUrl] = useState("");
  const [billingTaxExempt, setBillingTaxExempt] = useState(false);
  const [stripeCustomerId, setStripeCustomerId] = useState<string | null>(null);
  const [planType, setPlanType] = useState<string | null>(null);

  // Notification state
  const [notificationsEnabled, setNotificationsEnabled] = useState(true);
  const [notifyProductUpdates, setNotifyProductUpdates] = useState(true);
  const [notifyAuditAlerts, setNotifyAuditAlerts] = useState(true);
  const [notifyBilling, setNotifyBilling] = useState(true);

  // Branding state
  const [logoUrl, setLogoUrl] = useState("");
  const [logoFileName, setLogoFileName] = useState<string | null>(null);
  const [primaryColor, setPrimaryColor] = useState<string>(DEFAULT_PRIMARY_COLOR);
  const [secondaryColor, setSecondaryColor] = useState<string>(DEFAULT_SECONDARY_COLOR);

  // MFA state
  const [mfaEnabled, setMfaEnabled] = useState(false);
  const [mfaSetup, setMfaSetup] = useState<MfaSetupPayload | null>(null);
  const [mfaCode, setMfaCode] = useState("");

  // Password state
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");

  // Feedback state
  const [profileMessage, setProfileMessage] = useState("");
  const [profileError, setProfileError] = useState("");
  const [securityMessage, setSecurityMessage] = useState("");
  const [securityError, setSecurityError] = useState("");
  const [notificationMessage, setNotificationMessage] = useState("");
  const [notificationError, setNotificationError] = useState("");
  const [brandingMessage, setBrandingMessage] = useState("");
  const [brandingError, setBrandingError] = useState("");
  const [mfaMessage, setMfaMessage] = useState("");
  const [mfaError, setMfaError] = useState("");
  const [dataActionMessage, setDataActionMessage] = useState("");
  const [dataActionError, setDataActionError] = useState("");
  const [billingInfoError, setBillingInfoError] = useState("");
  const [recentInvoices, setRecentInvoices] = useState<BillingInvoicePayload[]>([]);

  // Loading state
  const [isSavingProfile, setIsSavingProfile] = useState(false);
  const [isSavingNotifications, setIsSavingNotifications] = useState(false);
  const [isSavingPassword, setIsSavingPassword] = useState(false);
  const [isSavingBranding, setIsSavingBranding] = useState(false);
  const [isUploadingBrandingLogo, setIsUploadingBrandingLogo] = useState(false);
  const [isPreparingMfa, setIsPreparingMfa] = useState(false);
  const [isSubmittingMfa, setIsSubmittingMfa] = useState(false);
  const [isExporting, setIsExporting] = useState(false);
  const [isDeleting, setIsDeleting] = useState(false);
  const [isLoadingInvoices, setIsLoadingInvoices] = useState(false);

  // SIGV2-1131: the confirmation for account deletion is owned here, not by
  // the view. Account deletion is irreversible, and before SIGV2-1039 this
  // route fired it straight from an onClick with no confirmation at all. The
  // dialog alone is not a durable guard, because nothing stopped a caller
  // from invoking the delete action directly again. Holding the flag next to
  // the request makes the confirmation a precondition of the request rather
  // than a convention the view is trusted to follow.
  const [isDeleteConfirmationOpen, setIsDeleteConfirmationOpen] = useState(false);

  const getAuthHeaders = useCallback(async () => {
    const token = await getToken();
    if (!token) {
      throw new Error("You must be signed in to manage account settings.");
    }
    return { Authorization: `Bearer ${token}` };
  }, [getToken]);

  const capabilities = useMemo(() => resolvePlanCapabilities(planType), [planType]);
  const hasWhiteLabel = capabilities.has_white_label;

  const loadInvoices = useCallback(async () => {
    setIsLoadingInvoices(true);
    setBillingInfoError("");
    try {
      const headers = await getAuthHeaders();
      const response = await fetch("/api/billing/invoices?limit=5", { method: "GET", headers });
      if (response.ok) {
        const payload = (await response.json()) as { invoices?: BillingInvoicePayload[] };
        setRecentInvoices(payload.invoices ?? []);
        return;
      }
      const responseError = await parseResponseError(response, "Unable to load Stripe invoices.");
      if (
        /stripe customer/i.test(responseError) ||
        /billing is currently disabled/i.test(responseError)
      ) {
        setRecentInvoices([]);
        return;
      }
      setBillingInfoError(
        response.status === 503
          ? "Invoice history is temporarily unavailable. Your billing data has not been changed."
          : responseError
      );
    } catch (error) {
      setBillingInfoError(
        error instanceof Error ? error.message : "Invoice history is temporarily unavailable."
      );
    } finally {
      setIsLoadingInvoices(false);
    }
  }, [getAuthHeaders]);

  const loadSettings = useCallback(async () => {
    if (authLoading || !isSignedIn) return;

    setIsBootLoading(true);
    setBootError("");

    try {
      const headers = await getAuthHeaders();
      const [summaryRes, profileRes, prefsRes, brandingRes, mfaRes] = await Promise.all([
        fetch("/api/users/me", { method: "GET", headers }),
        fetch("/api/users/me/profile", { method: "GET", headers }),
        fetch("/api/users/me/notification-preferences", { method: "GET", headers }),
        fetch("/api/users/me/branding", { method: "GET", headers }),
        fetch("/api/users/me/mfa/status", { method: "GET", headers }),
      ]);

      if (!summaryRes.ok)
        throw new Error(await parseResponseError(summaryRes, "Unable to load account summary."));
      if (!profileRes.ok)
        throw new Error(await parseResponseError(profileRes, "Unable to load profile details."));
      if (!prefsRes.ok)
        throw new Error(
          await parseResponseError(prefsRes, "Unable to load notification preferences.")
        );
      if (!brandingRes.ok)
        throw new Error(await parseResponseError(brandingRes, "Unable to load branding settings."));
      if (!mfaRes.ok)
        throw new Error(await parseResponseError(mfaRes, "Unable to load MFA status."));

      const summaryPayload = (await summaryRes.json()) as UserSummaryPayload;
      const profilePayload = (await profileRes.json()) as UserProfilePayload;
      const preferencesPayload = (await prefsRes.json()) as NotificationPreferences;
      const brandingPayload = (await brandingRes.json()) as BrandingPayload;
      const mfaPayload = (await mfaRes.json()) as { enabled: boolean };

      const resolvedPlan = summaryPayload.subscription?.plan_type ?? null;
      setPlanType(resolvedPlan);
      setProfileEmail(profilePayload.email || summaryPayload.email || "");
      setProfileRole(profilePayload.role || summaryPayload.role || "user");
      setProfileName(profilePayload.name ?? "");
      setCompanyLegalName(profilePayload.company_legal_name ?? "");
      setCompanyRegistrationNumber(profilePayload.company_registration_number ?? "");
      setCompanyVatNumber(profilePayload.company_vat_number ?? "");
      setBillingEmail(profilePayload.billing_email ?? "");
      setBillingPhone(profilePayload.billing_phone ?? "");
      setBillingAddressLine1(profilePayload.billing_address_line1 ?? "");
      setBillingAddressLine2(profilePayload.billing_address_line2 ?? "");
      setBillingCity(profilePayload.billing_city ?? "");
      setBillingState(profilePayload.billing_state ?? "");
      setBillingPostalCode(profilePayload.billing_postal_code ?? "");
      setBillingCountry(profilePayload.billing_country ?? "");
      setBillingWebsiteUrl(profilePayload.billing_website_url ?? "");
      setBillingTaxExempt(Boolean(profilePayload.billing_tax_exempt));
      setStripeCustomerId(profilePayload.stripe_customer_id ?? null);
      setNotificationsEnabled(preferencesPayload.notifications_enabled);
      setNotifyProductUpdates(preferencesPayload.notify_product_updates ?? true);
      setNotifyAuditAlerts(preferencesPayload.notify_audit_alerts ?? true);
      setNotifyBilling(preferencesPayload.notify_billing ?? true);
      setLogoUrl(brandingPayload.custom_logo_url ?? "");
      setLogoFileName(deriveLogoFileName(brandingPayload.custom_logo_url ?? null));
      setPrimaryColor(normalizeHexColor(brandingPayload.primary_color, DEFAULT_PRIMARY_COLOR));
      setSecondaryColor(
        normalizeHexColor(brandingPayload.secondary_color, DEFAULT_SECONDARY_COLOR)
      );
      setMfaEnabled(Boolean(mfaPayload.enabled));
      setMfaSetup(null);
      setMfaCode("");

      await loadInvoices();
    } catch (err) {
      setBootError(err instanceof Error ? err.message : "Unable to load account settings.");
    } finally {
      setIsLoadingInvoices(false);
      setIsBootLoading(false);
    }
  }, [authLoading, getAuthHeaders, isSignedIn, loadInvoices]);

  useEffect(() => {
    void loadSettings();
  }, [loadSettings]);

  const handleSaveProfile = async () => {
    setProfileMessage("");
    setProfileError("");
    setIsSavingProfile(true);
    try {
      const headers = await getAuthHeaders();
      const response = await fetch("/api/users/me", {
        method: "PATCH",
        headers: { ...headers, "Content-Type": "application/json" },
        body: JSON.stringify({
          name: profileName.trim() || null,
          company_legal_name: companyLegalName.trim() || null,
          company_registration_number: companyRegistrationNumber.trim() || null,
          company_vat_number: companyVatNumber.trim() || null,
          billing_email: billingEmail.trim() || null,
          billing_phone: billingPhone.trim() || null,
          billing_address_line1: billingAddressLine1.trim() || null,
          billing_address_line2: billingAddressLine2.trim() || null,
          billing_city: billingCity.trim() || null,
          billing_state: billingState.trim() || null,
          billing_postal_code: billingPostalCode.trim() || null,
          billing_country: billingCountry.trim().toUpperCase() || null,
          billing_website_url: billingWebsiteUrl.trim() || null,
          billing_tax_exempt: billingTaxExempt,
        }),
      });
      if (!response.ok)
        throw new Error(await parseResponseError(response, "Unable to update profile."));
      const payload = (await response.json()) as UserProfilePayload;
      setProfileName(payload.name ?? "");
      setCompanyLegalName(payload.company_legal_name ?? "");
      setCompanyRegistrationNumber(payload.company_registration_number ?? "");
      setCompanyVatNumber(payload.company_vat_number ?? "");
      setBillingEmail(payload.billing_email ?? "");
      setBillingPhone(payload.billing_phone ?? "");
      setBillingAddressLine1(payload.billing_address_line1 ?? "");
      setBillingAddressLine2(payload.billing_address_line2 ?? "");
      setBillingCity(payload.billing_city ?? "");
      setBillingState(payload.billing_state ?? "");
      setBillingPostalCode(payload.billing_postal_code ?? "");
      setBillingCountry(payload.billing_country ?? "");
      setBillingWebsiteUrl(payload.billing_website_url ?? "");
      setBillingTaxExempt(Boolean(payload.billing_tax_exempt));
      setStripeCustomerId(payload.stripe_customer_id ?? null);
      setProfileMessage("Profile updated.");
    } catch (err) {
      setProfileError(err instanceof Error ? err.message : "Unable to update profile.");
    } finally {
      setIsSavingProfile(false);
    }
  };

  const handleSaveNotifications = async () => {
    setNotificationMessage("");
    setNotificationError("");
    setIsSavingNotifications(true);
    try {
      const headers = await getAuthHeaders();
      const response = await fetch("/api/users/me/notification-preferences", {
        method: "PUT",
        headers: { ...headers, "Content-Type": "application/json" },
        body: JSON.stringify({
          notifications_enabled: notificationsEnabled,
          notify_product_updates: notifyProductUpdates,
          notify_audit_alerts: notifyAuditAlerts,
          notify_billing: notifyBilling,
        }),
      });
      if (!response.ok)
        throw new Error(
          await parseResponseError(response, "Unable to save notification preferences.")
        );
      const payload = (await response.json()) as NotificationPreferences;
      setNotificationsEnabled(payload.notifications_enabled);
      setNotifyProductUpdates(payload.notify_product_updates ?? true);
      setNotifyAuditAlerts(payload.notify_audit_alerts ?? true);
      setNotifyBilling(payload.notify_billing ?? true);
      setNotificationMessage("Notification preferences saved.");
    } catch (err) {
      setNotificationError(
        err instanceof Error ? err.message : "Unable to save notification preferences."
      );
    } finally {
      setIsSavingNotifications(false);
    }
  };

  const handleChangePassword = async () => {
    setSecurityMessage("");
    setSecurityError("");
    if (newPassword.length < 8) {
      setSecurityError("New password must be at least 8 characters.");
      return;
    }
    if (newPassword !== confirmPassword) {
      setSecurityError("Password confirmation does not match.");
      return;
    }
    setIsSavingPassword(true);
    try {
      const headers = await getAuthHeaders();
      const response = await fetch("/api/users/me/password", {
        method: "POST",
        headers: { ...headers, "Content-Type": "application/json" },
        body: JSON.stringify({ current_password: currentPassword, new_password: newPassword }),
      });
      if (!response.ok)
        throw new Error(await parseResponseError(response, "Unable to update password."));
      setCurrentPassword("");
      setNewPassword("");
      setConfirmPassword("");
      setSecurityMessage("Password updated successfully.");
    } catch (err) {
      setSecurityError(err instanceof Error ? err.message : "Unable to update password.");
    } finally {
      setIsSavingPassword(false);
    }
  };

  const handleGenerateMfaSetup = async () => {
    setMfaMessage("");
    setMfaError("");
    setIsPreparingMfa(true);
    try {
      const headers = await getAuthHeaders();
      const response = await fetch("/api/users/me/mfa/setup", { method: "POST", headers });
      if (!response.ok)
        throw new Error(await parseResponseError(response, "Unable to generate MFA setup."));
      const payload = (await response.json()) as MfaSetupPayload;
      setMfaSetup(payload);
      setMfaMessage("Scan the QR code and confirm with a 6-digit code.");
      setMfaCode("");
    } catch (err) {
      setMfaError(err instanceof Error ? err.message : "Unable to generate MFA setup.");
    } finally {
      setIsPreparingMfa(false);
    }
  };

  const handleEnableMfa = async () => {
    setMfaMessage("");
    setMfaError("");
    if (!mfaSetup) {
      setMfaError("Generate an MFA setup first.");
      return;
    }
    if (!mfaSetup.setup_token) {
      setMfaError("MFA setup token is missing. Regenerate setup and try again.");
      return;
    }
    if (!/^\d{6}$/.test(mfaCode.replace(/\s+/g, ""))) {
      setMfaError("Enter a valid 6-digit code.");
      return;
    }
    setIsSubmittingMfa(true);
    try {
      const headers = await getAuthHeaders();
      const response = await fetch("/api/users/me/mfa/enable", {
        method: "POST",
        headers: { ...headers, "Content-Type": "application/json" },
        body: JSON.stringify({ setup_token: mfaSetup.setup_token, otp_code: mfaCode }),
      });
      if (!response.ok)
        throw new Error(await parseResponseError(response, "Unable to enable MFA."));
      setMfaEnabled(true);
      setMfaSetup(null);
      setMfaCode("");
      setMfaMessage("Multi-factor authentication enabled.");
    } catch (err) {
      setMfaError(err instanceof Error ? err.message : "Unable to enable MFA.");
    } finally {
      setIsSubmittingMfa(false);
    }
  };

  const handleDisableMfa = async () => {
    setMfaMessage("");
    setMfaError("");
    if (!/^\d{6}$/.test(mfaCode.replace(/\s+/g, ""))) {
      setMfaError("Enter a valid 6-digit code.");
      return;
    }
    setIsSubmittingMfa(true);
    try {
      const headers = await getAuthHeaders();
      const response = await fetch("/api/users/me/mfa/disable", {
        method: "POST",
        headers: { ...headers, "Content-Type": "application/json" },
        body: JSON.stringify({ otp_code: mfaCode }),
      });
      if (!response.ok)
        throw new Error(await parseResponseError(response, "Unable to disable MFA."));
      setMfaEnabled(false);
      setMfaSetup(null);
      setMfaCode("");
      setMfaMessage("Multi-factor authentication disabled.");
    } catch (err) {
      setMfaError(err instanceof Error ? err.message : "Unable to disable MFA.");
    } finally {
      setIsSubmittingMfa(false);
    }
  };

  const handleSaveBranding = async () => {
    setBrandingMessage("");
    setBrandingError("");
    if (!hasWhiteLabel) {
      setBrandingError("Brand assets are available in the Executive plan.");
      return;
    }
    setIsSavingBranding(true);
    try {
      const headers = await getAuthHeaders();
      const response = await fetch("/api/users/me/branding", {
        method: "PUT",
        headers: { ...headers, "Content-Type": "application/json" },
        body: JSON.stringify({
          custom_logo_url: logoUrl.trim() || null,
          primary_color: primaryColor.trim() || null,
          secondary_color: secondaryColor.trim() || null,
        }),
      });
      if (!response.ok)
        throw new Error(await parseResponseError(response, "Unable to save brand settings."));
      const payload = (await response.json()) as BrandingPayload;
      setLogoUrl(payload.custom_logo_url ?? "");
      setLogoFileName(deriveLogoFileName(payload.custom_logo_url ?? null));
      setPrimaryColor(normalizeHexColor(payload.primary_color, DEFAULT_PRIMARY_COLOR));
      setSecondaryColor(normalizeHexColor(payload.secondary_color, DEFAULT_SECONDARY_COLOR));
      setBrandingMessage("Brand settings saved.");
    } catch (err) {
      setBrandingError(err instanceof Error ? err.message : "Unable to save brand settings.");
    } finally {
      setIsSavingBranding(false);
    }
  };

  const handleUploadBrandingLogo = async (file: File) => {
    setBrandingMessage("");
    setBrandingError("");
    if (!hasWhiteLabel) {
      setBrandingError("Brand assets are available in the Executive plan.");
      return;
    }

    setIsUploadingBrandingLogo(true);
    try {
      const headers = await getAuthHeaders();
      const uploaded = await uploadLogoAsset(file, "user", headers);
      setLogoUrl(uploaded.url);
      setLogoFileName(uploaded.filename);
      setBrandingMessage("Logo uploaded. Save branding to apply this logo.");
    } catch (err) {
      setBrandingError(err instanceof Error ? err.message : "Unable to upload logo.");
    } finally {
      setIsUploadingBrandingLogo(false);
    }
  };

  const handleRemoveBrandingLogo = () => {
    setLogoUrl("");
    setLogoFileName(null);
  };

  const handleExport = async () => {
    setDataActionMessage("");
    setDataActionError("");
    setIsExporting(true);
    try {
      const headers = await getAuthHeaders();
      const response = await fetch("/api/users/me/data-export", { method: "GET", headers });
      if (!response.ok)
        throw new Error(await parseResponseError(response, "Unable to export your data."));
      const payload = (await response.json()) as DataExportPayload;
      const blob = new Blob([JSON.stringify(payload, null, 2)], { type: "application/json" });
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = `qiko-signal-data-export-${payload.user_id}.json`;
      anchor.click();
      URL.revokeObjectURL(url);
      setDataActionMessage("Data export generated. Your download should start shortly.");
    } catch (err) {
      setDataActionError(err instanceof Error ? err.message : "Unable to export your data.");
    } finally {
      setIsExporting(false);
    }
  };

  const openDeleteConfirmation = () => {
    setDataActionMessage("");
    setDataActionError("");
    setIsDeleteConfirmationOpen(true);
  };

  const closeDeleteConfirmation = () => {
    setIsDeleteConfirmationOpen(false);
  };

  // SIGV2-1039: confirmation is the approved dialog in DataRightsSection,
  // which spells out what is erased and what must be retained. A second
  // window.confirm() on top of it would be a worse version of the same
  // question, so this does not prompt.
  //
  // SIGV2-1131: it refuses instead. Reaching the confirmation step is a
  // precondition, so a caller that has not been through the dialog cannot
  // delete an account by calling this. The refusal is deliberately silent:
  // on the built route the dialog is always open at this point, so there is
  // no user-visible state to report, only a caller to stop.
  const handleDelete = async () => {
    if (!isDeleteConfirmationOpen) {
      return;
    }
    setIsDeleteConfirmationOpen(false);
    setDataActionMessage("");
    setDataActionError("");
    setIsDeleting(true);
    try {
      const headers = await getAuthHeaders();
      const response = await fetch("/api/users/me", {
        method: "DELETE",
        headers: { ...headers, "Content-Type": "application/json" },
        body: JSON.stringify({ confirm: true }),
      });
      if (!response.ok)
        throw new Error(await parseResponseError(response, "Unable to delete your data."));
      const payload = (await response.json()) as DataDeletionPayload;
      setDataActionMessage(payload.message);
      await logout();
    } catch (err) {
      setDataActionError(err instanceof Error ? err.message : "Unable to delete your data.");
    } finally {
      setIsDeleting(false);
    }
  };

  return {
    // Auth state
    authLoading,
    isSignedIn,
    isBootLoading,
    bootError,

    // Profile
    profileName,
    setProfileName,
    profileEmail,
    profileRole,
    companyLegalName,
    setCompanyLegalName,
    companyRegistrationNumber,
    setCompanyRegistrationNumber,
    companyVatNumber,
    setCompanyVatNumber,
    billingEmail,
    setBillingEmail,
    billingPhone,
    setBillingPhone,
    billingAddressLine1,
    setBillingAddressLine1,
    billingAddressLine2,
    setBillingAddressLine2,
    billingCity,
    setBillingCity,
    billingState,
    setBillingState,
    billingPostalCode,
    setBillingPostalCode,
    billingCountry,
    setBillingCountry,
    billingWebsiteUrl,
    setBillingWebsiteUrl,
    billingTaxExempt,
    setBillingTaxExempt,
    stripeCustomerId,
    planType,
    profileMessage,
    profileError,
    isSavingProfile,
    handleSaveProfile,

    // Invoices
    recentInvoices,
    billingInfoError,
    isLoadingInvoices,
    loadInvoices,
    loadSettings,

    // Notifications
    notificationsEnabled,
    setNotificationsEnabled,
    notifyProductUpdates,
    setNotifyProductUpdates,
    notifyAuditAlerts,
    setNotifyAuditAlerts,
    notifyBilling,
    setNotifyBilling,
    notificationMessage,
    notificationError,
    isSavingNotifications,
    handleSaveNotifications,

    // Security
    currentPassword,
    setCurrentPassword,
    newPassword,
    setNewPassword,
    confirmPassword,
    setConfirmPassword,
    securityMessage,
    securityError,
    isSavingPassword,
    handleChangePassword,

    // MFA
    mfaEnabled,
    mfaSetup,
    mfaCode,
    setMfaCode,
    mfaMessage,
    mfaError,
    isPreparingMfa,
    isSubmittingMfa,
    handleGenerateMfaSetup,
    handleEnableMfa,
    handleDisableMfa,

    // Branding
    hasWhiteLabel,
    logoUrl,
    setLogoUrl,
    logoFileName,
    primaryColor,
    setPrimaryColor,
    secondaryColor,
    setSecondaryColor,
    brandingMessage,
    brandingError,
    isSavingBranding,
    isUploadingBrandingLogo,
    handleSaveBranding,
    handleUploadBrandingLogo,
    handleRemoveBrandingLogo,

    // Data rights
    dataActionMessage,
    dataActionError,
    isExporting,
    isDeleting,
    isDeleteConfirmationOpen,
    openDeleteConfirmation,
    closeDeleteConfirmation,
    handleExport,
    handleDelete,
  };
}
