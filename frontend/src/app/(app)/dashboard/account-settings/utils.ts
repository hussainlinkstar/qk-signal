import { formatDate } from "@/lib/dateFormatShared";
import { BRAND_HEX } from "@/lib/brandPalette";

export const DEFAULT_PRIMARY_COLOR = BRAND_HEX.atlasBlue;
export const DEFAULT_SECONDARY_COLOR = BRAND_HEX.signalTeal;

export const extractApiErrorMessage = (detail: unknown): string | null => {
  if (typeof detail === "string" && detail.trim()) {
    return detail;
  }
  if (Array.isArray(detail)) {
    const nested = detail
      .map((item) => extractApiErrorMessage(item))
      .filter((item): item is string => Boolean(item));
    if (nested.length > 0) {
      return nested.join("; ");
    }
    return null;
  }
  if (detail && typeof detail === "object") {
    const detailRecord = detail as Record<string, unknown>;
    return (
      extractApiErrorMessage(detailRecord.message) ??
      extractApiErrorMessage(detailRecord.detail) ??
      (Object.keys(detailRecord).length > 0 ? JSON.stringify(detailRecord) : null)
    );
  }
  return null;
};

export const parseResponseError = async (response: Response, fallback: string) => {
  const payload = (await response.json().catch(() => null)) as {
    detail?: unknown;
    message?: unknown;
  } | null;
  return (
    extractApiErrorMessage(payload?.detail) ?? extractApiErrorMessage(payload?.message) ?? fallback
  );
};

export const formatInvoiceAmount = (amount: number | null, currency: string | null) => {
  if (amount === null || amount === undefined) {
    return "N/A";
  }
  const normalizedCurrency = (currency ?? "usd").toUpperCase();
  try {
    return new Intl.NumberFormat("en-US", {
      style: "currency",
      currency: normalizedCurrency,
      maximumFractionDigits: 2,
    }).format(amount / 100);
  } catch {
    return `${(amount / 100).toFixed(2)} ${normalizedCurrency}`;
  }
};

export const formatInvoiceDate = (value: string | null) => {
  return value ? formatDate(value) : "N/A";
};
