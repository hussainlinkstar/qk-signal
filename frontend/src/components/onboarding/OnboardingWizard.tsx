"use client";

import SignalAlert from "@/components/signal/SignalAlert";
import React, { useEffect, useRef, useState } from "react";
import { Plus } from "lucide-react";
import { useTranslation } from "react-i18next";

import ProjectFormFields from "@/components/onboarding/ProjectSetupFields";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { GLOBAL_TARGET_MARKET, toTargetCountry } from "@/lib/targetMarket";
import { getPlanLockContent } from "@/lib/planLocks";
import type { ProjectCreatePayload } from "@/services/workspaceService";

export type Ga4ConnectContext = {
  /** The project the setup belongs to, so the return can resume it. */
  projectId: number | null;
  /** The step to come back to. */
  step: number;
};

export type Ga4ReturnOutcome = {
  status: "connected" | "error";
  message?: string | null;
};

type OnboardingWizardProps = {
  open: boolean;
  initialStep?: WizardStep;
  /** A project the customer already has, so a resumed wizard can still scan. */
  knownProjectId?: number | null;
  /**
   * Whether the customer's plan includes Competitive Intelligence
   * (`has_competitor_analysis`). SIGV2-1220: the step used to offer the chips
   * to everyone, so Starter and Standard filled them in and were answered
   * with the backend's raw 402 detail. The caller resolves this from the
   * entitlement the API serves (`resolveServedCapability`), which is why the
   * default is permissive: before that payload lands the wizard must not
   * lock out a customer who is in fact entitled.
   */
  canTrackCompetitors?: boolean;
  onClose: () => void;
  onDismiss: () => Promise<void> | void;
  onProjectCreated: (payload: ProjectCreatePayload) => Promise<{ id: number } | null>;
  /**
   * Saves one competitor. Per domain rather than per list on purpose: a batch
   * that fails halfway leaves the caller unable to say what landed, and the
   * retry then re-posts a competitor the project already has, which the API
   * refuses. One call per domain lets the wizard record exactly what is saved
   * and retry only the rest.
   */
  onSaveCompetitor?: (projectId: number, domain: string) => Promise<void>;
  /** Reads the workspace connections endpoint. `connected` when a Google
      (GA4/GSC) OAuth connection exists; `configured` when the deployment holds
      Google OAuth credentials at all - without them no Connect affordance can
      work, so none is shown. A click on Connect must never mark success. */
  onLoadGa4Status?: () => Promise<{ connected: boolean; configured: boolean }>;
  /** Starts the real workspace Google OAuth flow (full-page redirect). */
  onConnectGa4?: (context: Ga4ConnectContext) => void;
  /**
   * What the OAuth return said, when the wizard was reopened by one. It is a
   * report, never an entitlement: `connected` here does not mark the step
   * complete, because only the connections endpoint can confirm a connection
   * (SIGV2-1202). An `error` keeps every bit of progress and surfaces Retry.
   */
  ga4Outcome?: Ga4ReturnOutcome | null;
  onMarkStepComplete: (step: string) => Promise<void>;
  /**
   * Starts the customer's first scan. The approved onboarding's last step runs
   * the scan (mockup: Signal Onboarding.html launches Signal Audit Run.html),
   * so the target the wizard already collected travels with the call and the
   * customer is not asked to fill the same details in again. Omitted when the
   * wizard was resumed and holds no domain of its own; the caller then falls
   * back to what it knows about the project.
   */
  onLaunchAudit: (projectId: number, target?: { url: string; name: string }) => void;
};

type WizardStep = 1 | 2 | 3 | 4 | 5;

const TOTAL_STEPS = 5;
const MAX_COMPETITORS = 5;
const DOMAIN_PATTERN = /^[a-z0-9-]+(\.[a-z0-9-]+)+$/i;

