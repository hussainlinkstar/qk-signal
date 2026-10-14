"use client";

import React from "react";
import Link from "next/link";
import { useTranslation } from "react-i18next";
import { Compass, ArrowLeft, Home, AlertCircle } from "lucide-react";
import { motion } from "motion/react";
import Button from "@/components/ui/Button";
import { TYPO } from "@/components/ui/typographyTokens";
import { RADIUS_PANEL_CLASS } from "@/components/ui/radiusTokens";
import { cx } from "@/components/ui/utils";

type NotFoundContentProps = {
  title?: string;
  description?: string;
  primaryHref?: string;
  primaryLabel?: string;
  secondaryHref?: string;
  secondaryLabel?: string;
  titleKey?: string;
  descriptionKey?: string;
  primaryLabelKey?: string;
  secondaryLabelKey?: string;
  isAuditNotFound?: boolean;
};

const NotFoundContent = ({
  title,
  description,
  primaryHref = "/",
  primaryLabel,
  secondaryHref,
  secondaryLabel,
  titleKey = "notFound.defaults.title",
  descriptionKey = "notFound.defaults.description",
  primaryLabelKey = "notFound.defaults.primary",
  secondaryLabelKey = "notFound.defaults.secondary",
  isAuditNotFound = false,
}: NotFoundContentProps) => {
  const { t } = useTranslation();
  const Icon = isAuditNotFound ? AlertCircle : Compass;

  return (
    <div className="flex min-h-[70vh] items-center justify-center px-6 py-20 relative overflow-hidden">
      {/* Subtle ambient glow */}
      <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 -z-10 pointer-events-none">
        <div className="w-[420px] h-[420px] bg-primary/10 rounded-full blur-[160px]" />
      </div>

      <motion.div
        initial={{ opacity: 0, y: 16 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.4, ease: "easeOut" }}
        className="w-full max-w-lg"
      >
        <div
          className={cx(
            RADIUS_PANEL_CLASS,
            "border border-(--border) bg-(--surface) px-10 py-12 text-center shadow-surface-elevated"
          )}
        >
          <div className="flex flex-col items-center gap-8">
            {/* Icon */}
            <div className="flex items-center justify-center w-14 h-14 rounded-full border border-(--border) bg-(--surface-subtle)">
              <Icon className="w-7 h-7 text-primary" />
            </div>

            {/* Copy */}
            <div className="space-y-3">
              <p className={TYPO.microLabel}>
                {isAuditNotFound ? t("notFound.eyebrowAudit") : t("notFound.eyebrowPage")}
              </p>
              <h1 className="text-3xl font-bold tracking-tight text-(--foreground)">
                {title ?? t(titleKey)}
              </h1>
              <p className="mx-auto max-w-sm text-sm leading-relaxed text-(--text-muted)">
                {description ?? t(descriptionKey)}
              </p>
            </div>

            {/* Actions */}
            <div className="flex flex-col sm:flex-row items-center justify-center gap-3 w-full">
              <Link href={primaryHref} className="w-full sm:w-auto">
                <Button variant="primary" size="md" className="w-full">
                  <Home className="h-4 w-4" />
                  {primaryLabel ?? t(primaryLabelKey)}
                </Button>
              </Link>

              {secondaryHref && (
                <Link href={secondaryHref} className="w-full sm:w-auto">
                  <Button variant="ghost" size="md" className="w-full">
                    <ArrowLeft className="h-4 w-4" />
                    {secondaryLabel ?? t(secondaryLabelKey)}
                  </Button>
                </Link>
              )}
            </div>
          </div>
        </div>
      </motion.div>
    </div>
  );
};

export default NotFoundContent;
