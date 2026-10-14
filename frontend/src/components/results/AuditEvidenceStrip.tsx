"use client";

import React from "react";
import { AlertTriangle, CheckCircle2, DatabaseZap, ShieldAlert } from "lucide-react";

import Badge from "@/components/ui/Badge";
import SignalAlert from "@/components/signal/SignalAlert";
import { GlassCard } from "@/components/ui/GlassComponents";
import { cx } from "@/components/ui/utils";
import type { AuditModuleDiagnostics } from "@/lib/auditNormalization";

type AuditEvidenceStripProps = {
  title: string;
  diagnostics: AuditModuleDiagnostics;
  className?: string;
};

const badgeColor = (status: AuditModuleDiagnostics["status"]) => {
  if (status === "measured") return "success";
  if (status === "partial") return "warning";
  return "danger";
};

const fieldBadgeColor = (status: "measured" | "fallback" | "missing") => {
  if (status === "measured") return "success";
  if (status === "fallback") return "warning";
  return "danger";
};

const formatValue = (value: unknown): string => {
  if (typeof value === "number" && Number.isFinite(value)) {
    return String(Math.round(value));
  }
  if (typeof value === "string" && value.trim()) {
    return value;
  }
  if (value === null || value === undefined) {
    return "Unavailable";
  }
  if (typeof value === "object") {
    return "Structured evidence";
  }
  return String(value);
};

const statusLabel = (status: AuditModuleDiagnostics["status"]) => {
  if (status === "measured") return "High certainty";
  if (status === "partial") return "Mixed certainty";
  return "Unavailable";
};

export default function AuditEvidenceStrip({
  title,
  diagnostics,
  className,
}: AuditEvidenceStripProps) {
  return (
    <GlassCard className={cx("border-(--line) bg-(--line-2) p-6", className)}>
      <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
        <div className="space-y-2">
          <div className="flex items-center gap-3">
            <div className="flex h-9 w-9 items-center justify-center rounded-xl border border-(--line) bg-(--line-2) text-(--purple)">
              {diagnostics.status === "measured" ? (
                <CheckCircle2 className="h-4 w-4" />
              ) : diagnostics.status === "partial" ? (
                <AlertTriangle className="h-4 w-4" />
              ) : (
                <ShieldAlert className="h-4 w-4" />
              )}
            </div>
            <div>
              <p className="text-[10px] font-black uppercase tracking-[0.24em] text-(--t-3)">
                Evidence and Certainty
              </p>
              <h3 className="text-base font-semibold text-(--t-1)">{title}</h3>
            </div>
          </div>
          <p className="max-w-2xl text-sm text-(--t-2)">{diagnostics.summary}</p>
        </div>

        <Badge color={badgeColor(diagnostics.status)} size="md">
          {statusLabel(diagnostics.status)}
        </Badge>
      </div>

      <div className="mt-5 grid gap-3 md:grid-cols-2 xl:grid-cols-4">
        {diagnostics.fields.map((field) => (
          <div key={field.key} className="rounded border border-(--line) bg-(--line-2) p-4">
            <div className="flex items-start justify-between gap-3">
              <div>
                <p className="text-[10px] font-black uppercase tracking-[0.18em] text-(--t-3)">
                  {field.label}
                </p>
                <p className="mt-2 text-2xl font-black text-(--t-1)">{formatValue(field.value)}</p>
              </div>
              <Badge color={fieldBadgeColor(field.status)} size="sm">
                {field.status === "measured"
                  ? "Measured"
                  : field.status === "fallback"
                    ? "Fallback"
                    : "Missing"}
              </Badge>
            </div>
            <p className="mt-2 flex items-center gap-2 text-xs text-(--t-2)">
              <DatabaseZap className="h-3.5 w-3.5 shrink-0 text-(--t-3)" />
              {field.source}
            </p>
          </div>
        ))}
      </div>

      {diagnostics.issues.length > 0 ? (
        <SignalAlert tone="warning" title="Degraded Notes" className="mt-5">
          <ul className="mt-2 space-y-2">
            {diagnostics.issues.map((issue) => (
              <li key={issue} className="leading-relaxed">
                {issue}
              </li>
            ))}
          </ul>
        </SignalAlert>
      ) : null}
    </GlassCard>
  );
}
