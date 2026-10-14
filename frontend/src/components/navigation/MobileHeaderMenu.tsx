"use client";

import { usePathname, useSearchParams } from "next/navigation";
import { useEffect, useId, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { X } from "lucide-react";
import Link from "next/link";
import SignalBrandLockup from "@/components/signal/SignalBrandLockup";
import { cx } from "@/components/ui/utils";

type MobileHeaderMenuProps = {
  menuLabel: string;
  userContent?: React.ReactNode;
  navContent: React.ReactNode;
  actionContent?: React.ReactNode;
  className?: string;
  panelClassName?: string;
};

export default function MobileHeaderMenu({
  menuLabel,
  userContent,
  navContent,
  actionContent,
  className,
  panelClassName,
}: MobileHeaderMenuProps) {
  const [isOpen, setIsOpen] = useState(false);
  const [isMounted, setIsMounted] = useState(false);
  const buttonRef = useRef<HTMLButtonElement>(null);
  const panelRef = useRef<HTMLDivElement>(null);
  const controlsId = useId();
  const titleId = useId();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const searchParamsValue = searchParams?.toString() ?? "";

  const closeMenu = () => {
    setIsOpen(false);
  };

  useEffect(() => {
    setIsMounted(true);
  }, []);

  useEffect(() => {
    closeMenu();
    // search params are needed to close stale menu state on query route changes.
  }, [pathname, searchParamsValue]);

  useEffect(() => {
    if (!isOpen) {
      return;
    }

    const originalOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        closeMenu();
        buttonRef.current?.focus();
      }
    };

    const handlePointerDown = (event: MouseEvent | TouchEvent) => {
      const target = event.target;
      if (!(target instanceof Node)) {
        return;
      }

      if (panelRef.current?.contains(target) || buttonRef.current?.contains(target)) {
        return;
      }

      closeMenu();
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
    <div className={cx("relative md:hidden", className)}>
      <button
        ref={buttonRef}
        type="button"
        className={cx(
          "group relative inline-flex h-11 w-11 items-center justify-center rounded-lg border transition-colors duration-normal focus-visible:outline-hidden",
          isOpen
            ? "border-primary bg-(--surface-subtle) text-primary"
            : "border-(--border) bg-(--surface) text-(--foreground) hover:border-primary/40 hover:text-primary"
        )}
        aria-expanded={isOpen}
        aria-controls={controlsId}
        aria-label={menuLabel}
        onClick={() => {
          setIsOpen((currentState) => !currentState);
        }}
      >
        <span className="sr-only">{menuLabel}</span>
        <span aria-hidden className="relative block h-5 w-5">
          <span
            className={cx(
              "absolute left-0 top-0.5 h-0.5 w-5 rounded-full bg-current transition-all duration-300",
              isOpen && "top-2 -rotate-45"
            )}
          />
          <span
            className={cx(
              "absolute left-0 top-2 h-0.5 w-5 rounded-full bg-current transition-all duration-300",
              isOpen && "opacity-0"
            )}
          />
          <span
            className={cx(
              "absolute left-0 top-3.5 h-0.5 w-5 rounded-full bg-current transition-all duration-300",
              isOpen && "top-2 rotate-45"
            )}
          />
        </span>
      </button>

      {isMounted && isOpen
        ? createPortal(
            <div className="fixed inset-0 z-mobile-menu md:hidden">
              {/* Backdrop */}
              <div
                className="absolute inset-0 bg-(--overlay-backdrop) animate-in fade-in duration-150"
                aria-hidden
                onClick={closeMenu}
              />

              {/* Panel, full-screen, flush edges */}
              <div
                ref={panelRef}
                id={controlsId}
                role="dialog"
                aria-modal="true"
                aria-labelledby={titleId}
                className={cx(
                  "absolute inset-0 flex flex-col bg-(--background) animate-in fade-in slide-in-from-left duration-200",
                  panelClassName
                )}
                onClickCapture={(event) => {
                  const target = event.target;
                  if (!(target instanceof HTMLElement)) {
                    return;
                  }

                  if (target.closest("a[href], button[data-mobile-menu-close='true']")) {
                    closeMenu();
                  }
                }}
              >
                {/* Header, logo left, close right */}
                <header className="flex items-center justify-between border-b border-(--border) px-5 py-4">
                  <Link
                    href="/dashboard"
                    aria-label="Qiko Signal"
                    className="flex min-w-0 items-center rounded-sm focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-(--purple) focus-visible:ring-offset-2"
                  >
                    <SignalBrandLockup />
                  </Link>
                  <button
                    type="button"
                    className="inline-flex h-9 w-9 items-center justify-center rounded-md text-(--text-muted) transition-colors hover:bg-(--surface-subtle) hover:text-(--foreground) focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-ring/70"
                    onClick={closeMenu}
                    aria-label="Close menu"
                    data-mobile-menu-initial-focus="true"
                  >
                    <X className="h-5 w-5" />
                  </button>
                  <h2 id={titleId} className="sr-only">
                    {menuLabel}
                  </h2>
                </header>

                {/* Scrollable content */}
                <div className="flex-1 overflow-y-auto">
                  {/* User block, Spaceship-style, between header and nav */}
                  {userContent ? (
                    <>
                      <div className="flex flex-col">{userContent}</div>
                      <div className="mx-5 border-t border-(--border)" />
                    </>
                  ) : null}

                  {/* Nav links */}
                  <nav className="flex flex-col py-2">{navContent}</nav>

                  {/* Separator + action content */}
                  {actionContent ? (
                    <>
                      <div className="mx-5 border-t border-(--border)" />
                      <div className="flex flex-col py-2">{actionContent}</div>
                    </>
                  ) : null}
                </div>
              </div>
            </div>,
            document.body
          )
        : null}
    </div>
  );
}
