"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { toast } from "sonner";
import type { EntityCandidate, EntityExtractionResponse } from "@/types/auditWorkspace";
import { AUDIT_DRAFT_STORAGE_KEY } from "@/types/auditWorkspace";
import {
  auditFormSchema,
  AUDIT_FORM_DEFAULTS,
  withHttpScheme,
  type AuditFormValues,
} from "@/lib/auditFormSchema";
import { preflightAuditUrl } from "@/services/auditService";
import { isSameTarget } from "@/lib/scanLaunchIntent";
import {
  generateEntitySuggestions,
  inferCategoryFromEntities,
  normalizeDiscoveredCategory,
  normalizeDiscoveredLanguage,
  normalizeDiscoveredMarket,
  parseEntityTokens,
} from "@/lib/auditWorkspaceUtils";

type UseAuditFormParams = {
  getAuthHeaders: () => Promise<Record<string, string>>;
  onAutoDetectStart?: () => void;
  /**
   * The target a launch link names explicitly (SIGV2-1170). When present it
   * outranks a stored draft: a draft written for a different site is set
   * aside rather than restored over the target the link points at.
   */
  linkTarget?: string;
};

export type ModelSelectionOptions = {
  mode?: "single" | "toggle";
};

let lastAuditDraftRestoreToastAt = 0;

const normalizeAuditTargetType = (value: string | null | undefined): "website" | "brand" =>
  String(value ?? "")
    .trim()
    .toLowerCase() === "brand"
    ? "brand"
    : "website";

const normalizeAuditTier = (
  tier: string | null | undefined
): "fast" | "smart" | "deep_judgment" => {
  const normalized = String(tier ?? "")
    .trim()
    .toLowerCase();
  if (normalized === "deep_judgment" || normalized === "high_confidence") {
    return "deep_judgment";
  }
  if (normalized === "deep" || normalized === "smart") {
    return "smart";
  }
  return "fast";
};

const resolveTargetUrl = (value: Pick<AuditFormValues, "url" | "targetUrl">): string =>
  withHttpScheme(value.targetUrl) || withHttpScheme(value.url);

