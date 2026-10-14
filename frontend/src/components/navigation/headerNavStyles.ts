import { cx } from "@/components/ui/utils";

const DESKTOP_HEADER_BASE_CLASS =
  "inline-flex items-center gap-2 rounded-md px-2 py-1.5 text-sm font-medium text-(--text-soft) transition-colors duration-normal hover:bg-(--surface-subtle) hover:text-(--foreground) focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-ring/70 focus-visible:ring-offset-2 focus-visible:ring-offset-(--background)";

const DESKTOP_HEADER_LINK_CLASS = DESKTOP_HEADER_BASE_CLASS;

const DESKTOP_HEADER_TRIGGER_CLASS = DESKTOP_HEADER_BASE_CLASS;

const DESKTOP_HEADER_UTILITY_LINK_CLASS =
  "rounded-md px-2 py-1.5 text-sm font-medium text-(--text-soft) transition-colors duration-normal hover:bg-(--surface-subtle) hover:text-(--foreground) focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-ring/70 focus-visible:ring-offset-2 focus-visible:ring-offset-(--background)";

const MOBILE_HEADER_LINK_CLASS =
  "block w-full rounded-lg px-4 py-3 text-[0.95rem] font-medium text-(--foreground) transition-colors duration-normal hover:bg-(--surface-subtle) focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring/70";

export function getHeaderNavLinkClassName({
  mobile,
  className,
}: {
  mobile?: boolean;
  className?: string;
}) {
  return cx(mobile ? MOBILE_HEADER_LINK_CLASS : DESKTOP_HEADER_LINK_CLASS, className);
}

export function getHeaderNavButtonClassName({ className }: { className?: string } = {}) {
  return cx(DESKTOP_HEADER_TRIGGER_CLASS, className);
}

export function getHeaderUtilityLinkClassName({ className }: { className?: string } = {}) {
  return cx(DESKTOP_HEADER_UTILITY_LINK_CLASS, className);
}

export const mobileMenuActionGroupClassName = "flex flex-col px-5 py-2 gap-2";
