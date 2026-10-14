import "server-only";

import { serverFetch } from "@/utils/server-fetch";

export type AuthTenantBranding = {
  companyName?: string | null;
  customLogoUrl?: string | null;
  primaryColor?: string | null;
  secondaryColor?: string | null;
  customPageTitle?: string | null;
  customFaviconUrl?: string | null;
};

type TenantBrandingPayload = {
  company_name?: string | null;
  custom_logo_url?: string | null;
  primary_color?: string | null;
  secondary_color?: string | null;
  custom_page_title?: string | null;
  custom_favicon_url?: string | null;
};

export async function fetchAuthBranding(): Promise<AuthTenantBranding | null> {
  const brandingResponse = await serverFetch("/tenants/current-branding", {
    cache: "no-store",
    redirectOnUnauthorized: false,
  });

  if (!brandingResponse.ok) {
    return null;
  }

  const branding = (await brandingResponse.json()) as TenantBrandingPayload;
  return {
    companyName: branding.company_name,
    customLogoUrl: branding.custom_logo_url,
    primaryColor: branding.primary_color,
    secondaryColor: branding.secondary_color,
    customPageTitle: branding.custom_page_title,
    customFaviconUrl: branding.custom_favicon_url,
  };
}
