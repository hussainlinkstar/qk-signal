const DEFAULT_LOCALE = "en-US";
const INVALID_DATE_FALLBACK = "\u2014";

export type DateDisplayFormat = "date" | "long" | "datetime";

export function formatDate(input: string | Date): string {
  const date = typeof input === "string" ? new Date(input) : input;
  if (Number.isNaN(date.getTime())) return INVALID_DATE_FALLBACK;
  return date.toLocaleDateString(DEFAULT_LOCALE, {
    month: "short",
    day: "2-digit",
    year: "numeric",
  });
}

export function formatDateLong(input: string | Date): string {
  const date = typeof input === "string" ? new Date(input) : input;
  if (Number.isNaN(date.getTime())) return INVALID_DATE_FALLBACK;
  return date.toLocaleDateString(DEFAULT_LOCALE, {
    month: "long",
    day: "numeric",
    year: "numeric",
  });
}

export function formatDateTime(input: string | Date): string {
  const date = typeof input === "string" ? new Date(input) : input;
  if (Number.isNaN(date.getTime())) return INVALID_DATE_FALLBACK;
  return date.toLocaleString(DEFAULT_LOCALE, {
    month: "short",
    day: "2-digit",
    year: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

export function formatISO(input: string | Date): string {
  const date = typeof input === "string" ? new Date(input) : input;
  if (Number.isNaN(date.getTime())) return INVALID_DATE_FALLBACK;
  return date.toISOString().slice(0, 10);
}

export function formatDateForFilename(input: string | Date): string {
  const date = typeof input === "string" ? new Date(input) : input;
  if (Number.isNaN(date.getTime())) return "unknown";
  return date.toISOString().slice(0, 16).replace("T", "_").replace(":", "-");
}

export function formatRelativeTime(input: string | Date | null | undefined): string {
  if (!input) return "N/A";
  const date = typeof input === "string" ? new Date(input) : input;
  if (Number.isNaN(date.getTime())) return "N/A";

  const now = new Date();
  const diffInSeconds = Math.floor((now.getTime() - date.getTime()) / 1000);

  if (diffInSeconds < -5) return formatDate(date);
  if (diffInSeconds < 60) return "just now";

  const diffInMinutes = Math.floor(diffInSeconds / 60);
  if (diffInMinutes < 60) return `${diffInMinutes}m ago`;

  const diffInHours = Math.floor(diffInMinutes / 60);
  if (diffInHours < 24) return `${diffInHours}h ago`;

  const diffInDays = Math.floor(diffInHours / 24);
  if (diffInDays < 7) return `${diffInDays}d ago`;

  return formatDate(date);
}
