/**
 * White-label branding configuration for PDF report generation.
 *
 * When the backend ships the white-label API, this can be populated from
 * the user's account settings. Until then, DEFAULT_BRANDING is used.
 */

export type ReportBranding = {
  /** Base64-encoded logo image (data:image/png;base64,...) or null for default */
  logoBase64: string | null;
  /** Company / agency name shown on cover and footer */
  companyName: string;
  /** Primary brand color (hex), used for headers, score highlights */
  primaryColor: string;
  /** Secondary color (hex), used for sub-headers, table headers */
  secondaryColor: string;
  /** Accent color (hex), used for chart fills, highlights */
  accentColor: string;
  /** Footer text shown at bottom of every page */
  footerText: string;
};

export const DEFAULT_BRANDING: ReportBranding = {
  logoBase64: null,
  companyName: "Qiko Signal",
  primaryColor: "#2563EB",
  secondaryColor: "#9333EA",
  accentColor: "#9333EA",
  footerText: "Qiko Signal",
};

/** RGB tuple from a hex color string */
export function hexToRgb(hex: string): [number, number, number] {
  const cleaned = hex.replace("#", "");
  const num = parseInt(cleaned, 16);
  return [(num >> 16) & 255, (num >> 8) & 255, num & 255];
}
