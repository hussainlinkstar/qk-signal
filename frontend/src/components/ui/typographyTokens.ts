/**
 * Typography scale tokens - single source of truth for shared product hierarchy.
 */

export const PAGE_TITLE_CLASS = "font-sans text-3xl font-black tracking-tight text-(--foreground)";
export const SECTION_TITLE_CLASS = "text-xl font-bold text-(--foreground)";
export const TYPO_CARD_TITLE_CLASS = "text-lg font-semibold text-(--foreground)";
export const BODY_CLASS = "text-sm leading-7 text-(--text-soft) md:text-base";
export const BODY_STRONG_CLASS = "text-sm font-semibold leading-7 text-(--foreground) md:text-base";
export const LABEL_CLASS = "text-sm font-normal text-(--muted-foreground)";
export const MICRO_LABEL_CLASS =
  "font-mono text-[10.5px] font-medium uppercase tracking-[0.08em] text-(--text-soft)";
export const CAPTION_CLASS = "text-xs leading-6 text-(--muted-foreground)";
export const METRIC_CLASS = "text-3xl font-black tracking-tight text-(--foreground)";

export const TYPO = {
  pageTitle: PAGE_TITLE_CLASS,
  sectionTitle: SECTION_TITLE_CLASS,
  cardTitle: TYPO_CARD_TITLE_CLASS,
  body: BODY_CLASS,
  bodyStrong: BODY_STRONG_CLASS,
  label: LABEL_CLASS,
  microLabel: MICRO_LABEL_CLASS,
  caption: CAPTION_CLASS,
  metric: METRIC_CLASS,
} as const;
