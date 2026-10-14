"use client";

import React from "react";
import { useTranslation } from "react-i18next";

import EntityChips from "@/components/results/EntityChips";
import PlanLockNotice from "@/components/dashboard/PlanLockNotice";
import { getPlanLockContent } from "@/lib/planLocks";
import type { EntityCandidate } from "@/types/auditWorkspace";
import { REPORT_BLOCK } from "./reportBlock";
import type { EntityChipItem } from "@/components/results/EntityChips";
import type { LockedAuditSection } from "@/types/auditResult";

/**
 * "How AI describes your brand", on the approved visual language (SIGV2-1302).
 *
 * This was two shadowed cards side by side, each with its own glow, and when a
 * scan found no entities they said the same nothing twice: "Entities found, 0
 * found" on the left, "Entities, No entities found yet" on the right. Edward
 * screenshotted it under "UX all over the place".
 *
 * One card now. The counts are a quiet summary line above the entities they
 * describe, and when there are none the panel says so once.
 */

type EntitiesTabProps = {
  editableEntities: EntityCandidate[];
  setEditableEntities?: React.Dispatch<React.SetStateAction<EntityCandidate[]>>;
  entityChipSuggestions: EntityChipItem[];
  entitySummary: {
    total: number;
    categorized: number;
    avgConfidence: number | null;
    highConfidence: number;
  };
  readOnly?: boolean;
  lockedSection?: LockedAuditSection | null;
};

// signal.css `.card`.
// SIGV2-1317: a block, not a card. The disclosure already draws the card,
// and it already carries this section's name and its description, so both
// were being printed twice.
const LABEL_CLASS = "font-mono text-[10.5px] uppercase tracking-[0.08em] text-(--t-3)";

function Summary({
  label,
  value,
  note,
}: {
  label: string;
  value: React.ReactNode;
  note?: string | null;
}) {
  return (
    <div className="min-w-0">
      <div className={LABEL_CLASS}>{label}</div>
      <div className="mt-1 font-(family-name:--disp) text-[18px] font-bold leading-none tracking-[-0.01em] text-(--t-1)">
        {value}
      </div>
      {note ? <div className="mt-1 text-[11.5px] text-(--t-3)">{note}</div> : null}
    </div>
  );
}

export default function EntitiesTab({
  editableEntities,
  setEditableEntities,
  entityChipSuggestions,
  entitySummary,
  readOnly = false,
  lockedSection,
}: EntitiesTabProps) {
  const { t } = useTranslation();

  if (lockedSection?.is_locked) {
    return (
      <PlanLockNotice
        {...getPlanLockContent("entities", {
          // No hand-written fallback plan: when the payload names none, the
          // lock falls back to the plan `MINIMUM_PLAN_BY_FEATURE` puts this
          // capability on, never to a plan typed in here (SIGV2-1221).
          requiredPlanLabel: lockedSection.required_plan_label?.trim(),
          description:
            lockedSection.detail?.trim() ||
            "Upgrade this workspace to unlock entity extraction and semantic node mapping.",
        })}
        badgeLabel="Locked in API payload"
        align="center"
        className="mx-auto max-w-4xl"
      />
    );
  }

  const hasEntities = editableEntities.length > 0;

  return (
    <div className="space-y-4">
      {!readOnly ? (
        <p className="m-0 text-[12.5px] text-(--t-3)">
          <span className="text-(--t-2)">{t("signalAuditReport.entities.syncActive")}</span>{" "}
          {t("signalAuditReport.entities.syncDesc")}
        </p>
      ) : null}

      <div className={REPORT_BLOCK} data-entities-panel="">
        {hasEntities ? (
          <>
            <div className="mb-4 grid gap-5 border-b border-(--line-2) pb-4 sm:grid-cols-3">
              <Summary
                label={t("signalAuditReport.entities.indexTitle")}
                value={t("signalAuditReport.entities.total", { count: entitySummary.total })}
              />
              <Summary
                label={t("signalAuditReport.entities.classified")}
                value={
                  entitySummary.categorized > 0 ? entitySummary.categorized : entitySummary.total
                }
                note={
                  entitySummary.categorized === 0
                    ? t("signalAuditReport.entities.untyped")
                    : undefined
                }
              />
              <Summary
                label={t("signalAuditReport.entities.confidence")}
                value={
                  entitySummary.avgConfidence !== null ? (
                    `${entitySummary.avgConfidence}%`
                  ) : (
                    <span className="text-[13px] font-semibold text-(--t-3)">
                      {t("signalAuditReport.entities.notMeasured")}
                    </span>
                  )
                }
              />
            </div>

            <EntityChips
              entities={editableEntities}
              suggestions={readOnly ? [] : entityChipSuggestions}
              onEdit={
                readOnly || !setEditableEntities
                  ? undefined
                  : (next, prev) => {
                      setEditableEntities((curr) =>
                        curr.map((e) => (e.name === prev.name ? { ...e, name: next.name } : e))
                      );
                    }
              }
              onRemove={
                readOnly || !setEditableEntities
                  ? undefined
                  : (e) => setEditableEntities((curr) => curr.filter((x) => x.name !== e.name))
              }
              onAdd={
                readOnly || !setEditableEntities
                  ? undefined
                  : (e) =>
                      setEditableEntities((curr) => [
                        ...curr,
                        {
                          name: e.name,
                          type: e.type ?? "Entity",
                          confidence: e.confidence ?? null,
                        },
                      ])
              }
            />
          </>
        ) : (
          // Said once. Two panels used to say it simultaneously, one as a zero
          // and one as a sentence, which is how "0 found" ended up next to
          // "No entities found yet".
          <p className="m-0 text-[13px] leading-[1.55] text-(--t-3)">
            {t("signalAuditReport.entities.chipsEmpty")}
          </p>
        )}
      </div>
    </div>
  );
}
