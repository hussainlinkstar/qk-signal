// Nav item styles — exact match to app.qiko.ai GlobalLayout sidebar
// Active: gradient fill (indigo→cyan) + gradient left indicator + cyan icon
// Inactive: slate-400 text, white/5 hover — identical to GlobalLayout

const NAV_ITEM_BASE =
  "w-full flex items-center gap-3 py-3 px-3 rounded-xl " +
  "transition-all duration-200 group relative text-sm font-medium " +
  "focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-offset-1 focus-visible:ring-offset-(--background)";

const NAV_ITEM_VARIANTS = {
  primary: {
    active:
      "bg-(--purple-s) text-(--primary-hover) border border-transparent border-s-2 border-s-(--purple) " +
      "[&_svg]:text-(--primary-hover) focus-visible:ring-(--purple)",
    inactive:
      "border border-transparent text-(--t-2) hover:text-(--t-1) hover:bg-(--line-2) " +
      "focus-visible:ring-[#6366F1]/50",
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
