"use client";

import type { NavSection } from "@/components/navigation/navigationConfig";
import {
  isRouteActive,
  resolveNavBadge,
  resolveNavLabel,
  resolveNavName,
} from "@/components/navigation/navigationConfig";
import type { SignalNavSection } from "@/components/signal/SignalAppShell";

type Options = {
  /** Current pathname, when an active state should be computed. */
  pathname?: string;
  /** Handler wired to `action: "logout"` items (the approved "Sign out"). */
  onLogout?: () => void;
};

/**
 * The one mapping between navigationConfig's data-shaped NavSection (Lucide
 * icon types, i18n keys) and SignalAppShell's presentation-only
 * SignalNavSection (rendered icons, resolved strings). Shared by the
 * dashboard shell and the status pages so both render identical nav rows.
 */
export function toSignalNavSection(
  section: NavSection,
  t: (key: string) => string,
  { pathname, onLogout }: Options = {}
): SignalNavSection {
  return {
    label: resolveNavLabel(section, t),
    items: section.items.map((item) => ({
      name: resolveNavName(item, t),
      href: item.href,
      icon: <item.icon aria-hidden="true" />,
      badge: resolveNavBadge(item, t),
      disabled: item.disabled,
      onSelect: item.action === "logout" ? onLogout : undefined,
      active: pathname !== undefined && item.href ? isRouteActive(pathname, item.href) : false,
    })),
  };
}
