import { z } from "zod";

export const withHttpScheme = (value: string): string => {
  const trimmed = value.trim();
  if (!trimmed) return "";
  return /^https?:\/\//i.test(trimmed) ? trimmed : `https://${trimmed}`;
};

export const isValidHttpUrl = (value: string): boolean => {
  try {
    const parsed = new URL(withHttpScheme(value));
    return (
      (parsed.protocol === "http:" || parsed.protocol === "https:") && parsed.hostname.includes(".")
    );
  } catch {
    return false;
  }
};

export const auditFormSchema = z
  .object({
    auditTargetType: z.enum(["website", "brand"]),
    url: z.string(),
    targetName: z.string(),
    targetUrl: z.string(),
    provider: z.string().min(1, "Select an AI model provider."),
    tier: z.enum(["fast", "smart", "deep_judgment"], { message: "Select an analysis depth." }),
    language: z.string().min(1, "Select a language."),
    market: z.string(),
    category: z.string(),
    entities: z.array(z.string()),
    entityInput: z.string(),
    selectedModels: z.array(z.string()),
  })
  .superRefine((value, ctx) => {
    const trimmedUrl = value.url.trim();
    const trimmedTargetUrl = value.targetUrl.trim();
    const trimmedTargetName = value.targetName.trim();
    const resolvedTargetUrl = trimmedTargetUrl || trimmedUrl;

    if (trimmedUrl && !isValidHttpUrl(trimmedUrl)) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        message: "Please enter a valid website address (e.g. example.com).",
        path: ["url"],
      });
    }

    if (trimmedTargetUrl && !isValidHttpUrl(trimmedTargetUrl)) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        message: "Please enter a valid website address (e.g. example.com).",
        path: ["targetUrl"],
      });
    }

    if (value.auditTargetType === "website") {
      if (!resolvedTargetUrl) {
        ctx.addIssue({
          code: z.ZodIssueCode.custom,
          message: "A target URL is required.",
          path: ["targetUrl"],
        });
      }
      return;
    }

    if (!trimmedTargetName) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        message: "Brand name is required for brand assessments.",
        path: ["targetName"],
      });
    }
  });

export type AuditFormValues = z.infer<typeof auditFormSchema>;

export const AUDIT_FORM_DEFAULTS: AuditFormValues = {
  auditTargetType: "website",
  url: "",
  targetName: "",
  targetUrl: "",
  provider: "google",
  tier: "fast",
  language: "en",
  market: "",
  category: "",
  entities: [],
  entityInput: "",
  selectedModels: [],
};
