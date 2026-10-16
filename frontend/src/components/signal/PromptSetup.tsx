"use client";

import Link from "next/link";
import React, { useState } from "react";
import { useTranslation } from "react-i18next";
import { Plus } from "lucide-react";

import SignalAddPromptModal from "@/components/signal/SignalAddPromptModal";
import SignalInlineNote from "@/components/signal/SignalInlineNote";
import {
  SEARCH_TYPE_DESCRIPTIONS,
  SEARCH_TYPE_LABELS,
  VISIBILITY_PROVIDER_LABELS,
  offeredVisibilityProviders,
} from "@/components/dashboard/visibilityUtils";
import type { ScanPromptsState } from "@/hooks/useScanPrompts";
import {
  createVisibilityQuery,
  deleteVisibilityQuery,
  generateBaseVisibilityPrompts,
  updateVisibilityQuery,
} from "@/services/monitoringService";
import { cx } from "@/components/ui/utils";
import { SEARCH_TYPES } from "@/types/monitoring";
import type { SearchTypeId, VisibilityQuery } from "@/types/monitoring";

/**
 * The approved prompt-setup surface (mockup: prompt-setup.js / prompt-setup.css,
 * SIGV2-1194), one component in two modes: `scan` sits inside the start-scan
 * page's Prompts section, `manage` is the Prompts tab on the AIO detail page.
 * Both read the project's own prompt list and coverage, so what a scan will
 * measure and what the Prompts tab shows can never disagree.
 *
 * Two deliberate deviations from the mockup, both approved:
 *
 * - **no live type prediction.** The mockup guesses the search type as the
 *   customer types, using its own local classifier. A second classifier here
 *   would drift from `suggest_search_type` on the backend and the two would
 *   disagree, so instead the copy says Signal assigns the type from the
 *   wording and the row shows the assigned type once saved (SIGV2-1197). The
 *   remedy for a wrong type is rewording the question, which Edit does.
 * - **"Add your own" opens the existing dialog**, not the mockup's bare
 *   textarea: creation has to carry the plan-cap refusal and the engine
 *   selection, which live in `SignalAddPromptModal` and nowhere else.
 *
 * Removal exists only in manage mode, behind the spec's two-step confirm. In
 * scan mode a row can be reworded but never removed, so two runs of the same
 * project cannot quietly measure different prompt sets.
 */

export type PromptSetupProjectContext = {
  name?: string | null;
  domain_url?: string | null;
  target_country?: string | null;
  language?: string | null;
};

type PromptSetupProps = {
  mode: "scan" | "manage";
  /** The project's prompt list state; `useScanPrompts` serves both modes. */
  state: ScanPromptsState;
  /** The project's own details for the context line; absent fields are omitted. */
  project?: PromptSetupProjectContext | null;
  getAuthHeaders: () => Promise<HeadersInit>;
};

const DOMAIN_STRIP = /^https?:\/\/(www\.)?/;

const BTN =
  "inline-flex h-[32px] cursor-pointer items-center gap-1.5 rounded-full border-0 bg-[#EEF1F6] px-[13px] font-(family-name:--body-font) text-[12.5px] font-semibold text-(--t-1) hover:bg-[#E8ECF3] disabled:cursor-not-allowed disabled:opacity-50";
const BTN_GHOST =
  "inline-flex h-[30px] cursor-pointer items-center rounded-full border-0 bg-[#EEF1F6] px-[11px] font-(family-name:--body-font) text-[12px] font-semibold text-(--t-1) hover:bg-[#E8ECF3] disabled:cursor-not-allowed disabled:opacity-50";
const BTN_DANGER =
  "inline-flex h-[30px] cursor-pointer items-center rounded-full border-0 bg-[#FEECEC] px-[11px] font-(family-name:--body-font) text-[12px] font-semibold text-(--bad) hover:bg-[#FCDADA] disabled:cursor-not-allowed disabled:opacity-50";
const BTN_PRIMARY =
  "inline-flex h-[34px] cursor-pointer items-center gap-1.5 rounded-full border-0 bg-[#111827] px-[15px] font-(family-name:--body-font) text-[12px] font-semibold text-white hover:bg-black disabled:cursor-not-allowed disabled:opacity-50";
