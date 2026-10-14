"use client";

import React, { useEffect, useState } from "react";
import Button from "@/components/ui/Button";
import { cx } from "@/components/ui/utils";
import type { AnnotationVisibility } from "@/services/annotationService";

const MAX_CONTENT_LENGTH = 5000;

type AnnotationComposerProps = {
  disabled?: boolean;
  loading?: boolean;
  initialContent?: string;
  initialVisibility?: AnnotationVisibility;
  submitLabel?: string;
  placeholder?: string;
  showVisibilityToggle?: boolean;
  onCancel?: (() => void) | null;
  onSubmit: (payload: {
    content: string;
    visibility: AnnotationVisibility;
  }) => Promise<void> | void;
};

export default function AnnotationComposer({
  disabled = false,
  loading = false,
  initialContent = "",
  initialVisibility = "internal",
  submitLabel = "Add note",
  placeholder = "Add context for this report section...",
  showVisibilityToggle = true,
  onCancel = null,
  onSubmit,
}: AnnotationComposerProps) {
  const [content, setContent] = useState(initialContent);
  const [visibility, setVisibility] = useState<AnnotationVisibility>(initialVisibility);

  useEffect(() => {
    setContent(initialContent);
  }, [initialContent]);

  useEffect(() => {
    setVisibility(initialVisibility);
  }, [initialVisibility]);

  const trimmedContent = content.trim();
  const isInvalid = trimmedContent.length === 0 || trimmedContent.length > MAX_CONTENT_LENGTH;

  const handleSubmit = async () => {
    if (disabled || loading || isInvalid) {
      return;
    }
    await onSubmit({
      content: trimmedContent,
      visibility,
    });
    if (!initialContent) {
      setContent("");
      setVisibility(initialVisibility);
    }
  };

  return (
    <div className="rounded border border-(--line) bg-(--line-2) p-4">
      {showVisibilityToggle ? (
        <div className="mb-3 flex flex-wrap gap-2">
          {[
            { value: "internal" as const, label: "Internal only" },
            { value: "client_visible" as const, label: "Client visible" },
          ].map((option) => (
            <button
              key={option.value}
              type="button"
              disabled={disabled || loading}
              onClick={() => setVisibility(option.value)}
              className={cx(
                "rounded-full border px-3 py-1 text-[10px] font-black uppercase tracking-[0.2em] transition",
                visibility === option.value
                  ? "border-primary/50 bg-primary/15 text-primary"
                  : "border-(--line) bg-transparent text-(--t-2) hover:border-(--line) hover:text-(--t-1)"
              )}
            >
              {option.label}
            </button>
          ))}
        </div>
      ) : null}

      <label className="sr-only" htmlFor="annotation-composer-content">
        Annotation content
      </label>
      <textarea
        id="annotation-composer-content"
        value={content}
        onChange={(event) => setContent(event.target.value.slice(0, MAX_CONTENT_LENGTH))}
        disabled={disabled || loading}
        placeholder={placeholder}
        className="min-h-[112px] w-full rounded border border-(--line) bg-(--paper) px-4 py-3 text-sm leading-6 text-(--t-1) outline-hidden transition placeholder:text-(--t-3) focus:border-primary/40 focus:ring-2 focus:ring-primary/20 disabled:opacity-60"
      />

      <div className="mt-3 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <p className={cx("text-xs", isInvalid ? "text-rose-300" : "text-(--t-3)")}>
          {trimmedContent.length}/{MAX_CONTENT_LENGTH}
        </p>

        <div className="flex flex-wrap justify-end gap-2">
          {onCancel ? (
            <Button variant="ghost" size="sm" onClick={onCancel} disabled={loading}>
              Cancel
            </Button>
          ) : null}
          <Button
            variant="primary"
            size="sm"
            onClick={() => void handleSubmit()}
            loading={loading}
            disabled={disabled || isInvalid}
          >
            {submitLabel}
          </Button>
        </div>
      </div>
    </div>
  );
}
