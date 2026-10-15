"use client";

import React from "react";
import { CheckCircle2, Circle } from "lucide-react";

import { cx } from "@/components/ui/utils";
import {
  PASSWORD_REQUIREMENTS,
  getPasswordStrength,
  type PasswordStrength,
} from "@/lib/auth-validation";

const strengthLabelByKey: Record<PasswordStrength, string> = {
  weak: "Weak",
  fair: "Fair",
  strong: "Strong",
};

const strengthProgressByKey: Record<PasswordStrength, number> = {
  weak: 33,
  fair: 66,
  strong: 100,
};

const strengthToneByKey: Record<PasswordStrength, string> = {
  weak: "text-(--danger)",
  fair: "text-(--warning)",
  strong: "text-(--success)",
};

const strengthBarByKey: Record<PasswordStrength, string> = {
  weak: "bg-danger/80",
  fair: "bg-warning/80",
  strong: "bg-success/80",
};

type PasswordStrengthIndicatorProps = {
  password: string;
  className?: string;
};

export default function PasswordStrengthIndicator({
  password,
  className,
}: PasswordStrengthIndicatorProps) {
  if (!password) return null;

  const strength = getPasswordStrength(password);
  const metRequirementCount = PASSWORD_REQUIREMENTS.filter((requirement) =>
    requirement.test(password)
  ).length;

  return (
    <div
      className={cx("rounded-(--r-md) border-0 bg-[#EEF1F6] p-[15px]", className)}
      aria-live="polite"
    >
      <div className="flex items-center justify-between gap-3 text-xs">
        <p className="text-[12px] font-medium tracking-normal text-(--t-2)">Password strength</p>
        <p className={cx("text-[12px] font-medium tracking-normal", strengthToneByKey[strength])}>
          {strengthLabelByKey[strength]}
        </p>
      </div>

      <div className="mt-2 h-2 overflow-hidden rounded-full bg-(--muted)">
        <div
          className={cx(
            "h-full w-(--bw) rounded-full transition-[width,background-color] duration-150 motion-reduce:transition-none",
            strengthBarByKey[strength]
          )}
          style={{ "--bw": `${strengthProgressByKey[strength]}%` } as React.CSSProperties}
        />
      </div>

      <p className="mt-3 text-xs text-(--text-soft)">
        {metRequirementCount}/{PASSWORD_REQUIREMENTS.length} requirements met
      </p>

      <ul className="mt-3 space-y-2">
        {PASSWORD_REQUIREMENTS.map((requirement) => {
          const requirementMet = requirement.test(password);
          return (
            <li
              key={requirement.id}
              className={cx(
                "flex items-center gap-2 text-xs",
                requirementMet ? "text-(--success)" : "text-(--text-soft)"
              )}
            >
              {requirementMet ? (
                <CheckCircle2 className="h-3.5 w-3.5 text-(--success)" />
              ) : (
                <Circle className="h-3.5 w-3.5 text-(--text-muted)" />
              )}
              <span>{requirement.label}</span>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