const CAPTION = "m-0 text-[12px] leading-[1.7] text-(--t-2)";

export default function PromptSetup({ mode, state, project, getAuthHeaders }: PromptSetupProps) {
  const { t } = useTranslation();
  const {
    projectId,
    prompts,
    coverage,
    entitlements,
    canAddPrompt,
    isPlanLocked,
    isLoading,
    error,
  } = state;
  const manage = mode === "manage";

  // The prompt being reworded; Edit expands the inline editor at the foot,
  // matching the mockup's `.prompt-editor` placement.
  const [editing, setEditing] = useState<VisibilityQuery | null>(null);
  const [editText, setEditText] = useState("");
  const [editError, setEditError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  // The row waiting on its second Remove press, per the spec's two-step
  // confirm: the row itself becomes the confirm.
  const [confirmingRemoveId, setConfirmingRemoveId] = useState<number | null>(null);
  const [addOpen, setAddOpen] = useState(false);
  const [feedback, setFeedback] = useState("");
  // The mockup seeds the first canonical type open (`new Set(['brand'])`) so
  // the set reads as a list rather than a stack of closed headings; empty
  // groups also open by default. Open state survives the reload after an
  // action, tracked by type id.
  const [openGroups, setOpenGroups] = useState<Set<string>>(new Set([SEARCH_TYPES[0]]));

  const typed = (id: SearchTypeId) => prompts.filter((prompt) => prompt.search_type === id);
  const pendingPrompts = prompts.filter(
    (prompt) => !prompt.search_type || !SEARCH_TYPES.includes(prompt.search_type)
  );
  const coveredCount = coverage.filter((entry) => entry.covered).length;
  const totalTypes = coverage.length || SEARCH_TYPES.length;
  const complete = coveredCount >= totalTypes && prompts.length > 0;
  const allGenerated = prompts.length > 0 && prompts.every((prompt) => prompt.is_generated);

  const contextParts = [
    project?.name ?? null,
    project?.domain_url ? project.domain_url.replace(DOMAIN_STRIP, "").replace(/\/$/, "") : null,
    project?.target_country ?? null,
    project?.language ?? null,
  ].filter((part): part is string => Boolean(part));

  const coverageEntry = (id: SearchTypeId) => coverage.find((entry) => entry.id === id);

  const headers = async () => (await getAuthHeaders()) as Record<string, string>;

  const finish = async (message: string) => {
    setFeedback(message);
    setEditing(null);
    setConfirmingRemoveId(null);
    await state.reload();
  };

  const handleSaveEdit = async () => {
    if (!editing || projectId === null) return;
    const text = editText.trim().replace(/\s+/g, " ");
    if (text.length < 10) {
      setEditError(t("promptSetup.errorTooShort"));
      return;
    }
    if (
      prompts.some(
        (prompt) =>
          prompt.id !== editing.id && prompt.query_text.toLowerCase() === text.toLowerCase()
      )
    ) {
      setEditError(t("promptSetup.errorDuplicate"));
      return;
    }
    setBusy(true);
    setEditError(null);
    try {
      await updateVisibilityQuery(projectId, editing.id, { query_text: text }, await headers());
      await finish(t("promptSetup.feedbackSaved"));
    } catch (err) {
      setEditError(err instanceof Error && err.message ? err.message : t("promptSetup.failed"));
    } finally {
      setBusy(false);
    }
  };

  const handleAddStarter = async (typeId: SearchTypeId) => {
    const suggested = coverageEntry(typeId)?.suggested_prompt;
    if (!suggested || projectId === null) return;
    setBusy(true);
    try {
      await createVisibilityQuery(
        projectId,
        {
          query_text: suggested,
          query_type: "aeo",
          // SIGV2-1215: a starter prompt is never created against a
          // withdrawn engine.
          providers: offeredVisibilityProviders(entitlements?.allowed_providers).slice(0, 1),
          search_type: typeId,
        },
        await headers()
      );
      setOpenGroups((current) => new Set(current).add(typeId));
      await finish(t("promptSetup.feedbackStarter", { type: SEARCH_TYPE_LABELS[typeId] }));
    } catch (err) {
      setFeedback(err instanceof Error && err.message ? err.message : t("promptSetup.failed"));
    } finally {
      setBusy(false);
    }
  };

  const handleFillGaps = async () => {
    if (projectId === null) return;
    setBusy(true);
    try {
      await generateBaseVisibilityPrompts(projectId, await headers());
      await finish(t("promptSetup.feedbackFilled"));
    } catch (err) {
      setFeedback(err instanceof Error && err.message ? err.message : t("promptSetup.failed"));
    } finally {
      setBusy(false);
    }
  };

  const providerLabel = (provider: string) =>
    VISIBILITY_PROVIDER_LABELS[provider as keyof typeof VISIBILITY_PROVIDER_LABELS] ?? provider;

  // The first engine the plan measures is the same default starter prompts
  // are created against, so re-pointing a dead prompt lands where every other
  // prompt already measures.
  const rosterDefault = offeredVisibilityProviders(entitlements?.allowed_providers)[0] ?? null;

  const handleRepoint = async (query: VisibilityQuery) => {
    if (projectId === null || rosterDefault === null) return;
    setBusy(true);
    try {
      await updateVisibilityQuery(
        projectId,
        query.id,
        { providers: [rosterDefault] },
        await headers()
      );
      await finish(t("promptSetup.feedbackRepointed", { engine: providerLabel(rosterDefault) }));
    } catch (err) {
      setFeedback(err instanceof Error && err.message ? err.message : t("promptSetup.failed"));
    } finally {
      setBusy(false);
    }
  };

  const handleRemove = async (query: VisibilityQuery) => {
    if (projectId === null) return;
    setBusy(true);
    try {
      await deleteVisibilityQuery(projectId, query.id, await headers());
      await finish(t("promptSetup.feedbackRemoved"));
    } catch (err) {
      setFeedback(err instanceof Error && err.message ? err.message : t("promptSetup.failed"));
    } finally {
      setBusy(false);
    }
  };

  const startEdit = (query: VisibilityQuery) => {
    setEditing(query);
    setEditText(query.query_text);
    setEditError(null);
    setConfirmingRemoveId(null);
  };

  const renderGroup = (typeId: SearchTypeId | "pending") => {
    const isPending = typeId === "pending";
    const items = isPending ? pendingPrompts : typed(typeId as SearchTypeId);
    const label = isPending
      ? t("promptSetup.pendingTitle")
      : SEARCH_TYPE_LABELS[typeId as SearchTypeId];
    const help = isPending
      ? t("promptSetup.pendingHelp")
      : SEARCH_TYPE_DESCRIPTIONS[typeId as SearchTypeId];
    const suggested = !isPending ? coverageEntry(typeId as SearchTypeId)?.suggested_prompt : null;
    const isOpen = openGroups.has(typeId) || items.length === 0;

    return (
      <details
        key={typeId}
        open={isOpen}
        onToggle={(event) => {
          const open = (event.target as HTMLDetailsElement).open;
          setOpenGroups((current) => {
            const next = new Set(current);
            if (open) next.add(typeId);
            else next.delete(typeId);
            return next;
          });
        }}
        className="group border-t border-t-(--line) first:border-t-0"
        data-prompt-group={typeId}
      >
        <summary className="flex cursor-pointer list-none items-center gap-2.5 px-3.5 py-3.5 group-open:bg-(--paper) [&::-webkit-details-marker]:hidden">
          <div className="min-w-0 flex-1">
            <strong className="block font-(family-name:--disp) text-[13px] font-bold text-(--t-1)">
              {label}
            </strong>
            <span className="mt-[3px] block text-[11.5px] leading-[1.55] text-(--t-2)">{help}</span>
          </div>
          <span
            className={cx(
              "flex-none rounded-[5px] px-[7px] py-[5px] font-(family-name:--mono) text-[10px] font-medium",
              items.length === 0 ? "bg-(--warn-s) text-[#8A4A12]" : "bg-(--paper) text-(--t-2)"
            )}
          >
            {items.length === 0
              ? t("promptSetup.noPrompts")
              : t("promptSetup.count", { count: items.length })}
          </span>
          <span
            aria-hidden="true"
            className="w-3 flex-none text-center text-[18px] text-(--t-3) transition-transform group-open:rotate-45"
          >
            +
          </span>
        </summary>
        <div className="px-3.5 pb-3">
          {isPending ? (
            <p className={cx(CAPTION, "mt-1")}>{t("promptSetup.pendingNotScored")}</p>
          ) : null}
          {items.map((item) => (
            <div
              key={item.id}
              className="flex items-start gap-3 border-t border-t-(--line-2) py-3.5 pb-2.5 first:border-t-0"
            >
              {manage && confirmingRemoveId === item.id ? (
                <div className="flex-1 text-[12px] leading-[1.6] text-(--t-2)">
                  <p className="m-0">{t("promptSetup.removeConfirm")}</p>
                  <div className="mt-2 flex gap-2">
                    <button
                      type="button"
                      className={BTN_GHOST}
                      onClick={() => setConfirmingRemoveId(null)}
                    >
                      {t("promptSetup.keep")}
                    </button>
                    <button
                      type="button"
                      className={BTN_DANGER}
                      disabled={busy}
                      onClick={() => void handleRemove(item)}
                    >
                      {t("promptSetup.removeConfirmAction")}
                    </button>
                  </div>
                </div>
              ) : (
                <>
                  <div className="min-w-0 flex-1">
                    <p className="m-0 mb-[5px] text-[12.5px] leading-[1.65] text-(--t-1) wrap-anywhere">
                      {item.query_text}
                    </p>
                    <span className="text-[10px] text-(--t-2)">
                      {item.is_generated
                        ? t("promptSetup.originSignal")
                        : t("promptSetup.originYou")}
                      {/* SIGV2-1188: a downgrade suspends prompts past the cap
                          instead of deleting them; say so rather than showing a
                          prompt that will never be measured again. */}
                      {item.exceeds_plan_cap ? ` · ${t("promptSetup.notMeasuredOnPlan")}` : ""}
                      {/* A prompt pinned to an engine the plan roster stopped
                          measuring (SIGV2-1216 narrowed Specialist) is never
                          re-measured. Name the dead engine instead of letting
                          the row read as a live prompt that silently returns
                          nothing. */}
                      {item.unmeasured_providers?.length
                        ? ` · ${t("promptSetup.engineNotMeasured", {
                            engines: item.unmeasured_providers.map(providerLabel).join(", "),
                          })}`
                        : ""}
                    </span>
                  </div>
                  <div className="flex flex-none gap-1">
                    {/* The repair path for a fully dead prompt: one click
                        re-points it at the engine every prompt on this plan
                        already measures on. Half-dead prompts still measure,
                        so they get the note without the button. */}
                    {item.is_active &&
                    item.providers.length === 0 &&
                    (item.unmeasured_providers?.length ?? 0) > 0 &&
                    rosterDefault !== null ? (
                      <button
                        type="button"
                        className={BTN_GHOST}
                        disabled={busy}
                        aria-label={`${t("promptSetup.measureOn", { engine: providerLabel(rosterDefault) })}: ${item.query_text}`}
                        onClick={() => void handleRepoint(item)}
                      >
                        {t("promptSetup.measureOn", { engine: providerLabel(rosterDefault) })}
                      </button>
                    ) : null}
                    <button
                      type="button"
                      className={BTN_GHOST}
                      aria-label={`${t("promptSetup.edit")}: ${item.query_text}`}
                      onClick={() => startEdit(item)}
                    >
                      {t("promptSetup.edit")}
                    </button>
                    {manage ? (
                      <button
                        type="button"
                        className={BTN_DANGER}
                        aria-label={`${t("promptSetup.remove")}: ${item.query_text}`}
                        onClick={() => setConfirmingRemoveId(item.id)}
                      >
                        {t("promptSetup.remove")}
                      </button>
                    ) : null}
                  </div>
                </>
              )}
            </div>
          ))}
          {items.length === 0 && !isPending ? (
            <>
              <p className={cx(CAPTION, "mt-1")}>{t("promptSetup.groupEmpty")}</p>
              {suggested && canAddPrompt ? (
                <button
                  type="button"
                  className={`${BTN} mt-2`}
                  disabled={busy}
                  onClick={() => void handleAddStarter(typeId as SearchTypeId)}
                >
                  {t("promptSetup.addStarter", { type: label.toLowerCase() })}
                </button>
              ) : null}
            </>
          ) : null}
        </div>
      </details>
    );
  };

  // The three states where there is no list to show, stated rather than
  // styled as a refusal: still reading, the read failed, or the plan permits
  // no prompts at all. Scan mode intercepts the same states in its wrapper
  // before this renders.
  const unavailableReason = isLoading
    ? t("signalStartCheck.prompts.loading")
    : error
      ? t("signalStartCheck.prompts.unavailable")
      : isPlanLocked
        ? entitlements?.plan_label || entitlements?.plan
          ? t("signalAddPrompt.locked", {
              plan: entitlements.plan_label || entitlements.plan,
            })
          : t("signalAddPrompt.lockedUnknownPlan")
        : null;

  if (unavailableReason !== null) {
    return (
      <p className="m-0 text-xs leading-[1.5] text-(--t-3)" role="status">
        {unavailableReason}
      </p>
    );
  }

  return (
    <div>
      {/* Heading row: title, intro, and the starter-set badge that flips once
          the customer has made the set their own. */}
      <div className="mb-1 flex items-start justify-between gap-4 max-[1100px]:flex-wrap">
        <div>
          <h3 className="m-0 mb-1.5 font-(family-name:--disp) text-[19px] font-bold text-(--t-1)">
            {t(manage ? "promptSetup.manageTitle" : "promptSetup.scanTitle")}
          </h3>
          <p className="m-0 mb-4 max-w-[650px] text-[12.5px] leading-[1.65] text-(--t-2)">
            {t(
              manage
                ? allGenerated
                  ? "promptSetup.manageIntro"
                  : "promptSetup.manageIntroCustomised"
                : "promptSetup.scanIntro"
            )}
          </p>
        </div>
        <span className="flex-none rounded-full border-0 bg-[#F5F3FF] px-2.5 py-[5px] text-[10px] font-semibold whitespace-nowrap text-[#7C3AED]">
          {t(allGenerated ? "promptSetup.badgeStarter" : "promptSetup.badgeProject")}
        </span>
      </div>

      {/* Summary + context: how ready the set is, and what it was derived
          from. The context line only carries fields the project payload
          actually has; nothing is invented. */}
      <div
        className={cx(
          "flex flex-wrap items-center justify-between gap-2.5 rounded-[10px] border px-3.5 py-3 text-[12px]",
          complete
            ? "border-[#CEE9D7] bg-(--good-s) text-[#18683B]"
            : "border-[#EADABB] bg-(--warn-s) text-[#795113]"
        )}
      >
        <strong className="font-semibold">
          {t("promptSetup.summaryReady", { count: prompts.length })}
        </strong>
        <span>
          {t("promptSetup.summaryCoverage", { covered: coveredCount, total: totalTypes })}
        </span>
      </div>
      {contextParts.length > 0 ? (
        <p className="mx-0 my-3 font-(family-name:--mono) text-[10px] leading-[1.6] text-(--t-2)">
          {contextParts.join(" · ")}
        </p>
      ) : null}
      <p className={cx(CAPTION, "my-2.5")}>{t("promptSetup.captionSorted")}</p>

      {/* The two incomplete notices: prompts but a gap, or nothing at all. In
          scan mode "nothing at all" is the one state that stops the launch,
          so it keeps the danger note. */}
      {prompts.length === 0 ? (
        mode === "scan" ? (
          <SignalInlineNote tone="danger">
            {t("signalStartCheck.prompts.required")}
          </SignalInlineNote>
        ) : (
          <SignalInlineNote tone="warning">{t("promptSetup.noticeEmpty")}</SignalInlineNote>
        )
      ) : !complete ? (
        <SignalInlineNote tone="info">{t("promptSetup.noticeGap")}</SignalInlineNote>
      ) : null}

      <div className="mx-0 mt-3.5 mb-4 overflow-hidden rounded-[12px] border-0">
        {SEARCH_TYPES.map((typeId) => renderGroup(typeId))}
        {pendingPrompts.length > 0 ? renderGroup("pending") : null}
      </div>

      {/* Actions: add your own through the existing dialog, fill every gap at
          once through generate-base, and the per-mode link to the other
          surface. */}
      <div className="mt-3.5 mb-1.5 flex flex-wrap items-center gap-3">
        {projectId !== null && !isPlanLocked ? (
          <button
            type="button"
            className={BTN}
            disabled={!canAddPrompt || busy}
            onClick={() => setAddOpen(true)}
            data-add-prompt=""
          >
            <Plus className="h-[15px] w-[15px]" strokeWidth={2} aria-hidden="true" />
            {t("promptSetup.addOwn")}
          </button>
        ) : null}
        {prompts.length === 0 || !complete ? (
          <button
            type="button"
            className={BTN}
            disabled={!canAddPrompt || busy || projectId === null}
            onClick={() => void handleFillGaps()}
          >
            {t("promptSetup.fillGaps")}
          </button>
        ) : null}
        {mode === "scan" && projectId !== null ? (
          <Link
            href={`/dashboard/projects/${projectId}/ai-answers?tab=prompts`}
            className="text-[11.5px] text-[#7040B5] underline underline-offset-[3px]"
          >
            {t("promptSetup.manageAll")}
          </Link>
        ) : null}
        {manage ? (
          <Link
            href={`/dashboard/audit?projectId=${projectId}`}
            className="text-[11.5px] text-[#7040B5] underline underline-offset-[3px]"
          >
            {t("promptSetup.reviewScan")}
          </Link>
        ) : null}
      </div>

      <p className={cx(CAPTION, "my-2.5")}>
        {t(manage ? "promptSetup.closingManage" : "promptSetup.closingScan")}
      </p>
      <p
        role="status"
        tabIndex={-1}
        className={cx("m-0 my-2 text-[12px] leading-[1.6] text-(--good)", !feedback && "hidden")}
        data-prompt-feedback=""
      >
        {feedback}
      </p>

      {editing ? (
        <form
          className="mt-4 rounded-[12px] border-0 bg-[#EEF1F6] p-[18px]"
          noValidate
          onSubmit={(event) => {
            event.preventDefault();
            void handleSaveEdit();
          }}
        >
          <h4 className="m-0 font-(family-name:--disp) text-[14px] font-bold text-(--t-1)">
            {t("promptSetup.editorEditTitle")}
          </h4>
          <p className={cx(CAPTION, "mt-1")}>{t("promptSetup.editorIntro")}</p>
          <label className="mt-3 block" htmlFor="prompt-setup-editor">
            <span className="mb-1.5 block font-(family-name:--mono) text-[10.5px] uppercase tracking-[0.08em] text-(--t-3)">
              {t("promptSetup.questionLabel")}
            </span>
            <textarea
              id="prompt-setup-editor"
              rows={3}
              required
              maxLength={300}
              value={editText}
              onChange={(event) => setEditText(event.target.value)}
              aria-describedby="prompt-setup-auto-type prompt-setup-error"
              className="min-h-[88px] w-full resize-y rounded-full border-0 bg-[#EEF1F6] px-3 py-2.5 text-[12.5px] leading-[1.6] text-(--t-1)"
            />
          </label>
          {/* SIGV2-1197: no type select and no live prediction. The type is
              assigned by the backend from the wording and shown on the row
              once saved; a wrong type is fixed by rewording, not by a
              dropdown the customer cannot answer. */}
          <p id="prompt-setup-auto-type" role="status" className={cx(CAPTION, "mt-2")}>
            {t("promptSetup.autoAssign")}
          </p>
          <p
            id="prompt-setup-error"
            role="alert"
            className={cx(
              "m-0 mt-1 text-[12px] leading-[1.6] text-[#B52C31]",
              !editError && "hidden"
            )}
          >
            {editError}
          </p>
          <div className="mt-3 flex gap-2">
            <button
              type="button"
              className={BTN}
              disabled={busy}
              onClick={() => {
                setEditing(null);
                setEditError(null);
              }}
            >
              {t("promptSetup.cancel")}
            </button>
            <button type="submit" className={BTN_PRIMARY} disabled={busy}>
              {t("promptSetup.saveChanges")}
            </button>
          </div>
        </form>
      ) : null}

      {projectId !== null ? (
        <SignalAddPromptModal
          open={addOpen}
          onClose={() => setAddOpen(false)}
          projectId={String(projectId)}
          entitlements={entitlements}
          getAuthHeaders={getAuthHeaders}
          onCreated={state.reload}
        />
      ) : null}
    </div>
  );
}
