"use client";

import { usePathname, useSearchParams } from "next/navigation";
import { useEffect, useId, useRef, useState } from "react";
import { createPortal } from "react-dom";
import Link from "next/link";
import { Menu, X } from "lucide-react";
import SignalBrandLockup from "@/components/signal/SignalBrandLockup";
import { cx } from "@/components/ui/utils";
import type { NavSection } from "@/components/navigation/navigationConfig";
import SidebarSection from "@/components/navigation/SidebarSection";
import SidebarWorkspaceMenu from "@/components/app/SidebarWorkspaceMenu";

type MobileDashboardDrawerProps = {
  primarySections: NavSection[];
  adminSection?: NavSection;
  projectQuickLinks?: NavSection;
  isProjectContext: boolean;
  /** The project the drawer's switcher names; see SidebarWorkspaceMenu. */
  activeProjectId?: string | null;
  isStaff: boolean;
  email: string;
  onLogout: () => void;
};

export default function MobileDashboardDrawer({
  primarySections,
  adminSection,
  projectQuickLinks,
  isProjectContext,
  activeProjectId = null,
  isStaff,
  email,
  onLogout,
}: MobileDashboardDrawerProps) {
  const [isOpen, setIsOpen] = useState(false);
  const [isMounted, setIsMounted] = useState(false);
  const buttonRef = useRef<HTMLButtonElement>(null);
  const panelRef = useRef<HTMLDivElement>(null);
  const controlsId = useId();
  const titleId = useId();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const searchParamsValue = searchParams?.toString() ?? "";

  const closeDrawer = () => {
    setIsOpen(false);
  };

  useEffect(() => {
    setIsMounted(true);
  }, []);

  useEffect(() => {
    closeDrawer();
  }, [pathname, searchParamsValue]);

  useEffect(() => {
    if (!isOpen) return;

    const originalOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";

    const handleKeyDown = (event: KeyboardEvent) => {
      const activeDialog = document.activeElement?.closest('[role="dialog"][aria-modal="true"]');
      if (event.defaultPrevented || (activeDialog && activeDialog !== panelRef.current)) return;
      if (event.key === "Escape") {
        closeDrawer();
        buttonRef.current?.focus();
        return;
      }
      if (event.key !== "Tab") return;
      const controls = panelRef.current?.querySelectorAll<HTMLElement>(
        'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'
      );
      if (!controls?.length) return;
      const first = controls[0];
      const last = controls[controls.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      } else if (!panelRef.current?.contains(document.activeElement)) {
        event.preventDefault();
        first.focus();
      }
    };

    const handlePointerDown = (event: MouseEvent | TouchEvent) => {
      const target = event.target;
      if (!(target instanceof Node)) return;
      if (panelRef.current?.contains(target) || buttonRef.current?.contains(target)) {
        return;
      }
      closeDrawer();
    };

    document.addEventListener("keydown", handleKeyDown);
    document.addEventListener("mousedown", handlePointerDown);
    document.addEventListener("touchstart", handlePointerDown);

    const focusableElement = panelRef.current?.querySelector<HTMLElement>(
      '[data-mobile-menu-initial-focus], a[href], button:not([disabled]), [tabindex]:not([tabindex="-1"])'
    );
    focusableElement?.focus();

    return () => {
      document.body.style.overflow = originalOverflow;
      document.removeEventListener("keydown", handleKeyDown);
      document.removeEventListener("mousedown", handlePointerDown);
      document.removeEventListener("touchstart", handlePointerDown);
    };
  }, [isOpen]);

  return (
    <>
      <button
        ref={buttonRef}
        type="button"
        className={cx(
          "inline-flex h-11 w-11 items-center justify-center rounded-lg border border-(--line) text-(--t-1) transition-colors focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-(--purple) focus-visible:ring-offset-2 lg:hidden",
          isOpen ? "bg-(--line-2)" : "bg-(--panel) hover:bg-(--line-2)"
        )}
        aria-expanded={isOpen}
        aria-controls={controlsId}
        aria-label="Open dashboard menu"
        onClick={() => setIsOpen((s) => !s)}
      >
        <Menu className="h-5 w-5" />
      </button>

      {isMounted && isOpen
        ? createPortal(
            <div data-signal-theme className="fixed inset-0 z-mobile-menu bg-transparent lg:hidden">
              <div
                className="absolute inset-0 bg-(--overlay-backdrop) animate-in fade-in duration-150 motion-reduce:animate-none"
                aria-hidden
                onClick={closeDrawer}
              />
              <div
                ref={panelRef}
                id={controlsId}
                role="dialog"
                aria-modal="true"
                aria-labelledby={titleId}
                className="absolute inset-y-0 start-0 m-2 flex w-[min(320px,85vw)] max-w-full flex-col rounded-[24px] border-0 bg-[#F7F8FA] shadow-[0_16px_40px_-18px_rgba(15,23,42,0.28)] animate-in fade-in slide-in-from-left rtl:slide-in-from-right duration-200 motion-reduce:animate-none"
                onClickCapture={(event) => {
                  const target = event.target;
                  if (!(target instanceof HTMLElement)) return;
                  if (target.closest("a[href]")) {
                    closeDrawer();
                  }
                }}
              >
                <header className="flex items-center justify-between border-b border-(--line) px-5 py-4">
                  <Link
                    href="/dashboard"
                    aria-label="Qiko Signal"
                    className="flex min-w-0 items-center rounded-sm focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-(--purple) focus-visible:ring-offset-2"
                  >
                    <SignalBrandLockup />
                  </Link>
                  <button
                    type="button"
                    className="inline-flex h-10 w-10 items-center justify-center rounded-md text-(--t-3) transition-colors hover:bg-(--line-2) hover:text-(--t-1) focus-visible:outline-hidden focus-visible:ring-2"
                    onClick={closeDrawer}
                    aria-label="Close menu"
                    data-mobile-menu-initial-focus="true"
                  >
                    <X className="h-5 w-5" />
                  </button>
                  <h2 id={titleId} className="sr-only">
                    Dashboard navigation
                  </h2>
                </header>

                <div className="flex-1 overflow-y-auto p-4">
                  <nav className="space-y-4">
                    {primarySections.map((section) => (
                      <SidebarSection
                        key={section.label}
                        section={section}
                        pathname={pathname}
                        collapsed={false}
                        onAction={(action) => {
                          if (action === "logout") {
                            closeDrawer();
                            onLogout();
                          }
                        }}
                      />
                    ))}
                    {isProjectContext && projectQuickLinks && (
                      <SidebarSection
                        section={projectQuickLinks}
                        pathname={pathname}
                        collapsed={false}
                        className="border-t border-(--line) pt-3"
                      />
                    )}
                    {isStaff && adminSection && (
                      <SidebarSection
                        section={adminSection}
                        pathname={pathname}
                        tone="danger"
                        collapsed={false}
                        className="border-t border-(--line) pt-3"
                      />
                    )}
                  </nav>
                </div>

                {/* signal-MVP `.foot`: one switcher, same control as the desktop sidebar. */}
                <div className="border-t border-(--line) p-4 pt-3">
                  <SidebarWorkspaceMenu
                    email={email}
                    onLogout={onLogout}
                    projectScope={isProjectContext}
                    activeProjectId={activeProjectId}
                  />
                </div>
              </div>
            </div>,
            document.body
          )
        : null}
    </>
  );
}
