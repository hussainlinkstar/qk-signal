"use client";

import { useEffect } from "react";
import type { TabId } from "@/types/auditWorkspace";
import { tabs } from "@/types/auditWorkspace";

/**
 * useTabHotkeys, maps Alt+1 through Alt+7 to tab switching.
 */
export function useTabHotkeys(setActiveTab: (tab: TabId) => void): void {
  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      if (!event.altKey) return;

      const digit = parseInt(event.key, 10);
      if (digit >= 1 && digit <= tabs.length) {
        event.preventDefault();
        setActiveTab(tabs[digit - 1].id);
      }
    };

    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [setActiveTab]);
}
