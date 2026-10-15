"use client";

import React, { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import { useAuth } from "@/components/auth/custom-auth";
import { fetchAuditById } from "@/services/auditService";
import { fetchProjectAudits, fetchWorkspaceProjects } from "@/services/workspaceService";

/**
 * Raw JSON report download, in the Developer Hub (SIGV2-1124).
 *
 * The audit report screen used to carry a "Download JSON" button inside an
 * invented "Export this report" section. That section is gone, and the approved
 * Export menu is PDF-only on purpose: the approved home for raw JSON is this
 * page, which states "Trigger audits programmatically, consume raw JSON
 * reports, and wire completion callbacks into BI or workflow tooling"
 * (`Signal Developer Hub.html`).
 *
 * Programmatic access to the same payload needs an API key, which is a
 * Specialist-and-above entitlement, so this card exists so the download does
 * not silently become plan-gated by moving it here.
 *
 * It lives in the API Reference panel next to the endpoint that serves the same
 * thing over HTTP, and that panel is not the page's default state, so the
 * approved-design comparison of this screen is unaffected.
 */

type AuditOption = {
  id: number;
  url: string;
  createdAt: string | null;
};

const SELECT_LIMIT = 25;

export default function RawJsonReportCard() {
  const { t } = useTranslation();
  const { getToken, isSignedIn, isLoading: authLoading } = useAuth();

  const [options, setOptions] = useState<AuditOption[] | null>(null);
  const [selectedId, setSelectedId] = useState<string>("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const authHeaders = useCallback(async (): Promise<Record<string, string>> => {
    const token = await getToken();
    return token ? { Authorization: `Bearer ${token}` } : {};
  }, [getToken]);

  useEffect(() => {
    if (authLoading || !isSignedIn) return;
    let cancelled = false;
    void (async () => {
      try {
        const headers = await authHeaders();
        const projects = await fetchWorkspaceProjects(headers);
        const settled = await Promise.allSettled(
          projects.map((project) =>
            // The list only needs identifiers, so the full reports are left on
            // the server until one audit is actually chosen.
            fetchProjectAudits(project.id, headers, {
              includeFullReport: false,
              limit: SELECT_LIMIT,
            })
          )
        );
        const rows = settled
          .filter(
            (
              result
            ): result is PromiseFulfilledResult<Awaited<ReturnType<typeof fetchProjectAudits>>> =>
              result.status === "fulfilled"
          )
          .flatMap((result) => result.value)
          .map((audit) => ({
            id: audit.id,
            url: audit.target_name || audit.url || audit.target_url || String(audit.id),
            createdAt: audit.created_at ?? null,
          }))
          .sort((a, b) => (b.createdAt ?? "").localeCompare(a.createdAt ?? ""))
          .slice(0, SELECT_LIMIT);
        if (!cancelled) {
          setOptions(rows);
          setSelectedId(rows.length > 0 ? String(rows[0].id) : "");
        }
      } catch {
        if (!cancelled) setOptions([]);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [authHeaders, authLoading, isSignedIn]);

  const selectedOption = useMemo(
    () => options?.find((option) => String(option.id) === selectedId) ?? null,
    [options, selectedId]
  );

  const download = useCallback(async () => {
    if (!selectedOption) return;
    setBusy(true);
    setError(null);
    try {
      const audit = await fetchAuditById(selectedOption.id, await authHeaders());
      if (!audit.full_report) {
        setError(t("developerHub.rawJson.noReport"));
        return;
      }
      const blob = new Blob([JSON.stringify(audit, null, 2)], { type: "application/json" });
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = `audit-${selectedOption.id}.json`;
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      URL.revokeObjectURL(url);
    } catch {
      setError(t("developerHub.rawJson.failed"));
    } finally {
      setBusy(false);
    }
  }, [authHeaders, selectedOption, t]);

  return (
    <div className="rounded-[22px] border-0 bg-white px-[22px] py-[18px]">
      <h3 className="m-0 mb-[3px] font-(family-name:--disp) text-[15px] font-bold tracking-[-0.01em]">
        {t("developerHub.rawJson.title")}
      </h3>
      <p className="m-0 mb-[18px] text-[12.5px] leading-[1.5] text-(--t-3)">
        {t("developerHub.rawJson.description")}
      </p>
      <div className="flex flex-wrap items-end gap-3">
        <label className="flex min-w-[240px] flex-1 flex-col gap-1.5">
          <span className="font-(family-name:--mono) text-[10.5px] uppercase tracking-[0.08em] text-(--t-3)">
            {t("developerHub.rawJson.selectLabel")}
          </span>
          <select
            value={selectedId}
            onChange={(event) => setSelectedId(event.target.value)}
            disabled={!options || options.length === 0}
            className="h-[38px] rounded-[14px] border-0 bg-[#EEF1F6] px-3 text-[13px] text-(--t-1) disabled:opacity-50"
          >
            {options === null ? (
              <option value="">{t("developerHub.rawJson.loading")}</option>
            ) : options.length === 0 ? (
              <option value="">{t("developerHub.rawJson.empty")}</option>
            ) : (
              options.map((option) => (
                <option key={option.id} value={String(option.id)}>
                  {`${option.url} - ${option.createdAt ? option.createdAt.slice(0, 10) : option.id}`}
                </option>
              ))
            )}
          </select>
        </label>
        <button
          type="button"
          onClick={() => void download()}
          disabled={!selectedOption || busy}
          className="inline-flex h-[38px] cursor-pointer items-center gap-2 rounded-full border-0 bg-[#EEF1F6] px-[15px] font-(family-name:--body-font) text-[13.5px] font-semibold text-(--t-1) hover:bg-[#E8ECF3] disabled:cursor-not-allowed disabled:opacity-50"
        >
          {busy ? t("developerHub.rawJson.preparing") : t("developerHub.rawJson.download")}
        </button>
      </div>
      {error ? (
        <p className="mt-3 mb-0 text-[12.5px] text-(--bad)" role="alert">
          {error}
        </p>
      ) : null}
    </div>
  );
}