const normalizeDomain = (raw: string) =>
  raw
    .trim()
    .replace(/^https?:\/\//i, "")
    .replace(/\/.*$/, "")
    .replace(/^www\./i, "")
    .toLowerCase();

const STEP_KEYS = [1, 2, 3, 4, 5] as const;

/**
 * Whether a save was refused for want of entitlement rather than failing.
 * The HTTP layer puts the status on the error it throws, and 402 is the
 * backend's plan refusal. Read off the error by shape rather than by class so
 * the wizard does not care which transport raised it; anything else is an
 * ordinary failure and keeps its own message.
 */
const isPlanRefusal = (error: unknown): boolean =>
  typeof error === "object" && error !== null && (error as { status?: unknown }).status === 402;

export default function OnboardingWizard({
  open,
  initialStep = 1,
  knownProjectId = null,
  canTrackCompetitors = true,
  onClose,
  onDismiss,
  onProjectCreated,
  onSaveCompetitor,
  onLoadGa4Status,
  onConnectGa4,
  ga4Outcome = null,
  onMarkStepComplete,
  onLaunchAudit,
}: OnboardingWizardProps) {
  const { t } = useTranslation();
  const [step, setStep] = useState<WizardStep>(initialStep);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const submitInFlightRef = useRef(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [domainInvalid, setDomainInvalid] = useState(false);

  const [projectName, setProjectName] = useState("");
  const [projectDomain, setProjectDomain] = useState("");
  const [projectCountry, setProjectCountry] = useState(GLOBAL_TARGET_MARKET);
  const [projectLanguage, setProjectLanguage] = useState("en");

  const [competitors, setCompetitors] = useState<string[]>([]);
  const [competitorDraft, setCompetitorDraft] = useState<string | null>(null);
  const [competitorError, setCompetitorError] = useState<string | null>(null);
  // Exactly what the API has accepted. A retry posts the difference, so a save
  // that failed halfway never re-posts a competitor the project already has.
  const [savedCompetitors, setSavedCompetitors] = useState<string[]>([]);
  // The plan refused the save while the step was open: the entitlement moved
  // under the customer, or the two surfaces disagreed. Information, not an
  // error, and it never blocks Skip.
  const [competitorsPlanRefused, setCompetitorsPlanRefused] = useState(false);
  const competitorLock = getPlanLockContent("competitiveIntelligence");

  const [createdProjectId, setCreatedProjectId] = useState<number | null>(null);
  const [ga4Connected, setGa4Connected] = useState(false);
  // null = not yet read: no connect affordance until the real state is known.
  const [ga4Configured, setGa4Configured] = useState<boolean | null>(null);
  const ga4MarkedRef = useRef(false);

  // Resume from the persisted onboarding progress whenever the wizard opens,
  // so a refresh continues at the step the customer reached rather than step 1.
  useEffect(() => {
    if (open) {
      setStep(initialStep);
    }
  }, [open, initialStep]);

  // Step 4 reads the real connection state each time it is shown: a Connect
  // click starts OAuth and leaves the app, so connection can only ever be
  // learned from the connections endpoint, never from the click itself.
  useEffect(() => {
    if (!open || step !== 4 || !onLoadGa4Status) return;
    let active = true;
    void onLoadGa4Status()
      .then((status) => {
        if (!active) return;
        setGa4Configured(status.configured);
        if (!status.connected) return;
        setGa4Connected(true);
        if (!ga4MarkedRef.current) {
          ga4MarkedRef.current = true;
          void onMarkStepComplete("connect_integration").catch(() => undefined);
        }
      })
      .catch(() => undefined);
    return () => {
      active = false;
    };
  }, [onLoadGa4Status, onMarkStepComplete, open, step]);

  if (!open) return null;

  const dismissWizard = async () => {
    await onDismiss();
    onClose();
  };

  const scanProjectId = createdProjectId ?? knownProjectId;

  // The domain the wizard collected at step 1, which is the target of the
  // first scan. Undefined on a resumed wizard that starts at step 5 with no
  // domain in state: the caller knows the project and resolves it from there.
  const scanDomain = normalizeDomain(projectDomain);
  const scanTarget = scanDomain
    ? { url: scanDomain, name: projectName.trim() || scanDomain }
    : undefined;

  const handleNext = async () => {
    // Ref guard, not state: two clicks inside the same render batch must not
    // issue two create calls.
    if (submitInFlightRef.current) return;

    if (step === 1) {
      const domain = normalizeDomain(projectDomain);
      if (!DOMAIN_PATTERN.test(domain)) {
        setDomainInvalid(true);
        setFormError(t("onboarding.domainInvalid"));
        return;
      }
      setDomainInvalid(false);
      setFormError(null);
      setProjectDomain(domain);
      if (!projectName.trim()) setProjectName(domain);
      setStep(2);
      return;
    }

    if (step === 2) {
      setFormError(null);
      submitInFlightRef.current = true;
      setIsSubmitting(true);
      try {
        const createdProject = await onProjectCreated({
          name: projectName.trim() || normalizeDomain(projectDomain),
          domain_url: projectDomain.trim() || null,
          target_country: toTargetCountry(projectCountry),
          language: projectLanguage,
        });
        if (!createdProject?.id) {
          throw new Error(t("onboarding.projectIdMissing"));
        }
        setCreatedProjectId(createdProject.id);
        await onMarkStepComplete("first_project");
        setStep(3);
      } catch (error) {
        // The entered values stay in state so a retry does not lose them.
        setFormError(error instanceof Error ? error.message : t("onboarding.createFailed"));
      } finally {
        submitInFlightRef.current = false;
        setIsSubmitting(false);
      }
      return;
    }

    if (step === 3) {
      setStep(4);
      return;
    }

    if (step === 4) {
      setStep(5);
    }
  };

  /**
   * Step 3's Save & continue. Skip is a separate action (`handleNext`) and
   * never reaches this, so an ineligible plan issues no competitor POST at
   * all: that 402, surfaced as a form error, is what used to strand the
   * wizard on this step.
   */
  const handleSaveCompetitors = async () => {
    if (submitInFlightRef.current) return;

    const projectId = createdProjectId ?? knownProjectId;
    const pending = competitors.filter((domain) => !savedCompetitors.includes(domain));
    if (!onSaveCompetitor || !projectId || pending.length === 0) {
      setStep(4);
      return;
    }

    setFormError(null);
    setCompetitorsPlanRefused(false);
    submitInFlightRef.current = true;
    setIsSubmitting(true);
    try {
      for (const domain of pending) {
        await onSaveCompetitor(projectId, domain);
        // Recorded one at a time, so a failure halfway through leaves an
        // accurate picture of what the project already holds.
        setSavedCompetitors((current) =>
          current.includes(domain) ? current : [...current, domain]
        );
      }
      setStep(4);
    } catch (error) {
      if (isPlanRefusal(error)) {
        // A plan restriction is information, not a failed action: the
        // backend's own wording is an internal detail, the project and the
        // entries stay exactly as they are, and Skip carries on.
        setCompetitorsPlanRefused(true);
      } else {
        setFormError(error instanceof Error ? error.message : t("onboarding.competitorsFailed"));
      }
    } finally {
      submitInFlightRef.current = false;
      setIsSubmitting(false);
    }
  };

  const startGa4Connect = () => {
    onConnectGa4?.({ projectId: createdProjectId ?? knownProjectId, step });
  };

  const commitCompetitorDraft = () => {
    if (competitorDraft === null) return;
    const domain = normalizeDomain(competitorDraft);
    if (!domain) {
      // Blurring an empty input just closes it; only real text gets a reason.
      setCompetitorDraft(null);
      setCompetitorError(null);
      return;
    }
    if (!DOMAIN_PATTERN.test(domain)) {
      setCompetitorError(t("onboarding.competitorInvalid"));
      return;
    }
    if (competitors.includes(domain)) {
      setCompetitorError(t("onboarding.competitorDuplicate", { domain }));
      return;
    }
    if (competitors.length >= MAX_COMPETITORS) {
      setCompetitorError(t("onboarding.competitorLimit", { max: MAX_COMPETITORS }));
      return;
    }
    setCompetitors((current) => [...current, domain]);
    setCompetitorDraft(null);
    setCompetitorError(null);
  };

  const nextLabel = step >= 3 ? t("onboarding.skipContinue") : t("onboarding.continue");

  // The competitor step has something to save only on a plan that includes it
  // and with entries the API has not taken yet. That is the single condition
  // for offering Save & continue beside Skip; everywhere else the footer keeps
  // its one approved button.
  // After a plan refusal there is nothing left to save, so the step goes back
  // to a plain skip and the notice explains why.
  const hasCompetitorsToSave =
    step === 3 &&
    canTrackCompetitors &&
    !competitorsPlanRefused &&
    competitors.some((domain) => !savedCompetitors.includes(domain));
  const showCompetitorPlanNotice = step === 3 && (!canTrackCompetitors || competitorsPlanRefused);

  return (
    <div className="mx-auto w-full max-w-[640px]" data-testid="onboarding-wizard">
      <div className="mb-4 flex items-center gap-[14px]">
        <div className="flex h-[46px] w-[46px] flex-none items-center justify-center rounded-[13px] bg-(--purple-a10) text-(--purple)">
          <svg
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            aria-hidden="true"
            className="h-[23px] w-[23px] [stroke-width:1.9]"
          >
            <path d="M12 2l3 7h7l-5.5 4.5L18 21l-6-4-6 4 1.5-7.5L2 9h7z" />
          </svg>
        </div>
        <div className="min-w-0 flex-1">
          <h1 className="m-0 font-(family-name:--disp) text-[24px] leading-8 font-extrabold tracking-[-0.02em]">
            {t("onboarding.title")}
          </h1>
          <div className="mt-[3px] max-w-[640px] text-[13px] leading-[1.5] text-(--t-2)">
            {t(`onboarding.stepLabel${step}`)}
          </div>
        </div>
        <button
          type="button"
          className="flex-none self-start font-mono text-[11px] font-medium uppercase tracking-[0.12em] text-(--t-2) transition-colors hover:text-(--t-1)"
          onClick={() => {
            void dismissWizard();
          }}
        >
          {t("onboarding.setUpLater")}
        </button>
      </div>

      <div className="mb-[18px] flex gap-2" aria-hidden="true">
        {STEP_KEYS.map((key) => (
          <i
            key={key}
            className={`h-1 flex-1 rounded-full ${key <= step ? "bg-(--indigo)" : "bg-(--line)"}`}
          />
        ))}
      </div>

      {formError ? (
        <SignalAlert tone="danger" title={t("alerts.errorTitle")} className="mb-4">
          {formError}
        </SignalAlert>
      ) : null}

      {step === 1 ? (
        <section className="rounded-[22px] border-0 bg-white px-[22px] py-5">
          <h3 className="m-0 mb-[3px] font-(family-name:--disp) text-[14.5px] leading-[19px] font-bold">
            {t("onboarding.step1Title")}
          </h3>
          <div className="mb-4 text-[12.5px] leading-[16px] text-(--t-3)">
            {t("onboarding.step1Sub")}
          </div>
          <ProjectFormFields
            variant="wizard"
            fields={["domain"]}
            values={{
              name: projectName,
              domain: projectDomain,
              market: projectCountry,
              language: projectLanguage,
            }}
            domainInvalid={domainInvalid}
            disabled={isSubmitting}
            onChange={(key, value) => {
              if (key === "domain") {
                setProjectDomain(value);
                setDomainInvalid(false);
              }
            }}
          />
        </section>
      ) : null}

      {step === 2 ? (
        <section className="rounded-[22px] border-0 bg-white px-[22px] py-5">
          <h3 className="m-0 mb-[3px] font-(family-name:--disp) text-[14.5px] leading-[19px] font-bold">
            {t("onboarding.step2Title")}
          </h3>
          <div className="mb-4 text-[12.5px] leading-[16px] text-(--t-3)">
            {t("onboarding.step2Sub")}
          </div>
          <div className="flex flex-col gap-4">
            <ProjectFormFields
              variant="wizard"
              fields={["market", "language"]}
              values={{
                name: projectName,
                domain: projectDomain,
                market: projectCountry,
                language: projectLanguage,
              }}
              disabled={isSubmitting}
              onChange={(key, value) => {
                if (key === "market") setProjectCountry(value);
                if (key === "language") setProjectLanguage(value);
              }}
            />
          </div>
        </section>
      ) : null}

      {step === 3 ? (
        <section className="rounded-[22px] border-0 bg-white px-[22px] py-5">
          <h3 className="m-0 mb-[3px] font-(family-name:--disp) text-[14.5px] leading-[19px] font-bold">
            {t("onboarding.step3Title")}
          </h3>
          <div className="mb-4 text-[12.5px] leading-[16px] text-(--t-3)">
            {t("onboarding.step3Sub")}
          </div>
          {showCompetitorPlanNotice ? (
            // SIGV2-1171's MVP alert presentation. A plan restriction is
            // information about the plan, so it reads as a notice rather than
            // as something the customer did wrong, and it does not block the
            // step: Skip in the footer carries on to Google Analytics.
            <Alert variant="brand" className="mb-[10px]">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" aria-hidden="true">
                <circle cx="12" cy="12" r="9" />
                <path d="M12 11v5M12 8h.01" strokeLinecap="round" />
              </svg>
              <AlertTitle>
                {t("onboarding.competitorsPlanTitle", { plan: competitorLock.requiredPlanLabel })}
              </AlertTitle>
              <AlertDescription>{t("onboarding.competitorsPlanBody")}</AlertDescription>
            </Alert>
          ) : null}
          {/* No chips on a plan without the capability: nothing offered means
              nothing the API can refuse. */}
          {canTrackCompetitors ? (
            <div className="mb-[10px] flex flex-wrap gap-2">
              {competitors.map((domain) => (
                <span
                  key={domain}
                  className="inline-flex h-8 items-center gap-2 rounded-full border-0 pl-[10px] pr-[6px] text-[13px] font-semibold"
                >
                  {domain}
                  <button
                    type="button"
                    aria-label={t("onboarding.removeCompetitor", { domain })}
                    className="flex h-[18px] w-[18px] items-center justify-center rounded-full bg-(--line-2) text-(--t-3)"
                    onClick={() =>
                      setCompetitors((current) => current.filter((item) => item !== domain))
                    }
                  >
                    ×
                  </button>
                </span>
              ))}
              {competitors.length < MAX_COMPETITORS ? (
                competitorDraft === null ? (
                  <button
                    type="button"
                    className="inline-flex h-8 cursor-pointer items-center gap-1.5 rounded-full border border-dashed border-(--line) px-[10px] text-[13px] font-semibold text-(--t-2)"
                    onClick={() => setCompetitorDraft("")}
                  >
                    <Plus className="h-3.5 w-3.5" strokeWidth={2.25} aria-hidden="true" />
                    {t("onboarding.addCompetitor")}
                  </button>
                ) : (
                  <input
                    type="text"
                    autoFocus
                    className="field-focus-ring h-8 min-w-0 flex-1 rounded-full border-0 bg-[#EEF1F6] px-[10px] text-[13px] text-(--t-1) outline-none placeholder:text-(--t-3) focus:border-[#c7cdd6]"
                    placeholder={t("onboarding.competitorPlaceholder")}
                    value={competitorDraft}
                    disabled={isSubmitting}
                    onChange={(event) => {
                      setCompetitorDraft(event.target.value);
                      setCompetitorError(null);
                    }}
                    onBlur={commitCompetitorDraft}
                    onKeyDown={(event) => {
                      if (event.key === "Enter") {
                        event.preventDefault();
                        commitCompetitorDraft();
                      }
                      if (event.key === "Escape") {
                        setCompetitorDraft(null);
                        setCompetitorError(null);
                      }
                    }}
                  />
                )
              ) : null}
            </div>
          ) : null}
          {competitorError ? (
            <div role="alert" className="mb-[10px] text-[12px] text-(--bad)">
              {competitorError}
            </div>
          ) : null}
          <div className="text-[12px] text-(--t-3)">{t("onboarding.step3Note")}</div>
        </section>
      ) : null}

      {step === 4 ? (
        <section className="rounded-[22px] border-0 bg-white px-[22px] py-5">
          <h3 className="m-0 mb-[3px] font-(family-name:--disp) text-[14.5px] leading-[19px] font-bold">
            {t("onboarding.step4Title")}
          </h3>
          <div className="mb-4 text-[12.5px] leading-[16px] text-(--t-3)">
            {t("onboarding.step4Sub")}
          </div>
          <div className="mb-3 flex items-start gap-2 rounded-[14px] border-0 bg-[#F7F8FA] bg-(--blue-s) px-3 py-2.5 text-[12.5px] leading-[1.5] text-(--t-2)">
            <svg
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              aria-hidden="true"
              className="mt-[1px] h-4 w-4 flex-none text-(--blue)"
            >
              <circle cx="12" cy="12" r="9" />
              <path d="M12 11v5M12 8h.01" strokeLinecap="round" />
            </svg>
            <div>{t("onboarding.ga4Privacy")}</div>
          </div>
          {/* SIGV2-1220: the OAuth return reports what happened. A refusal, a
              cancellation or a provider error changed nothing, so it is said
              plainly, the progress is untouched, and Retry sits with the
              action it retries. Skip stays in the footer either way. */}
          {ga4Outcome?.status === "error" ? (
            <Alert variant="warning" className="mb-3">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" aria-hidden="true">
                <path d="M12 9v4M12 17h.01" strokeLinecap="round" />
                <path d="M10.3 3.9 2.4 18a1.8 1.8 0 0 0 1.6 2.7h16a1.8 1.8 0 0 0 1.6-2.7L13.7 3.9a1.8 1.8 0 0 0-3.1 0Z" />
              </svg>
              <AlertDescription>
                {ga4Outcome.message
                  ? t("onboarding.ga4FailedReason", { reason: ga4Outcome.message })
                  : t("onboarding.ga4Failed")}
              </AlertDescription>
            </Alert>
          ) : null}
          {ga4Configured === false ? (
            <div className="text-[12.5px] leading-[1.5] text-(--t-3)">
              {t("onboarding.ga4NotConfigured")}
            </div>
          ) : ga4Configured === null && onLoadGa4Status ? null : (
            <button
              type="button"
              className="inline-flex h-[38px] cursor-pointer items-center gap-2 rounded-full border-0 bg-[#EEF1F6] px-[15px] font-(family-name:--body-font) text-[13.5px] font-semibold text-(--t-1) transition-colors hover:bg-[#E8ECF3] disabled:cursor-not-allowed disabled:opacity-60"
              disabled={ga4Connected || !onConnectGa4}
              onClick={startGa4Connect}
            >
              {ga4Connected
                ? t("onboarding.ga4Connected")
                : ga4Outcome?.status === "error"
                  ? t("onboarding.ga4Retry")
                  : t("onboarding.connectGa4")}
            </button>
          )}
          {/* A granted account and a chosen property are two different facts.
              The wizard only ever learns the first, so it says so rather than
              implying traffic data is already flowing. */}
          {ga4Connected ? (
            <div className="mt-[10px] text-[12px] leading-[1.5] text-(--t-3)">
              {t("onboarding.ga4PropertyPending")}
            </div>
          ) : null}
          <div className="mt-[10px] text-[12px] text-(--t-3)">{t("onboarding.step4Note")}</div>
        </section>
      ) : null}

      {step === 5 ? (
        <section className="rounded-[22px] border-0 bg-white px-[22px] py-5">
          <h3 className="m-0 mb-[3px] font-(family-name:--disp) text-[14.5px] leading-[19px] font-bold">
            {t("onboarding.step5Title")}
          </h3>
          <div className="mb-4 text-[12.5px] leading-[16px] text-(--t-3)">
            {t("onboarding.step5Sub")}
          </div>
          <p className="m-0 text-[12px] text-(--t-3)">{t("onboarding.step5Note")}</p>
          <div className="mt-2 flex items-center gap-[10px]">
            <button
              type="button"
              className="inline-flex h-[38px] cursor-pointer items-center gap-2 rounded-full border-0 bg-[#111827] px-[15px] font-(family-name:--body-font) text-[13.5px] font-semibold text-white transition-colors hover:bg-black disabled:cursor-not-allowed disabled:opacity-60"
              disabled={!scanProjectId}
              onClick={() => {
                if (scanProjectId) {
                  onLaunchAudit(scanProjectId, scanTarget);
                }
                onClose();
              }}
            >
              {t("onboarding.runFirstScan")}
            </button>
            <button
              type="button"
              className="inline-flex h-[38px] cursor-pointer items-center gap-2 rounded-full px-[15px] font-(family-name:--body-font) text-[13.5px] font-semibold text-(--t-2) transition-colors hover:text-(--t-1)"
              onClick={() => {
                void dismissWizard();
              }}
            >
              {t("onboarding.skipToDashboard")}
            </button>
          </div>
        </section>
      ) : null}

      <div className="mt-[18px] flex justify-between gap-[10px]">
        <button
          type="button"
          className="inline-flex h-[38px] cursor-pointer items-center gap-2 rounded-full border-0 bg-[#EEF1F6] px-[15px] font-(family-name:--body-font) text-[13.5px] font-semibold text-(--t-1) transition-colors hover:bg-[#E8ECF3] disabled:cursor-not-allowed disabled:opacity-60"
          disabled={step === 1 || isSubmitting}
          onClick={() => {
            setFormError(null);
            setStep((current) => Math.max(1, current - 1) as WizardStep);
          }}
        >
          {t("onboarding.back")}
        </button>
        {/* SIGV2-1220: Skip and Save are two different requests, so they are
            two different buttons. They only separate on the competitor step
            with something to save; every other step keeps the single approved
            action, and this branch renders exactly the markup it always did so
            no other screen moves. */}
        {step < TOTAL_STEPS ? (
          hasCompetitorsToSave ? (
            <div className="flex gap-[10px]">
              <button
                type="button"
                className="inline-flex h-[38px] cursor-pointer items-center gap-2 rounded-full border-0 bg-[#EEF1F6] px-[15px] font-(family-name:--body-font) text-[13.5px] font-semibold text-(--t-1) transition-colors hover:bg-[#E8ECF3] disabled:cursor-not-allowed disabled:opacity-60"
                disabled={isSubmitting}
                onClick={() => {
                  void handleNext();
                }}
              >
                {t("onboarding.skip")}
              </button>
              <button
                type="button"
                className="inline-flex h-[38px] cursor-pointer items-center gap-2 rounded-full border-0 bg-[#111827] px-[15px] font-(family-name:--body-font) text-[13.5px] font-semibold text-white transition-colors hover:bg-black disabled:cursor-not-allowed disabled:opacity-60"
                disabled={isSubmitting}
                onClick={() => {
                  void handleSaveCompetitors();
                }}
              >
                {isSubmitting ? t("onboarding.working") : t("onboarding.saveContinue")}
              </button>
            </div>
          ) : (
            <button
              type="button"
              className="inline-flex h-[38px] cursor-pointer items-center gap-2 rounded-full border-0 bg-[#111827] px-[15px] font-(family-name:--body-font) text-[13.5px] font-semibold text-white transition-colors hover:bg-black disabled:cursor-not-allowed disabled:opacity-60"
              disabled={isSubmitting}
              onClick={() => {
                void handleNext();
              }}
            >
              {isSubmitting ? t("onboarding.working") : nextLabel}
            </button>
          )
        ) : null}
      </div>
    </div>
  );
}
