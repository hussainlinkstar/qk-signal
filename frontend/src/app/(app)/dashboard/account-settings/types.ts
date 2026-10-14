export type NotificationPreferences = {
  user_id: number;
  notifications_enabled: boolean;
  notify_product_updates: boolean;
  notify_audit_alerts: boolean;
  notify_billing: boolean;
};

export type UserSummaryPayload = {
  id: number;
  email: string;
  role: string;
  subscription?: {
    plan_type?: string | null;
  } | null;
  capabilities?: Record<string, boolean | number>;
};

export type UserProfilePayload = {
  user_id: number;
  email: string;
  name: string | null;
  company_legal_name: string | null;
  company_registration_number: string | null;
  company_vat_number: string | null;
  billing_email: string | null;
  billing_phone: string | null;
  billing_address_line1: string | null;
  billing_address_line2: string | null;
  billing_city: string | null;
  billing_state: string | null;
  billing_postal_code: string | null;
  billing_country: string | null;
  billing_website_url: string | null;
  billing_tax_exempt: boolean;
  stripe_customer_id: string | null;
  role: string;
  notifications_enabled: boolean;
  mfa_enabled: boolean;
};

export type BrandingPayload = {
  custom_logo_url: string | null;
  company_name: string | null;
  primary_color: string | null;
  secondary_color: string | null;
};

export type MfaSetupPayload = {
  issuer: string;
  account_name: string;
  secret: string;
  otpauth_uri: string;
  qr_code_url: string;
  setup_token: string;
};

export type DataExportPayload = {
  user_id: number;
  email: string;
  role: string;
  credits: number;
  notifications_enabled: boolean;
  company_profile?: Record<string, unknown>;
  audits: Array<{
    id: number;
    url: string;
    geo_score: number;
    created_at: string;
    full_report: Record<string, unknown>;
  }>;
  subscription: {
    plan_type: string;
    status: string;
    stripe_customer_id: string;
  } | null;
};

export type DataDeletionPayload = {
  user_id: number;
  deleted_audits: number;
  deleted_subscription: boolean;
  message: string;
};

export type { Invoice as BillingInvoicePayload } from "@/types/billing";

export type AccountTab = "profile" | "security" | "notifications" | "branding" | "data";
