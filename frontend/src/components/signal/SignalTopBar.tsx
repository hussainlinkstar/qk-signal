"use client";

import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { ChevronDown, Globe2, Search } from "lucide-react";
import { Command as CommandPrimitive } from "cmdk";
import { useTranslation } from "react-i18next";
import LanguageSwitcher from "@/components/LanguageSwitcher";
import SignalBrandLockup from "@/components/signal/SignalBrandLockup";
import type { SignalNavSection } from "@/components/signal/SignalAppShell";

export type DomPillProject = { id: number; name: string; domain_url: string | null };

/** cmdk assigns the input its own id, so callers focus it via this selector. */
export const SIGNAL_SEARCH_INPUT_SELECTOR = "[cmdk-input]";

/**
 * signal-MVP `.tsearch` + `.qs-panel`: a real input centred in the top bar
 * whose focus (or a keystroke, or ⌘K) opens the inline listbox directly under
 * the field. It is the design's only search surface - not a button that opens
 * a modal. Arrow keys move the selection, Enter runs it, Escape/Tab/outside
 * click close, matching app.js wireSearch.
 */
function SignalSearchBox({ sections }: { sections: SignalNavSection[] }) {
  const { t } = useTranslation();
  const router = useRouter();
  const rootRef = useRef<HTMLDivElement>(null);
  const [open, setOpen] = useState(false);

  const groups = useMemo(
    () =>
      sections
        .map((section) => ({
          label: section.label,
          items: section.items.filter((item) => !item.disabled && (item.href || item.onSelect)),
        }))
        .filter((section) => section.items.length > 0),
    [sections]
  );

  const runItem = (item: SignalNavSection["items"][number]) => {
    setOpen(false);
    if (item.onSelect) {
      item.onSelect();
    } else if (item.href) {
      router.push(item.href);
    }
  };

  // Outside click closes the panel, like wireSearch's document listener.
  useEffect(() => {
    if (!open) return;
    const onPointerDown = (event: MouseEvent) => {
      if (rootRef.current && !rootRef.current.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onPointerDown);
    return () => document.removeEventListener("mousedown", onPointerDown);
  }, [open]);

  // ⌘K/Ctrl+K focuses the field from anywhere in the shell.
  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        document.querySelector<HTMLElement>(SIGNAL_SEARCH_INPUT_SELECTOR)?.focus();
      }
    };
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, []);

  return (
    // Raw cmdk primitives: the shared ui/command wrappers carry their own base
    // classes (flex/overflow-hidden) whose merge order would clip the dropdown.
    <CommandPrimitive
      label={t("signalShell.palette")}
      filter={(value, search) => (value.toLowerCase().includes(search.toLowerCase()) ? 1 : 0)}
      className="contents"
    >
      <div ref={rootRef} className="relative mx-auto w-full max-w-[430px]">
        {/* `.tsearch`: 38px pill on #EFF1F6, radius 10, gap 9, pad 0 14. */}
        <div
          className={`flex h-[38px] w-full items-center gap-[9px] rounded-[10px] border bg-[#EFF1F6] px-3.5 text-sm text-(--t-3) transition-colors ${
            open
              ? "border-[#C9CEF7] bg-(--panel) shadow-[0_0_0_2px_color-mix(in_srgb,var(--brand)_28%,transparent)]"
              : "border-transparent hover:bg-[#E9ECF3]"
          }`}
        >
          <Search aria-hidden="true" className="h-4 w-4 flex-none" strokeWidth={2} />
          <CommandPrimitive.Input
            role="combobox"
            aria-autocomplete="list"
            placeholder={t("signalShell.search")}
            onFocus={() => setOpen(true)}
            onKeyDown={(event) => {
              if (event.key === "Escape" || event.key === "Tab") setOpen(false);
            }}
            className="min-w-0 flex-1 border-none bg-transparent p-0 text-[13px] text-(--t-1) outline-none placeholder:text-(--t-3) focus:shadow-none focus:ring-0 focus-visible:shadow-none focus-visible:ring-0"
          />
          <kbd
            className={`flex-none rounded border border-(--line) bg-(--paper) px-1.5 py-0.5 font-(family-name:--mono) text-[10px] text-(--t-3) ${
              open ? "hidden" : ""
            }`}
          >
            ⌘K
          </kbd>
        </div>
        {/* `.qs-panel`: absolute, centred under the field, width min(430px,100%). */}
        {open ? (
          <div
            id="signal-qs-panel"
            className="absolute start-1/2 top-[44px] z-50 max-h-[340px] w-[min(430px,100%)] -translate-x-1/2 overflow-auto rounded-xl border border-(--line) bg-(--panel) p-1.5 shadow-[0_16px_40px_-16px_rgba(12,15,22,0.28)] rtl:start-auto rtl:end-1/2 rtl:translate-x-1/2"
          >
            <CommandPrimitive.List>
              <CommandPrimitive.Empty className="px-2.5 py-3 text-[12.5px] text-(--t-2)">
                {t("signalShell.noResults")}
              </CommandPrimitive.Empty>
              {groups.map((group) => (
                <CommandPrimitive.Group
                  key={group.label}
                  heading={
                    <span className="block px-2.5 pb-1 pt-2 font-(family-name:--mono) text-[10px] uppercase tracking-[0.12em] text-(--t-3)">
                      {group.label}
                    </span>
                  }
                >
                  {group.items.map((item) => (
                    <CommandPrimitive.Item
                      key={item.href ?? item.name}
                      value={item.name}
                      role="option"
                      onSelect={() => runItem(item)}
                      className="flex items-center gap-2 rounded-[9px] px-2.5 py-2 text-[13px] text-(--t-1) data-[selected=true]:bg-(--line-2) data-[selected=true]:text-(--t-1)"
                    >
                      <span className="flex-none text-(--t-3) [&_svg]:h-[17px] [&_svg]:w-[17px] [&_svg]:stroke-[1.9]">
                        {item.icon}
                      </span>
                      <span className="min-w-0 flex-1 truncate">{item.name}</span>
                    </CommandPrimitive.Item>
                  ))}
                </CommandPrimitive.Group>
              ))}
            </CommandPrimitive.List>
          </div>
        ) : null}
      </div>
    </CommandPrimitive>
  );
}

