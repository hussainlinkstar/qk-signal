export type ReportLanguageOption = {
  code: string;
  label: string;
  shortLabel: string;
};

export const REPORT_LANGUAGE_OPTIONS: ReportLanguageOption[] = [
  { code: "en", label: "English (US)", shortLabel: "English" },
  { code: "es", label: "Spanish", shortLabel: "Spanish" },
  { code: "fr", label: "French", shortLabel: "French" },
  { code: "de", label: "German", shortLabel: "German" },
  { code: "it", label: "Italian", shortLabel: "Italian" },
  { code: "nl", label: "Dutch", shortLabel: "Dutch" },
  { code: "pt", label: "Portuguese", shortLabel: "Portuguese" },
  { code: "pl", label: "Polish", shortLabel: "Polish" },
  { code: "sv", label: "Swedish", shortLabel: "Swedish" },
  { code: "ja", label: "Japanese", shortLabel: "Japanese" },
  { code: "zh", label: "Chinese", shortLabel: "Chinese" },
];

export const normalizeReportLanguage = (value: string | null | undefined): string => {
  const candidate = (value || "").trim().toLowerCase();
  if (!candidate) {
    return "en";
  }
  const directMatch = REPORT_LANGUAGE_OPTIONS.find((option) => option.code === candidate);
  if (directMatch) {
    return directMatch.code;
  }
  const base = candidate.split("-", 1)[0];
  return REPORT_LANGUAGE_OPTIONS.some((option) => option.code === base) ? base : "en";
};

export const getReportLanguageLabel = (value: string | null | undefined): string => {
  const normalized = normalizeReportLanguage(value);
  return (
    REPORT_LANGUAGE_OPTIONS.find((option) => option.code === normalized)?.shortLabel || "English"
  );
};
