"use client";

import React, { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { useAuth } from "@/components/auth/custom-auth";
import { workspaceHeaders } from "@/components/app/WorkspaceSwitcher";
import { fetchCurrentWorkspace, updateCurrentWorkspace } from "@/services/workspaceService";
import type { RoleMode } from "@/lib/roleMode";

const DEFAULT_ROLE_MODE: RoleMode = "marketer";

type RoleModeContextValue = {
  roleMode: RoleMode;
  setRoleMode: (mode: RoleMode) => Promise<void>;
};

const RoleModeContext = createContext<RoleModeContextValue | null>(null);

export function RoleModeProvider({ children }: { children: React.ReactNode }) {
  const { getToken, isSignedIn } = useAuth();
  const [roleMode, setRoleModeState] = useState<RoleMode>(DEFAULT_ROLE_MODE);

  const getAuthHeaders = useCallback(async (): Promise<HeadersInit> => {
    const token = await getToken();
    if (!token) {
      throw new Error("Authentication token unavailable.");
    }
    return { Authorization: `Bearer ${token}`, ...workspaceHeaders() };
  }, [getToken]);

  // Hydrate role mode from the current workspace once signed in.
  useEffect(() => {
    if (!isSignedIn) {
      setRoleModeState(DEFAULT_ROLE_MODE);
      return;
    }

    let cancelled = false;
    const load = async () => {
      try {
        const headers = await getAuthHeaders();
        const workspace = await fetchCurrentWorkspace(headers);
        if (!cancelled) {
          setRoleModeState(workspace.role_mode ?? DEFAULT_ROLE_MODE);
        }
      } catch {
        if (!cancelled) {
          setRoleModeState(DEFAULT_ROLE_MODE);
        }
      }
    };

    void load();
    return () => {
      cancelled = true;
    };
  }, [getAuthHeaders, isSignedIn]);

  const setRoleMode = useCallback(
    async (mode: RoleMode) => {
      let previous: RoleMode = DEFAULT_ROLE_MODE;
      setRoleModeState((current) => {
        previous = current;
        return mode;
      });

      try {
        const headers = await getAuthHeaders();
        await updateCurrentWorkspace({ role_mode: mode }, headers);
      } catch (error) {
        // Roll back the optimistic update on failure.
        setRoleModeState(previous);
        throw error;
      }
    },
    [getAuthHeaders]
  );

  const value = useMemo<RoleModeContextValue>(
    () => ({ roleMode, setRoleMode }),
    [roleMode, setRoleMode]
  );

  return <RoleModeContext.Provider value={value}>{children}</RoleModeContext.Provider>;
}

export function useRoleMode(): RoleModeContextValue {
  const context = useContext(RoleModeContext);
  if (!context) {
    throw new Error("useRoleMode must be used within a RoleModeProvider");
  }
  return context;
}
