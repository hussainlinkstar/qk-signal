"use client";

import React from "react";
import Link from "next/link";
import { useTranslation } from "react-i18next";
import Card from "@/components/ui/Card";

type NoAuditCardProps = {
  className?: string;
  message?: string;
};

export default function NoAuditCard({ className, message }: NoAuditCardProps) {
  const { t } = useTranslation();

  return (
    <Card className={`p-6 ${className ?? ""}`.trim()}>
      <h2 className="text-lg font-semibold text-(--t-1)">{t("dashboard.empty.title")}</h2>
      <p className="mt-2 text-sm text-(--t-2)">{message ?? t("dashboard.empty.description")}</p>
      <Link
        href="/dashboard/audit"
        className="mt-4 inline-flex text-sm font-semibold text-primary hover:underline"
      >
        {t("dashboard.empty.runFirstAudit")}
      </Link>
    </Card>
  );
}
