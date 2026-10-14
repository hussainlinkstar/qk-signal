"use client";

import React, { useEffect, useState } from "react";
import Link from "next/link";
import { useTranslation } from "react-i18next";

import SignalInlineNote from "@/components/signal/SignalInlineNote";
import { formatDateTime } from "@/lib/dateFormat";
import type {
  ProjectDataSourceAssignment,
  ProjectDataSourceBindingMode,
  ProjectDataSourceType,
  ProjectMagicLinkStatus,
} from "@/services/workspaceService";

import SettingsSection from "./SettingsSection";

/**
 * The outcome of one action on this card, with the tone it actually carries.
 *
 * SIGV2-1171: it used to be a bare string. Every outcome - a save that worked,
 * a save that was refused, a catalogue Signal could not read, an access link
 * that could not be created - was printed into the same 12px `--t-3` grey
 * paragraph under `role="status"`, so a refusal looked exactly like a
 * confirmation and was quiet enough to be read as nothing happening.
 */
export type ConnectedDataMessage = {
  tone: "success" | "info" | "danger";
  text: string;
};

export const DATA_SOURCE_ORDER: ProjectDataSourceType[] = [
  "google_search_console",
  "google_analytics_4",
  "bing_webmaster",
];

export type ProjectDataSourceDraft = {
  bindingMode: ProjectDataSourceBindingMode;
  sourceId: string;
  sourceLabel: string;
  isActive: boolean;
};

export type ProjectDataSourceCatalogState = {
  loading: boolean;
  error: string | null;
  items: Array<{ id: string; label: string; description?: string | null }>;
  requiredScopes: string[];
  grantedScopes: string[];
  missingScopes: string[];
  // SIGV2-1207: the workspace has no connection but the user holds this
  // provider on another workspace they can access.
  connectedOnOtherWorkspace: boolean;
};

export type ConnectedDataSectionProps = {
  assignments: ProjectDataSourceAssignment[];
  drafts: Record<ProjectDataSourceType, ProjectDataSourceDraft>;
  catalogs: Record<ProjectDataSourceType, ProjectDataSourceCatalogState>;
  activeAction: string | null;
  interactionDisabled: boolean;
  message: ConnectedDataMessage | null;
  onDraftChange: (
    sourceType: ProjectDataSourceType,
    field: keyof ProjectDataSourceDraft,
    value: string | boolean
  ) => void;
  onAccountSelect: (sourceType: ProjectDataSourceType, sourceId: string) => void;
  onRefresh: (sourceType: ProjectDataSourceType) => void;
  onSave: (sourceType: ProjectDataSourceType) => void;
  onRemove: (sourceType: ProjectDataSourceType) => void;
  magicLinkStatus: ProjectMagicLinkStatus | null;
  loadingMagicLinkStatus: boolean;
  magicLinkMessage: ConnectedDataMessage | null;
  magicLinkUrl: string | null;
  generatingMagicLink: boolean;
  onGenerateMagicLink: () => void;
};

const normalizeScopeLabel = (value: string) =>
  value.replace("https://www.googleapis.com/auth/", "");

/** The approved `.ci` icons from Signal Settings.html, per source. */
const SourceIcon = ({ sourceType }: { sourceType: ProjectDataSourceType }) => {
  if (sourceType === "google_analytics_4") {
    return (
      <span
        aria-hidden="true"
        className="block h-[14px] w-[14px] rounded-[3px]"
        style={{
          background: "conic-gradient(#F9AB00 0 25%, #E37400 0 50%, #34A853 0 75%, #4285F4 0)",
        }}
      />
    );
  }
  if (sourceType === "google_search_console") {
    return (
      <svg
        width="17"
        height="17"
        viewBox="0 0 24 24"
        fill="none"
        stroke="var(--t-2)"
        strokeWidth="2"
        aria-hidden="true"
      >
        <circle cx="11" cy="11" r="7" />
        <path d="M21 21l-4.3-4.3" />
      </svg>
    );
  }
  return (
    <svg
      width="17"
      height="17"
      viewBox="0 0 24 24"
      fill="none"
      stroke="var(--t-2)"
      strokeWidth="2"
      aria-hidden="true"
    >
      <path d="M4 12l8-8 8 8M6 10v9a1 1 0 0 0 1 1h10a1 1 0 0 0 1-1v-9" />
    </svg>
  );
};