export function useAuditForm({
  getAuthHeaders,
  onAutoDetectStart,
  linkTarget,
}: UseAuditFormParams) {
  const rhf = useForm<AuditFormValues>({
    resolver: zodResolver(auditFormSchema),
    defaultValues: AUDIT_FORM_DEFAULTS,
    mode: "onBlur",
  });

  const { watch, setValue, getValues, reset, formState } = rhf;
  const form = watch(); // reactive snapshot of all form values

  const [entitySuggestions, setEntitySuggestions] = useState<EntityCandidate[]>([]);
  const [editableEntities, setEditableEntities] = useState<EntityCandidate[]>([]);
  const [isAutoDetecting, setIsAutoDetecting] = useState(false);
  const [isScanningEntities, setIsScanningEntities] = useState(false);
  const [aiSuggestedCategory, setAiSuggestedCategory] = useState<string | null>(null);
  const [isCategoryDetecting, setIsCategoryDetecting] = useState(false);
  const [manualOverrides, setManualOverrides] = useState({
    language: false,
    market: false,
    category: false,
  });
  const [isPreflightChecking, setIsPreflightChecking] = useState(false);
  const [preflightError, setPreflightError] = useState("");
  // The exact address the preflight resolved. The approved Target section
  // confirms reachability, and that confirmation must belong to the address
  // currently in the field, not to whatever resolved before the last edit.
  const [preflightVerifiedUrl, setPreflightVerifiedUrl] = useState("");
  const [isDraftRestored, setIsDraftRestored] = useState(false);

  // Pre-Scan AI state
  const [isPreScanning, setIsPreScanning] = useState(false);
  const [preScanResult, setPreScanResult] = useState<{
    language: string;
    market_region: string;
    category: string;
    primary_entities?: string[] | null;
    source: string;
    snapshot_title?: string | null;
    snapshot_description?: string | null;
    credits_deducted: number;
  } | null>(null);
  const [preScanError, setPreScanError] = useState<string | null>(null);
  // SIGV2-1171: the last autosave write failed. The page turns this into the
  // persistent warning at the launch row; a successful write clears it.
  const [draftSaveFailed, setDraftSaveFailed] = useState(false);

  const lastSavedDraftRef = useRef("");
  // SIGV2-1160: the draft confirmation is announced once per visit, not once
  // per change. See the save effect below.
  const hasAnnouncedSaveRef = useRef(false);

  const setFormValue = useCallback(
    (field: keyof AuditFormValues, value: string | string[]) => {
      if (field === "auditTargetType" && typeof value === "string") {
        const normalizedTargetType = normalizeAuditTargetType(value);
        const current = getValues();

        setValue("auditTargetType", normalizedTargetType, {
          shouldValidate: false,
          shouldDirty: true,
        });

        if (normalizedTargetType === "brand" && current.url.trim() && !current.targetUrl.trim()) {
          setValue("targetUrl", current.url, { shouldValidate: false, shouldDirty: true });
        }
        if (normalizedTargetType === "website" && current.targetUrl.trim() && !current.url.trim()) {
          setValue("url", current.targetUrl, { shouldValidate: false, shouldDirty: true });
        }
        setPreflightError("");
        return;
      }

      const normalizedValue =
        field === "tier" && typeof value === "string" ? normalizeAuditTier(value) : value;
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      setValue(field, normalizedValue as any, { shouldValidate: false, shouldDirty: true });
    },
    [getValues, setValue]
  );

  // --- Draft Restore ---
  useEffect(() => {
    if (typeof window === "undefined" || isDraftRestored) return;

    const rawDraft = window.localStorage.getItem(AUDIT_DRAFT_STORAGE_KEY);
    if (!rawDraft) {
      // SIGV2-1224: the form as it stands now is the baseline, not a change.
      // Without this the first autosave tick compared it against an empty
      // ref, persisted a draft nobody wrote, and announced the save.
      lastSavedDraftRef.current = JSON.stringify(getValues());
      setIsDraftRestored(true);
      return;
    }

    try {
      const parsed = JSON.parse(rawDraft) as Partial<AuditFormValues>;
      const restoredTargetType = normalizeAuditTargetType(
        typeof parsed.auditTargetType === "string"
          ? parsed.auditTargetType
          : AUDIT_FORM_DEFAULTS.auditTargetType
      );
      const restoredUrl = typeof parsed.url === "string" ? parsed.url : AUDIT_FORM_DEFAULTS.url;
      const restoredTargetUrl =
        typeof parsed.targetUrl === "string"
          ? parsed.targetUrl
          : restoredUrl || AUDIT_FORM_DEFAULTS.targetUrl;
      const restored: AuditFormValues = {
        ...AUDIT_FORM_DEFAULTS,
        ...parsed,
        auditTargetType: restoredTargetType,
        url: restoredUrl,
        targetUrl: restoredTargetUrl,
        targetName:
          typeof parsed.targetName === "string"
            ? parsed.targetName
            : AUDIT_FORM_DEFAULTS.targetName,
        tier: normalizeAuditTier(
          typeof parsed.tier === "string" ? parsed.tier : AUDIT_FORM_DEFAULTS.tier
        ),
        category: normalizeDiscoveredCategory(
          typeof parsed.category === "string" ? parsed.category : AUDIT_FORM_DEFAULTS.category,
          {
            url: restoredTargetUrl || restoredUrl || AUDIT_FORM_DEFAULTS.url,
          }
        ),
        entities: Array.isArray(parsed.entities)
          ? parsed.entities.map((entry) => String(entry).trim()).filter(Boolean)
          : [],
        entityInput: typeof parsed.entityInput === "string" ? parsed.entityInput : "",
      };
      const draftTarget =
        restoredTargetType === "brand"
          ? restored.targetName.trim()
          : restoredTargetUrl || restoredUrl;
      // SIGV2-1170: an explicit target in the launch link outranks a stored
      // draft. Without this the draft's site restored over `?url=` and the
      // customer was left configuring a scan for a site they did not choose
      // (and, under a launch intent, watching the autostart refuse with no
      // explanation). A blank draft carries no target to conflict with, and a
      // link that names no target changes nothing.
      if (linkTarget && draftTarget && !isSameTarget(draftTarget, linkTarget)) {
        // SIGV2-1171: informational, not a success. Nothing was accomplished
        // here - a draft the customer wrote was put aside - and calling that a
        // success is exactly the kind of tone collapse that makes a real
        // success and a real failure indistinguishable.
        toast.info(`Saved draft for ${draftTarget} set aside - this link opens ${linkTarget}.`, {
          id: "audit-draft-set-aside",
        });
        // The draft is being kept, so the current form is the baseline:
        // without this the next autosave tick overwrote the set-aside draft
        // with an untouched form and announced it as a save.
        lastSavedDraftRef.current = JSON.stringify(getValues());
        return;
      }
      reset(restored);
      if (
        restored.language !== AUDIT_FORM_DEFAULTS.language ||
        restored.market !== AUDIT_FORM_DEFAULTS.market ||
        restored.category !== AUDIT_FORM_DEFAULTS.category
      ) {
        setManualOverrides({
          language: restored.language !== AUDIT_FORM_DEFAULTS.language,
          market: restored.market !== AUDIT_FORM_DEFAULTS.market && Boolean(restored.market),
          category:
            restored.category !== AUDIT_FORM_DEFAULTS.category && Boolean(restored.category),
        });
      }
      lastSavedDraftRef.current = JSON.stringify(restored);
      const now = Date.now();
      if (now - lastAuditDraftRestoreToastAt > 2500) {
        toast.success("Assessment draft restored.", {
          id: "audit-draft-restored",
        });
        lastAuditDraftRestoreToastAt = now;
      }
    } catch {
      window.localStorage.removeItem(AUDIT_DRAFT_STORAGE_KEY);
      lastSavedDraftRef.current = JSON.stringify(getValues());
    } finally {
      setIsDraftRestored(true);
    }
  }, [isDraftRestored, getValues, reset, linkTarget]);

  // --- Draft Save (debounced via watch subscription) ---
  useEffect(() => {
    if (typeof window === "undefined" || !isDraftRestored) return;

    const timer = window.setTimeout(() => {
      const serialized = JSON.stringify(form);
      if (serialized === lastSavedDraftRef.current) return;

      try {
        window.localStorage.setItem(AUDIT_DRAFT_STORAGE_KEY, serialized);
        lastSavedDraftRef.current = serialized;
        // A save going through again clears the refusal: whatever filled the
        // storage has room now, and the warning would be lying if it stayed.
        setDraftSaveFailed(false);

        // SIGV2-1160: every field edit used to raise a "draft saved" toast,
        // throttled to one every 8 seconds, so setting up a scan was a stream
        // of interruptions. The autosave itself is unchanged; the customer is
        // told once per visit that their configuration persists, and nothing
        // pops up on later changes. The approved start-scan page (mockup:
        // Signal Audit.html) carries no saved-state element, so no inline
        // indicator is introduced here either.
        if (!hasAnnouncedSaveRef.current) {
          hasAnnouncedSaveRef.current = true;
          toast.success("Assessment draft saved.", { id: "audit-draft-saved" });
        }
      } catch {
        // SIGV2-1171: a failed save is the one case where the customer can
        // lose work, so it reports persistently at the launch row (where the
        // page surfaces every other refusal) rather than as a toast that
        // fades. The asymmetry is deliberate: a successful save is silent.
        setDraftSaveFailed(true);
      }
    }, 700);

    return () => window.clearTimeout(timer);
  }, [form, isDraftRestored]);

  // --- beforeunload flush ---
  useEffect(() => {
    if (typeof window === "undefined") return;

    const flushDraft = () => {
      const serialized = JSON.stringify(getValues());
      if (serialized !== lastSavedDraftRef.current) {
        try {
          window.localStorage.setItem(AUDIT_DRAFT_STORAGE_KEY, serialized);
          lastSavedDraftRef.current = serialized;
        } catch {
          // Quota exceeded on unload, silently skip
        }
      }
    };

    window.addEventListener("beforeunload", flushDraft);
    return () => window.removeEventListener("beforeunload", flushDraft);
  }, [getValues]);

  // --- Preflight clear ---
  const activeTargetUrl = useMemo(() => resolveTargetUrl(form), [form]);

  useEffect(() => {
    if (!activeTargetUrl) {
      setPreflightError("");
    }
  }, [activeTargetUrl]);

  // --- Sync editableEntities → form.entities ---
  useEffect(() => {
    const names = editableEntities.map((e) => e.name).filter(Boolean);
    const current = getValues("entities");
    const prevSorted = [...current].sort().join("\0");
    const nextSorted = [...names].sort().join("\0");
    if (prevSorted !== nextSorted) {
      setValue("entities", names, { shouldDirty: true });
      setValue("entityInput", "", { shouldDirty: false });
    }
  }, [editableEntities, getValues, setValue]);

  const verifyUrlPreflight = useCallback(
    async (rawUrl?: string) => {
      const targetUrl = (rawUrl ?? activeTargetUrl).trim();
      if (!targetUrl) {
        setPreflightError("");
        setPreflightVerifiedUrl("");
        return false;
      }

      setIsPreflightChecking(true);
      setPreflightError("");
      setPreflightVerifiedUrl("");
      try {
        const authHeaders = await getAuthHeaders();
        const result = await preflightAuditUrl(targetUrl, authHeaders);
        if (!result.ok) {
          throw new Error("URL preflight failed.");
        }
        setPreflightVerifiedUrl(targetUrl);
        return true;
      } catch (err) {
        const message = err instanceof Error ? err.message : "URL preflight failed.";
        setPreflightError(message);
        return false;
      } finally {
        setIsPreflightChecking(false);
      }
    },
    [activeTargetUrl, getAuthHeaders]
  );

  const fetchExtractedEntities = useCallback(
    async (targetUrl: string): Promise<EntityCandidate[]> => {
      const authHeaders = await getAuthHeaders();
      const response = await fetch("/api/v1/entities/extract", {
        method: "POST",
        headers: {
          ...authHeaders,
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ url: targetUrl }),
      });

      if (!response.ok) {
        const payload = await response.json().catch(() => null);
        throw new Error(payload?.detail ?? "Unable to extract entities from the URL.");
      }

      const payload = (await response.json()) as EntityExtractionResponse;
      const seen = new Set<string>();
      return (payload.entities ?? [])
        .map((item) => ({
          name: String(item?.name ?? "").trim(),
          type: String(item?.type ?? "Entity"),
          confidence:
            typeof item?.confidence === "number" && Number.isFinite(item.confidence)
              ? Math.round(item.confidence * 100)
              : null,
        }))
        .filter((entry) => {
          if (!entry.name) return false;
          const normalized = entry.name.toLowerCase();
          if (seen.has(normalized)) return false;
          seen.add(normalized);
          return true;
        });
    },
    [getAuthHeaders]
  );

  const fetchSiteCategory = useCallback(
    async (targetUrl: string): Promise<{ category: string; confidence: number } | null> => {
      try {
        const authHeaders = await getAuthHeaders();
        const response = await fetch("/api/v1/site/classify", {
          method: "POST",
          headers: {
            ...authHeaders,
            "Content-Type": "application/json",
          },
          body: JSON.stringify({ url: targetUrl }),
        });
        if (!response.ok) return null;
        return (await response.json()) as { category: string; confidence: number };
      } catch {
        return null;
      }
    },
    [getAuthHeaders]
  );

  const fetchPreScan = useCallback(
    async (targetUrl: string, targetName: string, auditTargetType: string) => {
      const authHeaders = await getAuthHeaders();
      const response = await fetch("/api/v1/audit/pre-scan", {
        method: "POST",
        headers: {
          ...authHeaders,
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          url: targetUrl || null,
          target_name: targetName || null,
          audit_target_type: auditTargetType,
        }),
      });

      if (!response.ok) {
        const payload = await response.json().catch(() => null);
        throw new Error(payload?.detail ?? "Pre-scan failed.");
      }

      return response.json();
    },
    [getAuthHeaders]
  );

  const runUrlAutoDetection = useCallback(
    async (forceOverride: boolean | React.FocusEvent | React.MouseEvent = false) => {
      const shouldForceOverride = forceOverride === true;
      const trimmedUrl = resolveTargetUrl(form);
      const trimmedName = form.targetName.trim();
      const isBrandWithoutUrl = form.auditTargetType === "brand" && trimmedName && !trimmedUrl;

      if (!trimmedUrl && !isBrandWithoutUrl) return;

      let parsedUrl: URL | undefined;
      if (trimmedUrl) {
        try {
          parsedUrl = new URL(trimmedUrl);
        } catch {
          setEntitySuggestions([]);
          setEditableEntities([]);
          return;
        }
      }

      if (trimmedUrl) {
        const preflightOk = await verifyUrlPreflight(trimmedUrl);
        if (!preflightOk) {
          setEntitySuggestions([]);
          setEditableEntities([]);
          return;
        }
      }

      const fallbackSuggestions = trimmedUrl ? generateEntitySuggestions(trimmedUrl) : [];

      // TLD-based overrides (always applied as instant fallback)
      if (parsedUrl) {
        const hostTld = parsedUrl.hostname.toLowerCase();
        if (hostTld.endsWith(".ro")) {
          const currentValues = getValues();
          const newOverrides = { ...manualOverrides };
          let changed = false;

          if (!manualOverrides.market || !currentValues.market) {
            setValue("market", "Romania", { shouldDirty: true });
            newOverrides.market = false;
            changed = true;
          }
          if (
            !manualOverrides.language ||
            currentValues.language === AUDIT_FORM_DEFAULTS.language
          ) {
            setValue("language", "en", { shouldDirty: true });
            newOverrides.language = false;
            changed = true;
          }
          if (changed) {
            setManualOverrides(newOverrides);
          }
        }
      }

      onAutoDetectStart?.();
      setIsAutoDetecting(true);
      setIsScanningEntities(true);
      setIsCategoryDetecting(true);
      setIsPreScanning(true);
      setPreScanError(null);

      try {
        // Attempt AI pre-scan first (single Gemini call for all fields)
        const scanResult = await fetchPreScan(trimmedUrl, trimmedName, form.auditTargetType);
        setPreScanResult({
          ...scanResult,
          primary_entities: Array.isArray(scanResult?.primary_entities)
            ? scanResult.primary_entities
            : [],
        });

        const currentValues = getValues();
        const newOverrides = { ...manualOverrides };
        let overridesChanged = false;

        // Auto-fill language if not manually overridden or left as default
        const scanContextEntities: EntityCandidate[] = [
          ...(scanResult.primary_entities ?? []).map((name: string) => ({
            name,
            type: "AI Detected",
            confidence: 85,
          })),
          ...(scanResult.snapshot_title
            ? [{ name: scanResult.snapshot_title, type: "Page Title", confidence: 70 }]
            : []),
          ...(scanResult.snapshot_description
            ? [{ name: scanResult.snapshot_description, type: "Meta Description", confidence: 65 }]
            : []),
        ];

        const normalizedScanCategory = normalizeDiscoveredCategory(scanResult.category, {
          url: trimmedUrl,
          entities: scanContextEntities,
        });

        const normalizedScanLanguage = normalizeDiscoveredLanguage(scanResult.language, {
          url: trimmedUrl,
          category: normalizedScanCategory || scanResult.category,
        });
        const normalizedScanMarket = normalizeDiscoveredMarket(scanResult.market_region, {
          url: trimmedUrl,
          language: normalizedScanLanguage,
          category: normalizedScanCategory || scanResult.category,
        });

        if (
          (shouldForceOverride ||
            !manualOverrides.language ||
            currentValues.language === AUDIT_FORM_DEFAULTS.language) &&
          normalizedScanLanguage
        ) {
          setValue("language", normalizedScanLanguage, { shouldDirty: true });
          newOverrides.language = false;
          overridesChanged = true;
        }

        // Auto-fill market region if not manually overridden or if empty
        if (
          (shouldForceOverride || !manualOverrides.market || !currentValues.market?.trim()) &&
          normalizedScanMarket
        ) {
          setValue("market", normalizedScanMarket, { shouldDirty: true });
          newOverrides.market = false;
          overridesChanged = true;
        }

        // Auto-fill category if not manually overridden or if empty
        if (
          (shouldForceOverride || !manualOverrides.category || !currentValues.category?.trim()) &&
          scanResult.category
        ) {
          setValue("category", normalizedScanCategory || scanResult.category, {
            shouldDirty: true,
          });
          setAiSuggestedCategory(normalizedScanCategory || scanResult.category);
          newOverrides.category = false;
          overridesChanged = true;
        }

        if (overridesChanged) {
          setManualOverrides(newOverrides);
        }

        // Auto-fill entities from AI
        const aiEntities: EntityCandidate[] = (scanResult.primary_entities ?? []).map(
          (name: string) => ({ name, type: "AI Detected", confidence: 85 })
        );
        if (aiEntities.length > 0) {
          setValue(
            "entities",
            aiEntities.map((e) => e.name),
            { shouldDirty: true }
          );
          setValue("entityInput", "", { shouldDirty: false });
          setEntitySuggestions(aiEntities);
          setEditableEntities(aiEntities);
        } else {
          setEntitySuggestions(fallbackSuggestions);
          setEditableEntities(fallbackSuggestions);
        }
      } catch (preScanErr) {
        // Pre-scan failed, fall back to site classification, with entity extraction only when needed.
        const errorMsg = preScanErr instanceof Error ? preScanErr.message : "Pre-scan unavailable.";
        setPreScanError(errorMsg);

        try {
          const classifyResult = trimmedUrl
            ? await fetchSiteCategory(trimmedUrl).catch(() => null)
            : null;
          const shouldAttemptEntityExtraction =
            trimmedUrl && (!classifyResult || classifyResult.confidence <= 0.3);
          const extractedEntities = shouldAttemptEntityExtraction
            ? await fetchExtractedEntities(trimmedUrl).catch(() => [])
            : [];

          const currentValues = getValues();
          const newOverrides = { ...manualOverrides };
          let changed = false;
          let normalizedCategoryCandidate = "";

          if (!manualOverrides.category || !currentValues.category?.trim()) {
            if (classifyResult?.category && classifyResult.confidence > 0.3) {
              normalizedCategoryCandidate = normalizeDiscoveredCategory(classifyResult.category, {
                url: trimmedUrl,
                entities: extractedEntities,
              });
              setValue("category", normalizedCategoryCandidate || classifyResult.category, {
                shouldDirty: true,
              });
              setAiSuggestedCategory(normalizedCategoryCandidate || classifyResult.category);
              newOverrides.category = false;
              changed = true;
            } else {
              normalizedCategoryCandidate = normalizeDiscoveredCategory(
                inferCategoryFromEntities(extractedEntities) ?? "",
                {
                  url: trimmedUrl,
                  entities: extractedEntities,
                }
              );
              if (normalizedCategoryCandidate) {
                setValue("category", normalizedCategoryCandidate, { shouldDirty: true });
                setAiSuggestedCategory(normalizedCategoryCandidate);
                newOverrides.category = false;
                changed = true;
              }
            }
          }

          const fallbackCategory =
            normalizedCategoryCandidate ||
            normalizeDiscoveredCategory(currentValues.category, {
              url: trimmedUrl,
            });
          const fallbackLanguage = normalizeDiscoveredLanguage(
            shouldForceOverride ? AUDIT_FORM_DEFAULTS.language : currentValues.language,
            {
              url: trimmedUrl,
              category: fallbackCategory,
            }
          );
          const fallbackMarket = normalizeDiscoveredMarket(
            shouldForceOverride ? AUDIT_FORM_DEFAULTS.market : currentValues.market,
            {
              url: trimmedUrl,
              language: fallbackLanguage,
              category: fallbackCategory,
            }
          );

          if (
            shouldForceOverride ||
            !manualOverrides.language ||
            currentValues.language === AUDIT_FORM_DEFAULTS.language
          ) {
            if (fallbackLanguage) {
              setValue("language", fallbackLanguage, { shouldDirty: true });
              newOverrides.language = false;
              changed = true;
            }
          }

          if (shouldForceOverride || !manualOverrides.market || !currentValues.market?.trim()) {
            if (fallbackMarket) {
              setValue("market", fallbackMarket, { shouldDirty: true });
              newOverrides.market = false;
              changed = true;
            }
          }

          if (changed) {
            setManualOverrides(newOverrides);
          }

          if (extractedEntities.length > 0) {
            setValue(
              "entities",
              extractedEntities.map((entity) => entity.name),
              { shouldDirty: true }
            );
            setValue("entityInput", "", { shouldDirty: false });
            setEntitySuggestions(extractedEntities);
          } else {
            setEntitySuggestions(fallbackSuggestions);
          }

          setEditableEntities(
            extractedEntities.length > 0 ? extractedEntities : fallbackSuggestions
          );
        } catch {
          setEntitySuggestions(fallbackSuggestions);
          setEditableEntities(fallbackSuggestions);
        }
      } finally {
        setIsAutoDetecting(false);
        setIsScanningEntities(false);
        setIsCategoryDetecting(false);
        setIsPreScanning(false);
      }
    },
    [
      fetchExtractedEntities,
      fetchPreScan,
      fetchSiteCategory,
      form,
      getValues,
      manualOverrides,
      onAutoDetectStart,
      setValue,
      verifyUrlPreflight,
    ]
  );

  const appendEntityTokens = useCallback(
    (value: string) => {
      const tokens = parseEntityTokens(value);
      if (!tokens.length) return;
      const current = getValues("entities");
      const seen = new Set(current.map((token) => token.toLowerCase()));
      const deduped = tokens.filter((token) => {
        const lower = token.toLowerCase();
        if (seen.has(lower)) return false;
        seen.add(lower);
        return true;
      });
      if (deduped.length) {
        setValue("entities", [...current, ...deduped], { shouldDirty: true });
      }
    },
    [getValues, setValue]
  );

  const removeEntity = useCallback(
    (token: string) => {
      const current = getValues("entities");
      setValue(
        "entities",
        current.filter((item) => item !== token),
        { shouldDirty: true }
      );
    },
    [getValues, setValue]
  );

  const handleEntityInputChange = useCallback(
    (event: React.ChangeEvent<HTMLInputElement>) => {
      const value = event.target.value;
      if (value.includes(",")) {
        appendEntityTokens(value);
        setValue("entityInput", "", { shouldDirty: false });
      } else {
        setValue("entityInput", value, { shouldDirty: false });
      }
    },
    [appendEntityTokens, setValue]
  );

  const handleEntityInputKeyDown = useCallback(
    (event: React.KeyboardEvent<HTMLInputElement>) => {
      if (event.key === "Enter") {
        event.preventDefault();
        appendEntityTokens(form.entityInput);
        setValue("entityInput", "", { shouldDirty: false });
      }
      if (event.key === "Backspace" && !form.entityInput && form.entities.length > 0) {
        const current = getValues("entities");
        setValue("entities", current.slice(0, -1), { shouldDirty: true });
      }
    },
    [appendEntityTokens, form.entities.length, form.entityInput, getValues, setValue]
  );

  const handleEntityInputBlur = useCallback(() => {
    if (!form.entityInput.trim()) return;
    appendEntityTokens(form.entityInput);
    setValue("entityInput", "", { shouldDirty: false });
  }, [appendEntityTokens, form.entityInput, setValue]);

  const handleAddSuggestion = useCallback(
    (suggestion: EntityCandidate) => {
      appendEntityTokens(suggestion.name);
    },
    [appendEntityTokens]
  );

  const entitySummary = useMemo(() => {
    if (!editableEntities.length) {
      return {
        total: 0,
        categorized: 0,
        avgConfidence: null as number | null,
        highConfidence: 0,
      };
    }

    const confidenceValues = editableEntities
      .map((entity) => entity.confidence)
      .filter((confidence): confidence is number => typeof confidence === "number");

    const categorized = editableEntities.filter(
      (entity) => entity.type && entity.type.toLowerCase() !== "entity"
    ).length;

    return {
      total: editableEntities.length,
      categorized,
      avgConfidence: confidenceValues.length
        ? Math.round(
            confidenceValues.reduce((total, confidence) => total + confidence, 0) /
              confidenceValues.length
          )
        : null,
      highConfidence: confidenceValues.filter((confidence) => confidence >= 70).length,
    };
  }, [editableEntities]);

  // Validate the full form (used before submission)
  const validateForm = useCallback(async () => {
    return rhf.trigger();
  }, [rhf]);

  const toggleModelSelection = useCallback(
    (modelKey: string, options?: ModelSelectionOptions) => {
      if ((options?.mode || "single") === "single") {
        setValue("provider", modelKey, { shouldDirty: true });
        setValue("selectedModels", [modelKey], { shouldDirty: true });
        return;
      }

      const currentProvider = getValues("provider");
      let current = getValues("selectedModels");
      if (!current || current.length === 0) {
        current = [currentProvider];
      }

      let next: string[];
      if (current.includes(modelKey)) {
        if (current.length <= 1) return; // prevent deselecting the last model
        next = current.filter((m) => m !== modelKey);
      } else {
        next = [...current, modelKey];
      }

      setValue("selectedModels", next, { shouldDirty: true });

      // Sync the primary provider flag to the first selected model (for backward compat)
      if (!next.includes(getValues("provider"))) {
        setValue("provider", next[0], { shouldDirty: true });
      }
    },
    [getValues, setValue]
  );

  return {
    form,
    resolvedTargetUrl: activeTargetUrl,
    resolvedTargetName: form.targetName.trim(),
    setFormValue,
    manualOverrides,
    setManualOverrides,
    entitySuggestions,
    editableEntities,
    setEditableEntities,
    isAutoDetecting,
    isScanningEntities,
    isCategoryDetecting,
    aiSuggestedCategory,
    isPreflightChecking,
    preflightError,
    preflightVerifiedUrl,
    isPreScanning,
    preScanResult,
    preScanError,
    draftSaveFailed,
    formErrors: formState.errors,
    verifyUrlPreflight,
    validateForm,
    runUrlAutoDetection,
    appendEntityTokens,
    removeEntity,
    handleEntityInputChange,
    handleEntityInputKeyDown,
    handleEntityInputBlur,
    handleAddSuggestion,
    entitySummary,
    toggleModelSelection,
  };
}
