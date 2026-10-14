export const SUPPORT_EMAIL =
  process.env.NEXT_PUBLIC_SUPPORT_EMAIL?.trim() ||
  process.env.NEXT_PUBLIC_CONTACT_EMAIL?.trim() ||
  "support@qiko.ai";

export const BILLING_EMAIL = process.env.NEXT_PUBLIC_BILLING_EMAIL?.trim() || "billing@qiko.ai";

export const PRIVACY_EMAIL = process.env.NEXT_PUBLIC_PRIVACY_EMAIL?.trim() || "privacy@qiko.ai";
