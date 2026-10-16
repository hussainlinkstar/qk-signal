"use client";

import React, { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { useAuth } from "@/components/auth/custom-auth";
import {
  fetchProjectById,
  updateProjectById,
  type ProjectScoreTargets,
} from "@/services/workspaceService";

type ScoreField = "aio" | "seo";

const clampScore = (value: number) => Math.min(100, Math.max(0, Math.round(value)));

function TargetSlider({
  label,
  value,
  current,
  onChange,
  disabled,
}: {
  label: string;
  value: number;
  current: number | null;
  onChange: (value: number) => void;
  disabled: boolean;
}) {
  const { t } = useTranslation();
  const currentPct = current === null ? null : clampScore(current);
  return (
    <div className="mb-[18px] last:mb-0">
      <div className="mb-2 flex items-baseline justify-between gap-4">
        <span className="text-[12.5px] font-medium text-(--t-2)">{label}</span>
        <b className="font-(family-name:--disp) text-[14px] font-extrabold tracking-[-0.01em]">
          {value}
        </b>
      </div>
      <div className="relative">
        <input
          type="range"
          min={0}
          max={100}
          step={1}
          value={value}
          disabled={disabled}
          aria-label={label}
          onChange={(event) => onChange(clampScore(Number(event.target.value)))}
          // SIGV2-1217: the only element in the product that draws its focus
          // indicator on a SIBLING rather than on itself. The input is a
          // transparent full-width hit area and the knob below lights for it,
          // so the new global focus outline would have drawn a second ring
          // around the whole track. `outline-hidden`, not `outline-none`, so
          // forced-colors mode still gets a ring.
          className="peer absolute inset-0 z-[2] h-full w-full cursor-pointer opacity-0 focus-visible:outline-hidden disabled:cursor-not-allowed"
        />
        <div aria-hidden="true" className="relative h-[6px] rounded-[999px] bg-(--line-2)">
          {currentPct !== null && (
            <div
              className="absolute top-0 bottom-0 left-0 rounded-[999px] bg-[var(--slate,#64748B)] opacity-35"
              style={{ width: `${currentPct}%` }}
            />
          )}
          <div
            className="absolute top-0 bottom-0 left-0 rounded-[999px] bg-(image:--grad) opacity-[0.28]"
            style={{ width: `${value}%` }}
          />
        </div>
        <div
          aria-hidden="true"
          className="absolute top-1/2 z-[1] h-4 w-4 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-(--purple) bg-white shadow-[0_1px_3px_rgba(12,15,22,.2)] peer-focus-visible:shadow-[0_0_0_3px_var(--ring)]"
          style={{ insetInlineStart: `${value}%` }}
        />
      </div>
      <div className="mt-2 flex justify-between font-(family-name:--mono) text-[10.5px] text-(--t-3)">
        <span>
          {currentPct === null
            ? t("signalProjectSettings.scoreTargets.notMeasured")
            : t("signalProjectSettings.scoreTargets.now", { score: Math.round(currentPct) })}
        </span>
        <span>{t("signalProjectSettings.scoreTargets.targetLine", { score: value })}</span>
      </div>
    </div>
  );
}

/**
 * Score targets card on project settings (SIGV2-1098). The backend persists
 * `aio_score_target` / `seo_score_target` on the project and resolves defaults
 * when no override is set, so this card reads `score_targets` off the project
 * response and PATCHes both fields together.
 */
export default function ScoreTargetsCard({ projectId }: { projectId: string | number }) {
  const { t } = useTranslation();
  const { getToken, isSignedIn, isLoading: authLoading } = useAuth();
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [targets, setTargets] = useState<ProjectScoreTargets | null>(null);
  const [draft, setDraft] = useState<Record<ScoreField, number> | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const getAuthHeaders = useCallback(async (): Promise<HeadersInit> => {
    const token = await getToken();
    if (!token) {
      throw new Error(t("signalProjectSettings.scoreTargets.signInRequired"));
    }
    return { Authorization: `Bearer ${token}` };
  }, [getToken, t]);

  const load = useCallback(async () => {
    if (!projectId || authLoading) {
      return;
    }
    if (!isSignedIn) {
      setLoading(false);
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const headers = await getAuthHeaders();
      const project = await fetchProjectById(projectId, headers);
      const resolved = project.score_targets ?? null;
      setTargets(resolved);
      setDraft(resolved ? { aio: resolved.aio.target, seo: resolved.seo.target } : null);
    } catch (loadError) {
      setError(
        loadError instanceof Error
          ? loadError.message
          : t("signalProjectSettings.scoreTargets.loadFailed")
      );
    } finally {
      setLoading(false);
    }
  }, [authLoading, getAuthHeaders, isSignedIn, projectId, t]);

  useEffect(() => {
    void load();
  }, [load]);

  const dirty =
    targets !== null &&
    draft !== null &&
    (draft.aio !== targets.aio.target || draft.seo !== targets.seo.target);

  const save = async () => {
    if (!draft || saving) {
      return;
    }
    setSaving(true);
    setMessage(null);
    setError(null);
    try {
      const headers = await getAuthHeaders();
      await updateProjectById(
        projectId,
        { aio_score_target: draft.aio, seo_score_target: draft.seo },
        headers
      );
      setMessage(t("signalProjectSettings.scoreTargets.saved"));
      await load();
    } catch (saveError) {
      setError(
        saveError instanceof Error
          ? saveError.message
          : t("signalProjectSettings.scoreTargets.saveFailed")
      );
    } finally {
      setSaving(false);
    }
  };

  const updateDraft = (field: ScoreField, value: number) =>
    setDraft((current) => (current ? { ...current, [field]: value } : current));

  return (
    <div>
      {loading ? (
        <p className="m-0 text-[12.5px] text-(--t-3)">
          {t("signalProjectSettings.scoreTargets.loading")}
        </p>
      ) : error && !targets ? (
        <p className="m-0 text-[12.5px] text-(--bad)">{error}</p>
      ) : draft ? (
        <>
          <TargetSlider
            label={t("signalProjectSettings.scoreTargets.aioLabel")}
            value={draft.aio}
            current={targets?.aio.current ?? null}
            disabled={saving}
            onChange={(value) => updateDraft("aio", value)}
          />
          <TargetSlider
            label={t("signalProjectSettings.scoreTargets.seoLabel")}
            value={draft.seo}
            current={targets?.seo.current ?? null}
            disabled={saving}
            onChange={(value) => updateDraft("seo", value)}
          />
          <div className="mt-4 flex flex-wrap items-center gap-3">
            <button
              type="button"
              onClick={() => void save()}
              disabled={!dirty || saving}
              className="inline-flex h-[38px] items-center justify-center rounded-full bg-(--ink) px-4 text-[13.5px] font-semibold text-white transition-colors hover:bg-black disabled:cursor-not-allowed disabled:opacity-40 max-md:min-h-11"
            >
              {saving
                ? t("signalProjectSettings.scoreTargets.saving")
                : t("signalProjectSettings.scoreTargets.save")}
            </button>
            {message && (
              <span className="text-[12px] text-(--good)" role="status">
                {message}
              </span>
            )}
            {error && (
              <span className="text-[12px] text-(--bad)" role="alert">
                {error}
              </span>
            )}
          </div>
        </>
      ) : (
        <p className="m-0 text-[12.5px] text-(--t-3)">
          {t("signalProjectSettings.scoreTargets.unavailable")}
        </p>
      )}
    </div>
  );
}
