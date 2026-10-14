"use client";

import React, { useState, useRef, useEffect, useCallback } from "react";
import Link from "next/link";
import { useAuth as useAuthContext } from "@/contexts/AuthContext";
import { LogOut, Settings, Shield } from "lucide-react";
import BrandMark, { type BrandMarkId } from "@/components/ui/BrandMark";
import { cx } from "@/components/ui/utils";

export function useAuth() {
  return useAuthContext();
}

type CompatUser = {
  id: string;
  primaryEmailAddress: {
    emailAddress: string;
  } | null;
  fullName?: string;
};

export function useUser() {
  const { user, isLoading } = useAuthContext();
  const compatUser: CompatUser | null = user
    ? {
        id: user.id,
        primaryEmailAddress: user.email ? { emailAddress: user.email } : null,
        fullName: user.name,
      }
    : null;

  return {
    user: compatUser,
    isLoaded: !isLoading,
    isSignedIn: Boolean(compatUser),
  };
}

export function SignedIn({ children }: { children: React.ReactNode }) {
  const { isSignedIn } = useAuthContext();
  if (!isSignedIn) return null;
  return <>{children}</>;
}

export function SignedOut({ children }: { children: React.ReactNode }) {
  const { isSignedIn } = useAuthContext();
  if (isSignedIn) return null;
  return <>{children}</>;
}

const SSO_BRAND_IDS: Record<string, BrandMarkId> = {
  google: "google",
  github: "github",
  linkedin: "linkedin",
  microsoft: "microsoft",
};

function UserAvatar({
  avatarUrl,
  initials,
  size = "sm",
  authProvider,
}: {
  avatarUrl?: string | null;
  initials: string;
  size?: "sm" | "md";
  authProvider?: string | null;
}) {
  const [imgError, setImgError] = useState(false);
  const dim = size === "sm" ? "h-8 w-8" : "h-10 w-10";
  const radius = size === "sm" ? "rounded-lg" : "rounded-full";
  const badgeDim = size === "sm" ? "h-3.5 w-3.5" : "h-4 w-4";
  const badgeOffset = size === "sm" ? "-bottom-0.5 -right-0.5" : "-bottom-0.5 -right-0.5";
  const brandId = authProvider && authProvider !== "local" ? SSO_BRAND_IDS[authProvider] : null;

  return (
    <span className="relative inline-flex shrink-0">
      {avatarUrl && !imgError ? (
        <img
          src={avatarUrl}
          alt=""
          referrerPolicy="no-referrer"
          onError={() => setImgError(true)}
          className={cx(dim, radius, "object-cover")}
        />
      ) : (
        <span
          className={cx(
            dim,
            radius,
            "flex items-center justify-center bg-accent text-xs font-black text-accent-foreground shadow-accent-glow"
          )}
        >
          {initials}
        </span>
      )}
      {brandId && (
        <span
          className={cx(
            "absolute flex items-center justify-center rounded-full bg-(--background) ring-1 ring-(--border)",
            badgeDim,
            badgeOffset
          )}
        >
          <BrandMark brand={brandId} markClassName="h-2.5 w-2.5" />
        </span>
      )}
    </span>
  );
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
export function UserButton(_props: any) {
  const { user, logout } = useAuthContext();
  const [isOpen, setIsOpen] = useState(false);
  const dropdownRef = useRef<HTMLDivElement>(null);

  const handleLogout = useCallback(async () => {
    setIsOpen(false);
    await logout();
  }, [logout]);

  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (dropdownRef.current && !dropdownRef.current.contains(event.target as Node)) {
        setIsOpen(false);
      }
    };
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  if (!user) return null;

  const initials = user.name
    ? user.name
        .split(" ")
        .map((n) => n[0])
        .join("")
        .toUpperCase()
    : user.email[0].toUpperCase();

  return (
    <div className="relative" ref={dropdownRef}>
      <button
        onClick={() => setIsOpen(!isOpen)}
        className="flex items-center gap-2 p-1 rounded-xl border border-(--border) bg-(--surface-subtle) hover:bg-(--muted) transition-all group"
      >
        <span className="transition-transform group-hover:scale-105">
          <UserAvatar
            avatarUrl={user.avatar_url}
            initials={initials}
            size="sm"
            authProvider={user.auth_provider}
          />
        </span>
        <div className="hidden md:flex flex-col items-start pr-2">
          <span className="text-xs font-bold text-(--foreground) leading-none capitalize">
            {user.name || user.email?.split("@")[0] || "there"}
          </span>
          <span className="text-[10px] text-(--text-muted) font-medium truncate max-w-[120px]">
            {user.email}
          </span>
        </div>
      </button>

      {isOpen && (
        <div className="absolute right-0 mt-2 w-56 rounded-xl border border-(--border) bg-(--background)  shadow-2xl p-2 z-50 animate-in fade-in slide-in-from-top-2 duration-200">
          <div className="px-3 py-2 border-b border-(--border) mb-2">
            <p className="text-xs font-bold text-(--text-muted) uppercase tracking-widest leading-none mb-1">
              Signed in as
            </p>
            <p className="text-sm font-bold text-(--foreground) truncate">{user.email}</p>
          </div>

          <Link
            href="/dashboard"
            className="flex items-center gap-3 px-3 py-2 rounded-lg text-(--text-soft) hover:text-(--foreground) hover:bg-(--surface-subtle) transition-colors text-sm font-medium group"
          >
            <Shield className="w-4 h-4 text-thoth-brass group-hover:scale-110 transition-transform" />
            Dashboard
          </Link>

          <Link
            href="/dashboard/account-settings"
            className="flex items-center gap-3 px-3 py-2 rounded-lg text-(--text-soft) hover:text-(--foreground) hover:bg-(--surface-subtle) transition-colors text-sm font-medium group"
          >
            <Settings className="w-4 h-4 text-(--text-soft) group-hover:rotate-45 transition-transform" />
            Account Settings
          </Link>

          <button
            onClick={() => void handleLogout()}
            className="w-full flex items-center gap-3 px-3 py-2 rounded-lg text-(--danger) hover:opacity-80 hover: transition-colors text-sm font-bold mt-2 pt-2 border-t border-(--border)"
          >
            <LogOut className="w-4 h-4" />
            Sign Out
          </button>
        </div>
      )}
    </div>
  );
}

export { UserAvatar };

// eslint-disable-next-line @typescript-eslint/no-explicit-any
export function UserProfile(_props: any) {
  return (
    <div className="text-sm text-(--text-soft)">
      Profile management is available from your account settings and security pages.
    </div>
  );
}
