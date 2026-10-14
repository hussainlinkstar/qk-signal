"use client";

import { asset } from "@/lib/basePath";
import React, {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { usePathname, useRouter } from "next/navigation";
import authService, { type LoginCredentials, type UserProfile } from "@/services/auth.service";
import { TokenManager } from "@/utils/token-manager";

type AuthContextValue = {
  user: UserProfile | null;
  isSignedIn: boolean;
  isAuthenticated: boolean;
  isLoading: boolean;
  getToken: () => Promise<string | null>;
  login: (credentials: LoginCredentials) => Promise<void>;
  logout: () => Promise<void>;
  setSession: () => Promise<void>;
};

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();
  const [user, setUser] = useState<UserProfile | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const loadCountRef = useRef(0);

  const isSignedIn = Boolean(user);

  const getToken = useCallback(async () => TokenManager.getAccessTokenWithFallback(), []);

  const loadUser = useCallback(async () => {
    const currentLoadId = ++loadCountRef.current;

    const token = await TokenManager.getAccessTokenWithFallback();
    if (!token) {
      if (currentLoadId === loadCountRef.current) {
        setUser(null);
        setIsLoading(false);
      }
      return;
    }

    try {
      const profile = await authService.getCurrentUser();
      if (currentLoadId === loadCountRef.current) {
        setUser(profile);
      }
    } catch {
      if (currentLoadId === loadCountRef.current) {
        TokenManager.clearTokens();
        setUser(null);
      }
    } finally {
      if (currentLoadId === loadCountRef.current) {
        setIsLoading(false);
      }
    }
  }, []);

  useEffect(() => {
    loadUser();
  }, [loadUser]);

  useEffect(() => {
    const handleStorageChange = (event: StorageEvent) => {
      const isExplicitLogout = event.key === "auth_logout" && event.newValue !== null;

      if (!isExplicitLogout) {
        return;
      }

      setUser(null);
      TokenManager.clearTokens();

      if (!pathname.startsWith("/login")) {
        router.push("/login");
      }
    };

    window.addEventListener("storage", handleStorageChange);

    return () => {
      window.removeEventListener("storage", handleStorageChange);
    };
  }, [pathname, router]);

  const login = useCallback(async (credentials: LoginCredentials) => {
    const payload = await authService.login(credentials);
    if (payload.user) {
      setUser(payload.user);
      return;
    }

    const profile = await authService.getCurrentUser();
    setUser(profile);
  }, []);

  const logout = useCallback(async () => {
    try {
      await authService.logout();
    } finally {
      setUser(null);
      // Hard navigation to clear Next.js Router Cache and all in-memory state.
      // router.push() would serve stale cached RSC payloads from the (app) layout.
      window.location.href = asset("/login");
    }
  }, []);

  const setSession = useCallback(async () => {
    const authenticated = await TokenManager.ensureSession(true);
    if (!authenticated) {
      throw new Error("Session setup failed");
    }
    await loadUser();
  }, [loadUser]);

  const value = useMemo<AuthContextValue>(
    () => ({
      user,
      isSignedIn,
      isAuthenticated: isSignedIn,
      isLoading,
      getToken,
      login,
      logout,
      setSession,
    }),
    [getToken, isLoading, isSignedIn, login, logout, user, setSession]
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error("useAuth must be used within an AuthProvider");
  }
  return context;
}
