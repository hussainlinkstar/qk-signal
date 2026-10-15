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
      className="inline-flex flex-wrap gap-1 rounded-full bg-[#EEF1F6] p-1"
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
              "rounded-full px-3.5 py-2 text-[12.5px] font-semibold transition-colors duration-150 focus:outline-hidden focus-visible:ring-2 focus-visible:ring-[#3B82F6] disabled:cursor-not-allowed disabled:opacity-60",
              isActive
                ? "bg-[#E8F1FF] text-[#1D4ED8]"
                : "text-[#6B7280] hover:bg-white/80 hover:text-[#111827]"
            )}
          >
            {ROLE_LABEL[mode]}
          </button>
        );
      })}
    </div>
  );
}