/**
 * signal-MVP `.dom-pill` (project scope, .top): the project domain with a live
 * status dot and a `.dp-chev` that opens the project switcher. The dot mirrors
 * real monitoring state: green while the project has at least one recorded
 * audit, warn once it has never been measured.
 */
function SignalDomPill({
  domain,
  live,
  fetchProjects,
}: {
  domain: string;
  live: boolean;
  fetchProjects: () => Promise<DomPillProject[]>;
}) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const [projects, setProjects] = useState<DomPillProject[] | null>(null);
  const rootRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    void fetchProjects()
      .then((list) => {
        if (!cancelled) setProjects(list);
      })
      .catch(() => {
        if (!cancelled) setProjects([]);
      });
    const onPointerDown = (event: MouseEvent) => {
      if (rootRef.current && !rootRef.current.contains(event.target as Node)) setOpen(false);
    };
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      cancelled = true;
      document.removeEventListener("mousedown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [open, fetchProjects]);

  return (
    // `.dom-zone` + `.mon-tag`: the "Monitoring" tag floats above the pill on
    // hover/focus (a rotated 7px square forms its pointer in the mock).
    /* On phones the top bar already carries menu + brand lockup + search;
       the pill's fixed 248px can't shrink, so project switching on <sm
       lives in the drawer instead of overflowing the header. */
    <div ref={rootRef} className="group/dom relative flex-none max-sm:hidden">
      <span className="pointer-events-none absolute start-2.5 top-[-10px] z-20 rounded-[5px] bg-(--ink) px-2 py-[3px] font-(family-name:--mono) text-[9.5px] leading-none tracking-[0.05em] text-white opacity-0 invisible transition-[opacity,transform,visibility] duration-180 translate-y-[3px] group-hover/dom:visible group-hover/dom:translate-y-0 group-hover/dom:opacity-100 group-focus-within/dom:visible group-focus-within/dom:translate-y-0 group-focus-within/dom:opacity-100">
        {t("signalShell.monitoring")}
      </span>
      <div className="relative flex h-[38px] items-center overflow-visible rounded-[10px] border border-(--line) bg-(--panel) text-[13.5px] font-semibold text-(--t-1)">
        <span className="flex min-w-0 items-center gap-[9px] px-3">
          <Globe2 aria-hidden="true" className="h-4 w-4 flex-none text-(--t-2)" strokeWidth={1.8} />
          <span className="truncate">{domain}</span>
          <span
            className={`h-[7px] w-[7px] flex-none rounded-full ${live ? "signal-pulse-dot bg-(--good)" : "bg-(--warn)"}`}
            title={live ? t("signalShell.domLive") : t("signalShell.domNotMeasured")}
          />
        </span>
        <button
          type="button"
          aria-label={t("signalShell.switchProject")}
          aria-expanded={open}
          onClick={() => setOpen((v) => !v)}
          className="flex cursor-pointer items-center self-stretch border-e-0 border-s border-(--line-2) bg-transparent px-2.5 text-(--t-3) hover:text-(--t-1)"
        >
          <ChevronDown aria-hidden="true" className="h-3.5 w-3.5" strokeWidth={2} />
        </button>
        {open ? (
          <div
            role="menu"
            className="absolute inset-s-0 top-[calc(100%+6px)] z-50 min-w-full overflow-hidden rounded-[10px] border border-(--line) bg-(--panel) py-1 shadow-[0_18px_44px_-18px_rgba(12,15,22,0.34)]"
          >
            {projects === null ? (
              <div className="px-3 py-2 text-[12.5px] text-(--t-3)">{t("signalShell.loading")}</div>
            ) : projects.length === 0 ? (
              <div className="px-3 py-2 text-[12.5px] text-(--t-3)">
                {t("signalShell.noProjects")}
              </div>
            ) : (
              projects.map((project) => (
                <Link
                  key={project.id}
                  role="menuitem"
                  href={`/dashboard/projects/${project.id}`}
                  onClick={() => setOpen(false)}
                  className="flex items-center gap-2 px-3 py-2 text-[12.5px] font-semibold text-(--t-1) no-underline hover:bg-(--line-2)"
                >
                  <span className="min-w-0 flex-1 truncate">{project.name}</span>
                  {project.domain_url ? (
                    <span className="max-w-[140px] truncate text-[11px] font-normal text-(--t-3)">
                      {project.domain_url.replace(/^https?:\/\/(www\.)?/i, "").replace(/\/$/, "")}
                    </span>
                  ) : null}
                </Link>
              ))
            )}
          </div>
        ) : null}
      </div>
    </div>
  );
}

