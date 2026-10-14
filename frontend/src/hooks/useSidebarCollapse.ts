"use client";

import { useCallback, useEffect, useState } from "react";

const SIDEBAR_COLLAPSE_STORAGE_KEY = "dashboard.sidebar.collapsed";

export function useSidebarCollapse() {
  const [isCollapsed, setIsCollapsed] = useState(false);
  const [isReady, setIsReady] = useState(false);

  useEffect(() => {
    try {
      const storedValue = window.localStorage.getItem(SIDEBAR_COLLAPSE_STORAGE_KEY);
      if (storedValue === "true") {
        setIsCollapsed(true);
      }
    } finally {
      setIsReady(true);
    }
  }, []);

  useEffect(() => {
    if (!isReady) {
      return;
    }
    window.localStorage.setItem(SIDEBAR_COLLAPSE_STORAGE_KEY, isCollapsed ? "true" : "false");
  }, [isCollapsed, isReady]);

  const toggleSidebar = useCallback(() => {
    setIsCollapsed((value) => !value);
  }, []);

  return {
    isCollapsed,
    isReady,
    setIsCollapsed,
    toggleSidebar,
  };
}
