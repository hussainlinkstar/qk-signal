"use client";

import React, { useState } from "react";
import { toast } from "sonner";
import { useRoleMode } from "@/contexts/RoleModeContext";
import { ROLE_LABEL, ROLE_MODES, type RoleMode } from "@/lib/roleMode";
import { cx } from "@/components/ui/utils";

export default function RoleModeSwitcher() {
  const { roleMode, setRoleMode } = useRoleMode();
  const [pendingMode, setPendingMode] = useState<RoleMode | null>(null);

  const handleSelect = async (mode: RoleMode) => {
    if (mode === roleMode || pendingMode !== null) {
      return;
    }
    setPendingMode(mode);
    try {
      await setRoleMode(mode);
    } catch {
      toast.error("Unable to update role mode.");
    } finally {
      setPendingMode(null);
    }
  };

  return (
    <div
      role="radiogroup"
      aria-label="Role mode"
      className="inline-flex flex-wrap gap-1 rounded-lg border border-(--line) bg-(--line-2) p-1"
    >
      {ROLE_MODES.map((mode) => {
        const isActive = mode === roleMode;
        return (
          <button
            key={mode}
            type="button"
            role="radio"
            aria-checked={isActive}
            disabled={pendingMode !== null}
            onClick={() => void handleSelect(mode)}
            className={cx(
              "rounded-md px-3 py-1.5 text-xs font-semibold transition-colors duration-normal focus:outline-hidden focus-visible:ring-1 focus-visible:ring-primary/40 disabled:cursor-not-allowed disabled:opacity-60",
              isActive
                ? "bg-primary/15 text-(--t-1)"
                : "text-(--text-secondary) hover:bg-(--line-2) hover:text-(--t-1)"
            )}
          >
            {ROLE_LABEL[mode]}
          </button>
        );
      })}
    </div>
  );
}