/**
 * Section 4. One block for everything Signal can read: the three sources it
 * maps, and the request it can send a client when the access is theirs rather
 * than yours. The handshake has no separate home in the design, so it sits
 * here with the rest of the connections instead of as a card of its own.
 *
 * SIGV2-1169: the resting state is the approved `.conn` anatomy - a heading,
 * one sentence, and three single-line rows of icon, name, descriptor and a
 * trailing state or action. The binding controls (binding mode, account
 * picker, manual entry, save/remove, refresh) live behind that row's action
 * instead of inline, because a literal three-row card would have deleted the
 * only route to binding a GA4 property.
 */
export default function ConnectedDataSection({
  assignments,
  drafts,
  catalogs,
  activeAction,
  interactionDisabled,
  message,
  onDraftChange,
  onAccountSelect,
  onRefresh,
  onSave,
  onRemove,
  magicLinkStatus,
  loadingMagicLinkStatus,
  magicLinkMessage,
  magicLinkUrl,
  generatingMagicLink,
  onGenerateMagicLink,
}: ConnectedDataSectionProps) {
  const { t } = useTranslation();
  const [expandedRows, setExpandedRows] = useState<Partial<Record<ProjectDataSourceType, boolean>>>(
    {}
  );

  // This section mounts only after the project resolves, so the browser's
  // initial hash scroll has nothing to land on. Once the card is in the DOM,
  // honour `#data-sources` ourselves and leave it keyboard-focusable.
  useEffect(() => {
    if (window.location.hash !== "#data-sources") return;
    const el = document.getElementById("data-sources");
    if (!el) return;
    el.scrollIntoView({ block: "start" });
    el.focus({ preventScroll: true });
  }, []);

  const toggleRow = (sourceType: ProjectDataSourceType, focusTarget?: string) => {
    const opening = !expandedRows[sourceType];
    setExpandedRows((current) => ({ ...current, [sourceType]: !current[sourceType] }));
    if (opening && focusTarget) {
      window.requestAnimationFrame(() => {
        document.getElementById(focusTarget)?.focus();
      });
    }
  };

  const handshakeStatusLabel = (status: ProjectMagicLinkStatus["status"] | undefined) => {
    if (status === "pending") return t("signalProjectSettings.handshake.statusPending");
    if (status === "expired") return t("signalProjectSettings.handshake.statusExpired");
    if (status === "connected") return t("signalProjectSettings.handshake.statusConnected");
    return t("signalProjectSettings.handshake.statusNotRequested");
  };

  const catalogNote = (
    sourceType: ProjectDataSourceType,
    catalog: ProjectDataSourceCatalogState,
    bindingMode: ProjectDataSourceBindingMode
  ) => {
    if (bindingMode === "client_magic_link" || !catalog.error) return null;
    const source = t(`signalProjectSettings.connectedData.sourceName.${sourceType}`);
    if (catalog.error.startsWith("insufficient_scope")) {
      return t("signalProjectSettings.connectedData.scopeNote", {
        source,
        scopes: catalog.missingScopes.map(normalizeScopeLabel).join(", "),
      });
    }
    if (catalog.error === "workspace_provider_not_connected") {
      // SIGV2-1207: connecting "again" without context reads as if the connect
      // they already did was lost; say where the existing grant lives.
      if (catalog.connectedOnOtherWorkspace) {
        return t("signalProjectSettings.connectedData.connectedElsewhereNote", { source });
      }
      return t("signalProjectSettings.connectedData.connectFirstNote", { source });
    }
    return catalog.error;
  };

  return (
    <SettingsSection
      id="data-sources"
      title={t("signalProjectSettings.connectedData.heading")}
      description={t("signalProjectSettings.connectedData.description")}
    >
      {DATA_SOURCE_ORDER.map((sourceType) => {
        const assignment = assignments.find((item) => item.source_type === sourceType);
        const draft = drafts[sourceType];
        const catalog = catalogs[sourceType];
        const sourceName = t(`signalProjectSettings.connectedData.sourceName.${sourceType}`);
        const providerConnected = assignment?.workspace_provider_connected || false;
        const note = catalogNote(sourceType, catalog, draft.bindingMode);
        const manualMode = draft.bindingMode === "client_magic_link";
        const pickerDisabled =
          draft.bindingMode !== "workspace" ||
          !providerConnected ||
          catalog.loading ||
          catalog.items.length === 0;
        const expanded = Boolean(expandedRows[sourceType]);
        const panelId = `${sourceType}-panel`;

        const placeholderLabel = manualMode
          ? t("signalProjectSettings.connectedData.accountManualMode")
          : draft.bindingMode !== "workspace"
            ? t("signalProjectSettings.connectedData.accountSwitchMode")
            : !providerConnected
              ? t("signalProjectSettings.connectedData.accountNeedsConnection")
              : catalog.loading
                ? t("signalProjectSettings.connectedData.accountLoading")
                : catalog.items.length === 0
                  ? t("signalProjectSettings.connectedData.accountNone")
                  : t(`signalProjectSettings.connectedData.accountChoose.${sourceType}`);

        const bound = Boolean(assignment?.is_active && assignment?.source_id);
        const boundButOff = Boolean(assignment?.source_id && !assignment?.is_active);

        const rowActionClass =
          "inline-flex h-8 flex-none cursor-pointer items-center rounded-[10px] border border-(--line) bg-(--panel) px-[15px] text-[13.5px] font-semibold text-(--t-1) hover:border-[#D7DAE0] max-md:min-h-11";

        return (
          <div key={sourceType} className="border-t border-t-(--line-2) first:border-t-0">
            {/* Approved `.conn` resting row: 32px icon tile, 13.5/600 title,
                short mono descriptor, action or badge at the row end. The
                binding controls for this row sit in the panel below it. */}
            <div className="flex items-center gap-3 py-3">
              <span className="flex h-8 w-8 flex-none items-center justify-center rounded-[8px] bg-(--line-2)">
                <SourceIcon sourceType={sourceType} />
              </span>
              <div className="min-w-0 flex-1">
                <div className="text-[13.5px] font-semibold">{sourceName}</div>
                <div className="font-mono text-[11.5px] text-(--t-3)">
                  {t(`signalProjectSettings.connectedData.descriptor.${sourceType}`)}
                </div>
              </div>
              {bound ? (
                <>
                  <span className="flex-none rounded-[999px] bg-(--good-s) px-[9px] py-1 font-mono text-[10.5px] text-(--good)">
                    {t("signalProjectSettings.connectedData.connected")}
                  </span>
                  <button
                    type="button"
                    aria-label={t("signalProjectSettings.connectedData.manageFor", {
                      source: sourceName,
                    })}
                    aria-expanded={expanded}
                    aria-controls={panelId}
                    onClick={() => toggleRow(sourceType)}
                    className={rowActionClass}
                  >
                    {t("signalProjectSettings.connectedData.manage")}
                  </button>
                </>
              ) : boundButOff ? (
                <>
                  {/* Bound but deliberately switched off: the "Use this source"
                      checkbox in the panel is the switch back on, so a muted
                      pill states the row rather than a misleading "Connect". */}
                  <span className="flex-none rounded-[999px] bg-(--line-2) px-[9px] py-1 font-mono text-[10.5px] text-(--t-2)">
                    {t("signalProjectSettings.connectedData.notInUse")}
                  </span>
                  <button
                    type="button"
                    aria-label={t("signalProjectSettings.connectedData.manageFor", {
                      source: sourceName,
                    })}
                    aria-expanded={expanded}
                    aria-controls={panelId}
                    onClick={() => toggleRow(sourceType)}
                    className={rowActionClass}
                  >
                    {t("signalProjectSettings.connectedData.manage")}
                  </button>
                </>
              ) : providerConnected ? (
                // The account grant is already held at workspace level; the
                // step left is choosing which account this project reads, so
                // the row must not say "Connect" (SIGV2-1169).
                <button
                  type="button"
                  aria-label={t(`signalProjectSettings.connectedData.chooseFor.${sourceType}`, {
                    source: sourceName,
                  })}
                  aria-expanded={expanded}
                  aria-controls={panelId}
                  onClick={() => toggleRow(sourceType, `${sourceType}-account`)}
                  className={rowActionClass}
                >
                  {t(`signalProjectSettings.connectedData.chooseAccount.${sourceType}`)}
                </button>
              ) : (
                // No workspace grant yet: "Connect" opens the row's panel,
                // which names the Connections Hub step and still exposes the
                // client-shared-access mode.
                <button
                  type="button"
                  aria-label={t("signalProjectSettings.connectedData.connectFor", {
                    source: sourceName,
                  })}
                  aria-expanded={expanded}
                  aria-controls={panelId}
                  onClick={() => toggleRow(sourceType)}
                  className={rowActionClass}
                >
                  {t("signalProjectSettings.connectedData.connect")}
                </button>
              )}
            </div>

            {expanded && (
              <div id={panelId} className="pb-3">
                {/* items-end: the three labels wrap to different line counts,
                    so the controls must align on the row's bottom edge rather
                    than hang off uneven label heights (SIGV2-1189). */}
                <div className="grid grid-cols-1 items-end gap-4 md:grid-cols-3">
                  <div className="mb-0">
                    <label
                      className="mb-2 block text-[10.5px] tracking-[0.08em] text-(--t-3)"
                      htmlFor={`${sourceType}-mode`}
                    >
                      {t("signalProjectSettings.connectedData.modeLabel")}
                    </label>
                    <select
                      id={`${sourceType}-mode`}
                      className="wselect-chevron field-focus-ring h-11 w-full cursor-pointer appearance-none rounded-[10px] border border-(--line) bg-(--paper) pl-[13px] pr-[34px] py-0 font-(family-name:--body-font) text-[13.5px] text-(--t-1) outline-none focus:border-[#C7CDD6]"
                      value={draft.bindingMode}
                      disabled={interactionDisabled}
                      onChange={(event) =>
                        onDraftChange(sourceType, "bindingMode", event.target.value)
                      }
                    >
                      <option value="workspace">
                        {t("signalProjectSettings.connectedData.modeWorkspace")}
                      </option>
                      <option value="client_magic_link">
                        {t("signalProjectSettings.connectedData.modeClient")}
                      </option>
                      <option value="ai_estimate">
                        {t("signalProjectSettings.connectedData.modeAi")}
                      </option>
                    </select>
                  </div>

                  <div className="mb-0">
                    <label
                      className="mb-2 block text-[10.5px] tracking-[0.08em] text-(--t-3)"
                      htmlFor={`${sourceType}-account`}
                    >
                      {t(`signalProjectSettings.connectedData.accountLabel.${sourceType}`)}
                    </label>
                    <select
                      id={`${sourceType}-account`}
                      className="wselect-chevron field-focus-ring h-11 w-full cursor-pointer appearance-none rounded-[10px] border border-(--line) bg-(--paper) pl-[13px] pr-[34px] py-0 font-(family-name:--body-font) text-[13.5px] text-(--t-1) outline-none focus:border-[#C7CDD6]"
                      value={draft.sourceId}
                      disabled={pickerDisabled}
                      onChange={(event) => onAccountSelect(sourceType, event.target.value)}
                    >
                      <option value="">{placeholderLabel}</option>
                      {catalog.items.map((item) => (
                        <option key={item.id} value={item.id}>
                          {item.label}
                        </option>
                      ))}
                    </select>
                  </div>

                  <div className="mb-0">
                    <label
                      className="mb-2 block text-[10.5px] tracking-[0.08em] text-(--t-3)"
                      htmlFor={`${sourceType}-manual`}
                    >
                      {t(`signalProjectSettings.connectedData.manualLabel.${sourceType}`)}
                    </label>
                    <input
                      id={`${sourceType}-manual`}
                      className="field-focus-ring h-11 w-full rounded-[10px] border border-(--line) bg-(--paper) px-[13px] py-0 font-(family-name:--body-font) text-[13.5px] text-(--t-1) outline-none placeholder:text-(--t-3) focus:border-[#C7CDD6]"
                      type="text"
                      placeholder={t(
                        `signalProjectSettings.connectedData.manualPlaceholder.${sourceType}`
                      )}
                      value={draft.sourceId}
                      readOnly={!pickerDisabled}
                      onChange={(event) =>
                        onDraftChange(sourceType, "sourceId", event.target.value)
                      }
                    />
                  </div>
                </div>

                {/* A catalogue or scope failure belongs to this row, so it is
                    the approved inline tier, with the warn glyph and
                    `role="alert"` rather than a bare coloured sentence. */}
                {note && (
                  <SignalInlineNote tone="warning" className="mt-2.5">
                    {t("signalProjectSettings.connectedData.setupNote", { detail: note })}
                  </SignalInlineNote>
                )}

                {/* Unconditional: the Hub is the only home for workspace
                    providers, so hiding this link once a provider connects is
                    what left the page unreachable (SIGV2-1189). */}
                <p className="mt-2.5 text-[12px]">
                  <Link href="/dashboard/connections" className="text-(--purple) underline">
                    {t("signalProjectSettings.connectedData.openHub")}
                  </Link>
                </p>

                <div className="mt-3.5 flex flex-wrap items-center gap-2.5">
                  <label
                    className="inline-flex cursor-pointer items-center gap-2 text-[13px] text-(--t-1)"
                    htmlFor={`${sourceType}-in-use`}
                  >
                    <input
                      id={`${sourceType}-in-use`}
                      type="checkbox"
                      className="h-4 w-4 cursor-pointer accent-(--ink)"
                      checked={draft.isActive}
                      disabled={interactionDisabled}
                      onChange={(event) =>
                        onDraftChange(sourceType, "isActive", event.target.checked)
                      }
                    />
                    {t("signalProjectSettings.connectedData.useSource")}
                  </label>
                  <button
                    type="button"
                    className="inline-flex h-8 cursor-pointer items-center gap-2 rounded-[10px] border border-(--line) bg-(--panel) px-[15px] font-(family-name:--body-font) text-[13.5px] font-semibold text-(--t-1) hover:border-[#D7DAE0]"
                    aria-label={t("signalProjectSettings.connectedData.refreshFor", {
                      source: sourceName,
                    })}
                    onClick={() => onRefresh(sourceType)}
                    disabled={activeAction === `${sourceType}:catalog`}
                  >
                    {activeAction === `${sourceType}:catalog`
                      ? t("signalProjectSettings.connectedData.refreshBusy")
                      : t("signalProjectSettings.connectedData.refresh")}
                  </button>
                  <button
                    type="button"
                    className="inline-flex h-8 cursor-pointer items-center gap-2 rounded-[10px] border border-(--ink) bg-(--ink) px-[15px] font-(family-name:--body-font) text-[13.5px] font-semibold text-white hover:bg-black"
                    aria-label={t("signalProjectSettings.connectedData.saveFor", {
                      source: sourceName,
                    })}
                    onClick={() => onSave(sourceType)}
                    disabled={activeAction === `${sourceType}:save`}
                  >
                    {activeAction === `${sourceType}:save`
                      ? t("signalProjectSettings.connectedData.saveBusy")
                      : t("signalProjectSettings.connectedData.save")}
                  </button>
                  <button
                    type="button"
                    className="inline-flex h-8 cursor-pointer items-center gap-2 rounded-[10px] border border-[color-mix(in_srgb,var(--bad)_40%,transparent)] bg-(--panel) px-[15px] font-(family-name:--body-font) text-[13.5px] font-semibold text-(--bad)"
                    aria-label={t("signalProjectSettings.connectedData.removeFor", {
                      source: sourceName,
                    })}
                    onClick={() => onRemove(sourceType)}
                    disabled={!assignment?.id || activeAction === `${sourceType}:clear`}
                  >
                    {activeAction === `${sourceType}:clear`
                      ? t("signalProjectSettings.connectedData.removeBusy")
                      : t("signalProjectSettings.connectedData.remove")}
                  </button>
                </div>
              </div>
            )}
          </div>
        );
      })}

      {/* The approved inline tier, which is what the component sheet
          prescribes for this: "inline for feedback attached to its cause"
          (Signal Components.html, #sec-notify). The cause is the Save,
          Refresh or Remove action a row above, so this is not the page-level
          alert tier - and keeping the design's own tier is also why this card
          adds no height to a gated screen. What it gains over the old shared
          grey paragraph is the tone's glyph, the tone's colour token, and
          `role="alert"` for a refusal instead of `role="status"` for
          everything. */}
      {message && (
        <SignalInlineNote tone={message.tone} className="mt-3.5">
          {message.text}
        </SignalInlineNote>
      )}

      <div className="mt-4 border-t border-t-(--line-2) pt-4" id="client-handshake">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="min-w-0">
            <div className="text-[13.5px] font-semibold">
              {t("signalProjectSettings.handshake.heading")}
            </div>
            <div className="mt-0.5 max-w-[560px] text-[12px] leading-[1.45] text-(--t-3)">
              {t("signalProjectSettings.handshake.description")}
            </div>
          </div>
          <span className="flex-none rounded-[6px] bg-(--purple-a10) px-[7px] py-[3px] font-mono text-[9.5px] uppercase tracking-[0.06em] text-(--purple-deep)">
            {loadingMagicLinkStatus
              ? t("signalProjectSettings.handshake.checking")
              : handshakeStatusLabel(magicLinkStatus?.status)}
          </span>
        </div>

        {magicLinkStatus && (
          <div className="mt-4 flex flex-col gap-3.5 md:flex-row">
            <div className="w-full min-w-0 flex-1 rounded-[12px] border border-(--line) bg-(--paper) px-[18px] py-4 md:min-w-[auto]">
              <div className="mb-1.5 text-[10px] uppercase tracking-[0.08em] text-(--t-3)">
                {t("signalProjectSettings.handshake.openLinks")}
              </div>
              <div className="font-(family-name:--disp) text-[20px] font-extrabold tracking-[-0.02em]">
                {magicLinkStatus.open_magic_link_count}
              </div>
            </div>
            <div className="w-full min-w-0 flex-1 rounded-[12px] border border-(--line) bg-(--paper) px-[18px] py-4 md:min-w-[auto]">
              <div className="mb-1.5 text-[10px] uppercase tracking-[0.08em] text-(--t-3)">
                {t("signalProjectSettings.handshake.expires")}
              </div>
              <div className="font-(family-name:--disp) text-[15px] font-extrabold tracking-[-0.02em]">
                {magicLinkStatus.latest_link_expires_at
                  ? formatDateTime(magicLinkStatus.latest_link_expires_at)
                  : t("signalProjectSettings.handshake.noExpiry")}
              </div>
            </div>
          </div>
        )}

        <div className="mt-4 flex justify-end">
          <button
            type="button"
            className="inline-flex h-[38px] cursor-pointer items-center gap-2 rounded-[10px] border border-(--ink) bg-(--ink) px-[15px] font-(family-name:--body-font) text-[13.5px] font-semibold text-white hover:bg-black max-md:min-h-11"
            onClick={onGenerateMagicLink}
            disabled={generatingMagicLink}
          >
            {generatingMagicLink
              ? t("signalProjectSettings.handshake.generateBusy")
              : t("signalProjectSettings.handshake.generate")}
          </button>
        </div>

        {magicLinkMessage && (
          <SignalInlineNote tone={magicLinkMessage.tone} className="mt-3.5">
            {magicLinkMessage.text}
          </SignalInlineNote>
        )}

        {magicLinkUrl && (
          <p
            className="mt-3.5 break-all rounded-[10px] border border-(--line) bg-(--paper) px-3.5 py-3 text-[12px] text-(--purple)"
            aria-label={t("signalProjectSettings.handshake.linkLabel")}
          >
            {magicLinkUrl}
          </p>
        )}
      </div>
    </SettingsSection>
  );
}
