"use client";

import React from "react";
import { Check, Pipette } from "lucide-react";
import { buttonClasses } from "@/components/ui/Button";
import { cx } from "@/components/ui/utils";
import { BRAND_HEX, BRAND_PRIMARY_PRESETS, BRAND_SECONDARY_PRESETS } from "@/lib/brandPalette";

export const COLOR_PICKER_PRIMARY_PRESETS = BRAND_PRIMARY_PRESETS;

export const COLOR_PICKER_SECONDARY_PRESETS = BRAND_SECONDARY_PRESETS;

const HEX_COLOR_PATTERN = /^#(?:[0-9a-fA-F]{6})$/;

export const normalizeHexColor = (value: string | null | undefined, fallback: string) =>
  value && HEX_COLOR_PATTERN.test(value) ? value.toUpperCase() : fallback.toUpperCase();

const normalizeHexDraft = (value: string) => {
  const trimmed = value.trim().toUpperCase();

  if (!trimmed) {
    return "";
  }

  return trimmed.startsWith("#") ? trimmed : `#${trimmed}`;
};

const withAlpha = (value: string, alpha: string) =>
  HEX_COLOR_PATTERN.test(value) ? `${value}${alpha}` : value;

type ColorPickerFieldProps = {
  label: string;
  value: string;
  presets?: readonly string[];
  onChange: (value: string) => void;
  description?: string;
  disabled?: boolean;
  className?: string;
};

