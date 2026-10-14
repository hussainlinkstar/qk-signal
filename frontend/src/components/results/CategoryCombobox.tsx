"use client";

import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { AnimatePresence, motion } from "motion/react";
import { Loader2, Search, Sparkles } from "lucide-react";

import { AUDIT_CATEGORIES } from "@/constants/auditCategories";
import { cx } from "@/components/ui/utils";

type CategoryComboboxProps = {
  value: string;
  onChange: (value: string) => void;
  disabled?: boolean;
  isDetecting?: boolean;
  aiSuggestion?: string | null;
};

export default function CategoryCombobox({
  value,
  onChange,
  disabled,
  isDetecting,
  aiSuggestion,
}: CategoryComboboxProps) {
  const [isOpen, setIsOpen] = useState(false);
  const [inputValue, setInputValue] = useState(value || "");
  const containerRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    setInputValue(value || "");
  }, [value]);

  const filtered = useMemo(() => {
    const q = inputValue.toLowerCase().trim();
    if (!q) return AUDIT_CATEGORIES;
    return AUDIT_CATEGORIES.filter(
      (cat) => cat.label.toLowerCase().includes(q) || cat.value.toLowerCase().includes(q)
    );
  }, [inputValue]);

  const handleSelect = useCallback(
    (val: string) => {
      onChange(val);
      setInputValue(val);
      setIsOpen(false);
      inputRef.current?.blur();
    },
    [onChange]
  );

  useEffect(() => {
    function handleClickOutside(e: MouseEvent) {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setIsOpen(false);
      }
    }
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  return (
    <div ref={containerRef} className="relative">
      <input
        ref={inputRef}
        id="audit-category"
        type="text"
        autoComplete="off"
        value={inputValue}
        disabled={disabled}
        placeholder="Search industries..."
        onChange={(e) => {
          setInputValue(e.target.value);
          onChange(e.target.value);
          setIsOpen(true);
        }}
        onFocus={() => setIsOpen(true)}
        onKeyDown={(e) => {
          if (e.key === "Escape") {
            setIsOpen(false);
            inputRef.current?.blur();
          }
          if (e.key === "Enter" && filtered.length > 0 && isOpen) {
            e.preventDefault();
            handleSelect(filtered[0].value);
          }
        }}
        className="field-focus-ring h-11 w-full rounded-[10px] border border-(--line) bg-(--paper) px-[13px] py-0 font-(family-name:--body-font) text-[13.5px] text-(--t-1) outline-none placeholder:text-(--t-3) focus:border-[#c7cdd6] disabled:bg-(--line-2) disabled:text-(--t-3)"
      />
      <div className="absolute right-3 top-1/2 -translate-y-1/2 flex items-center gap-2 pointer-events-none">
        {isDetecting ? (
          <Loader2 className="h-4 w-4 animate-spin text-(--purple)" />
        ) : (
          <Search className="h-4 w-4 text-(--t-3)" />
        )}
      </div>
      {aiSuggestion && value === aiSuggestion && (
        <div className="mt-2 flex items-center gap-2">
          <span className="inline-block h-1.5 w-1.5 rounded-full animate-pulse bg-(--purple)" />
          <span className="text-xs font-medium uppercase tracking-wider text-(--purple)">
            Filled in from the site
          </span>
        </div>
      )}
      <AnimatePresence>
        {isOpen && filtered.length > 0 && (
          <motion.ul
            initial={{ opacity: 0, y: 8, scale: 0.98 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: 8, scale: 0.98 }}
            transition={{ type: "spring", damping: 20, stiffness: 300 }}
            className="rounded-(--r) border border-(--line) bg-(--panel) absolute z-50 mt-2 max-h-64 w-full overflow-y-auto p-2"
          >
            {filtered.map((cat) => {
              const isAi = aiSuggestion && cat.value.toLowerCase() === aiSuggestion.toLowerCase();
              const isSelected = value === cat.value;
              return (
                <li
                  key={cat.value}
                  onMouseDown={(e) => {
                    e.preventDefault();
                    handleSelect(cat.value);
                  }}
                  className={cx(
                    "flex cursor-pointer items-center justify-between gap-3 rounded px-4 py-3 text-xs font-medium uppercase tracking-wider transition-colors",
                    isSelected
                      ? "bg-[rgba(147,51,234,0.10)] text-(--purple)"
                      : "text-(--t-3) hover:bg-(--line-2) hover:text-(--t-1)"
                  )}
                >
                  <div className="flex items-center gap-3">
                    {isAi ? (
                      <Sparkles className="h-4 w-4 text-(--purple)" />
                    ) : (
                      <div className="w-4" />
                    )}
                    <span>{cat.label}</span>
                  </div>
                  {isAi && (
                    <span className="rounded-md px-2 py-[3px] font-(family-name:--mono) text-[10.5px] uppercase tracking-[0.04em] bg-[rgba(147,51,234,0.1)] text-(--purple)">
                      SUGGESTED
                    </span>
                  )}
                </li>
              );
            })}
          </motion.ul>
        )}
      </AnimatePresence>
    </div>
  );
}
