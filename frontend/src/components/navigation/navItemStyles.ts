// Mobile drawer nav rows — aligned with the modern desktop sidebar.

const NAV_ITEM_BASE =
  "w-full flex items-center gap-3 py-3 px-2.5 rounded-full " +
  "transition-colors duration-200 group relative text-sm font-medium " +
  "focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-offset-1 focus-visible:ring-offset-(--background)";

const NAV_ITEM_VARIANTS = {
  primary: {
    active:
      "bg-[#E8F1FF] text-[#1D4ED8] border border-transparent " +
      "[&_svg]:text-[#2563EB] focus-visible:ring-[#3B82F6]",
    inactive:
      "border border-transparent text-[#4B5563] hover:text-[#111827] hover:bg-[#F3F4F6] " +
      "focus-visible:ring-[#111827]/40",
  },
  danger: {
    active:
      "bg-danger/10 text-danger border border-danger/20 " +
      "before:absolute before:start-0 before:top-1/2 before:-translate-y-1/2 before:w-1 before:h-8 before:rounded-e-full before:bg-danger " +
      "focus-visible:ring-danger/40",
    inactive:
      "border border-transparent text-(--t-2) hover:bg-danger/10 hover:text-danger " +
      "focus-visible:ring-danger/40",
  },
} as const;

type NavItemTone = keyof typeof NAV_ITEM_VARIANTS;

export function getNavItemClassName({ active, tone }: { active: boolean; tone?: NavItemTone }) {
  const t = tone ?? "primary";
  return `${NAV_ITEM_BASE} ${active ? NAV_ITEM_VARIANTS[t].active : NAV_ITEM_VARIANTS[t].inactive}`;
}