export default function ColorPickerField({
  label,
  value,
  presets = [],
  onChange,
  description = "Use quick presets or dial in an exact brand color.",
  disabled = false,
  className,
}: ColorPickerFieldProps) {
  const inputId = React.useId();
  const hexInputId = `${inputId}-hex`;
  const normalizedValue = normalizeHexColor(value, presets[0] ?? BRAND_HEX.atlasBlue);
  const [draftValue, setDraftValue] = React.useState(normalizedValue);

  React.useEffect(() => {
    setDraftValue(normalizedValue);
  }, [normalizedValue]);

  const normalizedDraftValue = normalizeHexDraft(draftValue);
  const draftIsInvalid =
    draftValue.trim().length > 0 && !HEX_COLOR_PATTERN.test(normalizedDraftValue);
  const usesPreset = presets.some(
    (preset) => normalizeHexColor(preset, normalizedValue) === normalizedValue
  );

  const commitDraftValue = () => {
    if (!draftValue.trim()) {
      setDraftValue(normalizedValue);
      return;
    }

    if (!HEX_COLOR_PATTERN.test(normalizedDraftValue)) {
      setDraftValue(normalizedValue);
      return;
    }

    if (normalizedDraftValue !== normalizedValue) {
      onChange(normalizedDraftValue);
      return;
    }

    setDraftValue(normalizedValue);
  };

  return (
    <div
      className={cx(
        "relative overflow-hidden rounded-2xl border border-(--border) bg-(--surface) p-5 shadow-xs",
        "bg-[radial-gradient(circle_at_top_right,var(--g20)_0%,transparent_36%),radial-gradient(circle_at_bottom_left,var(--g12)_0%,transparent_28%),linear-gradient(180deg,var(--surface)_0%,var(--surface-elevated)_100%)]",
        className
      )}
      style={
        {
          "--g20": withAlpha(normalizedValue, "20"),
          "--g12": withAlpha(normalizedValue, "12"),
        } as React.CSSProperties
      }
    >
      <div className="pointer-events-none absolute inset-x-6 top-0 h-px bg-linear-to-r from-transparent via-(--border) to-transparent" />

      <div className="relative space-y-4">
        <div className="flex items-start justify-between gap-4">
          <div className="min-w-0">
            <p className="text-[10px] font-semibold uppercase tracking-[0.18em] text-(--text-muted)">
              {label}
            </p>
            <p className="mt-2 text-sm text-(--text-soft)">{description}</p>
          </div>
          {presets.length > 0 ? (
            <span
              className={cx(
                "inline-flex shrink-0 items-center rounded-full border px-3 py-1 text-[10px] font-semibold uppercase tracking-[0.18em]",
                usesPreset
                  ? "border-primary/20 bg-primary/10 text-primary"
                  : "border-accent/20 bg-accent/10 text-accent"
              )}
            >
              {usesPreset ? "Preset" : "Custom"}
            </span>
          ) : null}
        </div>

        <div className="rounded-2xl border border-(--border) bg-(--surface-subtle) p-3">
          <div className="flex items-center gap-3">
            <div
              className="relative h-14 w-14 shrink-0 overflow-hidden rounded-2xl border border-white/20 bg-[linear-gradient(145deg,var(--gA)_0%,var(--gB)_100%)] shadow-[0_16px_32px_-24px_var(--gS)]"
              style={
                {
                  "--gA": withAlpha(normalizedValue, "F2"),
                  "--gB": withAlpha(normalizedValue, "8A"),
                  "--gS": withAlpha(normalizedValue, "90"),
                } as React.CSSProperties
              }
            >
              <div className="absolute inset-2 rounded-xl border border-white/25 bg-white/10" />
            </div>
            <div className="min-w-0 flex-1">
              <p className="text-[10px] font-semibold uppercase tracking-[0.18em] text-(--text-muted)">
                Live Preview
              </p>
              <p className="mt-1 font-mono text-base font-semibold text-(--foreground)">
                {normalizedValue}
              </p>
            </div>
          </div>
        </div>

        {presets.length > 0 ? (
          <div className="space-y-2">
            <div className="flex items-center justify-between gap-3">
              <p className="text-[10px] font-semibold uppercase tracking-[0.18em] text-(--text-muted)">
                Quick Palette
              </p>
              <p className="text-[10px] font-medium uppercase tracking-[0.18em] text-(--text-soft)">
                {presets.length} tones
              </p>
            </div>

            <div className="grid grid-cols-3 gap-2 sm:grid-cols-6">
              {presets.map((preset) => {
                const normalizedPreset = normalizeHexColor(preset, normalizedValue);
                const selected = normalizedPreset === normalizedValue;

                return (
                  <button
                    key={normalizedPreset}
                    type="button"
                    disabled={disabled}
                    onClick={() => onChange(normalizedPreset)}
                    aria-label={`${label} ${normalizedPreset}`}
                    aria-pressed={selected}
                    className={cx(
                      "group relative h-12 overflow-hidden rounded-xl border transition duration-normal focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-(--ring) focus-visible:ring-offset-2 focus-visible:ring-offset-(--background)",
                      "bg-[linear-gradient(145deg,var(--gA)_0%,var(--gB)_100%)] shadow-[0_18px_36px_-26px_var(--gS)]",
                      selected
                        ? "border-white/30 shadow-sm"
                        : "border-(--border) hover:border-(--border-hover)",
                      disabled && "cursor-not-allowed opacity-60"
                    )}
                    style={
                      {
                        "--gA": withAlpha(normalizedPreset, "F5"),
                        "--gB": withAlpha(normalizedPreset, "9C"),
                        "--gS": selected ? withAlpha(normalizedPreset, "80") : "transparent",
                      } as React.CSSProperties
                    }
                  >
                    <span className="absolute inset-x-0 bottom-0 h-5 bg-linear-to-t from-black/20 to-transparent" />
                    {selected ? (
                      <span className="absolute right-2 top-2 inline-flex h-5 w-5 items-center justify-center rounded-full border border-white/20 bg-slate-950/35 text-white">
                        <Check className="h-3 w-3" />
                      </span>
                    ) : null}
                  </button>
                );
              })}
            </div>
          </div>
        ) : null}

        <div className="grid gap-3 lg:grid-cols-[minmax(0,1fr)_auto] lg:items-end">
          <div className="space-y-1.5">
            <label
              htmlFor={hexInputId}
              className="block text-[10px] font-semibold uppercase tracking-[0.18em] text-(--text-muted)"
            >
              Hex Value
            </label>
            <input
              id={hexInputId}
              type="text"
              value={draftValue}
              onChange={(event) => setDraftValue(event.target.value.toUpperCase())}
              onBlur={commitDraftValue}
              onKeyDown={(event) => {
                if (event.key === "Enter") {
                  event.preventDefault();
                  commitDraftValue();
                }

                if (event.key === "Escape") {
                  event.preventDefault();
                  setDraftValue(normalizedValue);
                }
              }}
              disabled={disabled}
              spellCheck={false}
              inputMode="text"
              placeholder={normalizedValue}
              aria-label={`${label} hex value`}
              aria-invalid={draftIsInvalid}
              className={cx(
                "h-11 w-full rounded-xl border bg-(--surface) px-4 font-mono text-sm text-(--foreground) placeholder:text-(--text-soft) transition-colors focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-offset-2 focus-visible:ring-offset-(--background)",
                draftIsInvalid
                  ? "border-warning/50"
                  : "border-(--border) hover:border-(--border-hover) focus-visible:border-primary",
                disabled && "cursor-not-allowed opacity-60"
              )}
            />
            {draftIsInvalid && (
              <p className="text-[11px] text-warning">Use #RRGGBB or paste six hex digits.</p>
            )}
          </div>

          <div className="flex items-end">
            <label
              htmlFor={inputId}
              className={buttonClasses({
                variant: "ghost",
                size: "md",
                className: cx(
                  "h-11 w-full cursor-pointer gap-2 border-primary/20 bg-(--surface) px-4 text-[11px] font-semibold uppercase tracking-[0.18em] lg:w-auto",
                  disabled && "cursor-not-allowed"
                ),
              })}
            >
              <Pipette className="h-4 w-4" />
              Open Picker
            </label>
            <input
              id={inputId}
              type="color"
              value={normalizedValue}
              onChange={(event) => onChange(event.target.value.toUpperCase())}
              disabled={disabled}
              className="sr-only"
              aria-label={`${label} color picker`}
            />
          </div>
        </div>
      </div>
    </div>
  );
}