type Props = {
  siteLabel?: string | null;
  siteName?: string | null;
  /** `.top .meta`: the mono t-3 line that sits beside `.dom` (e.g. "3 projects"). */
  siteMeta?: string | null;
  /**
   * Workspace-scope dashboards render `.dom` (16px disp 700) rather than the
   * 13.5px status crumb, and an empty label is a valid state: the approved
   * workspace sub-pages leave `.top`'s left side empty.
   */
  workspaceDom?: boolean;
  /**
   * Sections the inline `.tsearch` quick-search lists. Same authorised
   * destinations the sidebar renders, scope- and mode-filtered by the caller,
   * plus the Actions group.
   */
  searchSections?: SignalNavSection[];
  menu?: ReactNode;
  /**
   * Status pages that mount no search surface may pass this to omit `.tsearch`.
   * Default renders it, matching the mockup where wireSearch injects the field
   * into every `.top`.
   */
  hideSearch?: boolean;
  /**
   * Approved `.top > .crumb` (project drilldowns: Dashboard > Page). When
   * present it replaces the `.dom` / label block - `.crumb` is a child of
   * `.top`, never a second row under it (SIGV2-1069).
   */
  crumb?: ReactNode;
  /** Approved `.top` actions after the spacer: Export, Improve settings. */
  actions?: ReactNode;
  /**
   * Project scope `.dom-pill`: the domain, a live status dot, and the chevron
   * that opens the project switcher. Replaces the `.dom` block when set.
   */
  domPill?: { domain: string; live: boolean; fetchProjects: () => Promise<DomPillProject[]> };
};

/**
 * signal-MVP `.top`: a sticky 64px bar with the blurred paper background, a
 * crumb (status pages) or domain label (dashboards) on the left, the
 * `.tsearch` search affordance that opens the shell command palette, and the
 * flag-gated language toggle the mockup appends to `.top`.
 */
