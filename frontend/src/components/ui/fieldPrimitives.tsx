import React from "react";
import { Field, FieldDescription, FieldError, FieldLabel } from "./field";
import { RADIUS_CONTROL_CLASS } from "./radiusTokens";
import { cx } from "./utils";

export type FieldVariant = "default" | "auth";

type FieldShellProps = {
  id: string;
  label?: string;
  error?: string;
  helperText?: string;
  variant?: FieldVariant;
  messageId?: string;
  children: React.ReactNode;
};

export const joinDescribedBy = (...ids: Array<string | undefined>) =>
  ids.filter(Boolean).join(" ") || undefined;

export const fieldControlClasses = ({
  variant = "default",
  error = false,
  multiline = false,
}: {
  variant?: FieldVariant;
  error?: boolean;
  multiline?: boolean;
}) =>
  variant === "auth"
    ? cx(
        "w-full rounded-(--r-md) border bg-(--paper) px-[13px] font-(family-name:--body-font) text-base font-normal leading-[1.5] text-(--t-1) shadow-none transition-[border-color,box-shadow] duration-150 placeholder:text-(--t-3) focus:outline-hidden focus:ring-[3px] focus:ring-(--ring) disabled:cursor-not-allowed disabled:bg-(--line-2) disabled:text-(--t-3) sm:text-[13.5px]",
        error
          ? "border-(--bad) focus:border-(--bad)"
          : "border-(--line) hover:bg-[#E8ECF3] focus:border-(--brand)",
        multiline ? "min-h-[124px] py-[11px]" : "h-11 py-0"
      )
    : cx(
        "w-full border border-(--line) bg-white font-(family-name:--body-font) font-normal leading-[normal] text-(--t-1) placeholder:text-(--t-3) shadow-none transition-[border-color,box-shadow] duration-150 focus:outline-hidden focus:border-(--purple) focus:ring-[3px] focus:ring-[rgba(147,51,234,0.12)] disabled:cursor-not-allowed disabled:border-transparent disabled:bg-(--line-2) disabled:text-(--t-3) disabled:opacity-80 read-only:text-(--t-2)",
        "rounded-[14px]",
        error
          ? "border-(--bad) bg-[color-mix(in_srgb,var(--danger)_6%,white)] focus:border-(--bad) focus:ring-[color-mix(in_srgb,var(--danger)_28%,transparent)]"
          : "hover:border-[color-mix(in_srgb,var(--purple)_28%,var(--line))]",
        "px-3.5 text-base sm:text-[13.5px]",
        multiline ? "min-h-[76px] py-[11px]" : "h-11 py-0"
      );

export const FieldShell = ({
  id,
  label,
  error,
  helperText,
  variant = "default",
  messageId,
  children,
}: FieldShellProps) => {
  const message = error ?? helperText;
  const Message = error ? FieldError : FieldDescription;

  return (
    <Field>
      {label &&
        (variant === "auth" ? (
          <label
            htmlFor={id}
            className="block font-(family-name:--body-font) text-[13px] font-medium leading-[1.5] tracking-normal text-(--t-2)"
          >
            {label}
          </label>
        ) : (
          <FieldLabel htmlFor={id}>{label}</FieldLabel>
        ))}
      {children}
      {message && <Message id={messageId}>{message}</Message>}
    </Field>
  );
};