export default function SignalTopBar({
  siteLabel,
  siteName,
  siteMeta,
  workspaceDom = false,
  menu,
  hideSearch = false,
  searchSections,
  crumb,
  actions,
  domPill,
}: Props) {
  const { t } = useTranslation();
  const isCrumb = !siteName;

  return (
    /* Three columns rather than a flex row: the side columns are equal `1fr`,
       so the middle one sits on the bar's true centre no matter how wide the
       left block is. The approved design centres the search with `flex:1`,
       which only looks centred when the flanking content happens to balance.
       Measured across fourteen pages it did not: nine distinct x positions at
       1440 and ten at 1920, drifting from 234px left of centre to 80px right,
       because the project pill, the crumb and the workspace title are all
       different widths. The grid delivers what the design intends, on every
       page, and the left column truncates instead of pushing the field. */
    <header className="sticky top-[15px] z-topbar flex min-h-16 items-center gap-3.5 rounded-se-[16px] border-b border-(--line) bg-[rgba(246,247,249,0.82)] px-3 backdrop-blur-[8px] sm:px-8 md:grid md:grid-cols-[1fr_minmax(0,430px)_1fr]">
      <div className="flex min-w-0 items-center gap-3">
        {menu}
        {/* The sidebar carries `.brand` at lg+; below that the top bar is the
            only header, so it renders the same lockup. */}
        <Link
          href="/dashboard"
          aria-label="Qiko Signal"
          className="flex flex-none items-center rounded-sm focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-(--purple) focus-visible:ring-offset-2 lg:hidden"
        >
          <SignalBrandLockup />
        </Link>
        {crumb ? (
          /* Caller-supplied crumbs (title + status pill) can't shrink below
             their content; on phones the lockup is the header identity and
             the in-page heading repeats the title. */
          <div className="flex min-w-0 items-center gap-3 max-sm:hidden">{crumb}</div>
        ) : isCrumb ? (
          /* Status pages: `.crumb` 13.5px t-3 with the leaf in --disp 700 t-1.
             Workspace scope: `.dom` 16px disp 700 t-1 + `.meta` mono 12 t-3,
             both empty by design on sub-pages that register no header. */
          <div className="flex min-w-0 items-center gap-3.5 text-[13.5px] text-(--t-3)">
            {siteLabel || !workspaceDom ? (
              <b
                className={
                  workspaceDom
                    ? "truncate font-(family-name:--disp) text-base font-bold tracking-[-0.01em] text-(--t-1)"
                    : "truncate font-(family-name:--disp) font-bold text-(--t-1)"
                }
              >
                {siteLabel || t("signalShell.account")}
              </b>
            ) : null}
            {siteMeta ? (
              <span className="min-w-0 truncate font-(family-name:--mono) text-xs">{siteMeta}</span>
            ) : null}
          </div>
        ) : domPill ? (
          <SignalDomPill
            domain={domPill.domain}
            live={domPill.live}
            fetchProjects={domPill.fetchProjects}
          />
        ) : (
          /* `.dom` line: the current project name, read-only - shown only
             when no domPill data is available yet. */
          <div className="min-w-0">
            <div className="flex min-w-0 items-center gap-2">
              <Globe2
                aria-hidden="true"
                className="hidden h-4 w-4 shrink-0 text-(--t-3) sm:block"
              />
              <span className="block truncate font-(family-name:--disp) text-base font-bold tracking-[-0.01em] text-(--t-1)">
                {siteName}
              </span>
            </div>
            {siteLabel && siteName !== siteLabel ? (
              <span className="block truncate text-xs text-(--t-3)">{siteLabel}</span>
            ) : null}
          </div>
        )}
      </div>
      {/* From md up this is the centre grid track, `minmax(0,430px)`: a
          definite size, so `.tsearch` holds its approved 430px. An `auto`
          track sizes to its content and left the field at its intrinsic
          148px, because the percentage had no definite size to resolve
          against. Below md the bar stays a flex row and the field takes the
          space left by the brand, since a 430px track there starves the side
          columns and the lockup and language toggle get squeezed out. */}
      <div className="min-w-0 flex-1 md:w-full md:flex-none">
        {!hideSearch ? (
          <div role="search" className="w-full">
            <SignalSearchBox sections={searchSections ?? []} />
          </div>
        ) : null}
      </div>
      <div className="flex min-w-0 items-center justify-end gap-2.5">
        {actions}
        {/* signal-MVP mounts `.lang-toggle` at the end of `.top`; still
            flag-gated so English-only builds render nothing. */}
        <LanguageSwitcher variant="compact" />
      </div>
    </header>
  );
}
